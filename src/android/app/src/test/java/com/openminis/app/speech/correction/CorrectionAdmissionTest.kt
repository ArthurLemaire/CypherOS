package com.openminis.app.speech.correction

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [T-android-correction-admission-multisignal] Locks the multi-signal admission
 * rule against the real correction_events that motivated the iOS redesign
 * (bf0234a7). Each case asserts whether the edit span should be COLLECTED (an
 * ASR/IME mistake worth learning) or REJECTED (a plain content rewrite), plus
 * targeted unit checks on each signal.
 *
 * The normalizer is injected: production PinyinNormalizer uses `android.icu`,
 * which is unavailable on the JVM. The fake maps the exact terms these cases
 * use to the same pinyin keys the real normalizer produces, and passes
 * Latin/digits through literally — which is what the real one does too, and is
 * precisely why the old single-axis rule mis-scored mixed-script edits.
 */
class CorrectionAdmissionTest {

    private val zh = object : PhoneticNormalizer {
        private val table = mapOf(
            "审推" to "shentui", "闪退" to "shantui",
            "绘画" to "huihua", "会话" to "huihua",
            "上帝" to "shangdi", "上" to "shang",
            "十七" to "shiqi",
            "二V三" to "erv san",
            "挂载" to "guazai", "规则" to "guize",
            "最后是" to "zuihoushi", "是最后" to "shizuihou",
            "英雄" to "yingxiong",
            "看看下一个英雄" to "kankanxiayigeyingxiong",
            "看看下一个Issue" to "kankanxiayigeissue",
        )
        override val locale: String = "zh"

        /**
         * Mirrors the real PinyinNormalizer's two observable behaviours:
         * Latin/digits pass through lowercased, and ALL whitespace is collapsed
         * (it joins ICU's per-syllable output, so "work on" keys as "workon" —
         * load-bearing, since that is what lifts worker→work on to sim 0.71).
         */
        override fun normalize(text: String): String =
            (table[text] ?: text.lowercase())
                .split(' ', '\t', '\n').filter { it.isNotEmpty() }.joinToString("")
    }

    /**
     * Default sentence length generously large so a bare span isn't rejected as
     * "too global" — in production a span is one word inside a full transcript,
     * so locality is small. Cases that exercise the locality guard pass an
     * explicit small [sentence].
     */
    private fun judge(from: String, to: String, sentence: Int? = null) =
        CorrectionAdmission.judge(
            from, to, zh,
            sentence ?: maxOf(from.length, to.length, 40),
        )

    // ── The four signal families (spans, as tokenPairs would emit them) ──

    @Test
    fun `chinese homophones are admitted`() {
        // The class the OLD rule already caught; must still pass.
        assertTrue(judge("审推", "闪退").isAdmitted)
        assertTrue(judge("绘画", "会话").isAdmitted)
        assertTrue(judge("LifeActivity", "LiveActivity").isAdmitted) // Latin near-form
    }

    @Test
    fun `chinese-english phonetic mixes are admitted`() {
        // Literally similar Latin — the phonetic axis catches these because
        // normalize passes Latin through.
        assertTrue(judge("cloud", "claude").isAdmitted)
        assertTrue(judge("worker", "work on").isAdmitted)
        assertTrue(judge("I worker", "I work on").isAdmitted)
    }

    @Test
    fun `acronym expansion is newly collected`() {
        // MediaS -> Media Server: the OLD rule dropped this (sim 0.55,
        // lengthRatio 2.0). New rule: acronym.
        assertEquals(CorrectionAdmission.Verdict.Acronym, judge("MediaS", "Media Server"))
        // 上帝 -> 上: dropping a syllable is an ordered-subsequence relation.
        assertTrue(judge("上帝", "上").isAdmitted)
    }

    @Test
    fun `digit normalization is newly collected`() {
        // OLD rule dropped both (sim ~0). New rule: digit-norm.
        assertEquals(CorrectionAdmission.Verdict.DigitNorm, judge("十七", "17"))
        assertEquals(CorrectionAdmission.Verdict.DigitNorm, judge("二V三", "v3"))
    }

    // ── Must stay REJECTED (no new false positives) ──

    @Test
    fun `semantic rewrites are rejected`() {
        assertFalse(judge("挂载", "规则").isAdmitted)       // phonetically far
        assertFalse(judge("secure", "SSH key").isAdmitted) // semantic
        // Cross-language semantic; the short sentence also makes it too-global.
        assertFalse(judge("英雄", "Issue", sentence = 6).isAdmitted)
    }

    @Test
    fun `a pure reorder is rejected`() {
        assertEquals(CorrectionAdmission.Verdict.RejectedReorder, judge("最后是", "是最后"))
    }

    @Test
    fun `an edit spanning most of a short sentence is rejected`() {
        // Not a homophone, not acronym/digit -> reword; and in a short sentence
        // the locality guard fires first.
        assertFalse(judge("看看下一个英雄", "看看下一个Issue", sentence = 8).isAdmitted)
    }

    @Test
    fun `locality alone flips the verdict on an identical span`() {
        // Same genuine-homophone span, different sentence sizes.
        assertTrue(judge("审推", "闪退", sentence = 20).isAdmitted) // 2/20 = 10%
        // The span IS the whole sentence (2/2 = 100%) -> too global, rejected,
        // even though it is phonetically a homophone.
        val v = judge("审推", "闪退", sentence = 2)
        assertTrue("expected RejectedTooGlobal, got ${v.reason}", v is CorrectionAdmission.Verdict.RejectedTooGlobal)
    }

    // ── Signal unit checks ──

    @Test
    fun `isPureReorder detects anagrams only`() {
        assertTrue(CorrectionAdmission.isPureReorder("最后是", "是最后"))
        assertTrue(CorrectionAdmission.isPureReorder("abc", "cba"))
        assertFalse(CorrectionAdmission.isPureReorder("审推", "闪退")) // different chars
        assertFalse(CorrectionAdmission.isPureReorder("abc", "abc")) // identical, not a reorder
    }

    @Test
    fun `isAcronymRelated requires an ordered, meaningfully shorter subsequence`() {
        assertTrue(CorrectionAdmission.isAcronymRelated("medias", "mediaserver"))
        assertTrue(CorrectionAdmission.isAcronymRelated("shang", "shangdi")) // 上 ⊂ 上帝
        assertFalse(CorrectionAdmission.isAcronymRelated("cat", "dog"))
        assertFalse(CorrectionAdmission.isAcronymRelated("abcd", "abce")) // same length
        assertFalse(CorrectionAdmission.isAcronymRelated("acb", "abcd"))  // not ORDERED (c before b)
        // Near-equal lengths must not qualify: 3/4 = 0.75 is under the 0.9 bar
        // so this DOES match; 9/10 = 0.9 is at the bar and must not.
        assertFalse(CorrectionAdmission.isAcronymRelated("abcdefghi", "abcdefghij"))
    }

    @Test
    fun `isDigitTermNormalization needs spoken-vs-digit on opposite sides`() {
        assertTrue(CorrectionAdmission.isDigitTermNormalization("十七", "17"))
        assertTrue(CorrectionAdmission.isDigitTermNormalization("二V三", "v3"))
        assertFalse(CorrectionAdmission.isDigitTermNormalization("挂载", "规则")) // no digits
        assertFalse(CorrectionAdmission.isDigitTermNormalization("17", "18"))    // both digits
    }

    // ── RTU→Retry stays deliberately UNCOLLECTED (per iOS design decision) ──

    @Test
    fun `RTU to Retry is deliberately not forced through`() {
        // sim 0.40, not an ordered subsequence, no digits. iOS chose NOT to
        // special-case it (risks false positives). Asserted so a future change
        // that tries to force it also revisits this decision.
        assertFalse(judge("RTU", "Retry").isAdmitted)
    }

    // ── Aggregate: the real-data matrix ──

    @Test
    fun `the real-data matrix collects ASR errors and rejects rewrites`() {
        val shouldCollect = listOf(
            "审推" to "闪退", "绘画" to "会话", "LifeActivity" to "LiveActivity",
            "cloud" to "claude", "worker" to "work on", "I worker" to "I work on",
            "MediaS" to "Media Server", "十七" to "17", "二V三" to "v3",
        )
        val shouldReject = listOf(
            "挂载" to "规则", "secure" to "SSH key", "最后是" to "是最后",
        )
        for ((a, b) in shouldCollect) {
            val v = judge(a, b, sentence = 40)
            assertTrue("expected COLLECT for $a->$b, got ${v.reason}", v.isAdmitted)
        }
        for ((a, b) in shouldReject) {
            val v = judge(a, b, sentence = 40)
            assertFalse("expected REJECT for $a->$b, got ${v.reason}", v.isAdmitted)
        }
    }

    // ── The regression this redesign exists to fix ──

    @Test
    fun `the old single-axis rule would have dropped these, the new one keeps them`() {
        // Reproduce the OLD rule and show it fails exactly where the new one
        // succeeds — this is the whole point of the change, so lock it in.
        fun oldRuleAdmits(from: String, to: String): Boolean {
            val sim = PinyinNormalizer.similarity(zh.normalize(from), zh.normalize(to))
            val lengthRatio = maxOf(from.length, to.length).toDouble() /
                maxOf(1, minOf(from.length, to.length)).toDouble()
            return sim >= 0.6 && lengthRatio <= 2.0
        }
        val recovered = listOf("MediaS" to "Media Server", "十七" to "17", "二V三" to "v3")
        for ((a, b) in recovered) {
            assertFalse("old rule should have DROPPED $a->$b", oldRuleAdmits(a, b))
            assertTrue("new rule must COLLECT $a->$b", judge(a, b, sentence = 40).isAdmitted)
        }
    }
}
