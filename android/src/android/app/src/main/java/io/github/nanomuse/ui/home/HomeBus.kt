package io.github.nanomuse.ui.home

import androidx.navigation.NavController
import com.openminis.app.ui.navigation.Routes
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
        /** Show the main chat with [text] typed into the composer and the keyboard up. */
        data class PrefillComposer(val text: String) : Request()
    }

    private val _requests = MutableSharedFlow<Request>(replay = 1, extraBufferCapacity = 8)
    val requests: SharedFlow<Request> = _requests

    fun showTab(tab: HomeTab) { _requests.tryEmit(Request.ShowTab(tab)) }

    fun showSession(sessionId: String) { _requests.tryEmit(Request.ShowSession(sessionId)) }

    fun prefillComposer(text: String) { _requests.tryEmit(Request.PrefillComposer(text)) }

    @Suppress("EXPERIMENTAL_API_USAGE")
    fun handled() { _requests.resetReplayCache() }
}

/**
 * Whether the home shell is what `Routes.SESSION_LIST` renders right now (compact windows), and
 * the one way to open a chat while it is.
 *
 * Every "open this session" entry point — a notification, the tool capsule, Hands bringing the
 * app back after a run — lands in upstream code that pushes `chat/{sessionId}` on the back
 * stack. On a phone that is the OpenMinis chat screen sitting on top of the shell: no Muse
 * header, no tabs, the old look. [openSession] takes those requests to the shell instead.
 */
object HomeShell {
    /** Set by AppNavigation from the window size class; read from MainActivity's warm-start path. */
    @Volatile var active: Boolean = false

    /**
     * Shows [sessionId] inside the shell — pops back to it if something sits on top, or mounts
     * it when the graph started elsewhere — and returns true. Returns false in wide windows,
     * where the caller keeps the upstream list/detail route.
     */
    fun openSession(nav: NavController, sessionId: String): Boolean {
        if (!active) return false
        val shellRoute = Routes.SESSION_LIST
        val onStack = try {
            nav.getBackStackEntry(shellRoute); true
        } catch (_: IllegalArgumentException) {
            false
        }
        if (onStack) {
            nav.popBackStack(shellRoute, inclusive = false) // no-op when the shell is already on top
        } else {
            nav.navigate(shellRoute) { popUpTo(nav.graph.startDestinationId) { inclusive = true } }
        }
        HomeBus.showSession(sessionId)
        return true
    }
}
