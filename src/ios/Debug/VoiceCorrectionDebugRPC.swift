#if DEBUG
import Foundation

/// `debug.voiceCorrection.*` JSON-RPC methods (design §10).
///
/// The whole file is `#if DEBUG`, matching every other debug-server handler — so these
/// methods simply do not exist in Release, which is what the task's constraint #4 asks
/// for (the debug server is already a DEBUG-only subsystem; no extra gating needed).
///
/// Two hard rules from design §10.3, enforced here:
///   • `dryRunCorrection` / `runCorrection` MUST NOT write capture data. Debugging must
///     never feed synthetic text back in as if it were real user behavior — that would
///     poison the very dictionary we're trying to evaluate.
///   • Destructive methods (`clearTable`, `injectConfusionRecord`) are flagged as such
///     in their registry descriptions so they can't be invoked casually.
@MainActor
enum VoiceCorrectionDebugRPC {

    /// Local required-param helper. `DebugRPCProviderChat` has an identical one but it's
    /// `private` to that file; duplicating three lines here is cheaper (and less
    /// intrusive) than widening another file's access level.
    private static func require<T>(_ value: T?, _ name: String) throws -> T {
        guard let v = value else { throw DebugRPCErr(-32602, "Missing required param: \(name)") }
        return v
    }

    // MARK: (a) Data viewing

    static func confusionList(params: [String: Any]) async throws -> [String: Any] {
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "voice-correction.db unavailable") }
        let orderBy = (params["orderBy"] as? String) ?? "confidence"
        let limit = (params["limit"] as? Int) ?? 50
        let locale = params["locale"] as? String
        let rows = await db.allConfusion(orderBy: orderBy, locale: locale, limit: limit)
        return [
            "count": rows.count,
            "rows": rows.map(confusionDict),
        ]
    }

    static func vocabularyList(params: [String: Any]) async throws -> [String: Any] {
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "voice-correction.db unavailable") }
        let orderBy = (params["orderBy"] as? String) ?? "frequency"
        let limit = (params["limit"] as? Int) ?? 50
        let rows = await db.allVocabulary(orderBy: orderBy, limit: limit)
        return [
            "count": rows.count,
            "rows": rows.map(vocabDict),
        ]
    }

    /// Cross-table history for one term, plus the phonetic key it hashes to — the fastest
    /// way to answer "why didn't this get corrected?" (design §10.2a).
    static func lookup(params: [String: Any]) async throws -> [String: Any] {
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "voice-correction.db unavailable") }
        let term = try require(params["term"] as? String, "term")
        let locale = (params["locale"] as? String) ?? "zh"
        let key = PhoneticNormalizerRegistry.normalizer(for: locale)?.normalize(term) ?? ""
        let confusion = await db.lookupConfusion(phoneticKeys: [key], locale: locale, minConfidence: 0, limit: 50)
        let vocab = await db.lookupVocabulary(phoneticKeys: [key], locale: locale, limit: 50)
        return [
            "term": term,
            "phoneticKey": key,
            "confusionMatches": confusion.map(confusionDict),
            "vocabularyMatches": vocab.map(vocabDict),
        ]
    }

    /// DB overview: row counts, schema version, file path/size. Doubles as the §11.5
    /// compatibility-matrix probe (user_version + the columns actually present).
    static func stats(params: [String: Any]) async throws -> [String: Any] {
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "voice-correction.db unavailable") }
        let path = await db.dbPath()
        let size = (try? FileManager.default.attributesOfItem(atPath: path)[.size] as? Int) ?? nil
        return [
            "dbPath": path,
            "dbSizeBytes": size ?? 0,
            "userVersion": await db.userVersion(),
            "schemaVersion": VoiceCorrectionDB.schemaVersion,
            "confusionRows": await db.rowCount(table: "confusion_dictionary"),
            "vocabularyRows": await db.rowCount(table: "typed_vocabulary"),
            "correctionEvents": await db.rowCount(table: "correction_events"),
        ]
    }

    // MARK: (b) Replay / tuning — the highest-value pair (design §10.2b)

    /// Retrieval + fusion + prompt assembly, WITHOUT calling the model. Answers "did the
    /// lookup even find anything?" in one shot, instead of the speak→edit→accumulate
    /// loop. Writes nothing (design §10.3).
    static func dryRunCorrection(params: [String: Any]) async throws -> [String: Any] {
        let transcript = try require(params["transcript"] as? String, "transcript")
        let locale = (params["locale"] as? String) ?? "zh"
        let context = contextFromParams(params)

        let started = Date()
        let result = await VoiceCorrectionEngine.shared.dryRun(transcript: transcript,
                                                               locale: locale, context: context)
        let ms = Int(Date().timeIntervalSince(started) * 1000)

        // Group candidates under the token that produced their phonetic key, which is how
        // you actually read this output ("did 张山 find anything?").
        let normalizer = PhoneticNormalizerRegistry.normalizer(for: locale)
        var byToken: [[String: Any]] = []
        for token in result.tokens where token.count >= 2 {
            let key = normalizer?.normalize(token) ?? ""
            let matches = result.candidates.filter { $0.phoneticKey == key }
            guard !matches.isEmpty else { continue }
            byToken.append([
                "token": token,
                "phoneticKey": key,
                "matches": matches.map {
                    ["term": $0.term, "source": $0.sourceIdentifier,
                     "confidence": $0.confidence, "evidence": $0.evidence]
                },
            ])
        }

        return [
            "segmentedTokens": result.tokens,
            "candidateCount": result.candidates.count,
            "candidates": byToken,
            "assembledPrompt": result.prompt,
            "retrievalMs": ms,
            "retrievalBudgetMs": VoiceCorrectionConfig.retrievalBudgetMs,
        ]
    }

    /// Full correction INCLUDING the model call. `persistEvent: false` — a debug run must
    /// never write capture data, or we'd be training the system on our own test strings
    /// (design §10.3).
    static func runCorrection(params: [String: Any]) async throws -> [String: Any] {
        let transcript = try require(params["transcript"] as? String, "transcript")
        let locale = (params["locale"] as? String) ?? "zh"
        let context = contextFromParams(params)

        let s = await VoiceCorrectionEngine.shared.correct(transcript: transcript,
                                                           locale: locale,
                                                           context: context,
                                                           persistEvent: false)
        return [
            "original": s.original,
            "corrected": s.corrected,
            "diffApplied": s.hasChange,
            "diffSummary": s.diffSummary,
            "modelGroupUsed": s.modelGroupUsed,
            "durationMs": s.durationMs,
            "rejectedReason": s.rejectedReason ?? NSNull(),
        ]
    }

    private static func contextFromParams(_ params: [String: Any]) -> ConversationContext {
        ConversationContext(
            lastUserMessage: (params["lastUserMessage"] as? String).map {
                ConversationContextTruncator.truncate($0).text
            },
            lastAgentReply: (params["lastAgentReply"] as? String).map {
                ConversationContextTruncator.truncate($0).text
            })
    }

    /// Run the typed_vocabulary intake rules over arbitrary text and show, per candidate,
    /// exactly why it was kept or dropped — WITHOUT writing anything. This replaces the
    /// "send 20 messages and see what sticks" loop when tuning the stopword list or the
    /// score threshold (design §10.2b).
    static func simulateVocabularyFilter(params: [String: Any]) async throws -> [String: Any] {
        let text = try require(params["text"] as? String, "text")
        var rows: [[String: Any]] = []
        for (term, occurrences, posTag) in VocabularyFilter.candidates(in: text) {
            let rank = BackgroundWordFrequency.shared.rank(of: term)
            switch VocabularyFilter.evaluate(term: term, posTag: posTag) {
            case .rejected(let reason):
                rows.append(["term": term, "rejected": true, "reason": reason,
                             "posTag": posTag ?? NSNull(), "occurrences": occurrences])
            case .accepted(let score, let b):
                rows.append([
                    "term": term, "rejected": false, "score": score,
                    "posTag": posTag ?? NSNull(), "occurrences": occurrences,
                    "backgroundRank": rank ?? NSNull(),
                    // Straight from evaluate() — never recomputed here, or the two copies drift.
                    "breakdown": ["backgroundRank": b.backgroundRank, "posTag": b.posTag,
                                  "hasLatinOrDigit": b.hasLatinOrDigit, "lengthOk": b.lengthOk],
                ])
            }
        }
        return ["count": rows.count, "candidates": rows,
                "backgroundListVersion": BackgroundWordFrequency.shared.version]
    }

    /// Force a full typed_vocabulary rebuild now (normally throttled + incremental).
    static func rebuildVocabulary(params: [String: Any]) async throws -> [String: Any] {
        let force = (params["force"] as? Bool) ?? true
        let started = Date()
        await TypedVocabularyBuilder.shared.build(force: force)
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "db unavailable") }
        return [
            "ok": true,
            "durationMs": Int(Date().timeIntervalSince(started) * 1000),
            "vocabularyRows": await db.rowCount(table: "typed_vocabulary"),
        ]
    }

    // MARK: (d) Effect metrics (design §10.2d)

    /// Acceptance rate over the window. This is the number that answers the product
    /// question the whole feature rests on — "is it actually getting better with use?".
    static func metrics(params: [String: Any]) async throws -> [String: Any] {
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "db unavailable") }
        let sinceDays = (params["sinceDays"] as? Int) ?? 30
        let counts = await db.correctionEventCounts(sinceDays: sinceDays)
        let accepted = counts["accepted"] ?? 0
        let reverted = counts["reverted"] ?? 0
        let suggested = counts["suggested"] ?? 0
        let decided = accepted + reverted
        return [
            "sinceDays": sinceDays,
            "suggestedCount": suggested,
            "acceptedCount": accepted,
            "revertedCount": reverted,
            // Undecided suggestions (user just sent without touching them) are excluded
            // from the denominator: "ignored" is not the same as "rejected".
            "acceptanceRate": decided > 0 ? Double(accepted) / Double(decided) : 0,
            "topConfusionPairs": (await db.allConfusion(orderBy: "confidence", locale: nil, limit: 10))
                .map { ["original": $0.variants.first ?? $0.phoneticKey, "corrected": $0.correctedTerm,
                        "frequency": $0.frequency, "confidence": $0.confidence] },
        ]
    }

    // MARK: (c) Admin / test-scaffolding (DESTRUCTIVE — see registry descriptions)

    /// Insert a confusion row without going through a real speak→edit cycle, so a
    /// correction scenario can be staged in one call (design §10.2c).
    static func injectConfusionRecord(params: [String: Any]) async throws -> [String: Any] {
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "voice-correction.db unavailable") }
        let original = try require(params["original"] as? String, "original")
        let corrected = try require(params["corrected"] as? String, "corrected")
        let locale = (params["locale"] as? String) ?? "zh"
        guard let normalizer = PhoneticNormalizerRegistry.normalizer(for: locale) else {
            throw DebugRPCErr(-32602, "no phonetic normalizer for locale \(locale)")
        }
        let key = normalizer.normalize(original)
        await db.upsertConfusion(phoneticKey: key,
                                 originalVariant: original,
                                 correctedTerm: corrected,
                                 locale: locale,
                                 contextSample: "(debug-injected)",
                                 asrProvider: "debug")
        return ["ok": true, "phoneticKey": key, "original": original, "corrected": corrected]
    }

    /// [T-text-input-correction-source] Drive the FULL recordEdit pipeline
    /// (diff → phonetic admission → consent gate → upsert with source tag) so
    /// the text-input capture path can be verified end-to-end on device —
    /// synthetic taps can't perform a real select-and-replace in the composer.
    static func recordManualEdit(params: [String: Any]) async throws -> [String: Any] {
        let before = try require(params["before"] as? String, "before")
        let after = try require(params["after"] as? String, "after")
        let locale = (params["locale"] as? String) ?? "zh"
        let source = (params["source"] as? String) ?? "text_input"
        await VoiceCorrectionRecorder.shared.recordEdit(before: before, after: after,
                                                        locale: locale, source: source)
        return ["ok": true, "before": before, "after": after, "source": source,
                "consentEnabled": VoiceCorrectionCollectionConsent.collectionEnabled]
    }

    static func clearTable(params: [String: Any]) async throws -> [String: Any] {
        guard let db = VoiceCorrectionDB.shared else { throw DebugRPCErr(-32603, "voice-correction.db unavailable") }
        let table = try require(params["table"] as? String, "table")
        guard (params["confirm"] as? Bool) == true else {
            throw DebugRPCErr(-32602, "refusing to clear \(table) without confirm:true")
        }
        let ok = await db.clearTable(table)
        return ["ok": ok, "table": table]
    }

    // MARK: - Encoding

    private static func confusionDict(_ r: ConfusionRow) -> [String: Any] {
        [
            "id": r.id,
            "originalPhoneticKey": r.phoneticKey,
            "originalVariants": r.variants,
            "correctedTerm": r.correctedTerm,
            "locale": r.locale,
            "frequency": r.frequency,
            "negativeFeedbackCount": r.negativeFeedbackCount,
            "confidence": r.confidence,
            "lastSeen": r.lastSeen,
            "source": r.source,
        ]
    }

    private static func vocabDict(_ r: VocabularyRow) -> [String: Any] {
        [
            "id": r.id,
            "term": r.term,
            "phoneticKey": r.phoneticKey,
            "locale": r.locale,
            "posTag": r.posTag ?? NSNull(),
            "frequency": r.frequency,
            "distinctDays": r.distinctDays,
            "backgroundRank": r.backgroundRank ?? NSNull(),
            "lastSeen": r.lastSeen,
            "source": r.source,
        ]
    }
}
#endif
