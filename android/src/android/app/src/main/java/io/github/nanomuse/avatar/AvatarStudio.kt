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
import kotlinx.coroutines.flow.update
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
        // Muse's house style: a small 3D toy figure, soft studio light, white ground — the
        // default, and the one the in-chat "change your avatar to …" flow uses.
        MUSE("muse", R.string.nm_avatar_style_muse, "cute 3D character render in the style of a collectible vinyl toy, soft matte materials with subtle sheen, rounded simplified forms, big friendly eyes, soft studio lighting with gentle shadows, pastel accents"),
        FLAT("flat", R.string.nm_avatar_style_flat, "flat vector illustration, soft pastel colours, clean simple shapes, subtle shading"),
        CLAY("clay", R.string.nm_avatar_style_clay, "3D clay render, soft studio lighting, matte rounded forms, gentle colours"),
        WATERCOLOR("watercolor", R.string.nm_avatar_style_watercolor, "gentle watercolour painting, soft edges, light paper texture"),
        PIXEL("pixel", R.string.nm_avatar_style_pixel, "crisp pixel art, limited palette, clean silhouette"),
        LINE("line", R.string.nm_avatar_style_line, "minimal line drawing with two accent colours on cream, confident strokes"),
        STICKER("sticker", R.string.nm_avatar_style_sticker, "glossy sticker style, thick white outline, bold saturated colours");

        companion object {
            fun byId(id: String?): Style = entries.firstOrNull { it.id == id } ?: MUSE
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
    /** A picture the user attached with the request ("make it look like this"), for the current candidates. */
    private var reference: Bitmap? = null

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
    val style = MutableStateFlow(Style.MUSE)

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

    /**
     * Four pictures from one sentence; each slot fills in as its picture arrives. With a
     * [referenceImage] the pictures are drawn *from* it (the edit endpoint) so the character
     * keeps what the user showed — "make it look like my cat".
     * @return false when no image model is configured (the error flow says which).
     */
    fun generateCandidates(context: Context, desc: String, chosen: Style, referenceImage: Bitmap? = null): Boolean {
        val ep = ImageGen.endpoint(context) ?: run {
            _error.value = context.getString(R.string.nm_avatar_no_provider); return false
        }
        if (ep.model.isBlank()) { _error.value = context.getString(R.string.nm_avatar_no_model); return false }
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
        reference = referenceImage
        candidateJob = scope.launch {
            (0 until CANDIDATES).map { i -> async { drawCandidate(context, ep, text, chosen, i) } }.awaitAll()
            if (_slots.value.all { it is Slot.Failed }) {
                _error.value = (_slots.value.first() as Slot.Failed).message
            }
        }
        return true
    }

    /** The same sentence again — a fresh set of four. */
    fun regenerate(context: Context): Boolean {
        val (text, chosen, _) = lastRequest ?: return false
        return generateCandidates(context, text, chosen, reference)
    }

    /** One tile again, after a failure. */
    fun retrySlot(context: Context, index: Int) {
        val (text, chosen, ep) = lastRequest ?: return
        if (_slots.value.getOrNull(index) !is Slot.Failed) return
        _slots.update { list -> list.toMutableList().also { it[index] = Slot.Loading } }
        scope.launch { drawCandidate(context, ep, text, chosen, index) }
    }

    private suspend fun drawCandidate(context: Context, ep: ImageGen.Endpoint, text: String, chosen: Style, i: Int) {
        val dir = AvatarStore.candidatesDir()
        val prompt = buildPrompt(text, chosen, i)
        val ref = reference
        val result = runCatching {
            throttled {
                if (ref != null) ImageGen.edit(context, ep, ref, REFERENCE_PREFIX + prompt)
                else ImageGen.generate(context, ep, prompt)
            }
        }
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
        // Atomic: the four candidates finish on different threads, and a plain
        // read-modify-write here would let one tile's result overwrite another's.
        _slots.update { list -> list.toMutableList().also { it[i] = slot } }
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

    /** Prepended when the candidates are drawn from a picture the user attached. */
    private const val REFERENCE_PREFIX = "Redraw the subject of this picture as the character described, keeping its recognisable features (species, colours, markings, hairstyle, accessories). "

    /**
     * Muse's house rules for the four candidates: the same subject four times, each a different
     * breed / colouring / outfit, full body, facing the viewer, centred on pure white, square. The
     * style phrase decides 3D toy (default) vs the older 2D styles kept for the studio page.
     */
    internal fun buildPrompt(desc: String, style: Style, index: Int): String {
        val variation = listOf(
            "variation 1: the most typical, classic colouring",
            "variation 2: a different breed or colour pattern, lighter tones",
            "variation 3: a different breed or colour pattern, darker or warmer tones, a small accessory such as a scarf or glasses",
            "variation 4: a playful take — unusual colouring or a tiny outfit, slight head tilt",
        )[index % 4]
        val subject = desc.trim().trimEnd('.', '。', '!', '！', ',', '，')
        return "A cute character based on: $subject. ${style.phrase}. Full body, standing, facing the viewer, " +
            "centred, whole figure visible with margin on all sides, big head and small body, friendly expression, " +
            "pure white background, soft ground shadow only. $variation. " +
            "Square composition. No text, no watermark, no border, no props other than what is described, one character only."
    }

    /**
     * The fixed poses the face cycles through — Muse's set: idle (the picture itself), working
     * with headphones at a laptop, waiting with a crystal ball, happy with a star, sorry with a
     * sweat drop. Each is an edit of the chosen picture so the character stays the same.
     */
    internal fun moodInstruction(mood: AgentMood): String {
        val keep = "Keep this exact character — same face, colours, outfit, art style, proportions, framing, " +
            "camera angle and pure white background. Change only the pose and props described. "
        return keep + when (mood) {
            AgentMood.WORKING -> "It now wears over-ear headphones and sits typing on a small open laptop in front of it, focused and content, a faint glow from the screen on its face."
            AgentMood.WAITING -> "It now holds a small glowing crystal ball in both hands at chest height and gazes into it with wide curious eyes, waiting for an answer."
            AgentMood.HAPPY -> "It is now celebrating, hugging a big glowing yellow five-pointed star, eyes closed with a wide smile. " +
                "Same white background; no confetti, no night sky, no extra decoration."
            AgentMood.ERROR -> "It now looks sheepish and apologetic, a small sweat drop beside its head, one hand behind its head, shoulders slightly raised."
            AgentMood.IDLE -> "No change."
        }
    }
}
