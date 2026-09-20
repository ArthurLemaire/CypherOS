package com.openminis.app.service

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * [T-android-session-paused-badge] Per-session badge-state queue shown in the
 * session-list cell's icon corner.
 *
 * Architecture mirror of the iOS design (spec /tmp/fix_session_paused_badge.md):
 * every session holds an ordered queue of [SessionBadgeState] values. The head
 * of the queue is what the cell renders; pushing a new state (e.g. [PAUSED]
 * when a background interruption is detected) prepends to the queue so it
 * shows first. When the user enters the session the [PAUSED] state is removed
 * — any underlying state (future: [ICLOUD_SYNCING]) re-surfaces. The store is
 * persisted to SharedPreferences so a process restart preserves badges.
 *
 * Only [PAUSED] has a wired producer today; [ICLOUD_SYNCING] is reserved for
 * the upcoming Android iCloud-equivalent sync surface and is plumbed through
 * the same data path so adding it later is a one-line emit.
 */
object SessionBadgeStore {
    private const val TAG = "SessionBadgeStore"
    private const val PREFS = "session_badge_store"
    private const val KEY = "badge_state_by_session"

    enum class SessionBadgeState {
        /** Background-interrupted while a stream was active; shown until the user re-opens the session. */
        PAUSED,
        /** Reserved for the upcoming sync-status badge (mirroring iOS iCloud). Not produced yet. */
        ICLOUD_SYNCING,
    }

    @Volatile private var prefs: SharedPreferences? = null

    // sessionId -> ordered queue (head = currently displayed).
    private val _byId = MutableStateFlow<Map<String, List<SessionBadgeState>>>(emptyMap())
    val byId: StateFlow<Map<String, List<SessionBadgeState>>> = _byId.asStateFlow()

    fun init(context: Context) {
        if (prefs != null) return
        val p = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        prefs = p
        _byId.value = loadFromDisk(p)
        Log.d(TAG, "init: restored ${_byId.value.size} sessions with badges")
    }

    /** Head of the queue, or null when empty. Render this in the cell. */
    fun headFor(sessionId: String): SessionBadgeState? =
        _byId.value[sessionId]?.firstOrNull()

    /** Push a state to the head of [sessionId]'s queue (no-op if already at head). */
    fun push(sessionId: String, state: SessionBadgeState) {
        mutate { current ->
            val q = current[sessionId].orEmpty()
            if (q.firstOrNull() == state) return@mutate current
            // De-dupe — if the same state is already elsewhere in the queue,
            // pull it forward instead of stacking duplicates.
            val deduped = q.filter { it != state }
            current + (sessionId to (listOf(state) + deduped))
        }
    }

    /** Remove [state] from [sessionId]'s queue; drop the key when empty. */
    fun remove(sessionId: String, state: SessionBadgeState) {
        mutate { current ->
            val q = current[sessionId] ?: return@mutate current
            val updated = q.filter { it != state }
            if (updated.isEmpty()) current - sessionId else current + (sessionId to updated)
        }
    }

    /** Drop everything for [sessionId] (e.g. session deletion). */
    fun clear(sessionId: String) {
        mutate { it - sessionId }
    }

    /**
     * [T-android-session-paused-badge-hardkill] Reconcile [PAUSED] badges against
     * the authoritative set of currently-interrupted sessions (derived from the
     * persisted message tail by the repository). Run once at launch so a session
     * hard-killed (force-quit / process death) while running — which never hit
     * the lifecycle-callback push path — still shows the badge after restart, and
     * a session that is NO longer interrupted gets its stale badge cleared.
     *
     * Only touches [PAUSED]; other queued states are left intact. Mirrors iOS
     * SessionBadgeStore.reconcileInterruptedSessions.
     */
    fun reconcileInterruptedSessions(interruptedIds: Set<String>) {
        mutate { current ->
            val next = current.toMutableMap()
            // Add PAUSED for interrupted sessions that don't have it yet.
            for (sid in interruptedIds) {
                val q = next[sid].orEmpty()
                if (q.firstOrNull() != SessionBadgeState.PAUSED && !q.contains(SessionBadgeState.PAUSED)) {
                    next[sid] = listOf(SessionBadgeState.PAUSED) + q
                }
            }
            // Remove PAUSED from sessions no longer interrupted.
            val iterIds = next.keys.toList()
            for (sid in iterIds) {
                val q = next[sid] ?: continue
                if (q.contains(SessionBadgeState.PAUSED) && !interruptedIds.contains(sid)) {
                    val updated = q.filter { it != SessionBadgeState.PAUSED }
                    if (updated.isEmpty()) next.remove(sid) else next[sid] = updated
                }
            }
            next
        }
        Log.d(TAG, "reconcileInterruptedSessions: ${interruptedIds.size} interrupted")
    }

    // ── internals ────────────────────────────────────────────────────────

    private fun mutate(block: (Map<String, List<SessionBadgeState>>) -> Map<String, List<SessionBadgeState>>) {
        synchronized(this) {
            val next = block(_byId.value)
            if (next === _byId.value) return
            _byId.value = next
            prefs?.let { persistToDisk(it, next) }
        }
    }

    private fun persistToDisk(p: SharedPreferences, map: Map<String, List<SessionBadgeState>>) {
        // Encoding: "id1=PAUSED,ICLOUD_SYNCING;id2=PAUSED". Plain text is fine —
        // SharedPreferences atomicity covers the whole string; entries are
        // small (max a few hundred sessions × short enum names) so a JSON
        // dependency or per-key shape would be overkill.
        val encoded = map.entries.joinToString(";") { (id, q) ->
            "$id=${q.joinToString(",") { it.name }}"
        }
        runCatching { p.edit().putString(KEY, encoded).apply() }
            .onFailure { Log.w(TAG, "persist failed: ${it.message}") }
    }

    private fun loadFromDisk(p: SharedPreferences): Map<String, List<SessionBadgeState>> {
        val raw = runCatching { p.getString(KEY, null) }.getOrNull() ?: return emptyMap()
        if (raw.isBlank()) return emptyMap()
        return raw.split(';').mapNotNull { entry ->
            val eq = entry.indexOf('=')
            if (eq <= 0 || eq == entry.lastIndex) return@mapNotNull null
            val id = entry.substring(0, eq)
            val q = entry.substring(eq + 1)
                .split(',')
                .mapNotNull { name -> runCatching { SessionBadgeState.valueOf(name) }.getOrNull() }
            if (q.isEmpty()) null else id to q
        }.toMap()
    }
}
