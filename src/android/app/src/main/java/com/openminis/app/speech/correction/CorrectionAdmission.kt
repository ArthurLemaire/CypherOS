package com.openminis.app.speech.correction

/**
 * [T-android-correction-admission-multisignal] Decides whether one diffed edit
 * span (`from` → `to`, already jieba-widened to word boundaries by
 * [VoiceCorrectionDiff.tokenPairs]) is an ASR/IME-style mistake worth learning
 * into `confusion_dictionary`, or a plain content rewrite to discard.
 *
 * Port of iOS `Agent/Speech/CorrectionAdmission.swift` (bf0234a7).
 *
 * Replaces the old single-axis rule (`phoneticSim >= 0.6 AND lengthRatio <= 2`),
 * which — because [PinyinNormalizer.normalize] passes Latin/digits through
 * literally — mis-scored the most common real edits (Chinese-English mixing,
 * acronym expansion, digit normalization) as rewrites and dropped them. Analysis
 * of 35 real correction_events on iOS: the old rule kept ~1 of the ~14 that
 * should have been collected.
 *
 * Pure value logic — no DB, no provider, no Android framework — so it unit-tests
 * standalone (the normalizer is injected, since the production one needs
 * `android.icu`, which is unavailable on the JVM).
 */
object CorrectionAdmission {

    /** Tunables, grouped so they're easy to retune from the tests. */
    object Config {
        /**
         * Phonetic-key Levenshtein similarity at/above which a span counts as a
         * homophone/near-homophone (covers Chinese homophones AND literally
         * similar Latin like cloud/claude). Kept at the historical 0.6 — the new
         * acronym/digit signals cover the sub-0.6 cases (MediaS→Media Server
         * etc.) without loosening this axis into false positives.
         */
        const val PHONETIC_SIMILARITY = 0.6

        /**
         * A span may be short but still be a rewrite if it's a big fraction of
         * the whole sentence. `editLocality` = changed-span chars / sentence
         * chars; above this the edit is treated as a rewrite regardless of the
         * other signals. Replaces lengthRatio as the primary "rewrite" guard.
         */
        const val MAX_EDIT_LOCALITY = 0.6

        /**
         * Acronym/subsequence relation requires the short side to be
         * meaningfully shorter than the long side (else "abc" ⊆ "abcd"
         * trivially matches near-equal strings and lets rewrites through).
         */
        const val MAX_ACRONYM_LENGTH_FRACTION = 0.9
    }

    /**
     * Why a span was admitted or rejected — surfaced in logs (privacy-safe: it
     * names the SIGNAL, never the user's text) and asserted in tests.
     */
    sealed class Verdict {
        /** Phonetic near-match. */
        data class Homophone(val sim: Double) : Verdict()

        /** One side is an ordered subsequence of the other. */
        object Acronym : Verdict()

        /** Chinese-number ↔ arabic / alphanumeric term. */
        object DigitNorm : Verdict()

        data class RejectedReword(val sim: Double) : Verdict()

        /** Same characters, only order changed. */
        object RejectedReorder : Verdict()

        data class RejectedTooGlobal(val locality: Double) : Verdict()

        val isAdmitted: Boolean
            get() = when (this) {
                is Homophone, is Acronym, is DigitNorm -> true
                is RejectedReword, is RejectedReorder, is RejectedTooGlobal -> false
            }

        /** Privacy-safe reason tag for logs — never contains user text. */
        val reason: String
            get() = when (this) {
                is Homophone -> "homophone(sim=%.2f)".format(sim)
                is Acronym -> "acronym"
                is DigitNorm -> "digit_norm"
                is RejectedReword -> "reword(sim=%.2f)".format(sim)
                is RejectedReorder -> "reorder"
                is RejectedTooGlobal -> "too_global(loc=%.2f)".format(locality)
            }
    }

    /**
     * Judge one span. [sentenceLength] is the character length of the sentence
     * the span was diffed within — used for the locality guard. Pass the max of
     * the before/after sentence lengths (the recorder has both).
     *
     * Signal order is load-bearing and mirrors iOS: locality → reorder →
     * homophone → digitNorm → acronym.
     */
    fun judge(
        from: String,
        to: String,
        normalizer: PhoneticNormalizer,
        sentenceLength: Int,
    ): Verdict {
        val a = from.trim()
        val b = to.trim()

        // Locality first: a span that IS most of the sentence is a rewrite even
        // if it happens to look phonetically similar. Uses the larger side so a
        // long deletion still counts as a big edit.
        val spanLen = maxOf(a.length, b.length)
        val locality = if (sentenceLength > 0) spanLen.toDouble() / sentenceLength.toDouble() else 1.0
        if (locality > Config.MAX_EDIT_LOCALITY) {
            return Verdict.RejectedTooGlobal(locality)
        }

        // Pure reorder (same multiset of characters, different order) → the user
        // rearranged words, not fixed a mis-hear. Caught BEFORE phonetics,
        // because reordered text often keeps a high phonetic similarity.
        if (isPureReorder(a, b)) return Verdict.RejectedReorder

        val keyA = normalizer.normalize(a)
        val keyB = normalizer.normalize(b)

        // Signal 1 — homophone / near-homophone (phonetic-key Levenshtein).
        val sim = PinyinNormalizer.similarity(keyA, keyB)
        if (sim >= Config.PHONETIC_SIMILARITY && keyA.isNotEmpty()) {
            return Verdict.Homophone(sim)
        }

        // Signal 2 — digit / term normalization (十七→17, 二V三→v3, A P P→APP).
        if (isDigitTermNormalization(a, b)) return Verdict.DigitNorm

        // Signal 3 — acronym ⇄ expansion (MediaS→Media Server, worker→work on,
        // 上帝→上). One phonetic key is an ordered subsequence of the other and
        // meaningfully shorter.
        if (isAcronymRelated(keyA, keyB)) return Verdict.Acronym

        return Verdict.RejectedReword(sim)
    }

    // -- Signals --

    /**
     * True when the two strings are anagrams over their non-space characters —
     * i.e. the same content reordered, not a substitution.
     */
    fun isPureReorder(a: String, b: String): Boolean {
        fun bag(s: String): Map<Char, Int> {
            val m = HashMap<Char, Int>()
            for (c in s) if (!c.isWhitespace()) m[c] = (m[c] ?: 0) + 1
            return m
        }
        val ba = bag(a)
        val bb = bag(b)
        // Require a real reorder: same non-empty multiset AND the ordered
        // strings actually differ (identical strings are handled elsewhere).
        if (ba.isEmpty() || ba != bb) return false
        return a != b
    }

    /**
     * One side's phonetic key is an ordered subsequence of the other's and
     * clearly shorter — an initialism / abbreviation of an expansion.
     */
    fun isAcronymRelated(keyA: String, keyB: String): Boolean {
        val short = if (keyA.length <= keyB.length) keyA else keyB
        val long = if (keyA.length <= keyB.length) keyB else keyA
        if (short.isEmpty() || short.length >= long.length) return false
        if (short.length.toDouble() / long.length.toDouble() >= Config.MAX_ACRONYM_LENGTH_FRACTION) {
            return false
        }
        // Ordered-subsequence test.
        var idx = 0
        for (ch in short) {
            val found = long.indexOf(ch, idx)
            if (found < 0) return false
            idx = found + 1
        }
        return true
    }

    /**
     * One side carries Chinese number words while the other carries Arabic
     * digits — the user normalized spoken numbers ("十七"→"17", "二V三"→"v3"),
     * which pinyin similarity scores as totally dissimilar. Also covers spaced
     * alphanumeric terms ("G P L 二 V 三"→"GPLv3") via the digit presence.
     */
    fun isDigitTermNormalization(a: String, b: String): Boolean {
        val chineseNumerals = "零一二三四五六七八九十百千万两".toSet()
        fun hasChineseNumeral(s: String) = s.any { it in chineseNumerals }
        fun hasArabicDigit(s: String) = s.any { it in '0'..'9' }
        // Direction-agnostic: spoken (Chinese numeral) on one side, digit on the other.
        val aCn = hasChineseNumeral(a)
        val bCn = hasChineseNumeral(b)
        val aDigit = hasArabicDigit(a)
        val bDigit = hasArabicDigit(b)
        return (aCn && bDigit && !bCn) || (bCn && aDigit && !aCn)
    }
}
