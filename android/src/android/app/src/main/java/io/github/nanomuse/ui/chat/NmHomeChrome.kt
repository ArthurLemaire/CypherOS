package io.github.nanomuse.ui.chat

import android.content.SharedPreferences
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.openminis.app.ui.settings.KEY_NM_HEADER_MODEL
import com.openminis.app.ui.settings.getAppearancePrefs
import com.openminis.app.ui.settings.headerModelEnabled
import io.github.nanomuse.ui.home.MuseTones

/**
 * Passed to `ChatScreen` when it is hosted inside the home shell (`io.github.nanomuse.ui.home`).
 * It swaps the back arrow for Muse's hamburger, the kebab for a round button, and — for the
 * main chat — grows the header into Muse's big-face layout; side chats get their title instead.
 * It also switches the conversation to Muse's dress: grey bubbles for the agent, the one-row
 * composer pill, no per-message name.
 */
data class NmHomeChrome(
    val isMainChat: Boolean,
    val onOpenDrawer: () -> Unit,
)

/**
 * Whether the header shows the model rows under the name (Settings → Appearance). Observed, so
 * flipping the switch and coming back to the home applies without a relaunch.
 */
@Composable
fun rememberHeaderModelShown(): State<Boolean> {
    val context = LocalContext.current
    val state = remember { mutableStateOf(headerModelEnabled(context)) }
    DisposableEffect(Unit) {
        val prefs = getAppearancePrefs(context)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { p, key ->
            if (key == KEY_NM_HEADER_MODEL) state.value = p.getBoolean(KEY_NM_HEADER_MODEL, false)
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        onDispose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }
    return state
}

/**
 * Muse's grey bubble around one block of the agent's reply. Each top-level block of a message
 * (a paragraph, a list) is its own bubble, which is also how Muse breaks a long reply up. Code
 * blocks, tables and the app's own `nanomuse-*` cards carry their own frame and are left bare.
 */
@Composable
fun NmAssistantBubble(
    enabled: Boolean,
    rawText: String,
    content: @Composable () -> Unit,
) {
    val bare = !enabled || isBareBlock(rawText)
    if (bare) {
        content()
        return
    }
    Box(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp), contentAlignment = Alignment.TopStart) {
        Box(
            modifier = Modifier
                .widthIn(max = 340.dp)
                .clip(RoundedCornerShape(20.dp))
                .background(MuseTones.bubble)
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            content()
        }
    }
}

private fun isBareBlock(raw: String): Boolean {
    val t = raw.trimStart()
    return t.startsWith("```") || t.startsWith("~~~") || t.startsWith("|") || t.startsWith("<")
}
