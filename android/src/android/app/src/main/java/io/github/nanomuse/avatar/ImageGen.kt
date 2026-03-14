package io.github.nanomuse.avatar

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import com.openminis.app.MinisApp
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import com.openminis.app.logging.AppLogger
import com.openminis.app.provider.ProviderFactory
import com.openminis.app.provider.openai.OpenAIProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Text-to-image and image-edit through the user's own providers — the same instances, keys and
 * model entries OpenMinis' `model-use` CLI drives. Generation and OpenAI-style edits go through
 * [OpenAIProvider.generateImage] / [OpenAIProvider.editImage] (Azure paths, header overrides and
 * the `response_format` retry included). Alibaba Model Studio's compatible host has neither
 * `images/generations` nor `images/edits`; there both drawing and posing go through DashScope's
 * native multimodal endpoint with the same qwen-image-3.x / wan-image (or a `qwen-image-edit-*`)
 * model on the same host and key.
 */
object ImageGen {
    private const val TAG = "ImageGen"
    private const val PREFS = "nanomuse"
    private const val KEY_INSTANCE = "avatar.provider_id"
    private const val KEY_MODEL = "avatar.model"

    data class Endpoint(
        val instance: ProviderInstance,
        val apiKey: String,
        val model: String,
    ) {
        val instanceId: String get() = instance.id
        val label: String get() = instance.label
        val baseUrl: String get() = baseUrlOf(instance)
        val isDashScope: Boolean get() = baseUrl.contains("aliyuncs.com") || baseUrl.contains("dashscope")
    }

    class ImageGenException(message: String) : IOException(message)

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(180, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build()
    }

    /** API-key providers that speak the OpenAI images API (OpenAI itself, xAI, OpenRouter, any custom base). */
    fun eligibleInstances(context: Context): List<ProviderInstance> {
        val app = context.applicationContext as? MinisApp ?: return emptyList()
        val repo = app.providerRepositoryOrNull ?: return emptyList()
        return repo.config.value.instances.filter { inst ->
            inst.isEnabled && inst.credentialType == ProviderCredential.apiKey && when (inst.providerType) {
                ProviderType.openAI, ProviderType.openAIResponses, ProviderType.openRouter, ProviderType.xAI -> true
                ProviderType.anthropic, ProviderType.gemini, ProviderType.kimiCode, ProviderType.antigravity, ProviderType.unsupported -> false
                else -> inst.customBaseURL != null
            }
        }
    }

    /**
     * Model entries of [instance] that draw: the catalogue says so (`image` among the output
     * modalities) or the name does ([looksLikeImageModel]). Providers' `/models` lists rarely
     * carry modalities — Model Studio's says nothing beyond the id — so the name is what tells
     * qwen-image-3.0-pro apart from qwen3-max. Edit-only models are left out: they need a
     * picture to start from.
     */
    fun imageEntries(context: Context, instance: ProviderInstance): List<ModelEntry> {
        val app = context.applicationContext as? MinisApp ?: return emptyList()
        val repo = app.providerRepositoryOrNull ?: return emptyList()
        val dashScope = speaksDashScope(baseUrlOf(instance))
        return repo.config.value.modelEntries.filter {
            it.providerInstanceId == instance.id && !it.isHidden && run {
                val id = it.model.id
                val draws = "image" in it.model.outputModalities.orEmpty() || looksLikeImageModel(id)
                // Model Studio's native endpoint takes qwen-image and wan-image; z-image and the
                // rest go through a different (asynchronous) API this build does not speak.
                val native = id.startsWith("qwen-image", ignoreCase = true) ||
                    (id.startsWith("wan", ignoreCase = true) && id.contains("-image", ignoreCase = true))
                draws && !id.contains("edit", ignoreCase = true) && (!dashScope || native)
            }
        }
    }

    /** Names that mean "text to image" across the providers nanoMuse meets. */
    fun looksLikeImageModel(id: String): Boolean {
        val s = id.lowercase()
        if (s.contains("embedding") || s.contains("-vl") || s.contains("vision") || s.contains("caption")) return false
        return listOf("image", "dall-e", "flux", "stable-diffusion", "sdxl", "sd3", "seedream", "kolors", "imagen", "ideogram", "recraft", "hidream", "cogview")
            .any { s.contains(it) }
    }

    /**
     * The models of [instance] the user can pick from, once the provider's list has been
     * fetched (the same `/models` call the chat models come from). The recommended one for the
     * host leads; dated snapshots (`…-2026-03-03`) hide behind their undated alias.
     */
    fun availableModels(context: Context, instance: ProviderInstance): List<String> {
        val ids = imageEntries(context, instance).map { it.model.id }.distinct()
        val undated = ids.filterNot { DATED.containsMatchIn(it) }.toSet()
        val shown = ids.filter { id -> !DATED.containsMatchIn(id) || DATED.replace(id, "") !in undated }
        val rec = recommendedModel(instance)
        return if (rec in shown) listOf(rec) + shown.filterNot { it == rec } else shown
    }

    private val DATED = Regex("-\\d{4}-\\d{2}-\\d{2}$")

    /** The model nanoMuse would pick on this host, list or no list. Empty when the host is unknown. */
    fun recommendedModel(instance: ProviderInstance): String {
        val base = baseUrlOf(instance)
        return when {
            speaksDashScope(base) -> "qwen-image-3.0-pro"
            base.contains("api.openai.com") -> "gpt-image-1"
            base.contains("api.x.ai") -> "grok-2-image"
            base.contains("openrouter.ai") -> "google/gemini-2.5-flash-image"
            else -> ""
        }
    }

    /**
     * The default when nothing was chosen: the host's recommended model if the provider lists
     * it (or lists nothing yet), otherwise the first model that draws. So a Model Studio key
     * lands on qwen-image-3.0-pro — the model the page talks about — not on whichever image
     * model happens to sort first.
     */
    fun suggestedModel(context: Context, instance: ProviderInstance): String {
        val available = availableModels(context, instance)
        val rec = recommendedModel(instance)
        return when {
            available.isEmpty() -> rec
            rec in available -> rec
            else -> available.first()
        }
    }

    fun speaksDashScope(baseUrl: String): Boolean = baseUrl.contains("aliyuncs.com") || baseUrl.contains("dashscope")

    fun baseUrlOf(inst: ProviderInstance): String =
        inst.effectiveBaseURL ?: when (inst.providerType) {
            ProviderType.openRouter -> "https://openrouter.ai/api/v1"
            ProviderType.xAI -> "https://api.x.ai/v1"
            else -> "https://api.openai.com/v1"
        }

    fun endpoint(context: Context): Endpoint? {
        val app = context.applicationContext as? MinisApp ?: return null
        val repo = app.providerRepositoryOrNull ?: return null
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val eligible = eligibleInstances(context)
        val savedId = prefs.getString(KEY_INSTANCE, null)
        val inst = eligible.firstOrNull { it.id == savedId } ?: eligible.firstOrNull() ?: return null
        val model = prefs.getString(KEY_MODEL, null)?.takeIf { it.isNotBlank() && inst.id == savedId }
            ?: suggestedModel(context, inst)
        val key = repo.usableApiKey(inst) ?: return null
        return Endpoint(inst, key, model)
    }

    fun save(context: Context, instanceId: String, model: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY_INSTANCE, instanceId).putString(KEY_MODEL, model.trim()).apply()
    }

    private fun provider(context: Context, ep: Endpoint, modelId: String): OpenAIProvider {
        val app = context.applicationContext as MinisApp
        val entry = app.providerRepositoryOrNull?.config?.value?.modelEntries
            ?.firstOrNull { it.providerInstanceId == ep.instanceId && it.model.id == modelId }
        val model = entry?.model ?: LLMModel(
            id = modelId,
            displayName = modelId,
            provider = ep.instance.providerType.name,
            outputModalities = listOf("image"),
        )
        return ProviderFactory.create(ep.instance, ep.apiKey, model, context) as? OpenAIProvider
            ?: throw ImageGenException("${ep.label} is not an OpenAI-compatible provider")
    }

    suspend fun generate(context: Context, ep: Endpoint, prompt: String, size: String = "1024x1024"): Bitmap = withContext(Dispatchers.IO) {
        if (ep.model.isBlank()) throw ImageGenException("No image model set")
        // Model Studio's OpenAI-compatible host has no `images/generations` (the public one
        // answers 404 to every model); its native endpoint draws with the same key.
        if (ep.isDashScope) return@withContext generateDashScope(ep, prompt, size)
        val response = try {
            provider(context, ep, ep.model).generateImage(prompt = prompt, n = 1, size = size)
        } catch (e: ImageGenException) {
            throw e
        } catch (e: Exception) {
            throw ImageGenException(e.message ?: e.javaClass.simpleName)
        }
        val bytes = response.mediaAttachments.firstOrNull()?.data
            ?: throw ImageGenException(response.text.take(200).ifBlank { "No image in response" })
        decode(bytes)
    }

    suspend fun edit(context: Context, ep: Endpoint, image: Bitmap, instruction: String): Bitmap = withContext(Dispatchers.IO) {
        if (ep.isDashScope) return@withContext editDashScope(ep, image, instruction)
        val png = pngBytes(image)
        val response = try {
            // gpt-image-* edits with the same model; other hosts get the configured one.
            provider(context, ep, ep.model).editImage(
                prompt = instruction,
                images = listOf(LLMMessage.ImagePart(data = png, mimeType = "image/png")),
                n = 1,
                size = "1024x1024",
            )
        } catch (e: Exception) {
            throw ImageGenException(e.message ?: e.javaClass.simpleName)
        }
        val bytes = response.mediaAttachments.firstOrNull()?.data
            ?: throw ImageGenException(response.text.take(200).ifBlank { "No image in edit response" })
        decode(bytes)
    }

    /**
     * DashScope text-to-image: the native multimodal endpoint with a text-only turn. qwen-image
     * (2.x, 3.x, plus, max) and wan-image all take `size` as `W*H`; prompt extension stays off
     * so the avatar prompts are drawn as written.
     */
    private fun generateDashScope(ep: Endpoint, prompt: String, size: String): Bitmap {
        val parameters = JSONObject().put("size", size.replace('x', '*')).put("watermark", false)
        if (ep.model.startsWith("qwen-image")) parameters.put("prompt_extend", false)
        val content = JSONArray().put(JSONObject().put("text", prompt))
        return callDashScope(ep, ep.model, content, parameters, what = "generation")
    }

    /** DashScope image editing: same host and key, native path, data-URI input. */
    private fun editDashScope(ep: Endpoint, image: Bitmap, instruction: String): Bitmap {
        // qwen-image-3.x, wan-image and the qwen-image-edit-* models take a picture themselves;
        // an older text-only qwen-image is posed by qwen-image-edit-max on the same key.
        val threeX = ep.model.startsWith("qwen-image-3") || ep.model.startsWith("wan")
        val model = if (threeX || ep.model.contains("edit")) ep.model else "qwen-image-edit-max"
        val parameters = if (threeX) JSONObject().put("size", "1024*1024").put("prompt_extend", false).put("watermark", false)
        else JSONObject().put("n", 1).put("watermark", false)
        val content = JSONArray()
            .put(JSONObject().put("image", "data:image/png;base64," + Base64.encodeToString(pngBytes(image), Base64.NO_WRAP)))
            .put(JSONObject().put("text", instruction))
        return callDashScope(ep, model, content, parameters, what = "edit")
    }

    /** One call to `multimodal-generation/generation`; returns the first image of the reply. */
    private fun callDashScope(ep: Endpoint, model: String, content: JSONArray, parameters: JSONObject, what: String): Bitmap {
        val host = ep.baseUrl.substringBefore("/compatible-mode").substringBefore("/api/v1").trimEnd('/')
        val body = JSONObject()
            .put("model", model)
            .put("input", JSONObject().put("messages", JSONArray().put(JSONObject().put("role", "user").put("content", content))))
            .put("parameters", parameters)
        val req = Request.Builder()
            .url("$host/api/v1/services/aigc/multimodal-generation/generation")
            .header("Authorization", "Bearer ${ep.apiKey}")
            .header("Content-Type", "application/json")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        val json = http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val msg = runCatching { JSONObject(text).optString("message") }.getOrNull()
                AppLogger.warning(TAG, "DashScope $what HTTP ${resp.code}: ${text.take(300)}")
                throw ImageGenException("HTTP ${resp.code}" + (msg?.takeIf { it.isNotBlank() }?.let { ": $it" } ?: ""))
            }
            runCatching { JSONObject(text) }.getOrElse { throw ImageGenException("Unreadable $what response") }
        }
        val url = json.optJSONObject("output")?.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optJSONArray("content")?.optJSONObject(0)?.optString("image")
            ?.takeIf { it.isNotBlank() }
            ?: throw ImageGenException(json.optString("message").ifBlank { "Empty $what response" })
        val bytes = http.newCall(Request.Builder().url(url).build()).execute().use { r ->
            if (!r.isSuccessful) throw ImageGenException("Image download failed (${r.code})")
            r.body?.bytes() ?: throw ImageGenException("Empty image")
        }
        return decode(bytes)
    }

    private fun decode(bytes: ByteArray): Bitmap =
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: throw ImageGenException("Undecodable image")

    private fun pngBytes(bitmap: Bitmap): ByteArray =
        ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
}
