import Foundation

private let logger = AppLogger(category: "AIChatVM")

// MARK: - Session Title Generation

extension AIChatViewModel {

    // MARK: - Session Title Generation

    /// [T-title-gen-fallback-first-message-ios] Build a fallback session title
    /// from the first user message when LLM title generation fails. Strips the
    /// `<user-attached-files>` metadata block + inline attachment markers,
    /// collapses whitespace/newlines, and truncates to ~30 chars to match the
    /// generated-title length. Returns nil if nothing usable remains.
    static func fallbackTitle(fromFirstUserMessage raw: String) -> String? {
        var t = raw
        // Drop the attached-files XML the composer injects.
        if let start = t.range(of: "<user-attached-files>") {
            let end = t.range(of: "</user-attached-files>")
            let endBound = end?.upperBound ?? t.endIndex
            t = String(t[t.startIndex..<start.lowerBound] + t[endBound...])
        }
        // Collapse all whitespace (incl. newlines) to single spaces.
        t = t.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        let maxLen = 30
        if t.count > maxLen {
            return String(t.prefix(maxLen)).trimmingCharacters(in: .whitespaces) + "…"
        }
        return t
    }

    /// Call after each LLM stream completes to asynchronously generate a session title.
    /// Retries up to 3 times across agent loop iterations if the title is still missing.
    /// Skips if a generation request is already in-flight to avoid wasting tokens.
    func generateSessionTitleIfNeeded(toolEntries: [(name: String, args: [String: Any])] = []) {
        guard let sessionId, titleGenAttempts < 3, !isTitleGenerating else { return }

        let userMessages = messages.filter { $0.role == .user }
        let assistantMessages = messages.filter { $0.role == .assistant }
        guard let firstUser = userMessages.first else { return }
        guard !assistantMessages.isEmpty else { return }

        // Extract plain text from an assistant message's blocks.
        func assistantText(_ msg: ChatMessage) -> String {
            msg.blocks
                .filter { $0.kind == .text }
                .map { $0.content }
                .joined(separator: "\n")
        }

        // First assistant message that actually carries text — early turns can
        // be tool-only, and a tool-only first message would summarize as "".
        let firstAssistantWithText = assistantMessages.first {
            !assistantText($0).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        var responseText = firstAssistantWithText.map(assistantText) ?? ""

        // If no assistant text anywhere yet, build a summary from tool call args
        if responseText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !toolEntries.isEmpty {
            let toolSummaries = toolEntries.prefix(3).map { entry in
                let argsPreview = (try? JSONSerialization.data(withJSONObject: entry.args))
                    .flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
                return "\(entry.name)(\(String(argsPreview.prefix(200))))"
            }
            responseText = "[Tool calls: \(toolSummaries.joined(separator: ", "))]"
        }

        guard !responseText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }

        // Summary scope: first user + first assistant text (200 chars each);
        // when the session has more than one user turn, also append the last
        // user + last assistant pair (200 chars each) so titles track topic
        // drift in longer sessions. Mirrors regenerateSessionTitle's shape.
        var summary = "User: \(String(firstUser.content.prefix(200)))\n\nAssistant: \(String(responseText.prefix(200)))"
        if userMessages.count > 1, let lastUser = userMessages.last {
            summary += "\n\n[... middle of conversation omitted ...]\n"
            summary += "\nUser: \(String(lastUser.content.prefix(200)))"
            if let lastAssistant = assistantMessages.last,
               lastAssistant.id != firstAssistantWithText?.id {
                let lastText = assistantText(lastAssistant)
                if !lastText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    summary += "\n\nAssistant: \(String(lastText.prefix(200)))"
                }
            }
        }
        // Captured for the fallback-title path below (full first-user content).
        let firstUserRaw = firstUser.content
        let userTurnCount = userMessages.count

        titleGenAttempts += 1
        isTitleGenerating = true

        let attempt = titleGenAttempts
        let subEntry = resolveSubEntry()
        logger.info("[TitleGen] Starting title generation attempt \(attempt)/3 for session \(sessionId ?? "nil"), subEntry: \(subEntry?.model.id ?? "nil")")
        Task { [weak self, sessionId, subEntry, firstUserRaw, summary] in
            do {
                // If title already exists (e.g. set by a previous async Task), stop trying
                if let session = await ChatStore.shared.getSession(sessionId), session.title != nil {
                    await MainActor.run {
                        self?.titleGenAttempts = 3
                        self?.isTitleGenerating = false
                    }
                    return
                }

                logger.info("[TitleGen] Summary length: \(summary.count) chars, userTurns=\(userTurnCount)")
                let (title, category) = try await Self.callSubModelForTitle(
                    conversationSummary: summary,
                    subEntry: subEntry
                )
                let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
                    .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
                guard !trimmed.isEmpty else {
                    logger.error("[TitleGen] FAILED attempt \(attempt)/3 — reason=empty-response (model returned no usable title after trimming, raw: \"\(title.prefix(80))\")")
                    await Self.applyFallbackTitle(sessionId: sessionId, firstUserRaw: firstUserRaw, attempt: attempt)
                    await MainActor.run {
                        self?.titleGenAttempts = 3
                        self?.isTitleGenerating = false
                    }
                    return
                }
                await ChatStore.shared.updateSessionTitle(sessionId, title: trimmed, category: category)
                await MainActor.run {
                    self?.titleGenAttempts = 3
                    self?.isTitleGenerating = false
                    SessionActivityTracker.shared.updateSessionTitle(sessionId, title: trimmed)
                }
                logger.info("[TitleGen] Attempt \(attempt): saved session title: \(trimmed), category: \(category ?? "nil")")
            } catch {
                // Classify the failure so logs show WHY (request error / timeout /
                // model-unavailable / parse failure all funnel here via thrown
                // NSError or LLMError).
                let reason: String
                if let urlErr = error as? URLError {
                    reason = urlErr.code == .timedOut ? "timeout" : "request-error(\(urlErr.code.rawValue))"
                } else if let llmErr = error as? LLMError {
                    reason = "llm-error(\(llmErr.errorDescription ?? "unknown"))"
                } else {
                    reason = "error(\(error.localizedDescription))"
                }
                logger.error("[TitleGen] FAILED attempt \(attempt)/3 — reason=\(reason)")
                // Fallback so the session never stays untitled.
                await Self.applyFallbackTitle(sessionId: sessionId, firstUserRaw: firstUserRaw, attempt: attempt)
                await MainActor.run {
                    self?.titleGenAttempts = 3
                    self?.isTitleGenerating = false
                }
            }
        }
    }

    /// [T-title-gen-fallback-first-message-ios] Apply a first-user-message
    /// fallback title, but only if the session is still untitled (another
    /// attempt / regenerate may have set one in the meantime).
    private static func applyFallbackTitle(sessionId: String, firstUserRaw: String, attempt: Int) async {
        if let session = await ChatStore.shared.getSession(sessionId), session.title != nil {
            logger.info("[TitleGen] Fallback skipped — session already titled: \(session.title ?? "")")
            return
        }
        guard let fallback = fallbackTitle(fromFirstUserMessage: firstUserRaw) else {
            logger.warning("[TitleGen] Fallback unavailable — first user message empty after cleanup; session stays untitled (attempt \(attempt))")
            return
        }
        await ChatStore.shared.updateSessionTitle(sessionId, title: fallback, category: nil)
        logger.info("[TitleGen] Applied fallback title from first user message: \"\(fallback)\" (attempt \(attempt))")
    }

    /// Build a lightweight provider for the sub model and call it to generate a title and category.
    /// Regenerate the title and category for a session using its stored messages.
    /// Uses the first user/assistant pair + last user/assistant pair for better context.
    static func regenerateSessionTitle(sessionId: String) async throws {
        let rawMessages = await ChatStore.shared.loadMessages(sessionId: sessionId)

        let userMessages = rawMessages.filter { $0.role == .user }
        let assistantMessages = rawMessages.filter { $0.role == .assistant }
        guard let firstUser = userMessages.first,
              let firstAssistantAny = assistantMessages.first else { return }

        func extractText(_ msg: RawMessage, limit: Int) -> String {
            String(msg.parts.compactMap {
                if case .text(let s) = $0 { return s } else { return nil }
            }.joined(separator: "\n").prefix(limit))
        }
        func hasText(_ msg: RawMessage) -> Bool {
            !extractText(msg, limit: Int.max)
                .trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }

        // First assistant message that actually carries text — a tool-only
        // first turn would emit an empty "Assistant:" line (aligns with
        // generateSessionTitleIfNeeded's firstAssistantWithText). When NO
        // assistant message has text, fall back to the raw first one so the
        // degenerate behavior stays exactly as before.
        let firstAssistant = assistantMessages.first(where: hasText) ?? firstAssistantAny

        // Build conversation summary: first pair + (optional) last pair.
        // 200 chars per excerpt — matches generateSessionTitleIfNeeded, enough
        // for topic signal without swamping the prompt on long messages.
        var summary = """
        [Start of conversation]
        User: \(extractText(firstUser, limit: 200))

        Assistant: \(extractText(firstAssistant, limit: 200))
        """

        let lastUser = userMessages.last
        let lastAssistant = assistantMessages.last
        if let lastUser, lastUser.id != firstUser.id {
            summary += "\n\n[... middle of conversation omitted ...]\n"
            summary += "\nUser: \(extractText(lastUser, limit: 200))"
            // Skip a tool-only tail assistant instead of appending an empty
            // "Assistant:" line (mirrors the auto-generation path's check).
            if let lastAssistant, lastAssistant.id != firstAssistant.id, hasText(lastAssistant) {
                summary += "\n\nAssistant: \(extractText(lastAssistant, limit: 200))"
            }
            summary += "\n[End of conversation]"
        }

        guard !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }

        // Try to resolve sub-model from session binding
        let store = ProviderConfigStore.shared
        var subEntry: ModelEntry? = nil
        if let binding = store.binding(for: sessionId),
           let sub = binding.subModelSource {
            switch sub {
            case .directEntry(let entryId, _):
                subEntry = store.entry(for: entryId)
            case .group(_, let resolvedEntryId):
                subEntry = store.entry(for: resolvedEntryId)
            }
        } else if let binding = store.binding(for: sessionId) {
            // No sub source — use primary
            switch binding.primarySource {
            case .directEntry(let entryId, _):
                subEntry = store.entry(for: entryId)
            case .group(_, let resolvedEntryId):
                subEntry = store.entry(for: resolvedEntryId)
            }
        }

        let (title, category) = try await callSubModelForTitle(
            conversationSummary: summary,
            subEntry: subEntry
        )
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
        guard !trimmed.isEmpty else { return }
        await ChatStore.shared.updateSessionTitle(sessionId, title: trimmed, category: category)
    }

    /// Build a lightweight provider for the sub model and call it to generate a title and category.
    private static func callSubModelForTitle(
        conversationSummary: String,
        subEntry: ModelEntry? = nil
    ) async throws -> (String, String?) {
        guard let entry = subEntry else {
            throw NSError(domain: "TitleGen", code: -1, userInfo: [NSLocalizedDescriptionKey: "No sub model available"])
        }

        // Route title generation through AgentProvider (with thinkingLevel:
        // .off) rather than the lower-level LLMProvider.streamMessage. The
        // agent path knows how to explicitly DISABLE thinking on providers
        // like Qwen3 / DeepSeek-v4 / OpenRouter-compat, which would otherwise
        // run with thinking ON by default and return finish_reason=tool_calls
        // with an empty text body — exactly the failure mode reported on
        // qwen3.6-plus (T-title-gen-disable-reasoning-ios). The agent
        // streaming surface uses `streamAgentMessage` which routes through
        // `injectThinkingParams` and emits `enable_thinking: false` /
        // `reasoning_effort: "none"` / `thinking_budget: 0` per model
        // family.
        let provider = await AIChatViewModel.makeAgentProvider(for: entry)
        logger.info("[TitleGen] Using provider: \(provider.name), model: \(entry.model.id), thinkingLevel=.off")

        let langInjection = titleLanguageInjection()

        let prompt = """
        Based on the following conversation, generate a short title (max 6 words) that captures the topic. \
        Also pick a task category from: code, writing, research, analysis, creative, chat, math, translation, health, finance, travel, education, design, productivity, support, other.

        \(langInjection)

        You MUST respond with valid JSON only. Example:
        {"title": "Debug Login Page Issue", "category": "code"}

        Conversation:
        \(conversationSummary)
        """

        let messages = [AgentMessage(role: .user, parts: [.text(prompt)])]
        let stream = try await provider.streamAgentMessage(
            messages: messages,
            systemPrompt: "You generate concise titles for conversations. You MUST respond with a single valid JSON object: {\"title\": \"...\", \"category\": \"...\"}. No other text.",
            tools: [],
            maxTokens: 1024,
            thinkingLevel: .off
        )

        var responseText = ""
        var stopReason: AgentStopReason?
        var usage: LLMUsage?
        var didTag = false
        for try await event in stream {
            // See compact path comment: tag on first chunk so the wire
            // request is actually in the ring buffer by then.
            #if DEBUG
            if !didTag {
                LastAPIRequestBody.shared.tagLatest("title")
                didTag = true
            }
            #endif
            switch event {
            case .textDelta(let delta):
                responseText += delta
            case .done(let reason):
                stopReason = reason
            case .usage(let u):
                usage = u
            // Title generation doesn't issue tools, so toolCallComplete /
            // toolInputDelta / contentBlockStart / reasoningContent /
            // reasoningEcho / thinkingDelta are all ignored. If a model
            // emits them anyway (qwen3 sometimes does even with thinking
            // off), we let the text accumulator finish what it can.
            default:
                break
            }
        }

        logger.info("[TitleGen] Raw LLM response (\(responseText.count) chars): \(responseText)")
        let stopStr: String
        switch stopReason {
        case .endTurn?:    stopStr = "endTurn"
        case .toolUse?:    stopStr = "toolUse"
        case .maxTokens?:  stopStr = "maxTokens"
        case .refusal?:    stopStr = "refusal"
        case nil:          stopStr = "nil"
        }
        logger.info("[TitleGen] stopReason: \(stopStr), usage: in=\(usage?.inputTokens ?? -1) out=\(usage?.outputTokens ?? -1)")

        // Strip markdown code fences if present (e.g. ```json ... ```)
        var cleaned = responseText.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.hasPrefix("```") {
            // Remove opening fence line and closing fence
            let lines = cleaned.components(separatedBy: .newlines)
                .drop(while: { $0.hasPrefix("```") })
            cleaned = lines.joined(separator: "\n")
            if cleaned.hasSuffix("```") {
                cleaned = String(cleaned.dropLast(3))
            }
            cleaned = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        // Try to extract JSON object if response contains extra text around it
        let jsonString: String
        if let start = cleaned.firstIndex(of: "{"),
           let end = cleaned.lastIndex(of: "}") {
            jsonString = String(cleaned[start...end])
        } else {
            jsonString = cleaned
        }

        // Attempt JSON parse
        if let data = jsonString.data(using: .utf8),
           let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let title = json["title"] as? String, !title.isEmpty {
            let category = json["category"] as? String
            logger.info("[TitleGen] Parsed JSON — title: \(title), category: \(category ?? "nil")")
            return (title, category)
        }

        logger.warning("[TitleGen] JSON parse failed for extracted: \(jsonString)")

        // Regex fallback: extract title value from malformed JSON
        if let titleMatch = jsonString.range(of: #""title"\s*:\s*"([^"]+)""#, options: .regularExpression) {
            let matchStr = String(jsonString[titleMatch])
            // Extract the captured group value
            if let valueStart = matchStr.range(of: #":\s*""#, options: .regularExpression)?.upperBound,
               let valueEnd = matchStr.lastIndex(of: "\""), valueStart < valueEnd {
                let title = String(matchStr[valueStart..<valueEnd])
                logger.info("[TitleGen] Regex fallback — title: \(title)")
                return (title, nil)
            }
        }

        // Last resort: use raw text only if it looks like a plain title (no JSON artifacts)
        let raw = cleaned
            .trimmingCharacters(in: CharacterSet(charactersIn: "\"{}"))
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if !raw.isEmpty && raw.count < 60 && !raw.contains("{") && !raw.contains("}") {
            logger.info("[TitleGen] Plain text fallback — title: \(raw)")
            return (raw, nil)
        }

        logger.error("[TitleGen] All parsing strategies failed. Response was: \(responseText)")
        throw NSError(domain: "TitleGen", code: -2, userInfo: [NSLocalizedDescriptionKey: "Failed to parse title from response: \(responseText.prefix(200))"])
    }

    /// Build a bilingual instruction asking the title-generation model to use
    /// the user's app interface language. The localized name is resolved from
    /// the same locale so it ships in the user's language (the native endonym
    /// for zh, "English" for en, etc.). Falls back to "en" if resolution fails.
    ///
    /// Resolution order:
    ///   1. The user's explicit `appLanguage` (Settings → Language, also
    ///      writable via minis-config `appearance.language`). Honors changes
    ///      made after launch — `Bundle.main.preferredLocalizations` is
    ///      computed once at launch from `AppleLanguages` and does NOT update
    ///      when `setLanguage(...)` rewrites that key at runtime, so reading
    ///      it here picked up the launch-time system locale instead of the
    ///      user's in-app choice.
    ///   2. `Bundle.main.preferredLocalizations.first` (launch-time matching
    ///      against the bundle's supported locales).
    ///   3. `Locale.current` language code.
    ///   4. "en".
    private static func titleLanguageInjection() -> String {
        let userSelected = (UserDefaults.standard.string(forKey: "appLanguage") ?? "")
            .trimmingCharacters(in: .whitespaces)
        let preferred: String = !userSelected.isEmpty
            ? userSelected
            : (Bundle.main.preferredLocalizations.first
               ?? Locale.current.language.languageCode?.identifier
               ?? "en")
        let locale = Locale(identifier: preferred)
        let localizedName = locale.localizedString(forIdentifier: preferred)
            ?? Locale(identifier: "en").localizedString(forIdentifier: preferred)
            ?? preferred
        return """
        The user's app interface language is "\(preferred)" (\(localizedName)). Generate the title primarily in this language. If the conversation content is in a different language, you may incorporate proper nouns from it, but the overall title language should match the interface language.
        用户的 App 界面语言是 "\(preferred)"（\(localizedName)）。请优先使用该语言生成标题。如果对话内容是其他语言，可保留专有名词，但标题整体语言应与界面语言一致。
        """
    }

}
