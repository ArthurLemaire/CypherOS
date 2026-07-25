package com.openminis.app.ui.scheduled

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * [T-android-scheduled-tasks-design] Backing VM for ScheduledTasksScreen
 * and ScheduledTaskEditScreen. Thin wrapper around [ScheduledTaskManager]
 * exposing a reactive [tasks] flow + suspend functions for the editor.
 */
class ScheduledTasksViewModel(private val appContext: Context) : ViewModel() {

    private val manager = ScheduledTaskManager(appContext)
    private val app get() = appContext as com.openminis.app.MinisApp

    /** Exposed for the editor's ModelPickerSheet — read-only access to the
     *  same ProviderRepository the chat screen uses. */
    val providerRepository get() = app.providerRepository

    val tasks: StateFlow<List<ScheduledTask>> = manager.store().observe()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    // ── [T-android-scheduled-tasks-full] Picker data for the editor ──

    /** Lightweight session row for the Follow-up / Re-run session picker. */
    data class SessionOption(val id: String, val title: String, val updatedAt: Long)

    /** A user message in a session, for the Re-run message picker. */
    data class MessageOption(val id: String, val preview: String, val createdAt: Long)

    /** A selectable model entry for the optional model override. */
    data class ModelOption(val entryId: String, val modelId: String, val displayName: String, val providerLabel: String)

    suspend fun listSessions(limit: Int = 100): List<SessionOption> = withContext(Dispatchers.IO) {
        app.chatRepository.querySessionsMeta(
            sessionIds = null, keywords = null, limit = limit, startMs = null, endMs = null,
        ).map {
            SessionOption(it.id, it.title?.ifBlank { null } ?: "Untitled", it.lastActive)
        }
    }

    suspend fun listUserMessages(sessionId: String): List<MessageOption> = withContext(Dispatchers.IO) {
        app.chatRepository.loadMessages(sessionId)
            .filter { it.role == "user" }
            .map { MessageOption(it.id, extractPreview(it.partsJson), it.createdAt) }
    }

    /** Best-effort human-readable label for a `model_binding` JSON string —
     *  group name for {"type":"group"}, model display name for
     *  {"type":"entry"}, null on parse failure or unknown ids. Mirrors the
     *  chip text the chat screen renders for the same binding. */
    fun describeBinding(json: String?): String? {
        if (json.isNullOrBlank()) return null
        return runCatching {
            val o = org.json.JSONObject(json)
            when (o.optString("type")) {
                "group" -> {
                    val gid = o.optString("groupId").takeIf { it.isNotEmpty() } ?: return@runCatching null
                    app.providerRepository.group(gid)?.name
                }
                "entry" -> {
                    val eid = o.optString("entryId").takeIf { it.isNotEmpty() } ?: return@runCatching null
                    app.providerRepository.config.value.modelEntries.firstOrNull { it.id == eid }?.model?.displayName
                }
                else -> null
            }
        }.getOrNull()
    }

    fun listModels(): List<ModelOption> =
        app.providerRepository.allVisibleEntries().mapNotNull { entry ->
            val instance = app.providerRepository.instance(entry.providerInstanceId) ?: return@mapNotNull null
            ModelOption(
                entryId = entry.id,
                modelId = entry.baseModel.id,
                displayName = entry.model.displayName,
                providerLabel = instance.label.ifEmpty { entry.model.provider },
            )
        }

    private fun extractPreview(partsJson: String): String {
        val text = runCatching {
            val arr = org.json.JSONArray(partsJson)
            val sb = StringBuilder()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                if (o.optString("type") == "text") sb.append(o.optString("value", ""))
            }
            sb.toString()
        }.getOrNull() ?: ""
        return text.trim().replace('\n', ' ').take(80).ifBlank { "(empty)" }
    }

    private val _runNowState = MutableStateFlow<RunNowState?>(null)
    val runNowState: StateFlow<RunNowState?> = _runNowState.asStateFlow()

    fun setEnabled(taskId: String, enabled: Boolean) {
        viewModelScope.launch(Dispatchers.IO) { manager.setEnabled(taskId, enabled) }
    }

    fun delete(taskId: String) {
        viewModelScope.launch(Dispatchers.IO) { manager.delete(taskId) }
    }

    suspend fun get(taskId: String): ScheduledTask? = withContext(Dispatchers.IO) {
        manager.get(taskId)
    }

    suspend fun upsert(task: ScheduledTask, isNew: Boolean): ScheduledTask =
        withContext(Dispatchers.IO) {
            if (isNew) manager.create(task) else manager.update(task)
        }

    /**
     * "Run now" button on the edit screen. Fires the task immediately without
     * touching the schedule.
     *
     * [T-android-scheduled-tasks-full] Async by design: we call the runner with
     * waitForCompletion=false, so this returns as soon as the session is
     * resolved and the prompt is dispatched (status STARTED). The agent keeps
     * running in the background; the completion notification fires later. The
     * UI shows a brief loading spinner that flips to "task started" — it does
     * NOT block on the whole agent loop. STARTED carries the session id so the
     * user can jump straight into the (now-running) chat.
     */
    fun runNow(task: ScheduledTask) {
        viewModelScope.launch(Dispatchers.IO) {
            _runNowState.value = RunNowState(taskId = task.id, status = RunStatus.RUNNING)
            val sid = runCatching {
                com.openminis.app.scheduled.ScheduledAgentRunner.run(
                    appContext, task, waitForCompletion = false,
                )
            }.getOrNull()
            _runNowState.value = RunNowState(
                taskId = task.id,
                status = if (sid != null) RunStatus.STARTED else RunStatus.FAILED,
                sessionId = sid,
            )
        }
    }

    fun clearRunNowState() { _runNowState.value = null }

    enum class RunStatus { RUNNING, STARTED, FAILED }
    data class RunNowState(
        val taskId: String,
        val status: RunStatus,
        val sessionId: String? = null,
    )

    companion object {
        fun factory(context: Context): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T {
                    return ScheduledTasksViewModel(context.applicationContext) as T
                }
            }
    }
}
