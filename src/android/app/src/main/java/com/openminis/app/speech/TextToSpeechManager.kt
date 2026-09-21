package com.openminis.app.speech

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.Locale
import java.util.UUID

/**
 * Manages Android TextToSpeech engine for reading assistant responses aloud.
 * Supports en-US and zh-CN with automatic language detection.
 */
class TextToSpeechManager : TextToSpeech.OnInitListener {

    companion object {
        private const val TAG = "TextToSpeech"
        private val HAN_REGEX = Regex("[\\u4e00-\\u9fff\\u3400-\\u4dbf]")
        // [T-android-tts-intranumber-guard] The sentence-boundary set moved to
        // SpeechSentenceSplitter.SENTENCE_ENDERS — a single source of truth
        // shared with ReadAloudPlayer, so the two TTS paths can't drift.
    }

    private var tts: TextToSpeech? = null
    var isInitialized = false
        private set

    private val _isSpeaking = MutableStateFlow(false)
    val isSpeaking: StateFlow<Boolean> = _isSpeaking.asStateFlow()

    private var isPaused = false
    private var pendingTexts = mutableListOf<String>()
    private var pausedAtIndex = 0

    /**
     * Rolling buffer of partial-streaming text that hasn't hit a sentence
     * boundary yet. Cleared by [flush] or [stop]. See [appendText].
     */
    private val sentenceBuffer = StringBuilder()

    var speechRate: Float = 1.0f
        set(value) {
            field = value.coerceIn(0.1f, 3.0f)
            tts?.setSpeechRate(field)
        }

    var speechPitch: Float = 1.0f
        set(value) {
            field = value.coerceIn(0.5f, 2.0f)
            tts?.setPitch(field)
        }

    var speechVolume: Float = 1.0f
        set(value) {
            field = value.coerceIn(0f, 1f)
        }

    /**
     * Initializes the TTS engine. Must be called before speaking.
     */
    fun init(context: Context) {
        tts = TextToSpeech(context.applicationContext, this)
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            isInitialized = true
            tts?.apply {
                setSpeechRate(speechRate)
                setPitch(speechPitch)
                setLanguage(Locale.US)
                setOnUtteranceProgressListener(createProgressListener())
            }
            Log.d(TAG, "TTS initialized successfully")
        } else {
            Log.e(TAG, "TTS initialization failed with status: $status")
        }
    }

    /**
     * Speaks text immediately, interrupting any ongoing speech (QUEUE_FLUSH).
     * Automatically detects language from text content.
     */
    fun speak(text: String) {
        if (!isInitialized || text.isBlank()) return

        isPaused = false
        pendingTexts.clear()
        pendingTexts.add(text)
        pausedAtIndex = 0
        sentenceBuffer.setLength(0)

        autoDetectAndSetLanguage(text)

        val params = buildSpeechParams()
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, params, generateUtteranceId())
        _isSpeaking.value = true
    }

    /**
     * Adds text to the speech queue without interrupting (QUEUE_ADD).
     */
    fun speakQueued(text: String) {
        if (!isInitialized || text.isBlank()) return

        pendingTexts.add(text)
        autoDetectAndSetLanguage(text)

        val params = buildSpeechParams()
        tts?.speak(text, TextToSpeech.QUEUE_ADD, params, generateUtteranceId())
        _isSpeaking.value = true
    }

    /**
     * Feed a chunk of streaming AI output. Any complete sentences the chunk
     * produces (boundary characters: `。！？.!?\n` — same set as iOS
     * `extractNewSentences` in AIChatViewModel) are immediately enqueued for
     * TTS via [speakQueued], so the first sentence starts speaking the moment
     * its terminator arrives instead of waiting for the full response.
     *
     * Incomplete tail text stays in [sentenceBuffer] until the next call, or
     * until [flush] runs at stream end.
     *
     * Safe to call before [init]/onInit — chunks are still split; the TTS
     * engine simply drops them if not yet ready (speakQueued guards).
     */
    fun appendText(chunk: String) {
        if (chunk.isEmpty()) return
        sentenceBuffer.append(chunk)
        val sentences = extractCompleteSentences(sentenceBuffer)
        if (sentences.isEmpty()) return
        for (sentence in sentences) {
            speakQueued(sentence)
        }
    }

    /**
     * Emit the remaining buffered tail (a sentence fragment with no trailing
     * punctuation) as a final utterance. Call at the end of a streaming
     * response. Mirrors iOS's post-stream "flush remaining speech" logic.
     */
    fun flush() {
        if (sentenceBuffer.isEmpty()) return
        val tail = sentenceBuffer.toString().trim()
        sentenceBuffer.setLength(0)
        if (tail.isNotEmpty()) {
            speakQueued(tail)
        }
    }

    /**
     * [T-android-tts-intranumber-guard] Delegates to the shared
     * [SpeechSentenceSplitter] so this path and [ReadAloudPlayer] apply the same
     * terminator set AND the same intra-number guards ("3.14" is never cut into
     * "3." + "14").
     */
    private fun extractCompleteSentences(buffer: StringBuilder): List<String> =
        SpeechSentenceSplitter.extractCompleteSentences(buffer)

    /**
     * Stops all speech immediately.
     */
    fun stop() {
        tts?.stop()
        isPaused = false
        pendingTexts.clear()
        pausedAtIndex = 0
        sentenceBuffer.setLength(0)
        _isSpeaking.value = false
    }

    /**
     * Toggles pause/resume. Since Android TTS doesn't natively support pause,
     * this stops playback and tracks position for manual resume.
     */
    fun togglePause() {
        if (isPaused) {
            // Resume: replay remaining texts from where we paused
            isPaused = false
            if (pausedAtIndex < pendingTexts.size) {
                val remaining = pendingTexts.subList(pausedAtIndex, pendingTexts.size)
                remaining.forEachIndexed { index, text ->
                    autoDetectAndSetLanguage(text)
                    val params = buildSpeechParams()
                    val queueMode = if (index == 0) TextToSpeech.QUEUE_FLUSH else TextToSpeech.QUEUE_ADD
                    tts?.speak(text, queueMode, params, generateUtteranceId())
                }
                _isSpeaking.value = true
            }
        } else {
            // Pause: stop and mark position
            isPaused = true
            tts?.stop()
            _isSpeaking.value = false
        }
    }

    /**
     * Sets the TTS language explicitly.
     */
    fun setLanguage(locale: Locale) {
        if (!isInitialized) return
        val result = tts?.setLanguage(locale)
        if (result == TextToSpeech.LANG_MISSING_DATA || result == TextToSpeech.LANG_NOT_SUPPORTED) {
            Log.w(TAG, "Language not supported: ${locale.toLanguageTag()}")
        } else {
            Log.d(TAG, "Language set to: ${locale.toLanguageTag()}")
        }
    }

    /**
     * Cleans up the TTS engine. Must be called when no longer needed.
     */
    fun shutdown() {
        stop()
        tts?.shutdown()
        tts = null
        isInitialized = false
        Log.d(TAG, "TTS shut down")
    }

    /**
     * Detects if text contains Han characters and sets language accordingly.
     */
    private fun autoDetectAndSetLanguage(text: String) {
        val locale = if (HAN_REGEX.containsMatchIn(text)) {
            Locale.SIMPLIFIED_CHINESE
        } else {
            Locale.US
        }
        tts?.setLanguage(locale)
    }

    private fun buildSpeechParams(): android.os.Bundle {
        return android.os.Bundle().apply {
            putFloat(TextToSpeech.Engine.KEY_PARAM_VOLUME, speechVolume)
        }
    }

    private fun generateUtteranceId(): String = UUID.randomUUID().toString()

    private fun createProgressListener(): UtteranceProgressListener =
        object : UtteranceProgressListener() {

            override fun onStart(utteranceId: String?) {
                _isSpeaking.value = true
            }

            override fun onDone(utteranceId: String?) {
                pausedAtIndex++
                // Only mark as not speaking if nothing else is queued
                if (pausedAtIndex >= pendingTexts.size) {
                    _isSpeaking.value = false
                }
            }

            @Deprecated("Deprecated in API level 21")
            override fun onError(utteranceId: String?) {
                Log.e(TAG, "TTS error for utterance: $utteranceId")
                _isSpeaking.value = false
            }

            override fun onError(utteranceId: String?, errorCode: Int) {
                Log.e(TAG, "TTS error for utterance $utteranceId, code: $errorCode")
                _isSpeaking.value = false
            }
        }
}
