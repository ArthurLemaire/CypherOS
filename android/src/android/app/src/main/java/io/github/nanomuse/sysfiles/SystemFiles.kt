package io.github.nanomuse.sysfiles

import android.content.Context
import androidx.annotation.StringRes
import com.openminis.app.R
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskStore
import java.io.File
import java.text.DateFormat
import java.util.Date

/**
 * The handful of files that make the agent who it is, listed the way Muse lists its system
 * files. Every entry is a real Markdown file the agent can also reach from its shell under
 * `/var/minis/memory/` — except HEARTBEAT, which is a read-only rendering of the routines.
 */
enum class SystemFiles(
    val fileName: String,
    @StringRes val about: Int,
    val editable: Boolean,
) {
    SOUL("SOUL.md", R.string.nm_sysfile_about_soul, editable = true),
    USER("USER.md", R.string.nm_sysfile_about_user, editable = true),
    MEMORY("GLOBAL.md", R.string.nm_sysfile_about_memory, editable = true),
    FEED("feed-preferences.md", R.string.nm_sysfile_about_feed, editable = true),
    HEARTBEAT("HEARTBEAT.md", R.string.nm_sysfile_about_heartbeat, editable = false);

    /** Where the file lives; HEARTBEAT has no file of its own. */
    fun file(context: Context): File = when (this) {
        SOUL, USER, MEMORY -> File(File(context.filesDir, "minis-global/memory"), fileName)
        FEED -> File(File(context.filesDir, "minis-global/nanomuse"), fileName)
        HEARTBEAT -> File(File(context.filesDir, "minis-global/nanomuse"), fileName)
    }

    fun read(context: Context): String = when (this) {
        HEARTBEAT -> renderHeartbeat(context)
        FEED -> io.github.nanomuse.feed.FeedStore.preferences.value
        else -> runCatching { file(context).takeIf { it.exists() }?.readText() }.getOrNull().orEmpty()
    }

    fun write(context: Context, text: String) {
        when (this) {
            HEARTBEAT -> Unit
            FEED -> io.github.nanomuse.feed.FeedStore.savePreferences(text)
            SOUL -> {
                file(context).parentFile?.mkdirs()
                file(context).writeText(text)
                com.openminis.app.agent.SoulStore.refreshCache(context)
            }
            else -> {
                file(context).parentFile?.mkdirs()
                file(context).writeText(text)
            }
        }
    }

    /** "MD · 886 B" plus when it last changed, for the list row. */
    fun subtitle(context: Context): String {
        val f = file(context)
        val size = when (this) {
            HEARTBEAT -> renderHeartbeat(context).toByteArray().size.toLong()
            else -> if (f.exists()) f.length() else 0L
        }
        val sizeText = android.text.format.Formatter.formatShortFileSize(context, size)
        val modified = when (this) {
            HEARTBEAT -> ScheduledTaskStore(context).all().maxOfOrNull { it.lastFiredAt ?: it.createdAt }
            else -> f.takeIf { it.exists() }?.lastModified()
        }
        val whenText = modified?.let { relative(context, it) }
        return if (whenText != null) "MD · $sizeText · $whenText" else "MD · $sizeText"
    }

    fun lastModified(context: Context): Long? = when (this) {
        HEARTBEAT -> ScheduledTaskStore(context).all().maxOfOrNull { it.lastFiredAt ?: it.createdAt }
        else -> file(context).takeIf { it.exists() }?.lastModified()
    }

    companion object {
        fun relative(context: Context, ms: Long): String {
            val now = System.currentTimeMillis()
            val diff = now - ms
            return when {
                diff < 60_000L -> context.getString(R.string.nm_time_just_now)
                android.text.format.DateUtils.isToday(ms) -> DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(ms))
                diff < 2 * 86_400_000L -> context.getString(R.string.nm_time_yesterday)
                else -> DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(ms))
            }
        }

        /** The routines, as the agent's heartbeat: what runs, when, and how the last run went. */
        fun renderHeartbeat(context: Context): String {
            val tasks = ScheduledTaskStore(context).all().sortedBy { it.timeOfDayHour * 60 + it.timeOfDayMinute }
            val goals = runCatching { io.github.nanomuse.goals.GoalStore.get(context).all() }.getOrDefault(emptyList())
            return buildString {
                appendLine("# HEARTBEAT.md")
                appendLine()
                appendLine(context.getString(R.string.nm_heartbeat_intro))
                appendLine()
                val routines = tasks.filterNot { it.hidden }
                appendLine("## " + context.getString(R.string.nm_heartbeat_routines))
                if (routines.isEmpty()) appendLine("_" + context.getString(R.string.nm_heartbeat_none) + "_")
                routines.forEach { appendLine(line(context, it)) }
                appendLine()
                val checks = tasks.filter { it.hidden && it.goalId != null }
                appendLine("## " + context.getString(R.string.nm_heartbeat_goal_checks))
                if (checks.isEmpty()) appendLine("_" + context.getString(R.string.nm_heartbeat_none) + "_")
                checks.forEach { t ->
                    val g = goals.firstOrNull { it.id == t.goalId }
                    val cadence = t.intervalMinutes?.let { m -> if (m % 60 == 0) "every ${m / 60} h" else "every $m min" }
                        ?: "daily %02d:%02d".format(t.timeOfDayHour, t.timeOfDayMinute)
                    appendLine("- ${if (t.enabled) "[x]" else "[ ]"} ${g?.title ?: t.label} — $cadence" + lastRun(context, t))
                }
            }
        }

        private fun line(context: Context, t: ScheduledTask): String {
            val time = "%02d:%02d".format(t.timeOfDayHour, t.timeOfDayMinute)
            val repeat = when (t.repeatMode) {
                com.openminis.app.scheduled.ScheduledRepeatMode.ONCE -> "once"
                com.openminis.app.scheduled.ScheduledRepeatMode.DAILY -> "daily"
                com.openminis.app.scheduled.ScheduledRepeatMode.WEEKDAYS -> "weekdays"
                com.openminis.app.scheduled.ScheduledRepeatMode.CUSTOM -> "custom days"
            }
            return "- ${if (t.enabled) "[x]" else "[ ]"} **${t.label.ifBlank { "routine" }}** — $repeat $time" + lastRun(context, t)
        }

        private fun lastRun(context: Context, t: ScheduledTask): String {
            val at = t.lastFiredAt ?: return ""
            val ok = t.runHistory.firstOrNull()?.ok ?: true
            return " · " + context.getString(if (ok) R.string.nm_heartbeat_last_ok else R.string.nm_heartbeat_last_failed, relative(context, at))
        }
    }
}

/** USER.md in the system prompt — one paragraph, only when the file has content. */
object UserFile {
    fun promptFragment(context: Context): String? {
        val text = SystemFiles.USER.read(context).trim()
        if (text.isEmpty()) return null
        return "## About the user (USER.md — maintained by you and the user)\n" +
            "Read at the start of every conversation. Fill it in over time from what the user tells you (name, how to address them, timezone, what they are working on, preferences); edit it with your shell at /var/minis/memory/USER.md when you learn something durable, and tell the user in one line when you do. Never write secrets into it.\n" +
            text.take(4000)
    }
}

/** "Import memory": paste what another assistant remembers, appended under `## Imported` in GLOBAL.md. */
object MemoryImport {
    /** The section heading in the user's language; any of these is recognised when appending. */
    private val HEADINGS = listOf("## 导入", "## 匯入", "## Imported")

    fun append(context: Context, pasted: String, from: String?): Boolean {
        val body = pasted.trim()
        if (body.isEmpty()) return false
        val file = SystemFiles.MEMORY.file(context)
        val existing = runCatching { file.takeIf { it.exists() }?.readText() }.getOrNull().orEmpty()
        val date = DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date())
        val header = "### $date" + (from?.takeIf { it.isNotBlank() }?.let { " · $it" } ?: "")
        val addition = "\n$header\n\n$body\n"
        val lines = existing.lines()
        val headingAt = lines.indexOfFirst { it.trim() in HEADINGS }
        val heading = "## " + context.getString(R.string.nm_import_heading)
        val updated = if (headingAt < 0) {
            existing.trimEnd().let { if (it.isEmpty()) "" else "$it\n\n" } + "$heading\n" + addition
        } else {
            // Insert at the end of the Imported section (before the next "## " heading, if any).
            val nextAt = (headingAt + 1 until lines.size).firstOrNull { lines[it].startsWith("## ") } ?: lines.size
            val before = lines.subList(0, nextAt).joinToString("\n").trimEnd()
            val after = lines.subList(nextAt, lines.size).joinToString("\n")
            before + "\n" + addition + (if (after.isNotBlank()) "\n$after" else "")
        }
        return runCatching {
            file.parentFile?.mkdirs()
            file.writeText(updated)
        }.isSuccess
    }
}
