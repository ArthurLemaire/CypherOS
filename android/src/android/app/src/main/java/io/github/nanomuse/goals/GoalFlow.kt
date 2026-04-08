package io.github.nanomuse.goals

import android.content.Context
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import com.openminis.app.scheduled.ScheduledRepeatMode
import com.openminis.app.scheduled.ScheduledTargetMode
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskManager
import io.github.nanomuse.chat.SessionAddenda
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.DateFormat
import java.util.Date

/**
 * The conversation half of Goals, Muse style: a goal is shaped in the chat (three short questions),
 * the model hands it over as a `nanomuse-goal` block, the app turns that into a [Goal] with its
 * own session and a hidden periodic ScheduledTask, and every check ends with a
 * `nanomuse-goal-update` block that flows back into the store. The blocks stay in the message
 * text; the markdown renderer draws them as cards.
 */
object GoalFlow {
    private const val TAG = "Goals"
    const val ADDENDUM_TAG = "nanomuse-goal-create"
    const val BLOCK_GOAL = "nanomuse-goal"
    const val BLOCK_UPDATE = "nanomuse-goal-update"

    private val goalBlock = Regex("```$BLOCK_GOAL[ \\t]*\\r?\\n([\\s\\S]*?)```")
    private val updateBlock = Regex("```$BLOCK_UPDATE[ \\t]*\\r?\\n([\\s\\S]*?)```")

    /**
     * The user tapped "Let's go" on a category sheet. Registers the steering addendum for
     * [chatSessionId] and returns the message to send on the user's behalf.
     */
    fun startCreation(context: Context, chatSessionId: String, category: GoalCategory): String {
        SessionAddenda.add(chatSessionId, ADDENDUM_TAG, creationAddendum(category), turns = 8)
        return context.getString(R.string.nm_goal_create_message, categoryLabel(context, category))
    }

    private fun creationAddendum(category: GoalCategory): String = """
        |## Creating a goal (nanoMuse)
        |The user just chose to create a goal in the "${category.key}" category from the Goals tab.
        |Shape it together, like Muse does: ask at most three short questions, ONE message at a time,
        |in the user's language — (1) what exactly they want to achieve, (2) why it matters and by
        |when, (3) how often you should check in (every N hours, or daily at a time). Two or three
        |sentences per message; if the user already answered something, skip that question.
        |When you have enough, reply with one warm sentence of confirmation and then EXACTLY ONE fenced
        |code block tagged `$BLOCK_GOAL` containing JSON with these keys:
        |{"title": "<= 40 chars", "why": "one sentence", "category": "${category.key}",
        | "check_every_hours": <integer, 0 means a daily check>, "check_time": "HH:MM" (used when check_every_hours is 0),
        | "steps": ["3 to 5 short steps you will take or track"], "first_check": "what you will do at the first check"}
        |Do not describe the block or mention JSON — the app renders it as a card. Say nothing after the block.
        |Later, checks for this goal will happen automatically in their own conversation.
    """.trimMargin()

    /** Called after every completed turn; parses goal blocks in the assistant's text. */
    fun afterTurn(context: Context, sessionId: String, assistantText: String?) {
        if (assistantText.isNullOrEmpty()) return
        if (assistantText.contains("```$BLOCK_GOAL")) {
            goalBlock.find(assistantText)?.groupValues?.get(1)?.let { json ->
                if (SessionAddenda.has(sessionId, ADDENDUM_TAG) || !alreadyCreatedFrom(context, json)) {
                    createFromBlock(context, json)
                }
                SessionAddenda.remove(sessionId, ADDENDUM_TAG)
            }
        }
        if (assistantText.contains("```$BLOCK_UPDATE")) {
            updateBlock.findAll(assistantText).forEach { m ->
                val o = runCatching { JSONObject(m.groupValues[1].trim()) }.getOrNull() ?: return@forEach
                val store = GoalStore.get(context)
                val goalId = o.optString("goal_id").ifEmpty { store.forSession(sessionId)?.id } ?: return@forEach
                store.applyUpdate(
                    goalId = goalId,
                    progress = if (o.has("progress")) o.optInt("progress") else null,
                    status = o.optString("status", null),
                    note = o.optString("note", null),
                )
            }
        }
    }

    /** Guard against re-creating a goal when the model repeats a block it emitted earlier. */
    private fun alreadyCreatedFrom(context: Context, json: String): Boolean {
        val title = runCatching { JSONObject(json.trim()).optString("title").trim().take(60) }.getOrNull()
            ?.takeIf { it.isNotEmpty() } ?: return true
        return GoalStore.get(context).all().any { it.title == title }
    }

    private fun createFromBlock(context: Context, json: String) {
        val o = runCatching { JSONObject(json.trim()) }.getOrElse {
            AppLogger.warning(TAG, "goal block is not JSON: ${it.message}")
            return
        }
        val title = o.optString("title").trim().ifEmpty { return }
        val everyHours = o.optInt("check_every_hours", 0).coerceIn(0, 24 * 7)
        val (h, m) = parseTime(o.optString("check_time", "09:00"))
        val steps = o.optJSONArray("steps")?.let { arr ->
            buildList { for (i in 0 until arr.length()) arr.optString(i).trim().takeIf { it.isNotEmpty() }?.let { add(GoalStep(it)) } }
        } ?: emptyList()
        val goal = Goal(
            title = title.take(60),
            why = o.optString("why").trim(),
            category = GoalCategory.fromKey(o.optString("category", null)),
            checkEveryHours = everyHours,
            checkHour = h,
            checkMinute = m,
            steps = steps.take(6),
        )
        val store = GoalStore.get(context)
        store.upsert(goal)
        // Session + check task are created off the main thread; the card in the chat already shows.
        setupScope.launch { setUpGoal(context, goal, o.optString("first_check").trim()) }
    }

    private val setupScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private suspend fun setUpGoal(context: Context, goal: Goal, firstCheck: String) {
        try {
            val app = context.applicationContext as MinisApp
            val sessionId: String? = GoalSessions.create(app, goal.title)
            if (sessionId == null) {
                AppLogger.warning(TAG, "goal ${goal.id}: no provider, no session")
                return
            }
            val withSession = goal.copy(sessionId = sessionId)
            val task = ScheduledTaskManager(app).create(
                ScheduledTask(
                    label = context.getString(R.string.nm_goal_check_task_label, goal.title),
                    timeOfDayHour = goal.checkHour,
                    timeOfDayMinute = goal.checkMinute,
                    repeatMode = ScheduledRepeatMode.DAILY,
                    prompt = checkPrompt(context, withSession, firstCheck),
                    targetMode = ScheduledTargetMode.AppendToSession(sessionId),
                    hidden = true,
                    goalId = goal.id,
                    intervalMinutes = if (goal.checkEveryHours > 0) goal.checkEveryHours * 60 else null,
                ),
            )
            GoalStore.get(context).upsert(withSession.copy(taskId = task.id))
            AppLogger.info(TAG, "goal ${goal.id} '${goal.title}': session=$sessionId task=${task.id}")
        } catch (e: Exception) {
            AppLogger.warning(TAG, "goal setup failed: ${e.message}")
        }
    }

    /**
     * The user message each scheduled check sends into the goal's session. Kept to one line the
     * user can read; the goal's context and the reporting protocol travel in the system prompt
     * (see [systemAddendum]) so the conversation reads like Muse's, not like a job spec.
     */
    fun checkPrompt(context: Context, goal: Goal, firstCheck: String? = null): String = buildString {
        append(context.getString(R.string.nm_goal_check_prompt, goal.title))
        if (!firstCheck.isNullOrBlank()) append("\n").append(context.getString(R.string.nm_goal_first_check, firstCheck))
    }

    /** Appended to the system prompt of a goal's session (null for every other session). */
    fun systemAddendum(context: Context, sessionId: String): String? {
        val goal = GoalStore.get(context).forSession(sessionId) ?: return null
        val cadence = if (goal.checkEveryHours > 0) "every ${goal.checkEveryHours} hour(s)"
        else "daily at %02d:%02d".format(goal.checkHour, goal.checkMinute)
        val steps = goal.steps.mapIndexed { i, s -> "${i + 1}. ${s.text}" }.joinToString("\n").ifEmpty { "(none yet)" }
        return buildString {
            appendLine("## This conversation tracks a goal (nanoMuse)")
            appendLine("Goal: ${goal.title}")
            if (goal.why.isNotBlank()) appendLine("Why: ${goal.why}")
            appendLine("Steps:")
            appendLine(steps)
            appendLine("Checks run $cadence; progress so far ${goal.progress}%" + (goal.lastNote?.let { ", last note: $it" } ?: "") + ".")
            appendLine()
            appendLine(
                "When a message asks you to check on the goal: find out where it stands right now with your tools " +
                    "(shell, browser, MCP servers, memory) and take the next small step if it is safe and reversible. " +
                    "Never pay, send messages or delete anything without asking. Then write the user a short update in " +
                    "their language (at most six lines) and end with EXACTLY ONE fenced code block tagged `$BLOCK_UPDATE` " +
                    "containing {\"goal_id\": \"${goal.id}\", \"progress\": <0-100>, \"status\": \"on_track|attention|done\", \"note\": \"one line\"}. " +
                    "In ordinary conversation here, answer normally and add that block only when the goal's progress actually changed.",
            )
        }
    }

    fun setPaused(context: Context, goal: Goal, paused: Boolean) {
        val store = GoalStore.get(context)
        goal.taskId?.let { ScheduledTaskManager(context).setEnabled(it, !paused) }
        store.upsert(goal.copy(status = if (paused) GoalStatus.PAUSED else GoalStatus.ACTIVE))
    }

    fun markDone(context: Context, goal: Goal, done: Boolean) {
        val store = GoalStore.get(context)
        goal.taskId?.let { ScheduledTaskManager(context).setEnabled(it, !done) }
        store.upsert(goal.copy(status = if (done) GoalStatus.DONE else GoalStatus.ACTIVE, progress = if (done) 100 else goal.progress))
    }

    /** Deletes the goal and its check; the goal's conversation stays (it is the user's history). */
    fun delete(context: Context, goal: Goal) {
        goal.taskId?.let { ScheduledTaskManager(context).delete(it) }
        GoalStore.get(context).delete(goal.id)
    }

    /** Runs the goal's check right now, in its session. */
    suspend fun checkNow(context: Context, goal: Goal) {
        val app = context.applicationContext as MinisApp
        val task = goal.taskId?.let { ScheduledTaskManager(app).get(it) } ?: return
        withContext(Dispatchers.Default) {
            com.openminis.app.scheduled.ScheduledAgentRunner.run(app, task, waitForCompletion = false)
        }
    }

    fun categoryLabel(context: Context, category: GoalCategory): String = context.getString(
        when (category) {
            GoalCategory.HEALTH -> R.string.nm_goal_cat_health
            GoalCategory.RELATIONSHIPS -> R.string.nm_goal_cat_relationships
            GoalCategory.FINANCE -> R.string.nm_goal_cat_finance
            GoalCategory.CAREER -> R.string.nm_goal_cat_career
            GoalCategory.INTERESTS -> R.string.nm_goal_cat_interests
            GoalCategory.PRODUCTIVITY -> R.string.nm_goal_cat_productivity
            GoalCategory.OTHER -> R.string.nm_goal_cat_other
        },
    )

    /** "Every 2 hours · next 09:51" / "Daily 08:00 · next tomorrow 08:00" for cards and rows. */
    fun cadenceLabel(context: Context, goal: Goal): String {
        val cadence = if (goal.checkEveryHours > 0) {
            context.resources.getQuantityString(R.plurals.nm_goal_every_hours, goal.checkEveryHours, goal.checkEveryHours)
        } else {
            context.getString(R.string.nm_goal_daily_at, "%02d:%02d".format(goal.checkHour, goal.checkMinute))
        }
        val next = goal.taskId?.let { ScheduledTaskManager(context).get(it) }?.nextTriggerMs()
        return if (next != null) {
            val fmt = DateFormat.getTimeInstance(DateFormat.SHORT)
            val sameDay = android.text.format.DateUtils.isToday(next)
            val when_ = if (sameDay) fmt.format(Date(next)) else DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(next))
            context.getString(R.string.nm_goal_cadence_next, cadence, when_)
        } else cadence
    }

    private fun parseTime(s: String): Pair<Int, Int> {
        val m = Regex("(\\d{1,2}):(\\d{2})").find(s) ?: return 9 to 0
        return (m.groupValues[1].toInt().coerceIn(0, 23)) to (m.groupValues[2].toInt().coerceIn(0, 59))
    }
}
