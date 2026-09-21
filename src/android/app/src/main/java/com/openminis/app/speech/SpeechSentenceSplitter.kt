package com.openminis.app.speech

/**
 * [T-android-tts-intranumber-guard] Streaming sentence extraction for the TTS
 * paths. Shared by [ReadAloudPlayer] and [TextToSpeechManager] so the two can
 * never drift — they previously carried byte-identical copies of this loop and
 * a fix to one would have silently missed the other.
 *
 * Port of the guards in iOS `AIChatViewModel+SSEStream.extractSentencesStatic`
 * (T-tts-decimal-split).
 */
object SpeechSentenceSplitter {

    /** Terminator set — the exact one iOS uses in `extractNewSentences`. */
    val SENTENCE_ENDERS: Set<Char> =
        charArrayOf('。', '！', '？', '.', '!', '?', '\n').toSet()

    /**
     * A `.` or `,` flanked by digits on BOTH sides is an intra-number separator
     * (decimal point "3.14" / "$1.5", European decimal comma "€28,98", or
     * thousands grouping "1,000,000"), NOT a sentence boundary. Splitting there
     * mangles the number into "3." + "14" and the TTS reads it wrong.
     *
     * BOTH neighbours must be digits, so a real sentence end after a number
     * ("He scored 5. Then…") still cuts. Uses [Char.isDigit] so ASCII and
     * full-width digits both count.
     */
    fun isIntraNumberSeparator(text: CharSequence, idx: Int): Boolean {
        val ch = text[idx]
        if (ch != '.' && ch != ',') return false
        if (idx <= 0 || idx + 1 >= text.length) return false
        return text[idx - 1].isDigit() && text[idx + 1].isDigit()
    }

    /**
     * Scan [buffer] for sentence terminators, returning each trimmed sentence
     * and removing the consumed prefix.
     *
     * Two number-aware guards, both from iOS:
     *  1. [isIntraNumberSeparator] positions are skipped outright.
     *  2. Streaming look-ahead — a `.`/`,` that trails a digit at the CURRENT
     *     END of the buffer might be a decimal point whose fractional part
     *     hasn't streamed yet ("price 28." with "98" still in flight).
     *     Committing it now would speak "28." early and split the number, so we
     *     stop scanning WITHOUT consuming it; the next delta reveals whether a
     *     digit (→ intra-number, skip) or a non-digit (→ real boundary) follows.
     *     Only applies at the very last char, so fully-arrived text is never
     *     delayed. Set [streaming] = false to disable this (e.g. a final flush,
     *     where no more text is coming and "28." IS the end).
     */
    fun extractCompleteSentences(
        buffer: StringBuilder,
        streaming: Boolean = true,
    ): List<String> {
        val sentences = mutableListOf<String>()
        var lastBoundary = 0
        var i = 0
        while (i < buffer.length) {
            val ch = buffer[i]
            if (isIntraNumberSeparator(buffer, i)) {
                i++
                continue
            }
            if (streaming &&
                i == buffer.length - 1 &&
                (ch == '.' || ch == ',') &&
                i > 0 && buffer[i - 1].isDigit()
            ) {
                // Might be a decimal point mid-stream — wait for the next delta.
                break
            }
            if (ch in SENTENCE_ENDERS) {
                val s = buffer.substring(lastBoundary, i + 1).trim()
                if (s.isNotEmpty()) sentences.add(s)
                lastBoundary = i + 1
            }
            i++
        }
        if (lastBoundary > 0) buffer.delete(0, lastBoundary)
        return sentences
    }
}
