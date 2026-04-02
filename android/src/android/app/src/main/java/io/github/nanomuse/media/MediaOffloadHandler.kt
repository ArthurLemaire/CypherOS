package io.github.nanomuse.media

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import com.openminis.app.logging.AppLogger
import com.openminis.app.sandbox.NativeOffloadHandler
import com.openminis.app.sandbox.NativeOffloadRequest
import com.openminis.app.sandbox.NativeOffloadResult
import com.openminis.app.sandbox.PRootKernel
import io.github.nanomuse.avatar.ImageGen
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * `nanomuse-media` — the agent's way to the image and video models, from the sandbox shell:
 *
 *     nanomuse-media status
 *     nanomuse-media image --prompt "<text>" [--from <picture>] [--size 1024x1024] [--name out.png]
 *     nanomuse-media video --prompt "<text>" [--from <picture>] [--seconds 4-15] [--ratio 16:9] [--name out.mp4]
 *
 * Files land in the session's `/var/minis/attachments/`, and the JSON reply carries a `markdown`
 * line (`![…](minis://attachments/…)`) that renders inline when the agent puts it in its answer.
 * Without the needed model it exits 3 with a plain reason and the settings link, so the agent can
 * tell the user instead of guessing. Registered in `MinisApp` next to `minis-model-use`.
 */
class MediaOffloadHandler(private val context: Context) : NativeOffloadHandler {

    override fun handle(request: NativeOffloadRequest): NativeOffloadResult {
        val args = Args(request.argv.drop(1))
        return when (args.positional.firstOrNull()) {
            null, "help", "--help", "-h" -> NativeOffloadResult(0, HELP)
            "status" -> ok(status())
            "image" -> image(args, request.sessionId)
            "video" -> video(args, request.sessionId)
            else -> NativeOffloadResult(2, "nanomuse-media: unknown subcommand '${args.positional.first()}'\n$HELP")
        }
    }

    private fun status(): JSONObject {
        val image = MediaModels.imageEndpoint(context)
        val video = MediaModels.videoEndpoint(context)
        return JSONObject()
            .put("image_model", image?.let { JSONObject().put("model", it.model).put("provider", it.label) } ?: JSONObject.NULL)
            .put("video_model", video?.let { JSONObject().put("model", it.model).put("provider", it.label) } ?: JSONObject.NULL)
            .put("settings", MediaModels.DEEP_LINK)
    }

    private fun image(args: Args, sessionId: String?): NativeOffloadResult {
        val prompt = args.get("prompt")?.trim().orEmpty()
        if (prompt.isEmpty()) return NativeOffloadResult(2, "nanomuse-media image: --prompt is required\n")
        val ep = MediaModels.imageEndpoint(context) ?: return missing("image")
        val reference = args.get("from")?.let { path ->
            loadPicture(path, sessionId) ?: return NativeOffloadResult(2, "nanomuse-media: cannot read picture '$path'\n")
        }
        val size = args.get("size")?.takeIf { Regex("\\d{3,4}x\\d{3,4}").matches(it) } ?: "1024x1024"
        val bitmap = try {
            runBlocking {
                if (reference != null) ImageGen.edit(context, ep, reference, prompt) else ImageGen.generate(context, ep, prompt, size)
            }
        } catch (e: Exception) {
            AppLogger.warning(TAG, "image failed: ${e.message}")
            return failed("image", e.message ?: "failed")
        }
        val name = fileName(args.get("name"), "png")
        val file = save(sessionId, name) { out -> bitmap.compress(Bitmap.CompressFormat.PNG, 100, out) }
            ?: return failed("image", "cannot write to /var/minis/attachments")
        return ok(JSONObject()
            .put("ok", true)
            .put("path", "/var/minis/attachments/$name")
            .put("markdown", "![${prompt.take(60).replace("]", "")}](minis://attachments/$name)")
            .put("model", ep.model).put("provider", ep.label)
            .put("bytes", file.length()))
    }

    private fun video(args: Args, sessionId: String?): NativeOffloadResult {
        val prompt = args.get("prompt")?.trim().orEmpty()
        if (prompt.isEmpty()) return NativeOffloadResult(2, "nanomuse-media video: --prompt is required\n")
        val ep = MediaModels.videoEndpoint(context) ?: return missing("video")
        val seconds = args.get("seconds")?.toIntOrNull()?.coerceIn(4, 15) ?: 4
        val ratio = args.get("ratio")?.takeIf { it in RATIOS } ?: "1:1"
        val from = args.get("from")?.let { path ->
            loadPicture(path, sessionId) ?: return NativeOffloadResult(2, "nanomuse-media: cannot read picture '$path'\n")
        }
        val bytes = try {
            runBlocking {
                if (from != null) VideoGen.imageToVideo(ep, from, prompt, seconds) else VideoGen.textToVideo(ep, prompt, seconds, ratio)
            }
        } catch (e: Exception) {
            AppLogger.warning(TAG, "video failed: ${e.message}")
            return failed("video", e.message ?: "failed")
        }
        val name = fileName(args.get("name"), "mp4")
        val file = save(sessionId, name) { out -> out.write(bytes) }
            ?: return failed("video", "cannot write to /var/minis/attachments")
        return ok(JSONObject()
            .put("ok", true)
            .put("path", "/var/minis/attachments/$name")
            .put("markdown", "[${prompt.take(60).replace("]", "")} (video, ${seconds}s)](minis://attachments/$name)")
            .put("model", ep.model).put("provider", ep.label)
            .put("seconds", seconds)
            .put("bytes", file.length()))
    }

    // ── helpers ───────────────────────────────────────────────────────────

    private fun missing(kind: String): NativeOffloadResult = NativeOffloadResult(
        3,
        JSONObject()
            .put("ok", false)
            .put("error", "no_${kind}_model")
            .put("message", "No $kind model is configured. nanoMuse uses the user's own providers for this (Muse has it built in). " +
                (if (kind == "image") "Alibaba Cloud Model Studio's qwen-image-3.0 or any OpenAI-compatible images endpoint works." else "Alibaba Cloud Model Studio's MiniMax/MiniMax-H3 works (activated in their console)."))
            .put("tell_user", "Explain this in a sentence and give the link [Image & video models](${MediaModels.DEEP_LINK}); do not invent a result.")
            .toString(2) + "\n",
    )

    private fun failed(kind: String, message: String): NativeOffloadResult = NativeOffloadResult(
        1,
        JSONObject().put("ok", false).put("error", "${kind}_failed").put("message", message)
            .put("tell_user", "Tell the user what went wrong in their language; the settings are at ${MediaModels.DEEP_LINK}.")
            .toString(2) + "\n",
    )

    private fun ok(body: JSONObject): NativeOffloadResult = NativeOffloadResult(0, body.toString(2) + "\n")

    private fun fileName(requested: String?, ext: String): String {
        val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
        val base = requested?.substringAfterLast('/')?.substringBeforeLast('.')?.replace(Regex("[^A-Za-z0-9._-]"), "_")?.takeIf { it.isNotBlank() }
            ?: "nanomuse-$stamp"
        return "$base.$ext"
    }

    private fun attachmentsDir(sessionId: String?): File? =
        if (sessionId != null) File(context.filesDir, "minis-sessions/$sessionId/attachments")
        else PRootKernel.resolveHostPath("/var/minis/attachments")

    private fun save(sessionId: String?, name: String, write: (java.io.OutputStream) -> Unit): File? {
        val dir = attachmentsDir(sessionId) ?: return null
        dir.mkdirs()
        val file = File(dir, name)
        return runCatching { file.outputStream().use(write); file }.getOrNull()
    }

    /** A picture the agent points at: a sandbox path, an attachment link or a host path. */
    private fun loadPicture(path: String, sessionId: String?): Bitmap? {
        val linux = when {
            path.startsWith("minis://attachments/") -> "/var/minis/attachments/" + path.removePrefix("minis://attachments/")
            path.startsWith("minis://") -> path.removePrefix("minis://")
            else -> path
        }
        val file = when {
            linux.startsWith("/var/minis/attachments/") && sessionId != null ->
                File(context.filesDir, "minis-sessions/$sessionId/attachments/" + linux.removePrefix("/var/minis/attachments/"))
            sessionId != null -> PRootKernel.resolveSessionHostPath(sessionId, linux, context)
            else -> PRootKernel.resolveHostPath(linux)
        } ?: File(linux)
        val f = file.takeIf { it.exists() } ?: File(linux).takeIf { it.exists() } ?: return null
        return runCatching { BitmapFactory.decodeFile(f.path) }.getOrNull()
    }

    /** `--flag value` and `--flag=value`; the first bare word is the subcommand. */
    internal class Args(argv: List<String>) {
        val positional = mutableListOf<String>()
        private val values = mutableMapOf<String, String>()
        init {
            var i = 0
            while (i < argv.size) {
                val a = argv[i]
                when {
                    a.startsWith("--") && a.contains('=') -> values[a.substring(2, a.indexOf('='))] = a.substringAfter('=')
                    a.startsWith("--") -> {
                        val next = argv.getOrNull(i + 1)
                        if (next != null && !next.startsWith("--")) { values[a.substring(2)] = next; i++ } else values[a.substring(2)] = "true"
                    }
                    else -> positional += a
                }
                i++
            }
        }
        fun get(name: String): String? = values[name]
    }

    companion object {
        private const val TAG = "nanomuse-media"
        private val RATIOS = setOf("16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
        const val HELP = """nanomuse-media — pictures and short clips through the user's image and video models

Usage:
  nanomuse-media status
  nanomuse-media image --prompt "<text>" [--from <picture>] [--size 1024x1024] [--name out.png]
  nanomuse-media video --prompt "<text>" [--from <picture>] [--seconds 4-15] [--ratio 16:9] [--name out.mp4]

Files are written to /var/minis/attachments/ and the JSON reply carries a `markdown`
line to put in the answer so the file shows inline. `--from` takes a sandbox path or a
minis://attachments/... link (image: edit that picture; video: start from it).
Video takes 1-5 minutes and is billed per second; keep --seconds low.
Exit 3 means the needed model is not configured — tell the user and link minis://settings/media.
"""
    }
}
