import Foundation

private let logger = AppLogger(category: "VoiceCorrection")

/// How a transcript actually gets corrected, given the retrieved candidates (design §4.3).
///
/// v1 ships only `LLMCorrectionStrategy`. The protocol exists now so that a
/// `RuleBasedCorrectionStrategy` (skip the LLM entirely when confidence is overwhelming —
/// saves tokens and ~600ms) or an on-device model strategy can be swapped in later
/// without touching the engine (design §8).
protocol CorrectionStrategy: Sendable {
    var strategyIdentifier: String { get }
    func correct(transcript: String,
                 candidates: [CorrectionCandidate],
                 context: ConversationContext,
                 locale: String) async throws -> CorrectionOutcome
}

// ConversationContext moved to CorrectionContextBuilder.swift (2026-07-16): the
// budgeted context builder both produces it and is unit-tested, and the test
// target compiles files individually — keeping the type next to its producer
// lets the tests build without dragging this file's provider-stack imports in.

struct CorrectionOutcome: Sendable {
    let correctedText: String
    /// The model group we actually reached ("sub" / "primary") — surfaced by
    /// `debug.voiceCorrection.runCorrection` so a bad correction can be traced to a model.
    let modelGroupUsed: String
    let durationMs: Int
}

enum CorrectionError: Error {
    case noModelAvailable
    case emptyResponse
    case timedOut
}

// MARK: - LLM strategy

struct LLMCorrectionStrategy: CorrectionStrategy {
    let strategyIdentifier = "llm"

    func correct(transcript: String,
                 candidates: [CorrectionCandidate],
                 context: ConversationContext,
                 locale: String) async throws -> CorrectionOutcome {
        let started = Date()

        guard let resolved = await CorrectionModelResolver.resolve() else {
            throw CorrectionError.noModelAvailable
        }

        let prompt = Self.buildPrompt(transcript: transcript, candidates: candidates, context: context)
        let provider = await AIChatViewModel.makeAgentProvider(for: resolved.entry)

        // thinkingLevel: .off, exactly like title generation — this is a mechanical
        // rewrite, reasoning traces would only add latency (and on some providers cause
        // an empty text body with finish_reason=tool_calls; see the TitleGen comment).
        let messages = [AgentMessage(role: .user, parts: [.text(prompt)])]
        let stream = try await provider.streamAgentMessage(
            messages: messages,
            systemPrompt: Self.systemPrompt,
            tools: [],
            // Output is at most the transcript re-emitted, so budget off its
            // length: floor 512 (a 256 floor once got fully eaten by adaptive
            // thinking_tokens before the explicit-disable fix landed — keep
            // headroom), target 1.2× the input chars, ceiling = the model
            // entry's own max-output limit (group override included).
            maxTokens: Self.correctionMaxTokens(transcriptChars: transcript.count,
                                                modelCap: resolved.entry.model.maxOutputTokens),
            thinkingLevel: .off
        )

        var responseText = ""
        for try await event in stream {
            switch event {
            case .textDelta(let delta): responseText += delta
            default: break
            }
        }

        let cleaned = Self.cleanResponse(responseText)
        guard !cleaned.isEmpty else { throw CorrectionError.emptyResponse }

        let ms = Int(Date().timeIntervalSince(started) * 1000)
        return CorrectionOutcome(correctedText: cleaned,
                                 modelGroupUsed: resolved.groupKind,
                                 durationMs: ms)
    }

    /// Output-token budget for one correction call (user decision 2026-07-17):
    /// max(512, ceil(1.2 × transcript chars)), clamped to the resolved model
    /// entry's maxOutputTokens (which already reflects any Model Group
    /// per-entry override) when one is declared.
    static func correctionMaxTokens(transcriptChars: Int, modelCap: Int?) -> Int {
        let target = max(512, Int((Double(transcriptChars) * 1.2).rounded(.up)))
        guard let cap = modelCap, cap > 0 else { return target }
        return min(target, cap)
    }

    static let systemPrompt = """
    You fix speech-recognition errors in transcribed text. Output ONLY the corrected text, \
    with no explanation, no quotes, and no preamble. If the text needs no correction, output it unchanged.
    """

    /// Design §6 prompt, assembled under the per-block budgets of
    /// `CorrectionContextBudget` (decided BEFORE assembly; every block's spend is
    /// logged under `[CorrectionPrompt]` so prompt composition is auditable).
    /// The evidence blocks are peers — none is presented as outranking the others;
    /// the model weighs them against the sentence. The context block is explicitly
    /// labeled "not the text to process", because otherwise models happily
    /// "correct" the quoted previous turn instead of the transcript.
    static func buildPrompt(transcript: String,
                            candidates: [CorrectionCandidate],
                            context: ConversationContext) -> String {
        var blocks: [String] = []
        var vocabChars = 0, confusionChars = 0, digestChars = 0, contextChars = 0

        // Typed vocabulary — clamped to its char budget, not just a term count.
        let vocab = candidates.filter { $0.sourceIdentifier == "typed_vocabulary" }
        if !vocab.isEmpty {
            var kept: [String] = []
            var used = 0
            for term in vocab.map(\.term).uniqued() {
                let cost = term.count + (kept.isEmpty ? 0 : 1)
                guard used + cost <= CorrectionContextBudget.vocabBlock else { break }
                kept.append(term); used += cost
            }
            if !kept.isEmpty {
                vocabChars = used
                blocks.append("以下是该用户的常用词汇（来自历史文字输入，仅供参考）：\n\(kept.joined(separator: "、"))")
            }
        }

        // Confusion history — line-clamped to its char budget.
        let confusion = candidates.filter { $0.sourceIdentifier == "confusion_dictionary" }
        if !confusion.isEmpty {
            var kept: [String] = []
            var used = 0
            for c in confusion {
                let line = c.evidence
                let cost = line.count + (kept.isEmpty ? 0 : 1)
                guard used + cost <= CorrectionContextBudget.confusionBlock else { break }
                kept.append(line); used += cost
            }
            if !kept.isEmpty {
                confusionChars = used
                blocks.append("以下是该用户过去的语音识别纠错记录（原文→修正，按可信度排序）：\n\(kept.joined(separator: "\n"))")
            }
        }

        // Rare-content digest (builder-capped at 200 chars; defensive re-clamp).
        if let digest = context.rareTermsDigest, !digest.isEmpty {
            let clamped = String(digest.prefix(CorrectionContextBudget.rareDigest))
            digestChars = clamped.count
            blocks.append("以下是近期对话中出现的少见词/专有名词（语音识别容易听错，供参考）：\n\(clamped)")
        }

        // Conversation context: budgeted excerpts preferred, legacy two-field fallback.
        if !context.recentExcerpts.isEmpty {
            let body = context.recentExcerpts.joined(separator: "\n")
            contextChars = body.count
            blocks.append("以下是当前对话的最近上下文（供理解语境使用，不是需要处理的内容）：\n\(body)")
        } else if !(context.lastUserMessage?.isEmpty ?? true) || !(context.lastAgentReply?.isEmpty ?? true) {
            var ctx = "以下是当前对话的最近上下文（供理解语境使用，不是需要处理的内容）："
            if let u = context.lastUserMessage, !u.isEmpty { ctx += "\n【用户上一条消息】：\(u)" }
            if let a = context.lastAgentReply, !a.isEmpty { ctx += "\n【AI上一条回复】：\(a)" }
            contextChars = ctx.count
            blocks.append(ctx)
        }

        let evidence = blocks.isEmpty ? "" : blocks.joined(separator: "\n\n") + "\n\n"
        let prompt = """
        \(evidence)请结合以上参考信息和对话上下文，判断并修正下面这段语音转录文本中可能的同音字/识别错误。\
        如果转录内容本身已经正确、或者是无法用参考信息判断的正常表达，请不要修改。只输出修正后的文本，不要输出任何解释。

        原文：\(transcript)
        """
        logger.info("[CorrectionPrompt] blocks vocab=\(vocabChars)/\(CorrectionContextBudget.vocabBlock) confusion=\(confusionChars)/\(CorrectionContextBudget.confusionBlock) digest=\(digestChars)/\(CorrectionContextBudget.rareDigest) context=\(contextChars) msg_ctx=\(digestChars + contextChars)/\(CorrectionContextBudget.messageContextTotal) transcript=\(transcript.count) prompt_total=\(prompt.count)")
        return prompt
    }

    /// Models like to wrap output in quotes, code fences, or an obliging "修正后：" prefix.
    /// Strip that before the diff check, or a perfectly good correction gets rejected as
    /// "too different" purely because of decoration.
    static func cleanResponse(_ raw: String) -> String {
        var t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.hasPrefix("```") {
            let lines = t.split(separator: "\n", omittingEmptySubsequences: false)
                .drop(while: { $0.hasPrefix("```") })
                .prefix(while: { !$0.hasPrefix("```") })
            t = lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        }
        for prefix in ["修正后的文本：", "修正后：", "修正：", "Corrected:", "Output:"] {
            if t.hasPrefix(prefix) { t = String(t.dropFirst(prefix.count)).trimmingCharacters(in: .whitespaces) }
        }
        // Only strip symmetric wrapping quotes — a quote that's part of the sentence stays.
        let pairs: [(Character, Character)] = [("\"", "\""), ("“", "”"), ("「", "」"), ("'", "'")]
        for (open, close) in pairs where t.count >= 2 && t.first == open && t.last == close {
            t = String(t.dropFirst().dropLast())
        }
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// MARK: - Model resolution

/// Sub-model-group → primary-model-group fallback (design §6), but VM-independent so the
/// engine and the debug RPCs can both use it. Mirrors the *intent* of
/// `AIChatViewModel.resolveSubEntry()`: prefer the cheap sub group, degrade to primary
/// rather than failing.
enum CorrectionModelResolver {
    struct Resolved {
        let entry: ModelEntry
        let groupKind: String   // "sub" | "primary"
    }

    @MainActor
    static func resolve() -> Resolved? {
        let store = ProviderConfigStore.shared
        if let subId = store.defaultSubGroupId,
           let group = store.group(for: subId),
           let entryId = ModelGroupRouter.resolve(group: group, sessionId: "voice-correction", store: store),
           let entry = store.entry(for: entryId) {
            return Resolved(entry: entry, groupKind: "sub")
        }
        if let primaryId = store.defaultPrimaryGroupId,
           let group = store.group(for: primaryId),
           let entryId = ModelGroupRouter.resolve(group: group, sessionId: "voice-correction", store: store),
           let entry = store.entry(for: entryId) {
            return Resolved(entry: entry, groupKind: "primary")
        }
        logger.error("[VoiceCorrection][Correct] no sub/primary model group configured — correction unavailable")
        return nil
    }
}

private extension Array where Element == String {
    /// Order-preserving dedup (Set would scramble the "most relevant first" ordering the
    /// retrieval step just established).
    func uniqued() -> [String] {
        var seen = Set<String>()
        return filter { seen.insert($0).inserted }
    }
}
