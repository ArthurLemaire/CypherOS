package io.github.nanomuse.avatar

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import com.openminis.app.R
import io.github.nanomuse.sysfiles.SystemFiles
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Changing the face from inside the conversation, the way Muse does it: a message such as
 * "把虚拟形象换成一只小狗" / "change your avatar to a corgi" is not sent to the model. It starts
 * this flow instead — four candidates drawn in the house style (a picture attached to the
 * message is used as the reference), a card in the chat to pick from (by tap, or by typing
 * "第二个" / "option 2"), then the chosen one becomes the face and its poses are drawn in the
 * background. The chat ViewModel owns the messages; this object owns the state and the words.
 */
object AvatarFlow {
    /** Fence of the options card once it is persisted: `{"desc","chosen","files":[…]}`. */
    const val BLOCK_OPTIONS = "nanomuse-avatar"

    sealed class Stage {
        data object Idle : Stage()

        /** Candidates are being drawn or waiting to be picked. */
        data class Choosing(val sessionId: String, val description: String) : Stage()

        /** One was picked; the poses are being drawn. */
        data class Finalizing(val sessionId: String, val description: String, val chosen: Int) : Stage()
    }

    sealed class Choice {
        data class Index(val index: Int) : Choice()
        data object Regenerate : Choice()
    }

    /** What finished: the description, so the share card can say what the new face is. */
    data class Done(val sessionId: String, val description: String)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private var finishJob: Job? = null

    private val _stage = MutableStateFlow<Stage>(Stage.Idle)
    val stage: StateFlow<Stage> = _stage

    private val _done = MutableSharedFlow<Done>(extraBufferCapacity = 4)
    val done: SharedFlow<Done> = _done

    // ── intent ────────────────────────────────────────────────────────────

    private val zhRequest = listOf(
        // 把/将 (你的/我的)? (虚拟)?形象 (改|换|变|更换|切换|设置)(成|为|到) X
        Regex("^(?:请|麻烦|帮我|帮忙|可以|能不能|能否)?\\s*(?:把|将)?\\s*(?:你的|你|我的|我)?\\s*(?:虚拟)?(?:形象|头像|样子|外形)\\s*(?:改|换|变|更换|切换|设置|设定|变更)(?:成|为|到|一下成|一下为)?\\s*(.+)$"),
        // 换个/换一个 (新)?形象[：,] X   /  换成 X 的形象
        Regex("^(?:请|麻烦|帮我|帮忙)?\\s*(?:换|变|改)(?:个|一个|一下)?\\s*(?:新的?)?(?:虚拟)?(?:形象|头像)\\s*[：:，,、]?\\s*(.+)$"),
        Regex("^(?:请|麻烦|帮我|帮忙)?\\s*(?:变成|化身为|变身为|变身成)\\s*(.+?)\\s*(?:的)?(?:形象|样子|头像)?$"),
    )
    private val enRequest = listOf(
        Regex("^(?:please\\s+)?(?:can you\\s+)?(?:change|switch|set|update|turn|make|transform)\\s+(?:your|the|my|ur)?\\s*(?:virtual\\s+)?(?:avatar|appearance|look|character)\\s+(?:to|into)\\s+(.+)$", RegexOption.IGNORE_CASE),
        Regex("^(?:please\\s+)?(?:new|another)\\s+(?:virtual\\s+)?avatar\\s*[:,-]?\\s*(.+)$", RegexOption.IGNORE_CASE),
        Regex("^(?:please\\s+)?(?:become|be)\\s+(.+)$", RegexOption.IGNORE_CASE),
    )

    /** The description of the new face if [text] asks for one, else null. */
    fun parseRequest(text: String): String? {
        val t = text.trim()
        if (t.isEmpty() || t.length > 400 || t.contains('\n')) return null
        val hit = (zhRequest + enRequest).firstNotNullOfOrNull { it.find(t) } ?: return null
        var desc = hit.groupValues[1].trim().trimEnd('。', '.', '!', '！', '~', '～', '吧', '呗', '呀', '哦', '啊', '嘛')
        // English articles go; "一只小狗" reads better than "小狗" in the announcement, so Chinese counters stay.
        desc = desc.replace(Regex("^(an?|the)\\s+", RegexOption.IGNORE_CASE), "").trim()
        // "be quiet", "become better": only accept the bare verbs with something that reads like a subject.
        if (desc.length < 1 || desc.length > 200) return null
        if (hit.value.startsWith("be ", ignoreCase = true) || hit.value.startsWith("become ", ignoreCase = true)) {
            if (!desc.contains(Regex("\\b(cat|dog|puppy|kitten|robot|bear|panda|fox|rabbit|bunny|bird|dragon|penguin|owl|corgi|shiba|husky|otter|character|creature|monster|alien)\\b", RegexOption.IGNORE_CASE))) return null
        }
        if (hit.value.startsWith("变成") || hit.value.startsWith("化身") || hit.value.startsWith("变身")) {
            if (desc.length < 2) return null
        }
        return desc
    }

    private val ordinalZh = mapOf("一" to 0, "1" to 0, "二" to 1, "两" to 1, "2" to 1, "三" to 2, "3" to 2, "四" to 3, "4" to 3)
    private val ordinalEn = mapOf("first" to 0, "1st" to 0, "second" to 1, "2nd" to 1, "third" to 2, "3rd" to 2, "fourth" to 3, "4th" to 3, "last" to 3)
    private val corners = mapOf("左上" to 0, "右上" to 1, "左下" to 2, "右下" to 3, "top left" to 0, "top right" to 1, "bottom left" to 2, "bottom right" to 3)

    /** While candidates are up: which one the user means, or that they want a new set. */
    fun parseChoice(text: String): Choice? {
        val t = text.trim().trimEnd('。', '.', '!', '！', '~', '～', '吧', '呗', '呀', '哦', '啊')
        if (t.isEmpty() || t.length > 40) return null
        val lower = t.lowercase(Locale.ROOT)
        if (Regex("^(重新生成|再来一组|再生成|换一批|都不喜欢|都不好|都不要|再来四个|重来|regenerate|try again|another set|none of (these|them)|new options)$").matches(lower)) return Choice.Regenerate
        Regex("^(?:就|选|要|我要|我选|用|我喜欢|喜欢)?\\s*第\\s*([一二两三四1234])\\s*(?:个|只|张|款|号)?(?:吧|好了|好)?$").find(t)?.let { return Choice.Index(ordinalZh.getValue(it.groupValues[1])) }
        Regex("^(?:就|选|要|我要|我选|用)?\\s*([1-4])\\s*(?:号|个|只|张)?(?:吧|好了|好)?$").find(t)?.let { return Choice.Index(it.groupValues[1].toInt() - 1) }
        Regex("^(?:i(?:'ll| will)? (?:take|pick|choose|like|want)|pick|choose|take|use|go with)?\\s*(?:the\\s+)?(?:option|number|no\\.?|#)?\\s*([1-4])$").find(lower)?.let { return Choice.Index(it.groupValues[1].toInt() - 1) }
        Regex("^(?:i(?:'ll| will)? (?:take|pick|choose|like|want)|pick|choose|take|use|go with)?\\s*(?:the\\s+)?(first|second|third|fourth|last|1st|2nd|3rd|4th)(?:\\s+one)?$").find(lower)?.let { return Choice.Index(ordinalEn.getValue(it.groupValues[1])) }
        corners.entries.firstOrNull { lower.contains(it.key) }?.let { if (t.length <= 8) return Choice.Index(it.value) }
        return null
    }

    // ── running ───────────────────────────────────────────────────────────

    /** Reads an attached picture for the reference, scaled to something an edit endpoint accepts. */
    fun loadReference(context: Context, uri: Uri?): Bitmap? {
        if (uri == null) return null
        return runCatching {
            context.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it) }
        }.getOrNull()?.let { bmp ->
            val max = 1024
            val scale = maxOf(bmp.width, bmp.height).toFloat() / max
            if (scale > 1f) Bitmap.createScaledBitmap(bmp, (bmp.width / scale).toInt(), (bmp.height / scale).toInt(), true) else bmp
        }
    }

    /** Draws the four candidates. False when no image model is configured; [AvatarStudio.error] says why. */
    fun start(context: Context, sessionId: String, description: String, reference: Bitmap?): Boolean {
        finishJob?.cancel()
        val ok = AvatarStudio.generateCandidates(context, description, AvatarStudio.Style.MUSE, reference)
        _stage.value = if (ok) Stage.Choosing(sessionId, description) else Stage.Idle
        return ok
    }

    fun regenerate(context: Context): Boolean {
        if (_stage.value !is Stage.Choosing) return false
        val ok = AvatarStudio.regenerate(context)
        if (!ok) _stage.value = Stage.Idle
        return ok
    }

    /**
     * The picked candidate becomes the face; the poses follow. Returns the files of the four
     * candidates (for the persisted card), or null when the pick is not ready.
     */
    fun choose(context: Context, index: Int): List<String>? {
        val s = _stage.value as? Stage.Choosing ?: return null
        val slots = AvatarStudio.slots.value
        if (slots.getOrNull(index) !is AvatarStudio.Slot.Ready) return null
        AvatarStudio.adopt(context, index)
        _stage.value = Stage.Finalizing(s.sessionId, s.description, index)
        appendMemory(context, s.description)
        finishJob = scope.launch {
            // adopt() started the poses; wait for the progress flow to report the run over.
            runCatching { AvatarStudio.moodProgress.first { it == null || !it.running } }
            _stage.value = Stage.Idle
            _done.tryEmit(Done(s.sessionId, s.description))
            // With a video model set, the poses come alive next — in the background, one clip
            // at a time; the header plays each as it lands.
            if (AvatarMotion.enabled(context)) AvatarMotion.animateAll(context)
        }
        return slots.map { (it as? AvatarStudio.Slot.Ready)?.file?.absolutePath ?: "" }
    }

    fun cancel() {
        finishJob?.cancel()
        _stage.value = Stage.Idle
    }

    /** True while the flow is showing options or finishing, in this session. */
    fun isActiveIn(sessionId: String): Boolean = when (val s = _stage.value) {
        is Stage.Choosing -> s.sessionId == sessionId
        is Stage.Finalizing -> s.sessionId == sessionId
        Stage.Idle -> false
    }

    /** Muse's status under the name while the flow runs. */
    fun statusLine(context: Context): String? = when (val s = _stage.value) {
        is Stage.Choosing -> if (AvatarStudio.generating) context.getString(R.string.nm_avatar_status_options) else null
        is Stage.Finalizing -> context.getString(R.string.nm_avatar_status_finalizing)
        Stage.Idle -> null
    }

    // ── words ─────────────────────────────────────────────────────────────

    fun optionsReadyText(context: Context, description: String): String =
        context.getString(R.string.nm_avatar_options_ready, description)

    fun adoptedText(context: Context, description: String): String =
        context.getString(R.string.nm_avatar_adopted, description)

    fun optionsFence(description: String, chosen: Int, files: List<String>): String {
        val o = JSONObject()
            .put("desc", description)
            .put("chosen", chosen)
            .put("files", JSONArray(files))
        return "```$BLOCK_OPTIONS\n$o\n```"
    }

    /** One line in MEMORY about the change, so the agent remembers what it looks like. */
    private fun appendMemory(context: Context, description: String) {
        runCatching {
            val day = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
            val line = context.getString(R.string.nm_avatar_memory_line, day, description)
            val current = SystemFiles.MEMORY.read(context)
            val next = if (current.isBlank()) line else current.trimEnd() + "\n" + line
            SystemFiles.MEMORY.write(context, next + "\n")
        }
    }
}
