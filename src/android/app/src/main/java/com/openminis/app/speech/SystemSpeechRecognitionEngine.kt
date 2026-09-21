package com.openminis.app.speech

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.Locale

/**
 * Wraps [android.speech.SpeechRecognizer]. Handles OEM fragmentation —
 * especially Chinese ROMs where [SpeechRecognizer.isRecognitionAvailable]
 * can return `true` yet [SpeechRecognizer.startListening] immediately fires
 * ERROR_INSUFFICIENT_PERMISSIONS or ERROR_CLIENT. A first-failure observation
 * marks the engine permanently degraded for the rest of the process so the
 * UI can hide the mic button.
 *
 * Must be constructed and used on the main thread because [SpeechRecognizer]
 * delivers callbacks on the thread that creates it.
 */
class SystemSpeechRecognitionEngine(private val appContext: Context) : SpeechRecognitionEngine {

    override val id: String = "system"
    override val displayName: String = "System recognizer"
    override val supportsPartialResults: Boolean = true

    /** Session-scoped degraded flag — set once a runtime error proves the service unusable. */
    @Volatile private var degraded: Boolean = false

    /** Cached supported locales (populated lazily on first request). */
    @Volatile private var cachedSupportedLocales: List<Locale>? = null

    private var recognizer: SpeechRecognizer? = null
    private var listener: SpeechRecognitionEngine.Listener? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    override val isAvailable: Boolean
        get() {
            if (degraded) return false
            // Two-layer probe. The first returns true on many Chinese ROMs
            // that actually ship no real service — the intent query is the
            // backstop. Both cheap.
            val systemSaysYes = try { SpeechRecognizer.isRecognitionAvailable(appContext) }
                catch (_: Throwable) { false }
            if (!systemSaysYes) return false
            val intent = Intent(RecognitionService.SERVICE_INTERFACE)
            val services = try {
                appContext.packageManager.queryIntentServices(intent, 0)
            } catch (_: Throwable) { emptyList() }
            return services.isNotEmpty()
        }

    override val supportedLocales: List<Locale>
        get() = cachedSupportedLocales ?: fallbackLocales

    /**
     * Fire the [RecognizerIntent.ACTION_GET_LANGUAGE_DETAILS] ordered broadcast
     * and cache the recognizer's reported supported languages. Safe to call
     * repeatedly — only the first call does work; subsequent calls short-circuit.
     *
     * The broadcast can take a few hundred ms and some OEM services never
     * respond, so [onResult] is guaranteed to fire exactly once — either with
     * the system's answer or with the curated fallback after a timeout.
     */
    fun fetchSupportedLocales(onResult: (List<Locale>) -> Unit) {
        cachedSupportedLocales?.let { onResult(it); return }

        val fired = java.util.concurrent.atomic.AtomicBoolean(false)
        fun deliver(locales: List<Locale>) {
            if (fired.compareAndSet(false, true)) {
                cachedSupportedLocales = locales
                onResult(locales)
            }
        }

        val receiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val tags = getResultExtras(true)
                    ?.getStringArrayList(RecognizerIntent.EXTRA_SUPPORTED_LANGUAGES)
                    .orEmpty()
                val locales = tags.mapNotNull { tag ->
                    runCatching { Locale.forLanguageTag(tag) }.getOrNull()
                        ?.takeIf { !it.language.isNullOrEmpty() }
                }.distinct()
                if (locales.isNotEmpty()) deliver(locales) else deliver(fallbackLocales)
            }
        }
        try {
            appContext.sendOrderedBroadcast(
                Intent(RecognizerIntent.ACTION_GET_LANGUAGE_DETAILS),
                null, receiver, mainHandler, 0, null, null,
            )
        } catch (e: Throwable) {
            Log.w(TAG, "ACTION_GET_LANGUAGE_DETAILS failed: ${e.message}")
            deliver(fallbackLocales)
            return
        }
        // Backstop in case no one responds.
        mainHandler.postDelayed({ deliver(fallbackLocales) }, 2500)
    }

    /**
     * Curated locale list used when the system refuses to enumerate. Covers
     * the major languages that Google and most OEM recognizers support.
     */
    private val fallbackLocales: List<Locale> by lazy {
        listOf(
            // [T-android-asr-script-subtag] Script-stripped: the raw default on
            // a Simplified-Chinese device is zh-Hans-CN, which the recognizer
            // rejects. Since this list is also what SpeechRecognitionManager
            // re-validates the saved locale against, leaving the raw default
            // here made the broken locale look "supported" and the fallback
            // never fired.
            Locale.forLanguageTag(recognizerLanguageTag(Locale.getDefault())),
            Locale.forLanguageTag("en-US"),
            Locale.forLanguageTag("zh-CN"),
            Locale.forLanguageTag("zh-TW"),
            Locale.forLanguageTag("ja-JP"),
            Locale.forLanguageTag("ko-KR"),
            Locale.forLanguageTag("es-ES"),
            Locale.forLanguageTag("fr-FR"),
            Locale.forLanguageTag("de-DE"),
            Locale.forLanguageTag("it-IT"),
            Locale.forLanguageTag("pt-BR"),
            Locale.forLanguageTag("ru-RU"),
            Locale.forLanguageTag("ar-SA"),
            Locale.forLanguageTag("hi-IN"),
            Locale.forLanguageTag("id-ID"),
            Locale.forLanguageTag("th-TH"),
            Locale.forLanguageTag("vi-VN"),
            Locale.forLanguageTag("tr-TR"),
        ).distinctBy { it.toLanguageTag() }
    }

    override fun start(locale: Locale, listener: SpeechRecognitionEngine.Listener) {
        this.listener = listener

        if (ContextCompat.checkSelfPermission(appContext, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            listener.onError(RecognitionError.PERMISSION_DENIED, "RECORD_AUDIO not granted")
            return
        }

        startInternal(locale, allowOnDeviceRetry = true)
    }

    /**
     * [T-android-asr-ondevice-fallback] Start a session.
     *
     * [allowOnDeviceRetry] is true for the first attempt; when the on-device
     * (SODA) recognizer answers ERROR_LANGUAGE_UNAVAILABLE we restart once with
     * it false, which forces the regular (typically cloud) recognizer.
     */
    private fun startInternal(locale: Locale, allowOnDeviceRetry: Boolean) {
        mainHandler.post {
            try {
                // Only reach for the on-device recognizer when the user actually
                // asked for offline. It used to be created unconditionally on
                // S+, which silently overrode the panel's "System Recognition
                // (Online)" choice — and on a device with no on-device pack for
                // the locale (e.g. a zh-CN Pixel 4a) SODA fails every session
                // with "Failed to get language pack" / ERROR_LANGUAGE_
                // UNAVAILABLE(12), so the mic opened and closed instantly.
                val wantOnDevice = preferOffline &&
                    Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
                    allowOnDeviceRetry
                val r = if (wantOnDevice) {
                    try { SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext) }
                    catch (_: Throwable) { SpeechRecognizer.createSpeechRecognizer(appContext) }
                } else {
                    SpeechRecognizer.createSpeechRecognizer(appContext)
                }
                usingOnDevice = wantOnDevice
                pendingLocale = locale
                recognizer = r
                r.setRecognitionListener(callbacks)
                r.startListening(buildIntent(locale))
            } catch (e: Throwable) {
                Log.w(TAG, "startListening threw: ${e.message}")
                this.listener?.onError(RecognitionError.UNKNOWN, e.message)
                markDegraded()
                tearDown()
            }
        }
    }

    /** True when the live session is using the on-device recognizer. */
    @Volatile private var usingOnDevice: Boolean = false

    /** Locale of the live session, so a fallback restart can reuse it. */
    @Volatile private var pendingLocale: Locale? = null

    override fun stop() {
        mainHandler.post {
            try { recognizer?.stopListening() }
            catch (e: Throwable) { Log.w(TAG, "stopListening: ${e.message}") }
        }
    }

    override fun cancel() {
        mainHandler.post {
            try { recognizer?.cancel() }
            catch (e: Throwable) { Log.w(TAG, "cancel: ${e.message}") }
            tearDown()
        }
    }

    override fun markDegraded() {
        degraded = true
    }

    private fun tearDown() {
        try { recognizer?.destroy() } catch (_: Throwable) {}
        recognizer = null
    }

    /**
     * [T-android-voice-panel] Prefer fully on-device recognition (maps the
     * panel's "System Recognition (Offline)" pick). Best-effort: the OS may
     * still fall back when no offline pack is installed for the locale.
     */
    @Volatile var preferOffline: Boolean = false

    /**
     * [T-android-asr-script-subtag] Strip the SCRIPT subtag from a language tag
     * before handing it to the recognizer.
     *
     * `Locale.getDefault()` on a Simplified-Chinese device is `zh-Hans-CN`, and
     * `toLanguageTag()` faithfully returns "zh-Hans-CN". Google's recognizer
     * matches its language packs on plain `language-REGION` tags, so the script
     * subtag makes it report "Locale not supported" / "Failed to get language
     * pack of required locale" and fail the session with ERROR_LANGUAGE_
     * UNAVAILABLE (12) — the mic opens and immediately closes. Observed on a
     * Pixel 4a whose system locale is zh-Hans-CN.
     *
     * Reducing to language(+region) keeps the meaningful part ("zh-CN") and is
     * safe for every other locale: tags without a script subtag are unchanged.
     */
    private fun recognizerLanguageTag(locale: Locale): String {
        val lang = locale.language
        var region = locale.country
        // A script-only locale carries no region ("zh-Hans"), and a bare "zh"
        // is just as unresolvable to the recognizer as "zh-Hans" — it needs a
        // concrete language pack. Derive the region from the script, which is
        // exactly the information the script subtag encodes.
        if (region.isNullOrEmpty() && lang == "zh") {
            region = if (locale.script == "Hant") "TW" else "CN"
        }
        // Last resort for any other script-only/region-less locale: ask ICU to
        // fill in the likely region (zh-Hans -> zh-Hans-CN, etc.).
        if (region.isNullOrEmpty()) {
            region = runCatching { Locale.Builder().setLocale(locale).build() }
                .getOrNull()?.country.orEmpty()
        }
        return if (region.isEmpty()) lang else "$lang-$region"
    }

    private fun buildIntent(locale: Locale): Intent {
        return Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, recognizerLanguageTag(locale))
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, appContext.packageName)
            if (preferOffline) putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            // Hint to the system: keep listening briefly through pauses so
            // multi-sentence dictation works without auto-stopping.
            // Docs say "long" but Pixel's AiAi service reads it as Int; pass both.
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 1500)
            putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 1500)
        }
    }

    private val callbacks = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) { listener?.onReadyForSpeech() }
        override fun onBeginningOfSpeech() {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {}
        override fun onEvent(eventType: Int, params: Bundle?) {}
        override fun onRmsChanged(rms: Float) { listener?.onRmsDb(rms) }

        override fun onPartialResults(partialResults: Bundle?) {
            val text = partialResults
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
            if (text.isNotEmpty()) listener?.onPartial(text)
        }

        override fun onResults(results: Bundle?) {
            val text = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
            listener?.onFinal(text)
            tearDown()
        }

        override fun onError(errorCode: Int) {
            val err = mapError(errorCode)
            val msg = errorMessage(errorCode)
            // [T-android-asr-ondevice-fallback] The on-device recognizer has no
            // language pack for this locale. That is a property of THIS
            // recognizer, not of the device's speech support — the cloud one
            // usually handles the same locale fine. Restart once against the
            // regular recognizer instead of surfacing a dead end to the user.
            val retryLocale = pendingLocale
            if (err == RecognitionError.LANGUAGE_UNSUPPORTED && usingOnDevice && retryLocale != null) {
                Log.i(TAG, "on-device recognizer lacks a pack for the locale — retrying via the default recognizer")
                usingOnDevice = false
                tearDown()
                startInternal(retryLocale, allowOnDeviceRetry = false)
                return
            }
            // First-class ROM-level failures poison the engine for the rest of
            // the process so we don't keep showing a button that doesn't work.
            if (err == RecognitionError.OEM_NO_SERVICE ||
                err == RecognitionError.PERMISSION_DENIED ||
                err == RecognitionError.AUDIO_ERROR
            ) {
                markDegraded()
            }
            Log.w(TAG, "recognizer error $errorCode ($msg)")
            listener?.onError(err, msg)
            tearDown()
        }
    }

    companion object {
        private const val TAG = "SystemSTT"

        private fun mapError(code: Int): RecognitionError = when (code) {
            SpeechRecognizer.ERROR_NO_MATCH,
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> RecognitionError.NO_MATCH
            SpeechRecognizer.ERROR_NETWORK,
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> RecognitionError.NETWORK
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> RecognitionError.PERMISSION_DENIED
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> RecognitionError.RECOGNIZER_BUSY
            SpeechRecognizer.ERROR_AUDIO -> RecognitionError.AUDIO_ERROR
            SpeechRecognizer.ERROR_CLIENT -> RecognitionError.OEM_NO_SERVICE
            SpeechRecognizer.ERROR_SERVER -> RecognitionError.NETWORK
            // Codes added in API 33; referenced by literal for compatibility.
            11 /* ERROR_LANGUAGE_NOT_SUPPORTED */,
            12 /* ERROR_LANGUAGE_UNAVAILABLE   */ -> RecognitionError.LANGUAGE_UNSUPPORTED
            else -> RecognitionError.UNKNOWN
        }

        private fun errorMessage(code: Int): String = when (code) {
            SpeechRecognizer.ERROR_AUDIO -> "Audio recording error"
            SpeechRecognizer.ERROR_CLIENT -> "Client error (no recognition service?)"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "RECORD_AUDIO required"
            SpeechRecognizer.ERROR_NETWORK -> "Network error"
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "Network timeout"
            SpeechRecognizer.ERROR_NO_MATCH -> "No speech recognized"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "Recognizer busy"
            SpeechRecognizer.ERROR_SERVER -> "Server error"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "Speech timeout"
            // [T-android-asr-script-subtag] mapError already classifies 11/12 as
            // LANGUAGE_UNSUPPORTED, but this function built the user-visible
            // string and had no case for them — so a language-pack problem
            // surfaced as the useless "Unknown error (12)". Name the actual
            // cause, and point at the fix the user can act on.
            11 /* ERROR_LANGUAGE_NOT_SUPPORTED */ ->
                "Language not supported by the recognizer"
            12 /* ERROR_LANGUAGE_UNAVAILABLE */ ->
                "Language pack unavailable — download it in the system speech settings"
            else -> "Unknown error ($code)"
        }
    }
}
