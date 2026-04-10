package io.github.nanomuse.ui.home

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

/** Route of the full OpenMinis session list when opened from the drawer's archive glyph. */
const val ROUTE_ALL_CHATS = "nanomuse/all_chats"

/**
 * Requests to the home shell from places that cannot see it (a card inside a chat message, an
 * idea sheet, the all-chats screen that sits above the shell on the back stack). The last
 * request is replayed so a shell that is only recomposed after the sender pops still gets it;
 * the shell clears the replay once handled.
 */
object HomeBus {
    sealed class Request {
        data class ShowTab(val tab: HomeTab) : Request()
        data class ShowSession(val sessionId: String) : Request()
    }

    private val _requests = MutableSharedFlow<Request>(replay = 1, extraBufferCapacity = 8)
    val requests: SharedFlow<Request> = _requests

    fun showTab(tab: HomeTab) { _requests.tryEmit(Request.ShowTab(tab)) }

    fun showSession(sessionId: String) { _requests.tryEmit(Request.ShowSession(sessionId)) }

    @Suppress("EXPERIMENTAL_API_USAGE")
    fun handled() { _requests.resetReplayCache() }
}
