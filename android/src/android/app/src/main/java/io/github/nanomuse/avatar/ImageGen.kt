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
 * the `response_format` retry included). Alibaba Model Studio has no `images/edits`; there the
 * moods are posed through DashScope's native multimodal endpoint with a `qwen-image-edit-*`
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

    /** Model entries of [instance] the catalogue marks as producing images — the quick picks. */
    fun imageEntries(context: Context, instance: ProviderInstance): List<ModelEntry> {
        val app = context.applicationContext as? MinisApp ?: return emptyList()
        val repo = app.providerRepositoryOrNull ?: return emptyList()
        return repo.config.value.modelEntries.filter {
            it.providerInstanceId == instance.id && !it.isHidden && "image" in it.model.outputModalities.orEmpty()
        }
    }

    fun suggestedModel(context: Context, instance: ProviderInstance): String {
        imageEntries(context, instance).firstOrNull()?.let { return it.model.id }
        val base = baseUrlOf(instance)
        return when {
            base.contains("aliyuncs.com") || base.contains("dashscope") -> "qwen-image-3.0"
            base.contains("api.openai.com") -> "gpt-image-1"
            base.contains("api.x.ai") -> "grok-2-image"
            base.contains("openrouter.ai") -> "google/gemini-2.5-flash-image"
            else -> ""
        }
    }

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

    /** DashScope image editing: same host and key, native path, data-URI input. */
    private fun editDashScope(ep: Endpoint, image: Bitmap, instruction: String): Bitmap {
        val host = ep.baseUrl.substringBefore("/compatible-mode").substringBefore("/api/v1").trimEnd('/')
        val model = if (ep.model.contains("edit")) ep.model else "qwen-image-edit-max"
        val content = JSONArray()
            .put(JSONObject().put("image", "data:image/png;base64," + Base64.encodeToString(pngBytes(image), Base64.NO_WRAP)))
            .put(JSONObject().put("text", instruction))
        val body = JSONObject()
            .put("model", model)
            .put("input", JSONObject().put("messages", JSONArray().put(JSONObject().put("role", "user").put("content", content))))
            .put("parameters", JSONObject().put("n", 1).put("watermark", false))
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
                AppLogger.warning(TAG, "DashScope edit HTTP ${resp.code}: ${text.take(300)}")
                throw ImageGenException("HTTP ${resp.code}" + (msg?.takeIf { it.isNotBlank() }?.let { ": $it" } ?: ""))
            }
            runCatching { JSONObject(text) }.getOrElse { throw ImageGenException("Unreadable edit response") }
        }
        val url = json.optJSONObject("output")?.optJSONArray("choices")?.optJSONObject(0)
            ?.optJSONObject("message")?.optJSONArray("content")?.optJSONObject(0)?.optString("image")
            ?.takeIf { it.isNotBlank() }
            ?: throw ImageGenException(json.optString("message").ifBlank { "Empty edit response" })
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
