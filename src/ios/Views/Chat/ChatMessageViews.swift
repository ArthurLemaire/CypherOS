import SwiftUI

// MARK: - Context-menu preview

/// Opaque rounded-card preview shown under a message's long-press context menu.
///
/// [T-ios-longpress-menu-preview-background] The message cells are hosted with a
/// clear background (host.view / cell backgroundColor = .clear), and the message
/// `.contextMenu`s are attached either to a zero-size `Color.clear` overlay
/// (assistant block/footer) or to a bubble whose fill is the translucent
/// `tertiarySystemFill` (user). Without an explicit `preview:`, SwiftUI snapshots
/// that (transparent) attached view, so the long-press preview platter shows
/// through to the messages below — the reported "transparent preview" bug.
///
/// Supplying this as the `.contextMenu(preview:)` gives the platter an opaque
/// `systemBackground` rounded card with the message text, so it reads as a
/// floating card. System colors only, so dark mode stays correct.
///
/// [T-ios-longpress-preview-full-content-card] The earlier version hard-capped
/// the text at 1500 chars with a trailing "…", which is what users saw as a
/// "truncated" preview on long assistant messages. It now renders the FULL
/// message content inside a vertical ScrollView: short messages size to their
/// content, long ones are capped to a fraction of the screen height and scroll
/// inside the platter (Telegram/iMessage-style), so the preview is both opaque
/// and complete. An explicit measured height is required because a ScrollView
/// has no intrinsic height — without it the context-menu platter would collapse.
struct MessageContextMenuPreview: View {
    let text: String

    /// [T-ios-usermsg-preview-adaptive-width] Width is now a CAP, not a fixed
    /// size. A short user bubble ("ok") previously lifted into a full 360pt
    /// platter; the platter now hugs the laid-out text width (measured by the
    /// same GeometryReader that already measured height) and only long lines
    /// wrap at this cap, iMessage-style.
    private let maxCardWidth: CGFloat = 360
    /// Long messages cap the platter to this fraction of screen height and
    /// scroll inside; short messages size to content (min of the two).
    private var maxCardHeight: CGFloat { UIScreen.main.bounds.height * 0.55 }

    @State private var contentSize: CGSize = .zero

    var body: some View {
        let shown = text.isEmpty ? " " : text
        ScrollView(.vertical, showsIndicators: true) {
            // No `.frame(maxWidth: .infinity)` here — the Text must report its
            // NATURAL width so short messages yield a narrow platter. The wrap
            // width comes from the ScrollView's width (the outer .frame below),
            // which starts at the cap and shrinks to the measured content.
            Text(shown)
                .font(.system(size: FontSettings.shared.scaledMessage(16.5)))
                .foregroundStyle(ChatColors.primaryText)
                .multilineTextAlignment(.leading)
                .padding(16)
                .background(
                    // Measure the laid-out text size so the platter can hug
                    // content (short) or cap + wrap/scroll (long).
                    GeometryReader { geo in
                        Color.clear
                            .preference(key: PreviewContentSizeKey.self, value: geo.size)
                    }
                )
        }
        .onPreferenceChange(PreviewContentSizeKey.self) { contentSize = $0 }
        // Size = content size, capped. Falls back to the caps until the first
        // measurement lands so the platter never collapses to zero. The small
        // width floor keeps an (attachment-only) empty-text preview from
        // rendering as a sliver.
        .frame(
            width: contentSize.width > 0 ? min(max(contentSize.width, 60), maxCardWidth) : maxCardWidth,
            height: contentSize.height > 0 ? min(contentSize.height, maxCardHeight) : maxCardHeight
        )
        .background(ChatColors.background)
    }
}

/// Preference key carrying the laid-out preview text size up to the platter.
private struct PreviewContentSizeKey: PreferenceKey {
    static var defaultValue: CGSize = .zero
    static func reduce(value: inout CGSize, nextValue: () -> CGSize) {
        let next = nextValue()
        value = CGSize(width: max(value.width, next.width), height: max(value.height, next.height))
    }
}

// MARK: - Chat Message Row

struct ChatMessageRow: View {
    @ObservedObject var message: ChatMessage
    /// Only the actively streaming message needs vm access (for typing indicator & stop button).
    let isActiveMessage: Bool
    var commandStartTime: Date?
    var onStop: (() -> Void)?
    var onRetry: (() -> Void)?
    var onEdit: (() -> Void)?
    var onWithdraw: (() -> Void)?
    var autoRetryAttempt: Int = 0
    var autoRetryCountdown: Int = 0
    var canResume: Bool = false
    var onResume: (() -> Void)?
    var onCompact: (() -> Void)?
    var onCopyScreenshot: (() -> Void)?
    /// Read this whole reply aloud from the start (clears any in-progress TTS).
    /// Wired from AIChatView (which owns the view model). Disabled while the
    /// message is still streaming to avoid fighting the live streaming TTS.
    var onReadAloud: (() -> Void)?
    /// When set, presents the compact summary sheet outside the cell tree (V3).
    /// Falls back to a local .sheet when nil (non-V3 / standalone usage).
    var onShowCompactSummary: ((String) -> Void)?
    /// Triggers AIChatViewModel.revertCompact(). Wired from AIChatView so the
    /// row + sheet stay free of view-model imports.
    var onRevertCompact: (() -> Void)?
    var browserPool: BrowserTabPool?
    var toolSnapshots: [ToolSnapshotItem] = []
    @State private var showUsage = false
    @State private var showCompactSummary = false
    /// Two-phase token usage reveal: space expands first, then content fades in.
    @State private var usageContentVisible = false
    /// Row frame in window coordinates — used to gate token-usage tap to bottom zone.
    @State private var rowFrameInWindow: CGRect = .zero
    private let usageTapLogger = AppLogger(category: "UsageTap")
    /// ID of the block currently highlighted after a copy action.
    @State private var highlightedBlockId: UUID?
    /// The tool block whose detail sheet is currently presented.
    /// Lifted out of ToolCapsuleView so ForEach item changes don't reset it.
    @State private var detailBlock: AssistantBlock?

    /// All text block contents joined, for "Copy All".
    private var fullReplyText: String {
        message.blocks
            .filter { if case .text = $0.kind { return true }; return false }
            .map(\.content)
            .joined(separator: "\n\n")
    }

    /// Full message including tool calls and their results, for clipboard export.
    private var fullMessageText: String {
        var parts: [String] = []
        for block in message.blocks {
            switch block.kind {
            case .text:
                if !block.content.isEmpty { parts.append(block.content) }
            case .shellTool(let command):
                let cmd = command.isEmpty ? block.toolDescription : command
                var s = "$ \(cmd)"
                if !block.content.isEmpty {
                    // content is "$ cmd\noutput…", strip the command line
                    let output = block.content.hasPrefix("$ ") ?
                        String(block.content.drop(while: { $0 != "\n" }).dropFirst()) : block.content
                    if !output.isEmpty { s += "\n\(output)" }
                }
                parts.append(s)
            case .fileReadTool(let path):
                parts.append("Read: \(path)\n\(block.content)")
            case .fileWriteTool(let path):
                parts.append("Write: \(path)\n\(block.content)")
            case .fileEditTool(let path):
                parts.append("Edit: \(path)\n\(block.content)")
            case .browserTool(let action):
                parts.append("Browser: \(action)\n\(block.content)")
            case .readImageTool(let path):
                parts.append("Image: \(path)")
            case .memoryTool(let action):
                parts.append("Memory: \(action)\n\(block.content)")
            case .thinking:
                if !block.content.isEmpty { parts.append("[Thinking]\n\(block.content)") }
            case .info:
                if !block.content.isEmpty { parts.append(block.content) }
            }
        }
        return parts.joined(separator: "\n\n")
    }

    var body: some View {
        switch message.role {
        case .user:
            userRow
                .opacity(message.isCompactedHistory ? 0.5 : 1.0)
        case .assistant:
            assistantRow
                .opacity(message.isCompactedHistory ? 0.5 : 1.0)
        case .compactDivider:
            compactDividerRow
        case .systemInfo:
            systemDividerRow(icon: message.isCompactLoading ? nil : (message.systemIcon ?? "info.circle"),
                             loading: message.isCompactLoading, compact: false)
        }
    }

    // MARK: Compact Divider Row

    private var compactDividerRow: some View {
        HStack(spacing: 10) {
            VStack { Divider() }
            HStack(spacing: 5) {
                if message.isCompactLoading {
                    ProgressView()
                        .scaleEffect(0.6)
                        .frame(width: 12, height: 12)
                } else {
                    Image(systemName: "arrow.down.right.and.arrow.up.left")
                        .font(.system(size: 10))
                }
                Text(message.content)
                    .font(.system(size: 12, weight: .medium))
                if !message.isCompactLoading && message.compactSummary != nil {
                    Button {
                        let summary = message.compactSummary ?? ""
                        if let onShowCompactSummary {
                            onShowCompactSummary(summary)
                        } else {
                            showCompactSummary = true
                        }
                    } label: {
                        Image(systemName: "info.circle")
                            .font(.system(size: 12))
                    }
                    .buttonStyle(.plain)
                }
            }
            .foregroundStyle(.secondary)
            .lineLimit(1)
            .fixedSize()
            VStack { Divider() }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
        .sheet(isPresented: $showCompactSummary) {
            CompactSummarySheet(summary: message.compactSummary ?? "", onRevert: onRevertCompact)
        }
    }

    // MARK: System Divider Row

    /// Shared divider-style row for system info messages.
    private func systemDividerRow(icon: String?, loading: Bool, compact: Bool) -> some View {
        HStack(spacing: 10) {
            VStack { Divider() }
            HStack(spacing: 5) {
                if loading {
                    ProgressView()
                        .scaleEffect(0.6)
                        .frame(width: 12, height: 12)
                } else if let icon {
                    Image(systemName: icon)
                        .font(.system(size: 10))
                }
                Text(message.content)
                    .font(.system(size: 12, weight: .medium))
                    .multilineTextAlignment(.center)
            }
            .foregroundStyle(.secondary)
            // [T-browser-download-ux-v4] No .lineLimit(1).fixedSize() here:
            // fixedSize forced the text to its full ideal width, so a long
            // systemInfo line (e.g. pre-v3 "Downloaded … to /var/minis/… —
            // minis://…" rows persisted in history) overflowed BOTH screen
            // edges from this centered row. layoutPriority keeps the flexible
            // dividers from squeezing the text; past the available width the
            // text wraps (UIKit breaks unspaced tokens like paths/URLs
            // mid-word) instead of clipping.
            .layoutPriority(1)
            VStack { Divider() }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, compact ? 16 : 6)
    }

    // MARK: User Row

    /// User message text with `<user-attached-files>` metadata stripped out.
    private var userDisplayText: String {
        var text = message.content
        if let start = text.range(of: "<user-attached-files>") {
            let end = text.range(of: "</user-attached-files>")
            let endBound = end?.upperBound ?? text.endIndex
            text = String(text[text.startIndex..<start.lowerBound] + text[endBound...])
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return text
    }

    private var userRow: some View {
        HStack {
            Spacer(minLength: 60)

            VStack(alignment: .trailing, spacing: 6) {
                // User-attached files above the text bubble
                if !message.attachments.isEmpty {
                    UserAttachmentList(attachments: message.attachments)
                } else if !message.inputAttachments.isEmpty {
                    // Queued message: show previews from cache before queue drain
                    QueuedAttachmentPreview(attachments: message.inputAttachments)
                }

                if !userDisplayText.isEmpty {
                    HStack(spacing: 6) {
                        Text(userDisplayText)
                            .font(.system(size: FontSettings.shared.scaledMessage(16.5)))
                            .foregroundStyle(message.isQueued ? ChatColors.secondaryText : ChatColors.primaryText)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .background(
                                RoundedRectangle(cornerRadius: 18)
                                    .fill(message.isQueued ? Color.clear : ChatColors.userBubble)
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 18)
                                    .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
                                    .foregroundStyle(ChatColors.secondaryText.opacity(0.5))
                                    .opacity(message.isQueued ? 1 : 0)
                            )

                        if message.isQueued {
                            if let onWithdraw {
                                Button {
                                    onWithdraw()
                                } label: {
                                    Image(systemName: "xmark.circle.fill")
                                        .font(.system(size: 22))
                                        .foregroundStyle(.red)
                                }
                            }
                        }
                    }
                }
            }
            .modifier(MinisOpenURLHandler())
            .contentShape(Rectangle())
            // [T-ios-usermsg-contextmenu-preview-shape] The hit-test shape above
            // stays a full Rectangle (so the whole row is long-pressable), but
            // the context-menu PREVIEW must clip to the bubble's rounded shape —
            // otherwise the lifted preview shows square corners while the bubble
            // is RoundedRectangle(cornerRadius: 18). iOS 16+ lets us specify the
            // preview clip shape independently from the interaction shape.
            .contentShape(.contextMenuPreview, RoundedRectangle(cornerRadius: 18))
            .contextMenu {
                Button {
                    UIPasteboard.general.string = message.content
                } label: {
                    Label("Copy", systemImage: "doc.on.doc")
                }
                if let onCopyScreenshot {
                    Button {
                        onCopyScreenshot()
                    } label: {
                        Label(String(localized: "Copy Screenshot"), systemImage: "camera.viewfinder")
                    }
                }
                if let onEdit {
                    Button {
                        onEdit()
                    } label: {
                        Label("Edit", systemImage: "square.and.pencil")
                    }
                }
                if let onRetry {
                    Button {
                        onRetry()
                    } label: {
                        Label("Retry", systemImage: "arrow.counterclockwise")
                    }
                }
                if let onCompact {
                    Divider()
                    Button(role: .destructive) {
                        onCompact()
                    } label: {
                        Label("Compact Above", systemImage: "arrow.down.right.and.arrow.up.left")
                    }
                }
            } preview: {
                // [T-ios-longpress-menu-preview-background] Opaque card so the
                // long-press preview isn't transparent (see MessageContextMenuPreview).
                MessageContextMenuPreview(text: message.content)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 4)
    }

    // MARK: Assistant Row

    private var assistantRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Assistant label
            HStack(spacing: 6) {
                Image(systemName: "sparkles")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [Color(red: 0.72, green: 0.69, blue: 0.59),
                                     Color(red: 0.6, green: 0.6, blue: 0.55)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                AssistantSoulName()
                    .font(.body.weight(.semibold))
                    .foregroundStyle(ChatColors.primaryText)
            }
            .padding(.top, 4)

            ForEach(message.blocks) { block in
                AssistantBlockView(
                    block: block,
                    message: message,
                    isActiveMessage: isActiveMessage,
                    commandStartTime: commandStartTime,
                    onStop: onStop,
                    onTapBlank: message.usage != nil ? { windowPoint in
                        // Only respond to taps in the bottom 100pt of the message row
                        let bottomZoneTop = rowFrameInWindow.maxY - 100
                        let inZone = windowPoint.y >= bottomZoneTop
                        usageTapLogger.debug("[usageTap] windowPt=\(String(format: "%.0f,%.0f", windowPoint.x, windowPoint.y)) rowBottom=\(String(format: "%.0f", rowFrameInWindow.maxY)) zoneTop=\(String(format: "%.0f", bottomZoneTop)) inZone=\(inZone) showUsage=\(showUsage)")
                        guard inZone else { return }

                        if showUsage {
                            withAnimation(.easeInOut(duration: 0.15)) { usageContentVisible = false }
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
                                showUsage = false
                            }
                        } else {
                            showUsage = true
                            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                                withAnimation(.easeInOut(duration: 0.2)) { usageContentVisible = true }
                            }
                        }
                    } : nil,
                    onCopyScreenshot: onCopyScreenshot,
                    browserPool: browserPool,
                    toolSnapshots: toolSnapshots,
                    highlightedBlockId: $highlightedBlockId,
                    detailBlock: $detailBlock
                )
            }

            // Typing indicator: show when waiting for first content, or when
            // all tools have completed and we're waiting for the model's next response
            if isActiveMessage && (!hasVisibleContent || message.isAwaitingModelResponse) {
                TypingIndicator()
            }

            // Inline error + retry
            if let error = message.error {
                inlineError(error)
            }

            // Resume banner for interrupted sessions
            if canResume && message.error == nil {
                resumeBanner
            }

            // Token usage — two-phase reveal: space expands first, then content fades in
            if message.streamInterruptCount > 0 || showUsage {
                HStack(spacing: 6) {
                    if message.streamInterruptCount > 0 {
                        streamInterruptBadge(message.streamInterruptCount)
                    }
                    if showUsage, let usage = message.usage {
                        usageCapsule(usage)
                            .opacity(usageContentVisible ? 1 : 0)
                    }
                    Spacer()
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 16)
        .padding(.vertical, 6)
        // [T-ios-geometry-observer-crash] THE crasher from the v1.8b13 IPS:
        // onChange(of: geo.frame(in: .global)) wrote state inside the
        // geometry-observer path and tripped the async renderer
        // (ViewGraphGeometryObservers.needsUpdate SIGTRAP). onGeometryChange
        // measures the same row bounds the background GeometryReader did,
        // and its initial fire covers the old onAppear seed.
        .onGeometryChange(for: CGRect.self) { proxy in
            proxy.frame(in: .global)
        } action: { rowFrameInWindow = $0 }
        .background {
            // Context menu on the background layer so it only fires on
            // blank areas — UITextView link taps in the foreground take priority.
            Color.clear
                .contentShape(Rectangle())
                .contextMenu {
                    // [T-ios-msg-contextmenu-recursion-crash] Gate the eager menu
                    // tree behind an Equatable key so the cell body churn during
                    // `gh`/shell streaming output doesn't rebuild + re-diff the
                    // whole menu subtree every frame — the deep ContextMenuModifier
                    // / UnwrapConditional recursion that blew the update stack into
                    // unmapped heap (incident 98E8805F). Copy actions read
                    // `fullReplyText` lazily at TAP time, so the menu structure
                    // only needs rebuilding when the key changes: which optional
                    // actions exist + the streaming-disabled state.
                    EquatableMenuGate(key: AssistantMenuKey(
                        messageId: message.id,
                        hasReadAloud: onReadAloud != nil,
                        hasCopyScreenshot: onCopyScreenshot != nil,
                        hasCompact: onCompact != nil,
                        isActive: isActiveMessage
                    )) {
                        Button {
                            UIPasteboard.general.string = fullReplyText
                        } label: {
                            Label("Copy All", systemImage: "doc.on.doc")
                        }
                        Button {
                            UIPasteboard.general.string = fullReplyText
                        } label: {
                            Label("Copy Markdown", systemImage: "text.quote")
                        }
                        if let onReadAloud {
                            Button {
                                onReadAloud()
                            } label: {
                                Label(String(localized: "Read from Start"), systemImage: "play.circle")
                            }
                            // Greyed out while streaming so it can't clash with the
                            // live streaming TTS of the same reply.
                            .disabled(isActiveMessage)
                        }
                        if let onCopyScreenshot {
                            Button {
                                onCopyScreenshot()
                            } label: {
                                Label(String(localized: "Copy Screenshot"), systemImage: "camera.viewfinder")
                            }
                        }
                        if let onCompact {
                            Divider()
                            Button(role: .destructive) {
                                onCompact()
                            } label: {
                                Label("Compact Above", systemImage: "arrow.down.right.and.arrow.up.left")
                            }
                        }
                    }
                    .equatable()
                } preview: {
                    // [T-ios-longpress-menu-preview-background] Opaque card for
                    // this Color.clear-attached contextMenu (see
                    // MessageContextMenuPreview).
                    MessageContextMenuPreview(text: fullReplyText)
                }
        }
        .sheet(item: $detailBlock) { block in
            ToolLiveSheet(toolBlocks: message.blocks.filter { $0.toolStatus != nil },
                          initialIdx: message.blocks.filter({ $0.toolStatus != nil }).firstIndex(where: { $0.id == block.id }) ?? 0,
                          toolSnapshots: toolSnapshots, browserPool: browserPool)
        }
    }

    @ViewBuilder
    private func usageCapsule(_ usage: TokenUsage) -> some View {
        HStack(spacing: 4) {
            Image(systemName: "speedometer")
                .font(.system(size: 9))
            Text(usageSummary(usage))
                .font(.system(size: 10, design: .monospaced))
        }
        .foregroundStyle(ChatColors.tertiaryText)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(ChatColors.userBubble.opacity(0.6))
        .clipShape(Capsule())
        .transition(.opacity.combined(with: .scale(scale: 0.8)))
    }

    @ViewBuilder
    private func streamInterruptBadge(_ count: Int) -> some View {
        HStack(spacing: 3) {
            Image(systemName: "arrow.clockwise")
                .font(.system(size: 9, weight: .semibold))
            Text("\(count)")
                .font(.system(size: 10, design: .monospaced))
        }
        .foregroundStyle(Color.orange.opacity(0.8))
        .padding(.horizontal, 7)
        .padding(.vertical, 3)
        .background(Color.orange.opacity(0.12))
        .clipShape(Capsule())
    }

    private func usageSummary(_ u: TokenUsage) -> String {
        var parts: [String] = []
        if u.latestContextTokens > 0 {
            parts.append("ctx:\(formatTokenCount(u.latestContextTokens))")
        }
        parts.append("in:\(formatTokenCount(u.inputTokens))")
        parts.append("out:\(formatTokenCount(u.outputTokens))")
        if u.cacheReadTokens > 0 {
            parts.append("cache:\(formatTokenCount(u.cacheReadTokens))")
        }
        if u.cacheCreationTokens > 0 {
            parts.append("+cache:\(formatTokenCount(u.cacheCreationTokens))")
        }
        return parts.joined(separator: " ")
    }

    private func formatTokenCount(_ count: Int) -> String {
        if count >= 1000 {
            let k = Double(count) / 1000.0
            return k.truncatingRemainder(dividingBy: 1) == 0
                ? "\(Int(k))k"
                : String(format: "%.1fk", k)
        }
        return "\(count)"
    }

    @ViewBuilder
    private func inlineError(_ error: String) -> some View {
        HStack(alignment: .center, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .lineLimit(2)
            }
            .contentShape(Rectangle())
            .contextMenu {
                Button {
                    UIPasteboard.general.string = error
                } label: {
                    Label(String(localized: "Copy Error"), systemImage: "doc.on.doc")
                }
            }

            Spacer()

            if autoRetryAttempt > 0 {
                Text("Retry in \(autoRetryCountdown)s (\(autoRetryAttempt)/\(AIChatViewModel.retryDelays.count))")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.secondary.opacity(0.12))
                    .clipShape(Capsule())
            } else if let onRetry {
                Button(action: onRetry) {
                    HStack(spacing: 4) {
                        Image(systemName: "arrow.clockwise")
                            .font(.caption.weight(.semibold))
                        Text("Retry")
                            .font(.caption.weight(.semibold))
                    }
                    .foregroundStyle(ChatColors.primaryText)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(ChatColors.primaryText.opacity(0.15))
                    .clipShape(Capsule())
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.red.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var resumeBanner: some View {
        HStack(alignment: .center, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: "pause.circle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                Text("Interrupted — tap Resume to continue")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if let onResume {
                Button(action: onResume) {
                    HStack(spacing: 4) {
                        Image(systemName: "play.fill")
                            .font(.caption.weight(.semibold))
                        Text("Resume")
                            .font(.caption.weight(.semibold))
                    }
                    .foregroundStyle(.white)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.orange)
                    .clipShape(Capsule())
                }
            }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.orange.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var hasVisibleContent: Bool {
        message.blocks.contains { block in
            switch block.kind {
            case .text: return !block.content.isEmpty
            case .thinking: return true
            case .info: return true
            case .shellTool, .fileReadTool, .fileWriteTool, .fileEditTool, .browserTool, .readImageTool, .memoryTool: return true
            }
        }
    }

}


