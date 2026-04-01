package io.github.nanomuse.ui.avatar

import androidx.annotation.DrawableRes
import androidx.annotation.RawRes
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.config.confirm.ConfigConfirmationGate
import com.openminis.app.offload.OffloadPermissionManager
import com.openminis.app.service.SessionActivityTracker
import com.openminis.app.service.ToolOutcome
import io.github.nanomuse.avatar.AvatarStore
import kotlinx.coroutines.delay

/**
 * What the face is doing. The built-in character — a small pale-yellow dragon, drawn and posed
 * with qwen-image-3.0-pro and animated with MiniMax-H3, the same way a user's own face is —
 * has a still per mood and a 4-second looping clip for the four moods that last long enough
 * to move; a custom face has a picture per mood when the image model could pose it.
 */
enum class AgentMood(@DrawableRes val drawable: Int, @RawRes val motion: Int?) {
    IDLE(R.drawable.nm_avatar_idle, R.raw.nm_motion_idle),
    WORKING(R.drawable.nm_avatar_working, R.raw.nm_motion_working),
    WAITING(R.drawable.nm_avatar_waiting, R.raw.nm_motion_waiting),
    HAPPY(R.drawable.nm_avatar_happy, R.raw.nm_motion_happy),
    ERROR(R.drawable.nm_avatar_error, null),
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
    val pendingRisk by io.github.nanomuse.guard.RiskGate.pending.collectAsState()
    val waiting = pendingPermission != null || pendingAndroidPermission != null ||
        pendingSettingsGate != null || pendingConfig != null || pendingRisk != null

    // The tracker's last tool outcome is sticky across turns, so only an outcome that landed
    // during *this* run may colour the afterglow: a plain reply after an old failure is a
    // success, not a second wince.
    var runOutcome by remember { mutableStateOf<ToolOutcome?>(null) }
    LaunchedEffect(isStreaming) {
        if (isStreaming) {
            runOutcome = null
            SessionActivityTracker.lastToolOutcome.collect { o ->
                if (o != ToolOutcome.Unknown) runOutcome = o
            }
        }
    }

    var afterglow by remember { mutableStateOf<AgentMood?>(null) }
    var previousStreaming by remember { mutableStateOf(isStreaming) }
    LaunchedEffect(isStreaming) {
        if (previousStreaming && !isStreaming) {
            val outcome = runOutcome
            val failed = error != null || outcome == ToolOutcome.Error || outcome == ToolOutcome.Timeout
            // A run the user stopped ends quietly: no smile, no wince.
            if (outcome != ToolOutcome.Cancelled) {
                afterglow = if (failed) AgentMood.ERROR else AgentMood.HAPPY
                delay(if (failed) ERROR_AFTERGLOW_MS else HAPPY_AFTERGLOW_MS)
                afterglow = null
            }
        }
        previousStreaming = isStreaming
    }

    // Drawing a new face is work too (the chat's "change your avatar" flow).
    val avatarStage by io.github.nanomuse.avatar.AvatarFlow.stage.collectAsState()
    val avatarSlots by io.github.nanomuse.avatar.AvatarStudio.slots.collectAsState()
    val drawing = avatarStage is io.github.nanomuse.avatar.AvatarFlow.Stage.Finalizing ||
        (avatarStage is io.github.nanomuse.avatar.AvatarFlow.Stage.Choosing && avatarSlots.any { it is io.github.nanomuse.avatar.AvatarStudio.Slot.Loading })

    return when {
        waiting -> AgentMood.WAITING
        isStreaming || drawing -> AgentMood.WORKING
        else -> afterglow ?: AgentMood.IDLE
    }
}

/**
 * The face at [size]: the built-in dragon, or the user's own picture set from Settings →
 * Appearance. It cross-fades between moods and moves the way Muse's does — a slow breath at
 * rest, a busy bob while working, a curious tilt while waiting, a pop when it is pleased and a
 * quick shake when something failed. Tapping it opens the appearance page.
 */
@Composable
fun AgentAvatar(
    mood: AgentMood,
    size: Dp,
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
    onClick: (() -> Unit)? = null,
) {
    val custom by AvatarStore.current.collectAsState()
    val clips by io.github.nanomuse.avatar.AvatarMotion.clips.collectAsState()
    val density = LocalDensity.current
    val motion = rememberInfiniteTransition(label = "avatarMotion")

    // Rest: a slow, barely visible breath. Working: a quicker one, plus a bob.
    val breath by motion.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(durationMillis = if (mood == AgentMood.WORKING) 700 else 2600, easing = FastOutSlowInEasing),
            RepeatMode.Reverse,
        ),
        label = "breath",
    )
    // Waiting: a gentle side-to-side tilt, as if listening.
    val tilt by motion.animateFloat(
        initialValue = -1f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(durationMillis = 1100, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "tilt",
    )
    // Happy: one springy pop on arrival. Error: one short shake.
    val pop = remember { Animatable(1f) }
    val shake = remember { Animatable(0f) }
    LaunchedEffect(mood) {
        when (mood) {
            AgentMood.HAPPY -> {
                pop.snapTo(1f)
                pop.animateTo(1.14f, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessMedium))
                pop.animateTo(1f, spring(dampingRatio = Spring.DampingRatioLowBouncy, stiffness = Spring.StiffnessLow))
            }
            AgentMood.ERROR -> {
                shake.snapTo(0f)
                shake.animateTo(
                    0f,
                    keyframes {
                        durationMillis = 420
                        -1f at 60 with LinearEasing
                        1f at 140 with LinearEasing
                        -0.6f at 220 with LinearEasing
                        0.6f at 300 with LinearEasing
                        0f at 420
                    },
                )
            }
            else -> { pop.snapTo(1f); shake.snapTo(0f) }
        }
    }

    val scale = when (mood) {
        AgentMood.WORKING -> 1f + 0.045f * breath
        AgentMood.HAPPY -> pop.value
        else -> 1f + 0.018f * breath
    }
    val bobPx = if (mood == AgentMood.WORKING) with(density) { (-2.5).dp.toPx() } * breath else 0f
    val shakePx = with(density) { 3.dp.toPx() } * shake.value
    val rotation = if (mood == AgentMood.WAITING) 4f * tilt else 0f

    val base = modifier
        .size(size)
        .graphicsLayer {
            scaleX = scale
            scaleY = scale
            translationY = bobPx
            translationX = shakePx
            rotationZ = rotation
        }
        .clip(CircleShape)
    Crossfade(
        targetState = mood,
        animationSpec = tween(durationMillis = 260),
        label = "avatarMood",
        modifier = if (onClick != null) base.clickable(onClick = onClick) else base,
    ) { current ->
        val set = custom
        if (set != null) {
            Image(
                bitmap = set.forMood(current),
                contentDescription = contentDescription,
                contentScale = ContentScale.Crop,
                modifier = Modifier.size(size),
            )
            // The clip for this mood, when the video model has made one: it plays over the
            // still and shows only once its first frame is on screen, so nothing flickers.
            val clip = clips[current]
            if (clip != null) {
                androidx.compose.runtime.key(clip.path) {
                    LoopingClip(key = clip.path, modifier = Modifier.size(size)) { it.setDataSource(clip.path) }
                }
            }
        } else {
            Image(
                painter = painterResource(current.drawable),
                contentDescription = contentDescription,
                contentScale = ContentScale.Crop,
                modifier = Modifier.size(size),
            )
            // The built-in character ships with its clips, so it moves without a video model.
            val res = current.motion
            if (res != null) {
                val context = androidx.compose.ui.platform.LocalContext.current
                androidx.compose.runtime.key(res) {
                    LoopingClip(key = "raw:$res", modifier = Modifier.size(size)) { player ->
                        context.resources.openRawResourceFd(res).use { fd -> player.setDataSource(fd.fileDescriptor, fd.startOffset, fd.length) }
                    }
                }
            }
        }
    }
}

/**
 * The face on its pale disc, the way both headers show it. Every face — the built-in dragon
 * too — brings its own white background and fills the disc.
 */
@Composable
fun AgentAvatarDisc(
    mood: AgentMood,
    discSize: Dp,
    modifier: Modifier = Modifier,
    contentDescription: String? = null,
    onClick: (() -> Unit)? = null,
) {
    androidx.compose.foundation.layout.Box(
        modifier = modifier
            .size(discSize)
            .clip(CircleShape)
            .background(io.github.nanomuse.ui.home.avatarDiscColor()),
        contentAlignment = androidx.compose.ui.Alignment.Center,
    ) {
        AgentAvatar(
            mood = mood,
            size = discSize,
            contentDescription = contentDescription,
            onClick = onClick,
        )
    }
}

/**
 * A muted, looping MP4 on a [android.view.TextureView] — the platform player, no extra
 * dependency; the clips are small H.264 files the video model made. Transparent until the first
 * frame renders, paused while the app is in the background, released with the surface.
 */
@Composable
private fun LoopingClip(key: String, modifier: Modifier = Modifier, open: (android.media.MediaPlayer) -> Unit) {
    var ready by remember(key) { mutableStateOf(false) }
    val player = remember(key) { android.media.MediaPlayer() }
    val lifecycle = androidx.compose.ui.platform.LocalLifecycleOwner.current.lifecycle
    androidx.compose.runtime.DisposableEffect(key) {
        val observer = androidx.lifecycle.LifecycleEventObserver { _, event ->
            runCatching {
                when (event) {
                    androidx.lifecycle.Lifecycle.Event.ON_PAUSE -> if (player.isPlaying) player.pause()
                    androidx.lifecycle.Lifecycle.Event.ON_RESUME -> if (ready && !player.isPlaying) player.start()
                    else -> {}
                }
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            runCatching { player.release() }
        }
    }
    androidx.compose.ui.viewinterop.AndroidView(
        factory = { ctx ->
            android.view.TextureView(ctx).apply {
                isOpaque = false
                surfaceTextureListener = object : android.view.TextureView.SurfaceTextureListener {
                    override fun onSurfaceTextureAvailable(surface: android.graphics.SurfaceTexture, width: Int, height: Int) {
                        runCatching {
                            player.reset()
                            open(player)
                            player.setSurface(android.view.Surface(surface))
                            player.isLooping = true
                            player.setVolume(0f, 0f)
                            player.setVideoScalingMode(android.media.MediaPlayer.VIDEO_SCALING_MODE_SCALE_TO_FIT_WITH_CROPPING)
                            player.setOnPreparedListener { it.start() }
                            player.setOnInfoListener { _, what, _ ->
                                if (what == android.media.MediaPlayer.MEDIA_INFO_VIDEO_RENDERING_START) ready = true
                                false
                            }
                            player.setOnErrorListener { _, _, _ -> true }
                            player.prepareAsync()
                        }
                    }
                    override fun onSurfaceTextureSizeChanged(surface: android.graphics.SurfaceTexture, width: Int, height: Int) {}
                    override fun onSurfaceTextureUpdated(surface: android.graphics.SurfaceTexture) {}
                    override fun onSurfaceTextureDestroyed(surface: android.graphics.SurfaceTexture): Boolean {
                        runCatching { player.setSurface(null) }
                        return true
                    }
                }
            }
        },
        modifier = modifier.graphicsLayer { alpha = if (ready) 1f else 0f },
    )
}
