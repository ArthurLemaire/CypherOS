package com.openminis.app.ui.chat

import android.util.Log
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner

/**
 * Process-level cache of ChatViewModels keyed by sessionId. Mirrors iOS
 * `ViewModelCache` — a session's agent loop keeps running even if the user
 * leaves the chat screen, and the row in the sessions list shows a spinning
 * indicator while streaming is in flight.
 *
 * Without this, scoping the ChatViewModel to a NavBackStackEntry means
 * `popBackStack()` would cancel `viewModelScope` and kill the streaming job.
 */
object ChatViewModelStore {

    private const val TAG = "ChatVMStore"

    /**
     * One ViewModelStore per canonical sessionId. Each store contains at most
     * one ChatViewModel (the one created by our factory). When we want to drop
     * a session's VM, we call `clear()` on its store which triggers
     * `onCleared`.
     */
    private val stores = mutableMapOf<String, ViewModelStore>()

    /**
     * Draft → canonical mapping. When a draft ("__new__...") session is
     * persisted, we add `draftKey -> realId` here so lookups via the old key
     * (from a ChatScreen whose `sessionId` parameter is still the draft)
     * continue to hit the same live store.
     */
    private val aliases = mutableMapOf<String, String>()

    private fun resolveKey(sessionId: String): String =
        aliases[sessionId] ?: sessionId

    @Synchronized
    fun ownerFor(sessionId: String): ViewModelStoreOwner {
        val key = resolveKey(sessionId)
        val store = stores.getOrPut(key) {
            Log.d(TAG, "allocate store for $key (total=${stores.size + 1})")
            ViewModelStore()
        }
        return object : ViewModelStoreOwner {
            override val viewModelStore: ViewModelStore = store
        }
    }

    /**
     * Drop the cached VM for this session (cancels `viewModelScope`, triggers
     * `ChatViewModel.onCleared`). Call when the session is deleted. Also
     * clears any draft alias pointing at this canonical id.
     */
    @Synchronized
    fun release(sessionId: String) {
        val key = resolveKey(sessionId)
        aliases.entries.removeAll { it.value == key }
        stores.remove(key)?.let {
            it.clear()
            Log.d(TAG, "release store for $key (remaining=${stores.size})")
        }
    }

    /**
     * Mark `fromSessionId` (a draft key) as an alias for `toSessionId` (the
     * real, persisted id). The live store stays under the real id; future
     * `ownerFor(draftKey)` lookups resolve to the same store so a ChatScreen
     * still rendering with the draft route continues to see the running VM.
     */
    /**
     * T311: id of the chat the user has on screen right now. Set by
     * `ChatScreen`'s lifecycle hook on enter, cleared on dispose.
     * `minis-config session.*` reads this so reads/writes target the
     * "current session" the same way iOS `AIChatViewModel.activeSessionId`
     * does. `null` = no chat is foregrounded → reads return empty / writes
     * throw `No active session`. Resolves through `aliases` so a draft id
     * still maps to the persisted row.
     */
    @Volatile
    private var activeSessionIdInternal: String? = null

    val activeSessionId: String?
        get() = activeSessionIdInternal?.let { resolveKey(it) }

    @Synchronized
    fun setActiveSession(sessionId: String?) {
        activeSessionIdInternal = sessionId
    }

    @Synchronized
    fun rename(fromSessionId: String, toSessionId: String) {
        if (fromSessionId == toSessionId) return
        val store = stores.remove(fromSessionId)
        if (store != null) {
            stores[toSessionId] = store
        }
        aliases[fromSessionId] = toSessionId
        Log.d(TAG, "rename store $fromSessionId -> $toSessionId (alias kept)")
    }

    /**
     * One-shot stash for the "Move to…" capsule flow. The source session
     * writes (inputText + attachments) here, navigates to the target,
     * and the target's ChatScreen drains it via [consumePendingTransfer].
     * Mirrors iOS `ViewModelCache.pendingTransfer`. Volatile + simple
     * read/write — only ever touched from the main thread.
     */
    data class PendingTransfer(
        val inputText: String,
        val attachments: List<InputAttachment>,
    )

    @Volatile
    private var pendingTransfer: PendingTransfer? = null

    fun stashPendingTransfer(transfer: PendingTransfer) {
        pendingTransfer = transfer
        Log.d(TAG, "stashPendingTransfer: text=${transfer.inputText.length}ch attachments=${transfer.attachments.size}")
    }

    /** Drain the pending-transfer slot exactly once. */
    fun consumePendingTransfer(): PendingTransfer? {
        val t = pendingTransfer
        pendingTransfer = null
        if (t != null) Log.d(TAG, "consumePendingTransfer: text=${t.inputText.length}ch attachments=${t.attachments.size}")
        return t
    }
}
