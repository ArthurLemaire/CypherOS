import Foundation

/// [T-correction-admission-multisignal] Decides whether one diffed edit span
/// (`from` → `to`, already jieba-widened to word boundaries by
/// `VoiceCorrectionDiff.tokenPairs`) is an ASR/IME-style mistake worth learning
/// into `confusion_dictionary`, or a plain content rewrite to discard.
///
/// Replaces the old single-axis rule (`phoneticSim ≥ 0.6 AND lengthRatio ≤ 2`),
/// which — because `PinyinNormalizer.normalize` passes Latin/digits through
/// literally — mis-scored the project's most common real edits (Chinese-English
/// mixing, acronym expansion, digit normalization) as rewrites and dropped them.
/// Analysis of 35 real correction_events: the old rule kept ~1 of the ~14 that
/// should have been collected. See CorrectionAdmissionTests.
///
/// Pure value logic — no DB, no provider, no actor — so it unit-tests standalone.
enum CorrectionAdmission {

    /// Tunables, grouped so they're easy to retune from the tests.
    enum Config {
        /// Phonetic-key Levenshtein similarity at/above which a span counts as a
        /// homophone/near-homophone (covers Chinese homophones AND literally
        /// similar Latin like cloud/claude). Kept at the historical 0.6 — the
        /// new acronym/digit signals cover the sub-0.6 cases (MediaS→Media
        /// Server etc.) without loosening this axis into false positives.
        static let phoneticSimilarity = 0.6
        /// A span may be short but still be a rewrite if it's a big fraction of
        /// the whole sentence. `editLocality` = changed-span chars / sentence
        /// chars; above this the edit is treated as a rewrite regardless of the
        /// other signals. Replaces lengthRatio as the primary "rewrite" guard.
        static let maxEditLocality = 0.6
        /// Acronym/subsequence relation requires the short side to be
        /// meaningfully shorter than the long side (else "abc"⊆"abcd" trivially
        /// matches near-equal strings and lets rewrites through).
        static let maxAcronymLengthFraction = 0.9
    }

    /// Why a span was admitted or rejected — surfaced in logs (privacy-safe: it
    /// names the SIGNAL, never the user's text) and asserted in tests.
    enum Verdict: Equatable {
        case homophone(sim: Double)   // phonetic near-match
        case acronym                  // one side is an ordered subsequence of the other
        case digitNorm                // Chinese-number ↔ arabic / alphanumeric term
        case rejectedReword(sim: Double)
        case rejectedReorder          // same characters, only order changed
        case rejectedTooGlobal(locality: Double)

        var isAdmitted: Bool {
            switch self {
            case .homophone, .acronym, .digitNorm: return true
            case .rejectedReword, .rejectedReorder, .rejectedTooGlobal: return false
            }
        }
        /// Privacy-safe reason tag for logs.
        var reason: String {
            switch self {
            case .homophone(let s): return "homophone(sim=\(String(format: "%.2f", s)))"
            case .acronym: return "acronym"
            case .digitNorm: return "digit_norm"
            case .rejectedReword(let s): return "reword(sim=\(String(format: "%.2f", s)))"
            case .rejectedReorder: return "reorder"
            case .rejectedTooGlobal(let l): return "too_global(loc=\(String(format: "%.2f", l)))"
            }
        }
    }

    /// Judge one span. `sentenceLength` is the character length of the sentence
    /// the span was diffed within — used for the locality guard. Pass the
    /// max of the before/after sentence lengths (the recorder has both).
    static func judge(from: String, to: String,
                      normalizer: any PhoneticNormalizer,
                      sentenceLength: Int) -> Verdict {
        let a = from.trimmingCharacters(in: .whitespacesAndNewlines)
        let b = to.trimmingCharacters(in: .whitespacesAndNewlines)

        // Locality first: a span that IS most of the sentence is a rewrite even
        // if it happens to look phonetically similar. Uses the larger side so a
        // long deletion still counts as a big edit.
        let spanLen = max(a.count, b.count)
        let locality = sentenceLength > 0 ? Double(spanLen) / Double(sentenceLength) : 1.0
        if locality > Config.maxEditLocality {
            return .rejectedTooGlobal(locality: locality)
        }

        // Pure reorder (same multiset of characters, different order) → the user
        // rearranged words, not fixed a mis-hear. Catch it before phonetics,
        // because reordered text often keeps a high phonetic similarity.
        if isPureReorder(a, b) {
            return .rejectedReorder
        }

        let keyA = normalizer.normalize(a)
        let keyB = normalizer.normalize(b)

        // Signal 1 — homophone / near-homophone (phonetic-key Levenshtein).
        let sim = PinyinNormalizer.similarity(keyA, keyB)
        if sim >= Config.phoneticSimilarity, !keyA.isEmpty {
            return .homophone(sim: sim)
        }

        // Signal 2 — digit / term normalization (十七→17, 二V三→v3, A P P→APP).
        if isDigitTermNormalization(a, b) {
            return .digitNorm
        }

        // Signal 3 — acronym ⇄ expansion (MediaS→Media Server, worker→work on,
        // 上帝→上). One phonetic key is an ordered subsequence of the other and
        // meaningfully shorter.
        if isAcronymRelated(keyA, keyB) {
            return .acronym
        }

        return .rejectedReword(sim: sim)
    }

    // MARK: - Signals

    /// True when the two strings are anagrams over their non-space characters —
    /// i.e. the same content reordered, not a substitution.
    static func isPureReorder(_ a: String, _ b: String) -> Bool {
        func bag(_ s: String) -> [Character: Int] {
            var m: [Character: Int] = [:]
            for c in s where !c.isWhitespace { m[c, default: 0] += 1 }
            return m
        }
        let ba = bag(a), bb = bag(b)
        // Require a real reorder: same non-empty multiset AND the ordered strings
        // actually differ (identical strings are handled elsewhere).
        guard !ba.isEmpty, ba == bb else { return false }
        return a != b
    }

    /// One side's phonetic key is an ordered subsequence of the other's and
    /// clearly shorter — an initialism / abbreviation of an expansion.
    static func isAcronymRelated(_ keyA: String, _ keyB: String) -> Bool {
        let (short, long) = keyA.count <= keyB.count ? (keyA, keyB) : (keyB, keyA)
        guard !short.isEmpty, short.count < long.count else { return false }
        guard Double(short.count) / Double(long.count) < Config.maxAcronymLengthFraction else { return false }
        // Ordered-subsequence test.
        var it = long.startIndex
        for ch in short {
            guard let f = long[it...].firstIndex(of: ch) else { return false }
            it = long.index(after: f)
        }
        return true
    }

    /// One side carries Chinese number words while the other carries Arabic
    /// digits — the user normalized spoken numbers ("十七"→"17", "二V三"→"v3"),
    /// which pinyin similarity scores as totally dissimilar. Also covers spaced
    /// alphanumeric terms ("G P L 二 V 三"→"GPLv3") via the digit presence.
    static func isDigitTermNormalization(_ a: String, _ b: String) -> Bool {
        let chineseNumerals = Set("零一二三四五六七八九十百千万两")
        func hasChineseNumeral(_ s: String) -> Bool { s.contains(where: chineseNumerals.contains) }
        func hasArabicDigit(_ s: String) -> Bool { s.contains(where: { $0.isNumber && $0.isASCII }) }
        // Direction-agnostic: spoken (Chinese numeral) on one side, digit on the other.
        let aCN = hasChineseNumeral(a), bCN = hasChineseNumeral(b)
        let aDigit = hasArabicDigit(a), bDigit = hasArabicDigit(b)
        return (aCN && bDigit && !bCN) || (bCN && aDigit && !aCN)
    }
}
