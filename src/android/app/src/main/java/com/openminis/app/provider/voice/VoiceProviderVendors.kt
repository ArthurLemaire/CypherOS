package com.openminis.app.provider.voice

import android.util.Base64
import android.util.Log
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.URLEncoder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * [T-android-provider-voice] Vendor subclasses — Android port of iOS
 * VoiceProvider+Vendors.swift. Each vendor overrides only what differs from
 * the OpenAI-compatible base: default model names, endpoint paths, request
 * bodies, response envelopes, or auth.
 */

// -- Groq (ASR only, OpenAI-compatible, only the default model differs) -------

class GroqVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {
    override val supportsVoiceOutput: Boolean get() = false
    override fun defaultVoiceInputModel() = "whisper-large-v3-turbo"
}

// -- Alibaba Bailian (OpenAI-compatible, only default models differ) ----------

class AlibabaVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {
    override fun defaultVoiceInputModel() = "paraformer-realtime-v2"
    override fun defaultVoiceOutputModel() = "cosyvoice-v2"
    override fun defaultVoiceOutputVoice() = "longxiaochun"
}

// -- xAI (ASR endpoint path differs: /v1/stt) ---------------------------------

class XAIVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {
    override fun voiceInputEndpointPath() = "/v1/stt"
    override fun defaultVoiceInputModel() = "grok-stt"
    override fun defaultVoiceOutputModel() = "grok-tts-1"
    override fun defaultVoiceOutputVoice() = "eve"
}

// -- MiniMax (TTS only, distinct body, base64-nested response) ----------------

class MiniMaxVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {

    override val supportsVoiceInput: Boolean get() = false

    /**
     * [T-voice-minimax-tts-404] MiniMax's NATIVE TTS endpoint (/v1/t2a_v2)
     * lives at the API host ROOT — not under the /anthropic chat-proxy path
     * users configure for chat. Strip trailing /v1 and /anthropic segments.
     */
    override fun effectiveBaseURL(): String {
        var base = super.effectiveBaseURL().trimEnd('/')
        for (suffix in listOf("/v1", "/anthropic")) {
            if (base.endsWith(suffix)) base = base.dropLast(suffix.length)
        }
        return base.trimEnd('/')
    }

    override fun voiceOutputEndpointPath() = "/v1/t2a_v2"
    override fun defaultVoiceOutputModel() = "speech-2.8-hd"
    override fun defaultVoiceOutputVoice() = "female-shaonv"

    override fun buildVoiceOutputRequest(request: VoiceOutputRequest): Request {
        val url = composedUrlString(voiceOutputEndpointPath())
        // MiniMax-specific shape: speed becomes an integer 0~200.
        val speedInt = ((request.speed ?: 1.0f) * 100).toInt()
        val body = JSONObject().apply {
            put("model", request.model ?: defaultVoiceOutputModel())
            put("text", request.input)
            put("stream", false)
            put(
                "voice_setting",
                JSONObject()
                    .put("voice_id", request.voice ?: defaultVoiceOutputVoice())
                    .put("speed", speedInt)
                    .put("vol", 100)
                    .put("pitch", 0),
            )
            put(
                "audio_setting",
                JSONObject()
                    .put("sample_rate", 32000)
                    .put("bitrate", 128000)
                    .put("format", request.responseFormat.wireValue),
            )
        }
        val builder = Request.Builder()
            .url(url)
            .post(body.toString().toRequestBody("application/json".toMediaType()))
        applyVoiceAuth(builder)
        return builder.build()
    }

    // Response: { "audio": { "audio": "base64..." }, "base_resp": { status_code, status_msg } }
    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        val raw = executeRequest(buildVoiceOutputRequest(request))
        val json = runCatching { JSONObject(String(raw, Charsets.UTF_8)) }.getOrNull()
        // Surface MiniMax's own error (base_resp) instead of a generic parse
        // failure — on failure t2a_v2 returns NO audio, only base_resp.
        json?.optJSONObject("base_resp")?.let { base ->
            val code = base.optInt("status_code", 0)
            if (code != 0) {
                val msg = base.optString("status_msg").ifBlank { "unknown error" }
                throw VoiceProviderException.Parse("MiniMax TTS error [$code]: $msg")
            }
        }
        val b64 = json?.optJSONObject("audio")?.optString("audio")
            ?.takeIf { it.isNotEmpty() }
            ?: throw VoiceProviderException.Parse("Unexpected MiniMax TTS response format")
        return runCatching { Base64.decode(b64, Base64.DEFAULT) }.getOrNull()
            ?: throw VoiceProviderException.Parse("Unexpected MiniMax TTS response format")
    }
}

// -- Doubao / Volcano (TTS + ASR, X-Api-Key auth, distinct formats) -----------

class DoubaoVoiceProvider(providerId: String, apiKey: String?) :
    VoiceProvider(providerId, "https://openspeech.bytedance.com", apiKey) {

    override fun applyVoiceAuth(builder: Request.Builder) {
        val key = apiKey?.takeIf { it.isNotEmpty() } ?: return
        builder.header("X-Api-Key", key)
    }

    // TTS (v3 unidirectional streaming) ---------------------------------------

    override fun voiceOutputEndpointPath() = "/api/v3/tts/unidirectional"
    override fun defaultVoiceInputModel() = "bigmodel"
    override fun defaultVoiceOutputModel() = "zh_female_cancan_uranus_bigtts"
    override fun defaultVoiceOutputVoice() = "zh_female_cancan_uranus_bigtts"

    override fun buildVoiceOutputRequest(request: VoiceOutputRequest): Request {
        val url = composedUrlString(voiceOutputEndpointPath())
        val raw = request.model ?: request.voice ?: defaultVoiceOutputVoice()
        val speaker = if (raw.startsWith("seed-tts-")) defaultVoiceOutputVoice() else raw
        val resourceId = if (speaker.contains("_uranus_") || speaker.startsWith("saturn_")) {
            "seed-tts-2.0"
        } else {
            "seed-tts-1.0"
        }
        val body = JSONObject().put(
            "req_params",
            JSONObject()
                .put("text", request.input)
                .put("speaker", speaker)
                .put(
                    "audio_params",
                    JSONObject()
                        .put("format", if (request.responseFormat == VoiceOutputFormat.WAV) "wav" else "mp3")
                        .put("sample_rate", 24000),
                ),
        )
        val builder = Request.Builder()
            .url(url)
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Api-Resource-Id", resourceId)
            .header("Connection", "keep-alive")
        applyVoiceAuth(builder)
        return builder.build()
    }

    // v3 TTS returns HTTP chunked: each line a JSON frame with base64 audio.
    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        val raw = executeRequest(buildVoiceOutputRequest(request))
        val out = ByteArrayOutputStream()
        for (line in String(raw, Charsets.UTF_8).split('\n')) {
            val frame = runCatching { JSONObject(line) }.getOrNull() ?: continue
            if (frame.optInt("code", -1) != 0) continue
            val b64 = frame.optString("data").takeIf { it.isNotEmpty() } ?: continue
            val chunk = runCatching { Base64.decode(b64, Base64.DEFAULT) }.getOrNull() ?: continue
            out.write(chunk)
        }
        val audio = out.toByteArray()
        if (audio.isEmpty()) {
            val preview = String(raw.copyOfRange(0, minOf(raw.size, 500)), Charsets.UTF_8)
            throw VoiceProviderException.Parse("Doubao v3 TTS: no audio frames in response. Raw: $preview")
        }
        return audio
    }

    // ASR (v3 bigmodel flash recognize) ---------------------------------------

    override fun voiceInputEndpointPath() = "/api/v3/auc/bigmodel/recognize/flash"

    override fun buildVoiceInputRequest(request: VoiceInputRequest): Request {
        val url = composedUrlString(voiceInputEndpointPath())
        val body = JSONObject()
            .put("user", JSONObject().put("uid", "minis_user"))
            .put("audio", JSONObject().put("data", Base64.encodeToString(request.audioData, Base64.NO_WRAP)))
            .put("request", JSONObject().put("model_name", "bigmodel"))
        val builder = Request.Builder()
            .url(url)
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .header("X-Api-Resource-Id", "volc.bigasr.auc_turbo")
            .header("X-Api-Request-Id", UUID.randomUUID().toString())
            .header("X-Api-Sequence", "-1")
        applyVoiceAuth(builder)
        return builder.build()
    }

    // v3 ASR response: { "result": { "text": "..." }, "audio_info": { duration } }
    override fun parseVoiceInputResponse(data: ByteArray, request: VoiceInputRequest): VoiceInputResponse {
        val json = runCatching { JSONObject(String(data, Charsets.UTF_8)) }.getOrNull()
        val text = json?.optJSONObject("result")?.optString("text")
            ?: throw VoiceProviderException.Parse("Unexpected Doubao v3 ASR response format")
        val durationMs = json.optJSONObject("audio_info")?.optDouble("duration")
            ?.takeIf { !it.isNaN() }
        return VoiceInputResponse(
            text = text,
            language = request.language,
            durationSeconds = durationMs?.div(1000),
        )
    }
}

// -- iFlytek / Xunfei (ASR with HMAC-SHA256 signed URL; TTS over WebSocket) ---

class XunfeiVoiceProvider(
    providerId: String,
    private val appId: String,
    apiKey: String,
    private val apiSecret: String,
) : VoiceProvider(providerId, "https://iat-api.xfyun.cn", apiKey) {

    companion object {
        private const val DEFAULT_TTS_VOICE = "xiaoyan"
    }

    // Xunfei authenticates via a signed URL, not a header.
    override fun applyVoiceAuth(builder: Request.Builder) {}

    override fun buildVoiceInputRequest(request: VoiceInputRequest): Request {
        val url = buildSignedURL(host = "iat-api.xfyun.cn", path = "/v2/iat", date = Date())
        val body = JSONObject()
            .put("header", JSONObject().put("app_id", appId).put("status", 3))
            .put(
                "parameter",
                JSONObject().put(
                    "iat",
                    JSONObject()
                        .put("domain", "iat")
                        .put("language", request.language ?: "zh_cn")
                        .put("accent", "mandarin")
                        .put(
                            "result",
                            JSONObject()
                                .put("encoding", "utf8")
                                .put("compress", "raw")
                                .put("format", "json"),
                        ),
                ),
            )
            .put(
                "payload",
                JSONObject().put(
                    "audio",
                    JSONObject()
                        .put("encoding", "raw")
                        .put("sample_rate", 16000)
                        .put("channels", 1)
                        .put("bit_depth", 16)
                        .put("status", 3)
                        .put("audio", Base64.encodeToString(request.audioData, Base64.NO_WRAP)),
                ),
            )
        return Request.Builder()
            .url(url)
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
    }

    override fun parseVoiceInputResponse(data: ByteArray, request: VoiceInputRequest): VoiceInputResponse {
        val json = runCatching { JSONObject(String(data, Charsets.UTF_8)) }.getOrNull()
            ?: throw VoiceProviderException.Parse("Unexpected Xunfei ASR response format")
        if (json.optJSONObject("header")?.optInt("code", -1) != 0) {
            throw VoiceProviderException.Parse("Unexpected Xunfei ASR response format")
        }
        val b64Text = json.optJSONObject("payload")?.optJSONObject("result")?.optString("text")
            ?.takeIf { it.isNotEmpty() }
            ?: throw VoiceProviderException.Parse("Unexpected Xunfei ASR response format")
        val textJson = runCatching {
            JSONObject(String(Base64.decode(b64Text, Base64.DEFAULT), Charsets.UTF_8))
        }.getOrNull() ?: throw VoiceProviderException.Parse("Unexpected Xunfei ASR response format")

        val sb = StringBuilder()
        val ws = textJson.optJSONArray("ws") ?: JSONArray()
        for (i in 0 until ws.length()) {
            val cw = ws.optJSONObject(i)?.optJSONArray("cw") ?: continue
            for (j in 0 until cw.length()) {
                cw.optJSONObject(j)?.optString("w")?.let { sb.append(it) }
            }
        }
        return VoiceInputResponse(text = sb.toString(), language = request.language)
    }

    /**
     * Xunfei TTS is a WebSocket endpoint (tts-api.xfyun.cn/v2/tts) streaming
     * base64 PCM frames, signed with the same HMAC scheme as ASR. Collect all
     * frames and wrap the 16k PCM in a WAV header.
     */
    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        val signedUrl = buildSignedURL(host = "tts-api.xfyun.cn", path = "/v2/tts", date = Date())
            .replaceFirst("https://", "wss://")
        val voice = request.voice?.takeIf { it.isNotEmpty() } ?: DEFAULT_TTS_VOICE
        val textB64 = Base64.encodeToString(request.input.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
        val payload = JSONObject()
            .put("common", JSONObject().put("app_id", appId))
            .put(
                "business",
                JSONObject()
                    .put("aue", "raw")
                    .put("auf", "audio/L16;rate=16000")
                    .put("vcn", voice)
                    .put("tte", "UTF8"),
            )
            .put("data", JSONObject().put("status", 2).put("text", textB64))
            .toString()

        return suspendCancellableCoroutine { cont ->
            val pcm = ByteArrayOutputStream()
            val wsRequest = Request.Builder().url(signedUrl).build()
            val socket = httpClient.newWebSocket(
                wsRequest,
                object : WebSocketListener() {
                    override fun onOpen(webSocket: WebSocket, response: Response) {
                        webSocket.send(payload)
                    }

                    override fun onMessage(webSocket: WebSocket, text: String) {
                        val json = runCatching { JSONObject(text) }.getOrNull() ?: return
                        val code = json.optInt("code", 0)
                        if (code != 0) {
                            webSocket.cancel()
                            if (cont.isActive) {
                                cont.resumeWithException(
                                    VoiceProviderException.Parse(
                                        "Xunfei TTS error code $code: ${json.optString("message")}",
                                    ),
                                )
                            }
                            return
                        }
                        val dataObj = json.optJSONObject("data") ?: return
                        dataObj.optString("audio").takeIf { it.isNotEmpty() }?.let { b64 ->
                            runCatching { Base64.decode(b64, Base64.DEFAULT) }.getOrNull()
                                ?.let(pcm::write)
                        }
                        if (dataObj.optInt("status", 0) == 2) {   // last frame
                            webSocket.close(1000, null)
                            if (cont.isActive) {
                                val bytes = pcm.toByteArray()
                                if (bytes.isEmpty()) {
                                    cont.resumeWithException(VoiceProviderException.Parse("Xunfei TTS empty audio"))
                                } else {
                                    cont.resume(wrapPcm16InWav(bytes, sampleRate = 16000))
                                }
                            }
                        }
                    }

                    override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                        if (cont.isActive) cont.resumeWithException(t)
                    }
                },
            )
            cont.invokeOnCancellation { socket.cancel() }
        }
    }

    // HMAC-SHA256 URL signature -----------------------------------------------

    private fun buildSignedURL(host: String, path: String, date: Date): String {
        val formatter = SimpleDateFormat("EEE, dd MMM yyyy HH:mm:ss z", Locale.US).apply {
            timeZone = TimeZone.getTimeZone("GMT")
        }
        val dateStr = formatter.format(date)
        val signatureOrigin = "host: $host\ndate: $dateStr\nGET $path HTTP/1.1"
        val signatureB64 = hmacSha256Base64(signatureOrigin, apiSecret)
        val authOrigin = "api_key=\"${apiKey ?: ""}\", " +
            "algorithm=\"hmac-sha256\", " +
            "headers=\"host date request-line\", " +
            "signature=\"$signatureB64\""
        val authB64 = Base64.encodeToString(authOrigin.toByteArray(Charsets.UTF_8), Base64.NO_WRAP)
        val encodedDate = URLEncoder.encode(dateStr, "UTF-8")
        return "https://$host$path?authorization=$authB64&date=$encodedDate&host=$host"
    }

    private fun hmacSha256Base64(data: String, key: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return Base64.encodeToString(mac.doFinal(data.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP)
    }
}

// -- Google Gemini (native TTS via generateContent + AUDIO modality) ----------

/**
 * Gemini TTS is NOT OpenAI-compatible: POST {base}/v1beta/models/{model}:
 * generateContent with the key in ?key= and base64 raw PCM (24 kHz mono) in
 * candidates[0].content.parts[].inlineData.data. Wrap the PCM in WAV.
 */
class GeminiVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {

    companion object {
        private val KNOWN_VOICES = setOf("Kore", "Puck", "Charon", "Fenrir", "Aoede", "Zephyr", "Leda", "Orus")
        private fun geminiVoice(requested: String?): String {
            val v = requested?.takeIf { it.isNotEmpty() } ?: return "Kore"
            return if (v in KNOWN_VOICES) v else "Kore"
        }

        private fun sampleRate(fromMime: String): Int {
            val idx = fromMime.indexOf("rate=")
            if (idx < 0) return 24000
            return fromMime.substring(idx + 5).takeWhile { it.isDigit() }.toIntOrNull() ?: 24000
        }
    }

    override val supportsVoiceInput: Boolean get() = false
    override fun defaultVoiceOutputModel() = "gemini-2.5-flash-preview-tts"

    override fun buildVoiceOutputRequest(request: VoiceOutputRequest): Request {
        val model = request.model ?: defaultVoiceOutputModel()
        var base = effectiveBaseURL()
        if (!base.contains("/v1beta")) base = base.trimEnd('/') + "/v1beta"
        val url = "$base/models/$model:generateContent?key=${apiKey ?: ""}"
        val body = JSONObject()
            .put(
                "contents",
                JSONArray().put(
                    JSONObject().put("parts", JSONArray().put(JSONObject().put("text", request.input))),
                ),
            )
            .put(
                "generationConfig",
                JSONObject()
                    .put("responseModalities", JSONArray().put("AUDIO"))
                    .put(
                        "speechConfig",
                        JSONObject().put(
                            "voiceConfig",
                            JSONObject().put(
                                "prebuiltVoiceConfig",
                                JSONObject().put("voiceName", geminiVoice(request.voice)),
                            ),
                        ),
                    ),
            )
        return Request.Builder()
            .url(url)
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
    }

    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        val raw = executeRequest(buildVoiceOutputRequest(request))
        val json = runCatching { JSONObject(String(raw, Charsets.UTF_8)) }.getOrNull()
            ?: throw VoiceProviderException.Parse("Unexpected Gemini TTS response")
        val parts = json.optJSONArray("candidates")
            ?.optJSONObject(0)
            ?.optJSONObject("content")
            ?.optJSONArray("parts")
            ?: throw VoiceProviderException.Parse("Unexpected Gemini TTS response")
        for (i in 0 until parts.length()) {
            val inline = parts.optJSONObject(i)?.optJSONObject("inlineData") ?: continue
            val b64 = inline.optString("data").takeIf { it.isNotEmpty() } ?: continue
            val pcm = runCatching { Base64.decode(b64, Base64.DEFAULT) }.getOrNull() ?: continue
            val mime = inline.optString("mimeType").ifBlank { "audio/L16;rate=24000" }
            if (mime.lowercase().contains("wav")) return pcm
            return wrapPcm16InWav(pcm, sampleRate(mime))
        }
        throw VoiceProviderException.Parse("No audio in Gemini TTS response")
    }
}

// -- ElevenLabs (TTS) — REST, xi-api-key header, returns MP3 ------------------

/**
 * ElevenLabs TTS. The model entry `id` carries the ElevenLabs voice_id; a fixed
 * model_id (eleven_multilingual_v2) drives synthesis.
 * POST {base}/v1/text-to-speech/{voice_id} → audio/mpeg.
 */
class ElevenLabsVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {

    companion object {
        private const val DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM" // Rachel
        private const val MODEL_ID = "eleven_multilingual_v2"
    }

    override val supportsVoiceInput: Boolean get() = false

    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        // The selected model entry id is the ElevenLabs voice_id.
        val voiceId = request.model?.takeIf { it.isNotEmpty() }
            ?: request.voice?.takeIf { it.isNotEmpty() }
            ?: DEFAULT_VOICE_ID
        var base = effectiveBaseURL()
        if (!base.contains("/v1")) base += "/v1"
        val body = JSONObject()
            .put("text", request.input)
            .put("model_id", MODEL_ID)
            .put(
                "voice_settings",
                JSONObject().put("stability", 0.5).put("similarity_boost", 0.75),
            )
        val req = Request.Builder()
            .url("$base/text-to-speech/$voiceId")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .header("xi-api-key", apiKey ?: "")
            .header("Accept", "audio/mpeg")
            .build()
        return executeRequest(req)   // MP3 bytes
    }
}

// -- Deepgram — ASR (/v1/listen) + TTS Aura (/v1/speak), Token header ---------

class DeepgramVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {

    companion object {
        private const val DEFAULT_ASR_MODEL = "nova-2"
        private const val DEFAULT_TTS_MODEL = "aura-asteria-en"
    }

    private fun dgBase(): String {
        var base = effectiveBaseURL()
        if (!base.contains("/v1")) base += "/v1"
        return base
    }

    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        val model = request.model?.takeIf { it.isNotEmpty() } ?: DEFAULT_TTS_MODEL
        val req = Request.Builder()
            .url("${dgBase()}/speak?model=$model")
            .post(
                JSONObject().put("text", request.input).toString()
                    .toRequestBody("application/json".toMediaType()),
            )
            .header("Authorization", "Token ${apiKey ?: ""}")
            .build()
        return executeRequest(req)
    }

    override fun buildVoiceInputRequest(request: VoiceInputRequest): Request {
        val model = request.model?.takeIf { it.isNotEmpty() } ?: DEFAULT_ASR_MODEL
        var qs = "model=$model&smart_format=true"
        request.language?.takeIf { it.isNotEmpty() }?.let { qs += "&language=$it" }
        return Request.Builder()
            .url("${dgBase()}/listen?$qs")
            .post(request.audioData.toRequestBody("audio/wav".toMediaType()))
            .header("Authorization", "Token ${apiKey ?: ""}")
            .build()
    }

    override fun parseVoiceInputResponse(data: ByteArray, request: VoiceInputRequest): VoiceInputResponse {
        val transcript = runCatching { JSONObject(String(data, Charsets.UTF_8)) }.getOrNull()
            ?.optJSONObject("results")
            ?.optJSONArray("channels")
            ?.optJSONObject(0)
            ?.optJSONArray("alternatives")
            ?.optJSONObject(0)
            ?.optString("transcript")
            ?: throw VoiceProviderException.Parse("Unexpected Deepgram ASR response")
        return VoiceInputResponse(text = transcript, language = request.language)
    }
}

// -- Azure TTS (REST API, Ocp-Apim-Subscription-Key auth) ---------------------

class AzureTTSVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {

    override val supportsVoiceInput: Boolean get() = false
    override fun defaultVoiceOutputModel() = "azure-tts"
    override fun defaultVoiceOutputVoice() = "zh-CN-XiaoxiaoNeural"

    override fun buildVoiceOutputRequest(request: VoiceOutputRequest): Request {
        val url = composedUrlString("/cognitiveservices/v1")
        val voice = request.voice ?: defaultVoiceOutputVoice()
        val parts = voice.split("-")
        val lang = if (parts.size >= 2) "${parts[0]}-${parts[1]}" else "en-US"
        val escaped = request.input
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        val ssml = "<speak version=\"1.0\" xmlns=\"http://www.w3.org/2001/10/synthesis\" xml:lang=\"$lang\">" +
            "<voice name=\"$voice\">$escaped</voice></speak>"
        val builder = Request.Builder()
            .url(url)
            .post(ssml.toRequestBody("application/ssml+xml".toMediaType()))
            .header("X-Microsoft-OutputFormat", "audio-24khz-48kbitrate-mono-mp3")
        apiKey?.takeIf { it.isNotEmpty() }?.let { builder.header("Ocp-Apim-Subscription-Key", it) }
        return builder.build()
    }
}

// -- Xiaomi MiMo (ASR + TTS, both ride on /v1/chat/completions) ---------------

class MimoVoiceProvider(providerId: String, baseURL: String, apiKey: String?) :
    VoiceProvider(providerId, baseURL, apiKey) {

    companion object {
        private const val TAG = "MimoVoice"
        private val API_MODELS = setOf("mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign", "mimo-v2.5-tts-voiceclone")
    }

    override fun defaultVoiceInputModel() = "mimo-v2.5-asr"
    override fun defaultVoiceOutputModel() = "mimo-v2.5-tts"
    override fun defaultVoiceOutputVoice() = "mimo_default"

    // ASR ----------------------------------------------------------------------

    override suspend fun transcribe(request: VoiceInputRequest): VoiceInputResponse {
        val url = composedUrlString("/v1/chat/completions")
        val audioBase64 = Base64.encodeToString(request.audioData, Base64.NO_WRAP)
        val lang = iso6391(request.language) ?: "auto"
        val body = JSONObject().apply {
            put("model", request.model ?: defaultVoiceInputModel())
            put(
                "messages",
                JSONArray().put(
                    JSONObject()
                        .put("role", "user")
                        .put(
                            "content",
                            JSONArray().put(
                                JSONObject()
                                    .put("type", "input_audio")
                                    .put(
                                        "input_audio",
                                        JSONObject().put("data", audioBase64).put("format", "wav"),
                                    ),
                            ),
                        ),
                ),
            )
            put("asr_options", JSONObject().put("language", lang))
        }
        val builder = Request.Builder()
            .url(url)
            .post(body.toString().toRequestBody("application/json".toMediaType()))
        applyVoiceAuth(builder)

        val data = executeRequest(builder.build())
        val json = runCatching { JSONObject(String(data, Charsets.UTF_8)) }.getOrNull()
        val text = json?.optJSONArray("choices")
            ?.optJSONObject(0)
            ?.optJSONObject("message")
            ?.optString("content")
            ?: throw VoiceProviderException.Parse("Unexpected MiMo ASR response format")
        val seconds = json.optJSONObject("usage")?.optDouble("seconds")?.takeIf { !it.isNaN() }
        return VoiceInputResponse(text = text, durationSeconds = seconds)
    }

    // TTS ----------------------------------------------------------------------

    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        val url = composedUrlString("/v1/chat/completions")
        val rawModel = request.model ?: defaultVoiceOutputModel()
        val apiModel: String
        val voiceId: String?
        if (rawModel in API_MODELS) {
            apiModel = rawModel
            voiceId = request.voice
        } else {
            apiModel = "mimo-v2.5-tts"
            voiceId = rawModel
        }
        val audioParams = JSONObject().put("format", "wav")
        if (apiModel != "mimo-v2.5-tts-voicedesign" && voiceId != null) {
            audioParams.put("voice", voiceId)
        }
        val body = JSONObject().apply {
            put("model", apiModel)
            put(
                "messages",
                JSONArray()
                    .put(JSONObject().put("role", "user").put("content", ""))
                    .put(JSONObject().put("role", "assistant").put("content", request.input)),
            )
            put("audio", audioParams)
        }
        val builder = Request.Builder()
            .url(url)
            .post(body.toString().toRequestBody("application/json".toMediaType()))
        applyVoiceAuth(builder)

        val data = executeRequest(builder.build())
        val b64 = runCatching { JSONObject(String(data, Charsets.UTF_8)) }.getOrNull()
            ?.optJSONArray("choices")
            ?.optJSONObject(0)
            ?.optJSONObject("message")
            ?.optJSONObject("audio")
            ?.optString("data")
            ?.takeIf { it.isNotEmpty() }
            ?: throw VoiceProviderException.Parse("Unexpected MiMo TTS response format")
        return runCatching { Base64.decode(b64, Base64.DEFAULT) }.getOrNull()
            ?: throw VoiceProviderException.Parse("Unexpected MiMo TTS response format")
    }
}
