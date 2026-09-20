package com.openminis.app.service

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.LinkedList
import kotlin.coroutines.Continuation
import kotlin.coroutines.resume

/**
 * Limits concurrent agent loop sessions to [maxConcurrent].
 * Excess sessions are suspended in a FIFO queue until a slot frees up.
 */
object SessionConcurrencyManager {
    const val MAX_CONCURRENT = 5

    private val _runningSessions = MutableStateFlow<Set<String>>(emptySet())
    val runningSessions: StateFlow<Set<String>> = _runningSessions.asStateFlow()

    private val _suspendedSessions = MutableStateFlow<List<String>>(emptyList())
    val suspendedSessions: StateFlow<List<String>> = _suspendedSessions.asStateFlow()

    private data class Waiter(val sessionId: String, val continuation: Continuation<Unit>)
    private val waitQueue = LinkedList<Waiter>()

    suspend fun acquireSlot(sessionId: String) {
        if (_runningSessions.value.size < MAX_CONCURRENT) {
            _runningSessions.value = _runningSessions.value + sessionId
            return
        }

        // Queue and suspend
        _suspendedSessions.value = _suspendedSessions.value + sessionId
        suspendCancellableCoroutine { cont ->
            synchronized(this@SessionConcurrencyManager) {
                waitQueue.add(Waiter(sessionId, cont))
            }
            cont.invokeOnCancellation {
                synchronized(this@SessionConcurrencyManager) {
                    waitQueue.removeAll { it.sessionId == sessionId }
                    _suspendedSessions.value = _suspendedSessions.value - sessionId
                }
            }
        }
    }

    @Synchronized
    fun releaseSlot(sessionId: String) {
        _runningSessions.value = _runningSessions.value - sessionId

        // Resume next waiter
        val next = synchronized(this) { waitQueue.pollFirst() }
        if (next != null) {
            _suspendedSessions.value = _suspendedSessions.value - next.sessionId
            _runningSessions.value = _runningSessions.value + next.sessionId
            next.continuation.resume(Unit)
        }
    }

    fun isSuspended(sessionId: String): Boolean = sessionId in _suspendedSessions.value
}
