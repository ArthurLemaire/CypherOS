package io.github.nanomuse.home

import android.content.Context
import com.openminis.app.data.repository.ChatRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.util.UUID

/**
 * The one conversation that is the home screen — Muse's "主要聊天". Every other session is a
 * side chat. The id lives in the `nanomuse` prefs; while nothing is persisted yet (fresh install,
 * or every session deleted) a process-lifetime draft id stands in, and the moment that draft is
 * promoted to a database row [onPromoted] pins the real id.
 */
object MainChat {
    private const val PREFS = "nanomuse"
    private const val KEY_SESSION = "main_chat.session"
    private const val KEY_FIRST_CONVERSATION_SESSION = "first_conversation.session"

    @Volatile private var draft: String? = null

    /** Draft id → real id, for the shell that keeps showing the chat under its draft key. */
    @Volatile private var promotedDraft: Pair<String, String>? = null

    private val _sessionId = MutableStateFlow<String?>(null)

    /** The current main chat id (real or draft) once [resolve] has run; null before that. */
    val sessionId: StateFlow<String?> = _sessionId

    fun persisted(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_SESSION, null)

    /**
     * Picks the main chat: the persisted one if it still exists, else the first-conversation
     * session, else the most recently updated session (so a 0.1.2 user's current chat becomes
     * home), else a fresh draft that becomes real on first send.
     */
    suspend fun resolve(context: Context, chatRepository: ChatRepository): String {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs.getString(KEY_SESSION, null)?.let { id ->
            if (chatRepository.getSession(id) != null) return publish(id)
        }
        prefs.getString(KEY_FIRST_CONVERSATION_SESSION, null)?.let { id ->
            if (!isDraftId(id) && chatRepository.getSession(id) != null) {
                prefs.edit().putString(KEY_SESSION, id).apply()
                return publish(id)
            }
        }
        chatRepository.dao.listSessions().firstOrNull()?.let { latest ->
            prefs.edit().putString(KEY_SESSION, latest.id).apply()
            return publish(latest.id)
        }
        val d = draft ?: "__new__${UUID.randomUUID()}".also { draft = it }
        return publish(d)
    }

    /** Called by ChatViewModel.ensureSession when a draft gets its database row. */
    fun onPromoted(context: Context, draftId: String, realId: String) {
        if (draftId != draft && draftId != _sessionId.value) return
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_SESSION, realId).apply()
        draft = null
        promotedDraft = draftId to realId
        _sessionId.value = realId
    }

    /** Make [id] the home conversation (the drawer's "set as main chat"). */
    fun set(context: Context, id: String) {
        if (isDraftId(id)) return
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_SESSION, id).apply()
        _sessionId.value = id
    }

    fun isMain(context: Context, id: String): Boolean {
        if (id == _sessionId.value || id == draft) return true
        promotedDraft?.let { (from, to) -> if (id == from && to == _sessionId.value) return true }
        return persisted(context) == id
    }

    fun isDraftId(id: String?): Boolean = id?.startsWith("__new__") == true

    private fun publish(id: String): String {
        _sessionId.value = id
        return id
    }
}
