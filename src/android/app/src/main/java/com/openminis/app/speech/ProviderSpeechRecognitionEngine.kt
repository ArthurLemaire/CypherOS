package com.openminis.app.speech

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Log
import com.openminis.app.MinisApp
import com.openminis.app.provider.voice.VoiceInputRequest
import com.openminis.app.provider.voice.VoiceProvider
import com.openminis.app.provider.voice.VoiceProviderException
import com.openminis.app.provider.voice.VoiceProviderFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.log10
import kotlin.math.sqrt

/**
 * [T-android-provider-voice] Provider-backed transcription engine — the
 * formerly-stubbed Phase 2. Captures PCM16 mono 16 kHz via [AudioRecord],
 * wraps the take in a WAV container on stop, and ships it to the VoiceProvider
 * resolved from the Voice Input group (VoiceProviderFactory + the instance's
 * stored API key). Mirrors the iOS provider ASR path (VoiceProvider.transcribe:
 * dedicated Whisper-style endpoint, vendor adapters, or chat-based ASR for
 * audio chat models).
 *
 * No partial results: cloud transcription is one-shot on stop. The System
 * engine remains the streaming/live option.
 */
class ProviderSpeechRecognitionEngine(private val appContext: Context) : SpeechRecognitionEngine {

    companion object {
        private const val TAG = "ProviderASR"
        private const val SAMPLE_RATE = 16_000
        /** Hard cap on a single take (60 s at 16 kHz PCM16 mono ≈ 1.9 MB). */
        private const val MAX_RECORD_SECONDS = 60
    }

    override val id: String = "provider"
    override val displayName: String = "Provider transcription"
    override val supportsPartialResults: Boolean = false

    /** Cheap check only: is a provider ASR selection resolvable right now? */
    override val isAvailable: Boolean
        get() = !degraded && repository()?.resolveVoiceInputEntry() != null

    /** Cloud ASR is language-agnostic (auto-detect); no fixed locale list. */
    override val supportedLocales: List<Locale> = emptyList()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var captureJob: Job? = null
    private var transcribeJob: Job? = null
    private val recording = AtomicBoolean(false)
    private val cancelled = AtomicBoolean(false)
    private var degraded = false

    /**
     * [T-voice-asr-group-failover] STICKY fail-over (mirrors iOS
     * VoiceInputViewModel and the text agent loop's nextFallback): once a take
     * succeeds on a group member, later takes start there — only advance when
     * IT fails. Cleared implicitly when the entry leaves the candidate set
     * (the ordering below just falls back to chain order then).
     */
    @Volatile
    private var stickyEntryId: String? = null

    private fun repository() =
        (appContext.applicationContext as? MinisApp)?.providerRepository

    override fun markDegraded() {
        degraded = true
    }

    @SuppressLint("MissingPermission") // caller ensures RECORD_AUDIO per interface contract
    override fun start(locale: Locale, listener: SpeechRecognitionEngine.Listener) {
        val repo = repository()
        // [T-voice-asr-group-failover] Resolve the whole ordered candidate
        // chain instead of one entry. loadBalance groups get a fresh rotation
        // seed per capture so takes spread across members; fallback groups
        // keep declaration order. Provider construction is deferred to the
        // transcription step, where a failing member advances to the next.
        val candidates = repo?.resolveVoiceInputCandidates(
            loadBalanceSeed = kotlin.random.Random.nextInt(Int.MAX_VALUE),
        ).orEmpty()
        if (repo == null || candidates.isEmpty()) {
            listener.onError(
                RecognitionError.OEM_NO_SERVICE,
                "No provider voice-input model configured. Add an ASR model to the Voice Input group.",
            )
            return
        }
        if (recording.getAndSet(true)) {
            listener.onError(RecognitionError.RECOGNIZER_BUSY, "A capture is already in flight.")
            return
        }
        cancelled.set(false)

        captureJob = scope.launch {
            val minBuf = AudioRecord.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
            )
            if (minBuf <= 0) {
                recording.set(false)
                listener.onError(RecognitionError.AUDIO_ERROR, "AudioRecord unsupported buffer size.")
                return@launch
            }
            val recorder = try {
                AudioRecord(
                    MediaRecorder.AudioSource.MIC,
                    SAMPLE_RATE,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                    minBuf * 4,
                )
            } catch (e: Exception) {
                recording.set(false)
                listener.onError(RecognitionError.AUDIO_ERROR, "AudioRecord init failed: ${e.message}")
                return@launch
            }
            if (recorder.state != AudioRecord.STATE_INITIALIZED) {
                recorder.release()
                recording.set(false)
                listener.onError(RecognitionError.AUDIO_ERROR, "AudioRecord not initialized.")
                return@launch
            }

            val pcm = ByteArrayOutputStream()
            val buf = ByteArray(minBuf)
            val maxBytes = SAMPLE_RATE * 2 * MAX_RECORD_SECONDS
            try {
                recorder.startRecording()
                listener.onReadyForSpeech()
                while (recording.get() && pcm.size() < maxBytes) {
                    val n = recorder.read(buf, 0, buf.size)
                    if (n <= 0) continue
                    pcm.write(buf, 0, n)
                    listener.onRmsDb(rmsDb(buf, n))
                }
            } catch (e: Exception) {
                Log.e(TAG, "capture failed: ${e.message}", e)
                recording.set(false)
                listener.onError(RecognitionError.AUDIO_ERROR, e.message)
                return@launch
            } finally {
                runCatching { recorder.stop() }
                recorder.release()
            }

            if (cancelled.get()) return@launch
            val audio = pcm.toByteArray()
            if (audio.isEmpty()) {
                listener.onError(RecognitionError.NO_MATCH, "No audio captured.")
                return@launch
            }

            // One-shot cloud transcription of the whole take, with SEAMLESS
            // fail-over across the candidate chain (mirrors iOS
            // transcribeWithFailover / VoiceOutputPlayer): a candidate that
            // throws advances to the next; the first success becomes the
            // STICKY member for later takes; only when EVERY candidate fails
            // does the error surface (last error wins).
            transcribeJob = scope.launch {
                val wav = VoiceProvider.wrapPcm16InWav(audio, SAMPLE_RATE)
                // Sticky-first try order: rotate the chain so the last
                // successful member goes first, the rest wrap around.
                val ordered = stickyEntryId
                    ?.let { sticky -> candidates.indexOfFirst { it.second.id == sticky } }
                    ?.takeIf { it > 0 }
                    ?.let { i -> candidates.drop(i) + candidates.take(i) }
                    ?: candidates
                var lastError: Exception? = null
                for ((instance, entry) in ordered) {
                    if (cancelled.get()) return@launch
                    val provider = VoiceProviderFactory.make(instance, repo.loadApiKey(instance.id))
                    if (provider == null) {
                        Log.w(TAG, "candidate ${instance.label} cannot serve voice input — skipping")
                        continue
                    }
                    try {
                        val response = provider.transcribe(
                            VoiceInputRequest(
                                audioData = wav,
                                model = entry.baseModel.id,
                                language = locale.toLanguageTag(),
                                resolvedModel = entry.model,
                            ),
                        )
                        if (cancelled.get()) return@launch
                        stickyEntryId = entry.id
                        val text = response.text.trim()
                        if (text.isEmpty()) {
                            // A successful round-trip that heard nothing is a
                            // semantic no-match, not a provider failure — do
                            // NOT advance the chain for it.
                            listener.onError(RecognitionError.NO_MATCH, "Empty transcription.")
                        } else {
                            listener.onFinal(text)
                        }
                        return@launch
                    } catch (e: kotlinx.coroutines.CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        Log.e(TAG, "transcribe failed on ${entry.model.displayName}: ${e.message} — trying next candidate")
                        lastError = e
                    }
                }
                if (!cancelled.get()) {
                    val e = lastError
                    val kind = when {
                        e is VoiceProviderException.Auth -> RecognitionError.PERMISSION_DENIED
                        e is java.io.IOException -> RecognitionError.NETWORK
                        else -> RecognitionError.UNKNOWN
                    }
                    listener.onError(kind, e?.message ?: "All voice-input candidates failed.")
                }
            }
        }
    }

    override fun stop() {
        // Flip the capture loop off; the capture coroutine then hands the take
        // to the transcription step, which delivers onFinal/onError.
        recording.set(false)
    }

    override fun cancel() {
        cancelled.set(true)
        recording.set(false)
        transcribeJob?.cancel()
    }

    /** Rough dB estimate over the chunk for the UI waveform. */
    private fun rmsDb(buf: ByteArray, len: Int): Float {
        var sum = 0.0
        var count = 0
        var i = 0
        while (i + 1 < len) {
            val sample = ((buf[i + 1].toInt() shl 8) or (buf[i].toInt() and 0xFF)).toShort().toInt()
            sum += sample.toDouble() * sample
            count++
            i += 2
        }
        if (count == 0) return 0f
        val rms = sqrt(sum / count)
        if (rms <= 1.0) return 0f
        // Map amplitude RMS onto the [0, 12]-ish scale the System engine's
        // onRmsChanged reports, so the shared normalizer behaves identically.
        return (20 * log10(rms / 32768.0) + 50).toFloat().coerceIn(0f, 12f)
    }
}
