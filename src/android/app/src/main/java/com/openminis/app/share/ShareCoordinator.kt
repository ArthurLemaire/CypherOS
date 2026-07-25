package com.openminis.app.share

import android.content.Context
import com.openminis.app.logging.AppLogger
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Mirrors iOS Shared/ShareCoordinator.swift. Singleton bridge between
 * ShareReceiverActivity (producer, lives in a different Activity instance
 * before re-launching MainActivity) and ChatScreen (consumer, lives inside
 * MainActivity). Holds the [PendingShare] in memory with a 30s TTL —
 * long enough for the launch flow to land in a chat session, short enough
 * that a stale share doesn't surprise the user weeks later.
 */
object ShareCoordinator {
    private const val TAG = "ShareCoordinator"
    private const val BUFFER_TTL_MS = 30_000L
    private const val LAUNCH_MAX_AGE_MS = 5L * 60 * 1000

    private data class Buffered(val share: PendingShare, val bufferedAtMs: Long)

    @Volatile private var buffer: Buffered? = null

    private val _bufferVersion = MutableStateFlow(0)
    /**
     * Increments every time a new share is buffered. ChatScreen observes
     * this via collectAsState so a warm-start (user already inside a
     * session) injects too. Cold starts pick up the buffer on first
     * composition since the version is non-zero by then.
     */
    val bufferVersion: StateFlow<Int> = _bufferVersion.asStateFlow()

    /**
     * Called from MainActivity.onCreate / onNewIntent when the share
     * receiver re-launched MainActivity with the `shared_content` extra.
     * Loads from prefs, drops if older than [LAUNCH_MAX_AGE_MS] (5 min,
     * mirrors iOS launch check), stores in the in-memory buffer, clears
     * prefs.
     */
    fun processPendingShare(context: Context) {
        val pending = SharedShareStore.loadPendingShare(context) ?: run {
            AppLogger.info(TAG, "[Share] processPendingShare: no pending share")
            return
        }
        val ageMs = System.currentTimeMillis() - pending.timestampMs
        if (ageMs > LAUNCH_MAX_AGE_MS) {
            AppLogger.info(TAG, "[Share] processPendingShare: stale (age=${ageMs}ms), discarding")
            SharedShareStore.clearPendingShare(context)
            SharedShareStore.cleanSharedFiles(context)
            return
        }
        AppLogger.info(TAG, "[Share] processPendingShare: buffering ${pending.items.size} item(s)")
        SharedShareStore.clearPendingShare(context)
        buffer = Buffered(pending, System.currentTimeMillis())
        _bufferVersion.value = _bufferVersion.value + 1
    }

    /** Consume the buffer (one-shot). Returns null if empty or expired. */
    fun consumeBuffer(context: Context): PendingShare? {
        val buf = buffer ?: return null
        buffer = null
        val ageMs = System.currentTimeMillis() - buf.bufferedAtMs
        if (ageMs > BUFFER_TTL_MS) {
            AppLogger.info(TAG, "[Share] consumeBuffer: expired (age=${ageMs}ms)")
            SharedShareStore.cleanSharedFiles(context)
            return null
        }
        AppLogger.info(TAG, "[Share] consumeBuffer: ${buf.share.items.size} item(s)")
        return buf.share
    }
}
