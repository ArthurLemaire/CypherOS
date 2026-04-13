package io.github.nanomuse.ui.avatar

import androidx.annotation.DrawableRes
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import com.openminis.app.R
import com.openminis.app.config.confirm.ConfigConfirmationGate
import com.openminis.app.offload.OffloadPermissionManager
import com.openminis.app.service.SessionActivityTracker
import com.openminis.app.service.ToolOutcome
import kotlinx.coroutines.delay

/** What the red panda's face is doing. One drawable per mood, see scripts/gen-avatar.py. */
enum class AgentMood(@DrawableRes val drawable: Int) {
    IDLE(R.drawable.nm_avatar_idle),
    WORKING(R.drawable.nm_avatar_working),
    WAITING(R.drawable.nm_avatar_waiting),
    HAPPY(R.drawable.nm_avatar_happy),
    ERROR(R.drawable.nm_avatar_error),
}

private const val HAPPY_AFTERGLOW_MS = 3_000L
private const val ERROR_AFTERGLOW_MS = 4_000L

/**
 * The mood of the chat header, derived from the session's own streaming flag and the app-wide
 * "it needs you" gates. Nothing here is new state: waiting comes from the permission and config
 * confirmation queues, working from [isStreaming], and the short smile / wince after a turn ends
 * is the only thing remembered locally.
 */
@Composable
fun rememberAgentMood(isStreaming: Boolean, error: String?): AgentMood {
    val pendingPermission by OffloadPermissionManager.pendingRequest.collectAsState()
    val pendingAndroidPermission by OffloadPermissionManager.pendingAndroidPermission.collectAsState()
    val pendingSettingsGate by OffloadPermissionManager.pendingSettingsGate.collectAsState()
    val pendingConfig by ConfigConfirmationGate.pending.collectAsState()
    val waiting = pendingPermission != null || pendingAndroidPermission != null ||
        pendingSettingsGate != null || pendingConfig != null

    var afterglow by remember { mutableStateOf<AgentMood?>(null) }
    var previousStreaming by remember { mutableStateOf(isStreaming) }
    LaunchedEffect(isStreaming) {
        if (previousStreaming && !isStreaming) {
            val outcome = SessionActivityTracker.lastToolOutcome.value
            val failed = error != null || outcome == ToolOutcome.Error || outcome == ToolOutcome.Timeout
            afterglow = if (failed) AgentMood.ERROR else AgentMood.HAPPY
            delay(if (failed) ERROR_AFTERGLOW_MS else HAPPY_AFTERGLOW_MS)
            afterglow = null
        }
        previousStreaming = isStreaming
    }

    return when {
        waiting -> AgentMood.WAITING
        isStreaming -> AgentMood.WORKING
        else -> afterglow ?: AgentMood.IDLE
    }
}

/**
 * The red panda at [size], cross-fading between moods and breathing while it works.
 * Tapping it is how the user customises the agent (name, icon, style), like Muse's avatar.
 */
@Composable
fun AgentAvatar(
    mood: AgentMood,
    size: Dp,
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
    onClick: (() -> Unit)? = null,
) {
    val breathing = rememberInfiniteTransition(label = "avatarBreathing")
    val breath by breathing.animateFloat(
        initialValue = 1f,
        targetValue = 1.05f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 800, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "avatarBreath",
    )
    val scale = if (mood == AgentMood.WORKING) breath else 1f
    val base = modifier
        .size(size)
        .scale(scale)
        .clip(CircleShape)
    Crossfade(
        targetState = mood,
        animationSpec = tween(durationMillis = 220),
        label = "avatarMood",
        modifier = if (onClick != null) base.clickable(onClick = onClick) else base,
    ) { current ->
        Image(
            painter = painterResource(current.drawable),
            contentDescription = contentDescription,
            modifier = Modifier.size(size),
        )
    }
}
