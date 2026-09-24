package io.github.nanomuse.status

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalView
import com.openminis.app.service.SessionActivityTracker
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * The screen stays on while the agent is driving something the user would otherwise watch go
 * dark: the in-app browser, or another app through the accessibility service. Ordinary chat and
 * shell work let the screen time out as usual.
 */
object KeepAwake {
    /** How long after the last accessibility / browser action the work still counts as ongoing. */
    private const val RECENT_MS = 3 * 60_000L

    private val _lastA11yAt = MutableStateFlow(0L)
    val lastA11yAt: StateFlow<Long> = _lastA11yAt

    /** Called by the android-a11y-cli handler on every command. */
    fun a11yTouched() { _lastA11yAt.value = System.currentTimeMillis() }

    @Composable
    fun Effect(isStreaming: Boolean) {
        val view = LocalView.current
        val toolName by SessionActivityTracker.currentToolName.collectAsState()
        val toolRunning by SessionActivityTracker.isToolRunning.collectAsState()
        val a11yAt by lastA11yAt.collectAsState()
        var browserAt by remember { mutableStateOf(0L) }
        LaunchedEffect(toolRunning, toolName) {
            if (toolRunning && toolName == "browser_use") browserAt = System.currentTimeMillis()
        }
        // Re-evaluate on a timer so the flag drops once the recent window passes.
        var now by remember { mutableStateOf(System.currentTimeMillis()) }
        LaunchedEffect(isStreaming) {
            while (isStreaming) { now = System.currentTimeMillis(); delay(15_000L) }
        }
        val awake = isStreaming && (now - a11yAt < RECENT_MS || now - browserAt < RECENT_MS || (toolRunning && toolName == "browser_use"))
        DisposableEffect(awake, view) {
            view.keepScreenOn = awake
            onDispose { view.keepScreenOn = false }
        }
    }
}
