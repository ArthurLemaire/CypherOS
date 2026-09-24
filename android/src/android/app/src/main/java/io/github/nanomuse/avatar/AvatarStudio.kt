package io.github.nanomuse.avatar

import android.content.Context
import android.graphics.Bitmap
import androidx.annotation.StringRes
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.ui.avatar.AgentMood
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import java.io.File

/**
 * Making a face: four candidates from one description, the user picks one, and the picked one
 * is posed for each mood by the image model. State lives here so the page can be left and come
 * back while the model is still drawing.
 */
object AvatarStudio {
    private const val TAG = "Avatar"
    const val CANDIDATES = 4

    enum class Style(val id: String, @StringRes val label: Int, val phrase: String) {
        FLAT("flat", R.string.nm_avatar_style_flat, "flat vector illustration, soft pastel colours, clean simple shapes, subtle shading"),
        CLAY("clay", R.string.nm_avatar_style_clay, "3D clay render, soft studio lighting, matte rounded forms, gentle colours"),
        WATERCOLOR("watercolor", R.string.nm_avatar_style_watercolor, "gentle watercolour painting, soft edges, light paper texture"),
        PIXEL("pixel", R.string.nm_avatar_style_pixel, "crisp pixel art, limited palette, clean silhouette"),
        LINE("line", R.string.nm_avatar_style_line, "minimal line drawing with two accent colours on cream, confident strokes"),
        STICKER("sticker", R.string.nm_avatar_style_sticker, "glossy sticker style, thick white outline, bold saturated colours");

        companion object {
            fun byId(id: String?): Style = entries.firstOrNull { it.id == id } ?: FLAT
        }
    }

    sealed class Slot {
        data object Empty : Slot()
        data object Loading : Slot()
        data class Ready(val bitmap: Bitmap, val file: File) : Slot()
        data class Failed(val message: String) : Slot()
    }

    data class MoodProgress(val done: Int, val total: Int, val failed: List<AgentMood>, val running: Boolean)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var candidateJob: Job? = null
    private var moodJob: Job? = null
    /** Image endpoints throttle hard; two in flight is what most of them tolerate. */
    private val lane = Semaphore(2)
    private var lastRequest: Triple<String, Style, ImageGen.Endpoint>? = null

    internal fun looksRateLimited(e: Throwable): Boolean {
        val m = e.message.orEmpty().lowercase()
        return "429" in m || "rate" in m || "throttl" in m || "too many" in m || "limit" in m
    }

    /** Runs [block] in a lane, retrying a rate-limited call twice with a growing pause. */
    private suspend fun <T> throttled(block: suspend () -> T): T {
        var attempt = 0
        while (true) {
            try {
                return lane.withPermit { block() }
            } catch (e: Exception) {
                if (attempt >= 2 || !looksRateLimited(e)) throw e
                attempt += 1
                delay(4_000L * attempt)
            }
        }
    }

    private val _slots = MutableStateFlow(List<Slot>(CANDIDATES) { Slot.Empty })
    val slots: StateFlow<List<Slot>> = _slots
    private val _selected = MutableStateFlow<Int?>(null)
    val selected: StateFlow<Int?> = _selected
    private val _moodProgress = MutableStateFlow<MoodProgress?>(null)
    val moodProgress: StateFlow<MoodProgress?> = _moodProgress
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error

    /** Description and style of the current candidates, so the page can restore its fields. */
    val description = MutableStateFlow("")
    val style = MutableStateFlow(Style.FLAT)

    private const val PREFS = "nanomuse"

    fun init(context: Context) {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        description.value = prefs.getString("avatar.description", "").orEmpty()
        style.value = Style.byId(prefs.getString("avatar.style", null))
        // Earlier candidates are still there: no need to pay for them again.
        val dir = AvatarStore.candidatesDir()
        _slots.value = List(CANDIDATES) { i ->
            val f = File(dir, "$i.png")
            AvatarStore.decodeBitmap(f)?.let { Slot.Ready(it, f) } ?: Slot.Empty
        }
    }

    val generating: Boolean get() = _slots.value.any { it is Slot.Loading }

    fun select(index: Int?) { _selected.value = index }

    fun dismissError() { _error.value = null }

    /** Four pictures from one sentence; each slot fills in as its picture arrives. */
    fun generateCandidates(context: Context, desc: String, chosen: Style) {
        val ep = ImageGen.endpoint(context) ?: run {
            _error.value = context.getString(R.string.nm_avatar_no_provider); return
        }
        if (ep.model.isBlank()) { _error.value = context.getString(R.string.nm_avatar_no_model); return }
        val text = desc.trim().ifEmpty { context.getString(R.string.nm_avatar_default_description) }
        description.value = text
        style.value = chosen
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString("avatar.description", text).putString("avatar.style", chosen.id).apply()
        candidateJob?.cancel()
        _selected.value = null
        _error.value = null
        _slots.value = List(CANDIDATES) { Slot.Loading }
        lastRequest = Triple(text, chosen, ep)
        candidateJob = scope.launch {
            (0 until CANDIDATES).map { i -> async { drawCandidate(context, ep, text, chosen, i) } }.awaitAll()
            if (_slots.value.all { it is Slot.Failed }) {
                _error.value = (_slots.value.first() as Slot.Failed).message
            }
        }
    }

    /** One tile again, after a failure. */
    fun retrySlot(context: Context, index: Int) {
        val (text, chosen, ep) = lastRequest ?: return
        if (_slots.value.getOrNull(index) !is Slot.Failed) return
        _slots.value = _slots.value.toMutableList().also { it[index] = Slot.Loading }
        scope.launch { drawCandidate(context, ep, text, chosen, index) }
    }

    private suspend fun drawCandidate(context: Context, ep: ImageGen.Endpoint, text: String, chosen: Style, i: Int) {
        val dir = AvatarStore.candidatesDir()
        val prompt = buildPrompt(text, chosen, i)
        val result = runCatching { throttled { ImageGen.generate(context, ep, prompt) } }
        val slot = result.fold(
            onSuccess = { bmp ->
                val f = File(dir, "$i.png")
                AvatarStore.write(f, bmp)
                Slot.Ready(AvatarStore.decodeBitmap(f) ?: bmp, f)
            },
            onFailure = { e ->
                AppLogger.warning(TAG, "candidate $i failed: ${e.message}")
                Slot.Failed(e.message ?: "failed")
            },
        )
        _slots.value = _slots.value.toMutableList().also { it[i] = slot }
    }

    /** The picked candidate becomes the face; the moods follow in the background. */
    fun adopt(context: Context, index: Int) {
        val slot = _slots.value.getOrNull(index) as? Slot.Ready ?: return
        val ep = ImageGen.endpoint(context)
        AvatarStore.adopt(slot.bitmap, description.value, style.value.id, ep?.model.orEmpty())
        _selected.value = null
        generateMoods(context)
    }

    /** Pose the current face for each mood. Skips moods that already have a picture. */
    fun generateMoods(context: Context, force: Boolean = false) {
        val ep = ImageGen.endpoint(context) ?: return
        val base = AvatarStore.decodeBitmap(AvatarStore.baseFile()) ?: return
        val todo = AgentMood.entries.filter { it != AgentMood.IDLE && (force || !AvatarStore.moodFile(it).exists()) }
        if (todo.isEmpty()) return
        moodJob?.cancel()
        _moodProgress.value = MoodProgress(0, todo.size, emptyList(), running = true)
        moodJob = scope.launch {
            val failed = java.util.Collections.synchronizedList(mutableListOf<AgentMood>())
            val done = java.util.concurrent.atomic.AtomicInteger(0)
            todo.map { mood ->
                async {
                    val result = runCatching { throttled { ImageGen.edit(context, ep, base, moodInstruction(mood)) } }
                    result.onSuccess { AvatarStore.putMood(mood, it) }
                        .onFailure { AppLogger.warning(TAG, "mood $mood failed: ${it.message}"); failed += mood }
                    _moodProgress.value = MoodProgress(done.incrementAndGet(), todo.size, failed.toList(), running = true)
                }
            }.awaitAll()
            _moodProgress.value = MoodProgress(done.get(), todo.size, failed.toList(), running = false)
        }
    }

    fun reset(context: Context) {
        moodJob?.cancel()
        _moodProgress.value = null
        AvatarStore.reset()
    }

    fun clearMoodProgress() { if (_moodProgress.value?.running == false) _moodProgress.value = null }

    internal fun buildPrompt(desc: String, style: Style, index: Int): String {
        val variation = listOf(
            "warm palette, three-quarter view",
            "cool palette, facing the viewer",
            "playful mood, slight head tilt",
            "calm mood, soft light from the left",
        )[index % 4]
        val subject = desc.trim().trimEnd('.', '。', '!', '！')
        return "$subject. ${style.phrase}. Character portrait for an app avatar: head and shoulders, " +
            "centred, large readable face, friendly expression, plain single-colour soft background, " +
            "$variation. No text, no watermark, no border, no extra characters."
    }

    internal fun moodInstruction(mood: AgentMood): String {
        val keep = "Keep this exact character — same face, colours, outfit, art style, framing and background. "
        return keep + when (mood) {
            AgentMood.WORKING -> "It now wears headphones and is typing on a small laptop in front of it, focused and content."
            AgentMood.WAITING -> "It now looks up at the viewer expectantly with raised eyebrows, one hand slightly raised, a small question mark floating beside its head."
            AgentMood.HAPPY -> "It is now celebrating, hugging a big glowing yellow star, eyes closed with a wide smile. " +
                "Keep the same plain background; no confetti, no night sky, no extra decoration."
            AgentMood.ERROR -> "It now looks sheepish and apologetic, a small sweat drop on its forehead, one hand behind its head."
            AgentMood.IDLE -> "No change."
        }
    }
}
