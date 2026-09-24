package io.github.nanomuse.goals

import android.content.Context
import com.openminis.app.logging.AppLogger
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONArray
import java.io.File

/**
 * `minis-global/nanomuse/goals.json` — every goal, newest first. Small file, read once, written
 * whole on every change; the flow is what the Goals tab and the goal cards observe.
 */
class GoalStore private constructor(context: Context) {
    private val file = File(context.filesDir, "minis-global/nanomuse/goals.json")
    private val _goals = MutableStateFlow(load())
    val goals: StateFlow<List<Goal>> = _goals

    fun all(): List<Goal> = _goals.value

    fun get(id: String): Goal? = _goals.value.firstOrNull { it.id == id }

    fun forSession(sessionId: String): Goal? = _goals.value.firstOrNull { it.sessionId == sessionId }

    @Synchronized
    fun upsert(goal: Goal) {
        val stamped = goal.copy(updatedAt = System.currentTimeMillis())
        val rest = _goals.value.filterNot { it.id == goal.id }
        _goals.value = (listOf(stamped) + rest).sortedByDescending { it.createdAt }
        save()
    }

    @Synchronized
    fun delete(id: String) {
        _goals.value = _goals.value.filterNot { it.id == id }
        save()
    }

    /** A `nanomuse-goal-update` block from the goal's session. */
    fun applyUpdate(goalId: String, progress: Int?, status: String?, note: String?) {
        val goal = get(goalId) ?: return
        val newStatus = when (status?.lowercase()) {
            "done", "completed" -> GoalStatus.DONE
            "paused" -> GoalStatus.PAUSED
            else -> if (goal.status == GoalStatus.DONE) GoalStatus.ACTIVE else goal.status
        }
        upsert(
            goal.copy(
                progress = (progress ?: goal.progress).coerceIn(0, 100),
                status = newStatus,
                lastNote = note?.takeIf { it.isNotBlank() } ?: goal.lastNote,
                lastCheckedAt = System.currentTimeMillis(),
            ),
        )
    }

    private fun load(): List<Goal> {
        if (!file.exists()) return emptyList()
        return runCatching {
            val arr = JSONArray(file.readText())
            buildList { for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { add(Goal.fromJson(it)) } }
        }.onFailure { AppLogger.warning(TAG, "goals.json unreadable: ${it.message}") }
            .getOrDefault(emptyList())
            .sortedByDescending { it.createdAt }
    }

    private fun save() {
        runCatching {
            file.parentFile?.mkdirs()
            val tmp = File(file.parentFile, file.name + ".tmp")
            tmp.writeText(JSONArray().apply { _goals.value.forEach { put(it.toJson()) } }.toString(2))
            if (!tmp.renameTo(file)) {
                file.writeText(tmp.readText())
                tmp.delete()
            }
        }.onFailure { AppLogger.warning(TAG, "goals.json write failed: ${it.message}") }
    }

    companion object {
        private const val TAG = "Goals"

        @Volatile private var instance: GoalStore? = null

        fun get(context: Context): GoalStore =
            instance ?: synchronized(this) {
                instance ?: GoalStore(context.applicationContext).also { instance = it }
            }
    }
}
