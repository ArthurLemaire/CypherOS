package io.github.nanomuse.media

import android.graphics.Bitmap
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.avatar.ImageGen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Short clips through Alibaba Cloud Model Studio's asynchronous video API — MiniMax-H3 by
 * default (`model` is whatever the user typed, so a newer MiniMax build works too). The user's
 * provider key and host are reused: `POST {host}/api/v1/services/aigc/video-generation/
 * video-synthesis` with `X-DashScope-Async: enable` returns a task, `GET {host}/api/v1/tasks/{id}`
 * is polled until it succeeds, and the MP4 is downloaded. A first frame is uploaded to Model
 * Studio's free 48-hour temporary storage first (`/api/v1/uploads`), because the video API takes
 * URLs, not inline data.
 *
 * Costs are the user's: billing is per output second, so callers keep [imageToVideo]'s
 * `seconds` at the minimum that reads well (4 for an avatar loop).
 */
object VideoGen {
    private const val TAG = "VideoGen"
    private const val POLL_MS = 10_000L
    private const val MAX_WAIT_MS = 12 * 60_000L

    data class Endpoint(val instance: ProviderInstance, val apiKey: String, val model: String) {
        val instanceId: String get() = instance.id
        val label: String get() = instance.label
        /** `https://….maas.aliyuncs.com` or `https://dashscope.aliyuncs.com`, without the API path. */
        val host: String get() = ImageGen.baseUrlOf(instance).substringBefore("/compatible-mode").substringBefore("/api/v1").trimEnd('/')
    }

    class VideoGenException(message: String) : IOException(message)

    sealed class Progress {
        object Uploading : Progress()
        object Submitted : Progress()
        data class Running(val elapsedSec: Int) : Progress()
        object Downloading : Progress()
    }

    fun speaksDashScope(baseUrl: String): Boolean = baseUrl.contains("aliyuncs.com") || baseUrl.contains("dashscope")

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(120, TimeUnit.SECONDS)
            .build()
    }

    /** A clip that starts from [image]. Returns the MP4 bytes. */
    suspend fun imageToVideo(
        ep: Endpoint,
        image: Bitmap,
        prompt: String,
        seconds: Int = 4,
        onProgress: (Progress) -> Unit = {},
    ): ByteArray = withContext(Dispatchers.IO) {
        onProgress(Progress.Uploading)
        val png = pngBytes(fitFrame(image))
        val ossUrl = uploadTemp(ep, png, "first-frame.png", "image/png")
        val body = JSONObject()
            .put("model", ep.model)
            .put("input", JSONObject()
                .put("prompt", prompt)
                .put("media", JSONArray().put(JSONObject().put("type", "first_frame").put("url", ossUrl))))
            .put("parameters", JSONObject().put("resolution", "768P").put("duration", seconds.coerceIn(4, 15)).put("watermark", false))
        val task = createTask(ep, body, ossInput = true)
        onProgress(Progress.Submitted)
        val url = poll(ep, task, onProgress)
        onProgress(Progress.Downloading)
        download(url)
    }

    /** A clip from words alone. [ratio] is one of 16:9, 9:16, 1:1, 4:3, 3:4, 21:9. */
    suspend fun textToVideo(
        ep: Endpoint,
        prompt: String,
        seconds: Int = 4,
        ratio: String = "1:1",
        onProgress: (Progress) -> Unit = {},
    ): ByteArray = withContext(Dispatchers.IO) {
        val body = JSONObject()
            .put("model", ep.model)
            .put("input", JSONObject().put("prompt", prompt))
            .put("parameters", JSONObject().put("resolution", "768P").put("ratio", ratio).put("duration", seconds.coerceIn(4, 15)).put("watermark", false))
        val task = createTask(ep, body, ossInput = false)
        onProgress(Progress.Submitted)
        val url = poll(ep, task, onProgress)
        onProgress(Progress.Downloading)
        download(url)
    }

    // ── the protocol ──────────────────────────────────────────────────────

    /** Model Studio's temporary storage: a signed OSS policy, then a multipart POST. Returns the `oss://` URL. */
    internal fun uploadTemp(ep: Endpoint, bytes: ByteArray, name: String, mime: String): String {
        val policyReq = Request.Builder()
            .url("${ep.host}/api/v1/uploads?action=getPolicy&model=${ep.model}")
            .header("Authorization", "Bearer ${ep.apiKey}")
            .get()
            .build()
        val policy = http.newCall(policyReq).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw VideoGenException("Upload policy failed (HTTP ${resp.code})" + apiMessage(text))
            JSONObject(text).optJSONObject("data") ?: throw VideoGenException("Upload policy: no data")
        }
        val key = policy.getString("upload_dir") + "/" + name
        val form = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("OSSAccessKeyId", policy.getString("oss_access_key_id"))
            .addFormDataPart("Signature", policy.getString("signature"))
            .addFormDataPart("policy", policy.getString("policy"))
            .addFormDataPart("x-oss-object-acl", policy.optString("x_oss_object_acl", "private"))
            .addFormDataPart("x-oss-forbid-overwrite", policy.optString("x_oss_forbid_overwrite", "true"))
            .addFormDataPart("key", key)
            .addFormDataPart("file", name, bytes.toRequestBody(mime.toMediaType()))
            .build()
        http.newCall(Request.Builder().url(policy.getString("upload_host")).post(form).build()).execute().use { resp ->
            if (!resp.isSuccessful) throw VideoGenException("Upload failed (HTTP ${resp.code})")
        }
        return "oss://$key"
    }

    private fun createTask(ep: Endpoint, body: JSONObject, ossInput: Boolean): String {
        val req = Request.Builder()
            .url("${ep.host}/api/v1/services/aigc/video-generation/video-synthesis")
            .header("Authorization", "Bearer ${ep.apiKey}")
            .header("Content-Type", "application/json")
            .header("X-DashScope-Async", "enable")
            .apply { if (ossInput) header("X-DashScope-OssResourceResolve", "enable") }
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        return http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                AppLogger.warning(TAG, "create HTTP ${resp.code}: ${text.take(300)}")
                throw VideoGenException("HTTP ${resp.code}" + apiMessage(text))
            }
            val json = runCatching { JSONObject(text) }.getOrElse { throw VideoGenException("Unreadable response") }
            json.optJSONObject("output")?.optString("task_id")?.takeIf { it.isNotBlank() }
                ?: throw VideoGenException(json.optString("message").ifBlank { "No task id" })
        }
    }

    private suspend fun poll(ep: Endpoint, taskId: String, onProgress: (Progress) -> Unit): String {
        val started = System.currentTimeMillis()
        while (true) {
            delay(POLL_MS)
            val req = Request.Builder()
                .url("${ep.host}/api/v1/tasks/$taskId")
                .header("Authorization", "Bearer ${ep.apiKey}")
                .get()
                .build()
            val json = http.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) throw VideoGenException("Task query failed (HTTP ${resp.code})" + apiMessage(text))
                runCatching { JSONObject(text) }.getOrElse { throw VideoGenException("Unreadable task") }
            }
            val out = json.optJSONObject("output") ?: JSONObject()
            when (out.optString("task_status")) {
                "SUCCEEDED" -> return out.optString("video_url").takeIf { it.isNotBlank() } ?: throw VideoGenException("No video URL")
                "FAILED", "CANCELED", "UNKNOWN" -> throw VideoGenException(failureMessage(out))
            }
            val elapsed = ((System.currentTimeMillis() - started) / 1000).toInt()
            onProgress(Progress.Running(elapsed))
            if (System.currentTimeMillis() - started > MAX_WAIT_MS) throw VideoGenException("Timed out after ${elapsed / 60} min")
        }
    }

    private fun download(url: String): ByteArray =
        http.newCall(Request.Builder().url(url).get().build()).execute().use { resp ->
            if (!resp.isSuccessful) throw VideoGenException("Video download failed (${resp.code})")
            resp.body?.bytes()?.takeIf { it.isNotEmpty() } ?: throw VideoGenException("Empty video")
        }

    /** The user-facing reason from a failed task; the activation message gets a plainer wording. */
    internal fun failureMessage(output: JSONObject): String {
        val code = output.optString("code")
        val message = output.optString("message")
        return when {
            message.contains("not activated", ignoreCase = true) ->
                "The video model is not activated on this account — open the model's card in the Model Studio console and activate it"
            message.isNotBlank() -> if (code.isNotBlank()) "$code: $message" else message
            code.isNotBlank() -> code
            else -> "Video task ${output.optString("task_status").ifBlank { "failed" }}"
        }
    }

    private fun apiMessage(text: String): String =
        runCatching { JSONObject(text).optString("message") }.getOrNull()?.takeIf { it.isNotBlank() }?.let { ": $it" } ?: ""

    /** The API wants 256–5760 px on each side and an aspect within [0.4, 2.5]; a face is square, so only size matters. */
    private fun fitFrame(image: Bitmap): Bitmap {
        val max = 1024
        val min = 256
        val longest = maxOf(image.width, image.height)
        val shortest = minOf(image.width, image.height)
        return when {
            longest > max -> {
                val s = max.toFloat() / longest
                Bitmap.createScaledBitmap(image, (image.width * s).toInt().coerceAtLeast(min), (image.height * s).toInt().coerceAtLeast(min), true)
            }
            shortest < min -> {
                val s = min.toFloat() / shortest
                Bitmap.createScaledBitmap(image, (image.width * s).toInt(), (image.height * s).toInt(), true)
            }
            else -> image
        }
    }

    private fun pngBytes(bitmap: Bitmap): ByteArray =
        ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
}
