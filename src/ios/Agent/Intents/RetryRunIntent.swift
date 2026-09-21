import AppIntents
import Foundation

/// Retries (re-runs) from a specific user message in a session.
/// At runtime, shows a picker of user messages from the selected session,
/// then deletes all messages after the chosen one and re-runs the agent.
@available(iOS 17.0, *)
struct RetryRunIntent: AppIntent {
    static var title: LocalizedStringResource = "Retry Run"
    static var description = IntentDescription("Re-runs the AI agent from a specific user message in a session. Presents a list of user messages to choose from, then retries from that point.")
    static var openAppWhenRun = false

    @Parameter(title: "Session")
    var session: SessionEntity

    @Parameter(title: "Message")
    var message: UserMessageEntity?

    @Parameter(title: "Attachments", description: "Images, videos, or files to replace existing attachments. Accepts output from previous Shortcuts actions. If empty, keeps original attachments.",
               supportedTypeIdentifiers: ["public.image", "public.movie", "public.data"],
               inputConnectionBehavior: .connectToPreviousIntentResult)
    var files: [IntentFile]?

    @Parameter(title: "Wait for Result", description: "When enabled, waits for the AI to finish and returns the full response for use in subsequent actions.", default: false)
    var waitForResult: Bool

    @MainActor
    func perform() async throws -> some IntentResult & ReturnsValue<SendPromptResult> & ProvidesDialog {
        BackgroundKeepAliveManager.shared.setup()

        // [T-shortcuts-eager-keepalive] Arm keep-alive BEFORE any await so
        // iOS doesn't suspend the AppIntent-woken process before the normal
        // setActive path (buried behind vm.send() → currentTask → await
        // ensureSession()) has a chance to fire. No-op unless the user has
        // enhancedBackgroundEffective on.
        let eagerResult = BackgroundKeepAliveManager.shared.armEagerlyForShortcut(
            sessionId: session.id, caller: "RetryRunIntent")
        // [T-shortcuts-diag-and-pending] Snapshot state and mark pending; the
        // completion path clears it.
        ShortcutRunTracker.logPerformEntry(
            intent: "RetryRunIntent",
            sessionId: session.id,
            eagerKeepAliveArmed: eagerResult.armed,
            eagerKeepAliveSkippedReason: eagerResult.skipReason
        )
        let pendingId = ShortcutRunTracker.markPending(
            intent: "RetryRunIntent",
            sessionId: session.id,
            eagerKeepAliveArmed: eagerResult.armed,
            eagerKeepAliveSkippedReason: eagerResult.skipReason
        )

        let (vm, isNew) = ViewModelCache.shared.getOrCreate(for: session.id)
        if isNew {
            await vm.loadSession()
        }

        // Wait if session is currently processing
        if vm.isProcessing {
            for await processing in vm.$isProcessing.values {
                if !processing { break }
            }
        }

        // Find user messages
        let userMessages = vm.messages.filter { $0.role == .user }
        guard !userMessages.isEmpty else {
            // [T-shortcuts-diag-and-pending] Early-return before any agent
            // work — clear the pending marker so the next foreground scan
            // doesn't flag this as orphaned.
            ShortcutRunTracker.markCompleted(recordId: pendingId, reason: "earlyReturn.noUserMessages")
            // [T-ios-session-status-mismatch] The eager setActive above added
            // this session id to the tracker before we knew we'd bail. The VM
            // sink pairs setActive/setInactive on $isProcessing transitions,
            // but we're returning without ever flipping isProcessing → the
            // sink never fires setInactive and the tracker leaks a phantom
            // "running" session (home spinner stuck, chat.session.status
            // false-positive). Drop it here.
            if eagerResult.armed {
                SessionActivityTracker.shared.setInactive(session.id,
                    source: "RetryRunIntent.eager.earlyReturnNoUserMessages")
            }
            return .result(
                value: SendPromptResult(sessionId: session.id, modelName: "N/A", status: "Error", isNewSession: false),
                dialog: "No user messages found in this session."
            )
        }

        // Build entity list from this session's user messages
        let sessionTitle = session.displayName
        let entities = userMessages.enumerated().map { idx, msg -> UserMessageEntity in
            let text = msg.content.trimmingCharacters(in: .whitespacesAndNewlines)
            let preview = text.isEmpty ? "(attachment)" : String(text.prefix(80))
            return UserMessageEntity(
                id: "\(session.id):\(idx)",
                sessionId: session.id,
                preview: preview,
                index: idx + 1,
                sessionTitle: sessionTitle
            )
        }

        // Resolve which message to retry from
        let chosenEntity: UserMessageEntity
        if let provided = message {
            chosenEntity = provided
        } else if entities.count == 1 {
            chosenEntity = entities[0]
        } else {
            // Runtime disambiguation — shows the correct session's messages
            chosenEntity = try await $message.requestDisambiguation(
                among: entities,
                dialog: IntentDialog("Which message do you want to retry from?")
            )
        }

        // Map entity index back to ChatMessage
        let targetIdx = chosenEntity.index - 1
        let targetMessage: ChatMessage
        if targetIdx >= 0 && targetIdx < userMessages.count {
            targetMessage = userMessages[targetIdx]
        } else {
            targetMessage = userMessages.last!
        }

        let promptPreview = String(targetMessage.content.prefix(50))

        // Convert intent files to InputAttachments for replacement (if provided)
        var replacementAttachments: [InputAttachment]? = nil
        if let intentFiles = files, !intentFiles.isEmpty {
            // Stage files via the VM's cache, then detach them for retryFromMessage
            let countBefore = vm.attachments.count
            for file in intentFiles {
                let name = SendPromptIntent.resolvedFileName(for: file)
                vm.addDataAttachment(data: file.data, fileName: name)
            }
            replacementAttachments = Array(vm.attachments.dropFirst(countBefore))
            vm.attachments.removeSubrange(countBefore...)
        }

        // Retry from that message (replacement attachments override the original ones)
        vm.retryFromMessage(targetMessage.id, replacementAttachments: replacementAttachments)

        let sid = vm.sessionId ?? session.id

        // Resolve model name
        var modelName = vm.selectedModel.displayName
        let store = ProviderConfigStore.shared
        if let binding = store.binding(for: sid) {
            switch binding.primarySource {
            case .group(_, let resolvedEntryId):
                if let entry = store.entry(for: resolvedEntryId) {
                    modelName = entry.model.displayName
                }
            case .directEntry(let modelEntryId, _):
                if let entry = store.entry(for: modelEntryId) {
                    modelName = entry.model.displayName
                }
            }
        }

        ShortcutNotification.post(
            id: "shortcut-retry-\(sid)",
            title: "Minis: Retrying",
            body: "\(modelName): \(promptPreview)\(targetMessage.content.count > 50 ? "…" : "")",
            sessionId: sid
        )

        if waitForResult {
            for await processing in vm.$isProcessing.values {
                if !processing { break }
            }

            // [T-shortcuts-diag-and-pending] Loop finished.
            ShortcutRunTracker.markCompleted(recordId: pendingId, reason: "waitForResult.done")

            let responseText = SendPromptIntent.extractResponseText(from: vm)

            ShortcutNotification.post(
                id: "shortcut-retry-done-\(sid)",
                title: "Minis: Retry Done",
                body: "\(modelName): \(String(responseText.prefix(200)))",
                sessionId: sid
            )

            let result = SendPromptResult(
                sessionId: sid,
                modelName: modelName,
                status: "Completed",
                isNewSession: false,
                prompt: targetMessage.content,
                responseText: responseText
            )
            return .result(value: result, dialog: "\(responseText.prefix(500))")
        }

        // Async mode
        let capturedModelName = modelName
        let capturedSid = sid
        let capturedPendingId = pendingId
        Task { @MainActor in
            for await processing in vm.$isProcessing.values {
                if !processing { break }
            }

            // [T-shortcuts-diag-and-pending] Loop finished.
            ShortcutRunTracker.markCompleted(recordId: capturedPendingId, reason: "async.done")

            let summary = String(SendPromptIntent.extractResponseText(from: vm).prefix(200))

            ShortcutNotification.post(
                id: "shortcut-retry-done-\(capturedSid)",
                title: "Minis: Retry Done",
                body: "\(capturedModelName): \(summary)",
                sessionId: capturedSid
            )
        }

        let result = SendPromptResult(
            sessionId: sid,
            modelName: modelName,
            status: "Retrying",
            isNewSession: false,
            prompt: targetMessage.content
        )

        return .result(value: result, dialog: "Retrying from message: \(promptPreview)\(targetMessage.content.count > 50 ? "…" : "")")
    }

    static var parameterSummary: some ParameterSummary {
        Summary("Retry \(\.$session) from \(\.$message)")
    }
}
