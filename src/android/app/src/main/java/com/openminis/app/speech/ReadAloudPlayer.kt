package com.openminis.app.speech

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.widget.Toast
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import com.openminis.app.provider.voice.VoiceOutputRequest
import com.openminis.app.provider.voice.VoiceProviderFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlin.coroutines.resume

/**
 * [T-android-provider-tts-readaloud] Read-aloud playback that routes through
 * the resolved Voice OUTPUT selection, falling back to the on-device engine.
 *
 * ## Why this exists
 * Read-aloud previously constructed a bare [TextToSpeechManager], so it always
 * used the on-device Android engine. The whole provider TTS stack —
 * `VoiceProvider.synthesize()` plus ~723 lines of vendor adapters (MiniMax,
 * Doubao, ElevenLabs, Azure, Gemini, Xunfei, …) — was reachable only from the
 * settings Quick Test sheet, so no provider voice was usable in chat.
 *
 * ## Routing
 * Each utterance asks [com.openminis.app.data.repository.ProviderRepository
 * .resolveVoiceOutputChoice] (added in the P0-1 commit) where to go:
 *  - System choice, no credentials, unsupported vendor, or ANY synthesis
 *    failure → [TextToSpeechManager] (the on-device engine).
 *  - Provider choice → `synthesize()` then play the returned bytes.
 *
 * Fallback is per-utterance and silent by design: a mid-reply network blip
 * degrades to the device voice rather than dropping the sentence.
 *
 * ## Ordering
 * Utterances go through a [Channel] consumed by a single worker coroutine, so
 * sentence N+1 is synthesized/played only after N finishes. Without this,
 * concurrent `synthesize()` calls would return out of order and the reply would
 * be read scrambled. This is the Android stand-in for iOS's
 * `VoiceOutputPlayer` queue (we deliberately do NOT prefetch-ahead yet — that
 * is P1 territory).
 *
 * Text is sanitized via [VoiceTextSanitizer] before either path, so Markdown,
 * URLs and emoji are never pronounced.
 *
 * Not thread-safe beyond the channel; call from the main thread.
 */
class ReadAloudPlayer(context: Context) {

    private val appContext = context.applicationContext
    private val system = TextToSpeechManager().also { it.init(appContext) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val queue = Channel<String>(Channel.UNLIMITED)
    private var worker: Job? = null

    /** Currently playing provider audio, if any — held so [stop] can cancel it. */
    private var player: MediaPlayer? = null

    /**
     * Completes the in-flight [playBytes] suspension when [stop] tears the
     * MediaPlayer down. Releasing the player means its completion/error
     * callbacks will never fire, so without this the worker coroutine would
     * wait forever and the queue would wedge.
     */
    private var playbackFinisher: (() -> Unit)? = null

    /** Utterances enqueued but not yet finished; drives [isSpeaking]. */
    private val pending = AtomicInteger(0)

    private val _isSpeaking = MutableStateFlow(false)
    val isSpeaking: StateFlow<Boolean> = _isSpeaking.asStateFlow()

    /**
     * Rolling buffer for streaming input. Mirrors [TextToSpeechManager]'s own
     * buffer, but lives here so the sentence split happens BEFORE the routing
     * decision (each sentence is independently a provider or system utterance).
     */
    private val sentenceBuffer = StringBuilder()

    private val linkPhrases by lazy {
        VoiceTextSanitizer.LinkPhrases(
            linkToHost = appContext.getString(R.string.voice_link_to_host),
            bareLink = appContext.getString(R.string.voice_bare_link),
        )
    }

    init {
        worker = scope.launch {
            for (text in queue) {
                runCatching { speakOne(text) }
                    .onFailure { AppLogger.error(TAG, "utterance failed: $it") }
                // Queue drained → speech is over. Counter rather than
                // Channel.isEmpty, which is experimental API.
                if (pending.decrementAndGet() <= 0) _isSpeaking.value = false
            }
        }
    }

    /**
     * Feed a chunk of streaming assistant output. Complete sentences are
     * enqueued as they appear so the first one starts speaking the moment its
     * terminator arrives, instead of waiting for the whole reply.
     */
    fun appendText(chunk: String) {
        if (chunk.isEmpty()) return
        sentenceBuffer.append(chunk)
        for (sentence in extractCompleteSentences(sentenceBuffer)) {
            enqueue(sentence)
        }
    }

    /** Emit the buffered tail (a fragment with no terminator). Call at stream end. */
    fun flush() {
        if (sentenceBuffer.isEmpty()) return
        val tail = sentenceBuffer.toString().trim()
        sentenceBuffer.setLength(0)
        if (tail.isNotEmpty()) enqueue(tail)
    }

    /** Speak [text] as a single utterance, after stopping anything in flight. */
    fun speak(text: String) {
        stop()
        enqueue(text)
    }

    private fun enqueue(raw: String) {
        // Sanitize here, not at playback: a chunk that is pure Markdown (e.g. a
        // fenced code block) sanitizes to empty and must not occupy the queue.
        val clean = VoiceTextSanitizer.sanitize(raw, linkPhrases)
        if (clean.isBlank()) return
        pending.incrementAndGet()
        _isSpeaking.value = true
        queue.trySend(clean)
    }

    /** Stop playback and drop everything pending. */
    fun stop() {
        sentenceBuffer.setLength(0)
        while (queue.tryReceive().isSuccess) { /* drain */ }
        // Unblock the worker BEFORE releasing, so the in-flight utterance's
        // suspension completes instead of waiting on callbacks that a released
        // MediaPlayer will never deliver.
        playbackFinisher?.invoke()
        releasePlayer()
        system.stop()
        pending.set(0)
        _isSpeaking.value = false
    }

    /** Release both engines. Call from the owner's DisposableEffect. */
    fun shutdown() {
        stop()
        worker?.cancel()
        queue.close()
        scope.cancel()
        system.shutdown()
    }

    // -- internals --

    private suspend fun speakOne(text: String) {
        val entry = runCatching {
            (appContext as? MinisApp)?.providerRepository?.resolveVoiceOutputEntry()
        }.getOrNull()

        if (entry != null) {
            val (instance, modelEntry) = entry
            val ok = runCatching { speakViaProvider(instance, modelEntry, text) }
                .getOrElse {
                    AppLogger.error(
                        TAG,
                        "provider TTS failed (model=${modelEntry.model.id} " +
                            "vendor=${instance.providerType}), falling back to system engine: $it",
                    )
                    false
                }
            if (ok) return
        }
        if (!speakViaSystem(text)) {
            // [T-android-tts-silent-blackhole] Terminal state: the provider path
            // did not produce audio AND the device speech engine is unusable.
            // iOS can't reach this (AVSpeechSynthesizer always exists), which is
            // why read-aloud "just works" there while Android could go silent
            // with no feedback at all — the reported OPPO symptom. Tell the user
            // once instead of swallowing it.
            notifySpeechUnavailable(providerConfigured = entry != null)
        }
    }

    /** One-shot user-visible signal that read-aloud cannot produce sound. */
    private var unavailableNotified = false

    private fun notifySpeechUnavailable(providerConfigured: Boolean) {
        AppLogger.error(
            TAG,
            "read-aloud produced NO audio: providerConfigured=$providerConfigured " +
                "systemEngine=${if (system.initFailed) "init-failed" else "unavailable"}",
        )
        if (unavailableNotified) return
        unavailableNotified = true
        // The worker runs on Dispatchers.Main.immediate, so Toast is safe here.
        Toast.makeText(
            appContext,
            appContext.getString(R.string.read_aloud_unavailable),
            Toast.LENGTH_LONG,
        ).show()
    }

    /** @return true when provider audio was synthesized AND played. */
    private suspend fun speakViaProvider(
        instance: com.openminis.app.data.model.ProviderInstance,
        modelEntry: com.openminis.app.data.model.ModelEntry,
        text: String,
    ): Boolean {
        // [T-android-safemode-lateinit-crash-147] `?.` guards a null
        // Application but NOT an unassigned lateinit — the getter throws.
        // Read-aloud can be driven from a notification action with no
        // Activity, so gate on subsystemsReady() before touching a repository.
        // Each bail-out logs its reason: these gates used to return false
        // silently, which made "no sound" undiagnosable from a user device
        // (the daily log files showed nothing at all).
        val repo = (appContext as? MinisApp)
            ?.takeIf { it.subsystemsReady() }
            ?.providerRepository
            ?: return false.also { AppLogger.error(TAG, "provider TTS skipped: repository unavailable") }
        val apiKey = repo.loadApiKey(instance.id)
            ?: return false.also { AppLogger.error(TAG, "provider TTS skipped: no API key for ${instance.id}") }
        val voice = VoiceProviderFactory.make(instance, apiKey)
            ?: return false.also { AppLogger.error(TAG, "provider TTS skipped: no voice adapter for ${instance.providerType}/${instance.customBaseURL}") }
        if (!voice.supportsVoiceOutput) {
            AppLogger.error(TAG, "provider TTS skipped: ${voice.javaClass.simpleName} does not support output")
            return false
        }

        val data = withContext(Dispatchers.IO) {
            voice.synthesize(
                // The entry id doubles as the voice id — template voices carry
                // the voice id as the model id (same convention QuickTestSheet
                // relies on, iOS 0a52bdbf).
                VoiceOutputRequest(
                    input = text,
                    model = modelEntry.model.id,
                    voice = modelEntry.model.id,
                ),
            )
        }
        if (data.isEmpty()) {
            AppLogger.error(TAG, "provider TTS returned empty audio (model=${modelEntry.model.id})")
            return false
        }
        playBytes(data)
        return true
    }

    /**
     * Write [data] to a cache file and play it to completion. Same approach as
     * QuickTestSheet — MediaPlayer needs a file/descriptor, not a byte array.
     */
    private suspend fun playBytes(data: ByteArray) {
        val file = withContext(Dispatchers.IO) {
            File(appContext.cacheDir, "readaloud_tts.audio").apply { writeBytes(data) }
        }
        suspendCancellableCoroutine { cont ->
            val mp = MediaPlayer()
            player = mp
            var resumed = false
            fun finish() {
                if (resumed) return
                resumed = true
                playbackFinisher = null
                releasePlayer()
                if (cont.isActive) cont.resume(Unit)
            }
            // Let stop()/shutdown() complete this suspension after releasing
            // the player, since the callbacks below can no longer fire.
            playbackFinisher = ::finish
            runCatching {
                // [T-android-tts-silent-blackhole] Explicit attributes + audio
                // focus. iOS routes playback through AudioSessionCoordinator;
                // Android had neither, and some OEM ROMs (ColorOS among them)
                // will silently mute focus-less media playback. Focus denial is
                // logged but non-fatal — muting is the exception, not the rule.
                mp.setAudioAttributes(playbackAttributes)
                requestAudioFocus()
                mp.setDataSource(file.absolutePath)
                mp.setOnCompletionListener { finish() }
                mp.setOnErrorListener { _, what, extra ->
                    AppLogger.error(TAG, "MediaPlayer error what=$what extra=$extra")
                    finish()
                    true
                }
                mp.prepare()
                mp.start()
            }.onFailure {
                AppLogger.error(TAG, "MediaPlayer setup failed: $it")
                finish()
            }
            cont.invokeOnCancellation { releasePlayer() }
        }
    }

    // -- audio focus [T-android-tts-silent-blackhole] --

    private val audioManager =
        appContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    private val playbackAttributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_MEDIA)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()

    private var focusRequest: AudioFocusRequest? = null

    private fun requestAudioFocus() {
        val req = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(playbackAttributes)
            .build()
        focusRequest = req
        val granted = audioManager.requestAudioFocus(req)
        if (granted != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            AppLogger.info(TAG, "audio focus not granted ($granted) — playing anyway")
        }
    }

    private fun abandonAudioFocus() {
        focusRequest?.let { audioManager.abandonAudioFocusRequest(it) }
        focusRequest = null
    }

    /**
     * Speak via the on-device engine and wait for it to finish, so the queue
     * stays ordered. [TextToSpeechManager.isSpeaking] flips false on the last
     * utterance's onDone.
     *
     * @return false when the engine is unusable (init failed / never bound) —
     *   the caller surfaces that instead of pretending the sentence was spoken.
     */
    private suspend fun speakViaSystem(text: String): Boolean {
        // [T-android-tts-silent-blackhole] Engine binding is async; speaking
        // before it settles used to drop the text on the floor. Wait (bounded)
        // for a verdict first.
        if (!system.awaitReady()) return false
        system.speak(text)
        // Poll rather than plumb a callback through: utterances are short and
        // this keeps TextToSpeechManager's public surface unchanged.
        while (system.isSpeaking.value) {
            kotlinx.coroutines.delay(POLL_MS)
        }
        return true
    }

    private fun releasePlayer() {
        player?.runCatching {
            if (isPlaying) stop()
            release()
        }
        player = null
        abandonAudioFocus()
    }

    /**
     * [T-android-tts-intranumber-guard] Delegates to the shared
     * [SpeechSentenceSplitter] so this path and [TextToSpeechManager] apply the
     * same terminator set AND the same intra-number guards ("3.14" is never cut
     * into "3." + "14").
     */
    private fun extractCompleteSentences(buffer: StringBuilder): List<String> =
        SpeechSentenceSplitter.extractCompleteSentences(buffer)

    companion object {
        private const val TAG = "ReadAloud"
        private const val POLL_MS = 80L
    }
}
