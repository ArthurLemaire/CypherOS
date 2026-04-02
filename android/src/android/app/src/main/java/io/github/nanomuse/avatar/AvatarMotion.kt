package io.github.nanomuse.avatar

import android.content.Context
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.media.MediaModels
import io.github.nanomuse.media.VideoGen
import io.github.nanomuse.ui.avatar.AgentMood
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.io.File

/**
 * The face in motion: one short looping clip per mood, drawn from that mood's pose by the video
 * model — Muse's fixed set: a head shake and a sway at rest, the crystal ball while waiting, the
 * five-pointed star when pleased, headphones and a laptop while working. Clips live next to the
 * pictures (`avatar/motion/<mood>.mp4`) and the header plays whichever exists for the current
 * mood, falling back to the still picture. Clips are made one after another (each takes a few
 * minutes and costs the user per second) and only when a video model is set.
 */
object AvatarMotion {
    private const val TAG = "AvatarMotion"
    const val SECONDS = 4

    /** The moods that get a clip, in the order they are drawn: the one seen most first. */
    val animated: List<AgentMood> = listOf(AgentMood.IDLE, AgentMood.WORKING, AgentMood.WAITING, AgentMood.HAPPY)

    data class Progress(
        val done: Int,
        val total: Int,
        val failed: List<AgentMood>,
        val running: Boolean,
        val current: AgentMood? = null,
        val stage: VideoGen.Progress? = null,
        val error: String? = null,
    )

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null
    private val _progress = MutableStateFlow<Progress?>(null)
    val progress: StateFlow<Progress?> = _progress
    private val _clips = MutableStateFlow<Map<AgentMood, File>>(emptyMap())
    /** The clips on disk, by mood. */
    val clips: StateFlow<Map<AgentMood, File>> = _clips

    private fun dir(): File = File(AvatarStore.root(), "motion").apply { mkdirs() }
    fun clipFile(mood: AgentMood): File = File(dir(), mood.name.lowercase() + ".mp4")

    fun init() { rescan() }

    fun rescan() {
        _clips.value = AgentMood.entries.mapNotNull { m -> clipFile(m).takeIf { it.exists() && it.length() > 0 }?.let { m to it } }.toMap()
    }

    /** A new face, or none: the old clips belonged to the old face. */
    fun clear() {
        job?.cancel()
        _progress.value = null
        dir().listFiles()?.forEach { it.delete() }
        rescan()
    }

    /** True when a video model is set and the user has not turned the animation off. */
    fun enabled(context: Context): Boolean = MediaModels.animateAvatar(context) && MediaModels.videoEndpoint(context) != null

    /**
     * Draws the missing clips (all of them with [force]). No-op without a face or a video model.
     * Returns false when nothing was started.
     */
    fun animateAll(context: Context, force: Boolean = false): Boolean {
        val ep = MediaModels.videoEndpoint(context) ?: return false
        if (!AvatarStore.baseFile().exists()) return false
        val todo = animated.filter { force || !clipFile(it).exists() }
        if (todo.isEmpty()) return false
        job?.cancel()
        _progress.value = Progress(0, todo.size, emptyList(), running = true)
        job = scope.launch {
            val failed = mutableListOf<AgentMood>()
            var lastError: String? = null
            todo.forEachIndexed { i, mood ->
                _progress.value = Progress(i, todo.size, failed.toList(), running = true, current = mood)
                val frame = AvatarStore.decodeBitmap(AvatarStore.moodFile(mood).takeIf { it.exists() } ?: AvatarStore.baseFile())
                if (frame == null) { failed += mood; return@forEachIndexed }
                val result = runCatching {
                    VideoGen.imageToVideo(ep, frame, motionPrompt(mood), SECONDS) { stage ->
                        _progress.value = Progress(i, todo.size, failed.toList(), running = true, current = mood, stage = stage)
                    }
                }
                result.onSuccess { bytes ->
                    val f = clipFile(mood)
                    val tmp = File(f.parentFile, f.name + ".tmp")
                    tmp.writeBytes(bytes)
                    if (!tmp.renameTo(f)) { f.delete(); tmp.renameTo(f) }
                    rescan()
                }.onFailure { e ->
                    AppLogger.warning(TAG, "clip $mood failed: ${e.message}")
                    failed += mood
                    lastError = e.message
                }
            }
            _progress.value = Progress(todo.size, todo.size, failed.toList(), running = false, error = lastError)
        }
        return true
    }

    fun cancel() {
        job?.cancel()
        _progress.value = _progress.value?.copy(running = false)
    }

    fun clearProgress() { if (_progress.value?.running == false) _progress.value = null }

    /** Muse's fixed motions, one per mood, on top of the pose picture. */
    internal fun motionPrompt(mood: AgentMood): String {
        val action = when (mood) {
            AgentMood.IDLE -> "The character stays in place and gently shakes its head left and right while its round body sways very slightly, calm and friendly, like the idle animation of a mascot."
            AgentMood.WAITING -> "The character holds a small glowing crystal ball in its hands and plays with it, turning it slowly and peeking into it with curiosity."
            AgentMood.HAPPY -> "The character plays happily with a small golden five-pointed star, tossing it up a little and catching it, bouncing gently with joy."
            AgentMood.WORKING -> "The character wears headphones and types busily on the small laptop in front of it, nodding slightly to the rhythm, focused and content."
            AgentMood.ERROR -> "The character looks a little flustered, a sweat drop on its brow, then takes a breath and settles."
        }
        return "$action Plain white background, static camera, no zoom, no cuts, soft even studio lighting, the same 3D toy look as the picture throughout, " +
            "nothing else appears in the frame, and the motion loops naturally with the character back in its starting pose at the end."
    }
}
