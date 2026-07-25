import SwiftUI

/// Settings page for SOUL.md — Minis's persistent personality file.
/// Lives between Skills and Memory in the Agent Runtime section.
struct SoulSettingsView: View {
    @State private var name: String = SoulMetadata.default.name
    /// Raw emoji value loaded from SOUL.md. Not user-editable; preserved
    /// verbatim on save so we don't rewrite a value the user (or another
    /// device) may have set in the file. UI always shows `displayEmoji`.
    @State private var rawEmoji: String = SoulMetadata.default.emoji
    @State private var style: String = SoulMetadata.default.style
    @State private var lang: String = SoulMetadata.default.lang
    @State private var bodyText: String = ""
    @State private var saveError: String? = nil
    @State private var didJustSave: Bool = false
    @State private var showRestoreConfirm: Bool = false
    @State private var showForceSyncDone: Bool = false
    @StateObject private var loadedRef = LoadedFileRef()
    /// Mirrors `SyncV2Bootstrap.isEnabled` so the Force iCloud Sync row
    /// shows / hides reactively when the user toggles iCloud sync in
    /// Settings. Same pattern as SkillDetailView (#440 / 3a4fe546).
    @AppStorage("cloudSync.v2.enabled") private var iCloudSyncEnabled: Bool = false

    private static var langOptions: [(label: String, value: String)] {
        [
            (String(localized: "Auto"), "auto"),
            (String(localized: "Chinese"), "zh"),
            (String(localized: "English"), "en"),
        ]
    }

    var body: some View {
        Form {
            Section {
                previewCard
            }

            Section(String(localized: "Identity")) {
                LabeledContent(String(localized: "Name")) {
                    TextField("Minis", text: $name)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.words)
                        .submitLabel(.done)
                }
                LabeledContent(String(localized: "Style")) {
                    TextField(String(localized: "e.g. Warm, direct, opinionated"), text: $style)
                        .multilineTextAlignment(.trailing)
                }
                Picker(String(localized: "Language"), selection: $lang) {
                    ForEach(Self.langOptions, id: \.value) { opt in
                        Text(opt.label).tag(opt.value)
                    }
                }
            }

            Section {
                personalityEditor
            } header: {
                Text(String(localized: "Personality Prompt"))
            } footer: {
                bodyLengthFooter
            }

            Section {
                Button(role: .destructive) {
                    showRestoreConfirm = true
                } label: {
                    Label(String(localized: "Restore Default"), systemImage: "arrow.uturn.backward")
                }

                // Force iCloud Sync — re-marks SOUL.md dirty and asks
                // SyncCore to send immediately. Same gating predicate
                // as SkillDetailView (47fd61ef / 3a4fe546): hidden
                // entirely when the user has iCloud sync off, since
                // the action would no-op on a disabled engine.
                if #available(iOS 17.0, *), iCloudSyncEnabled {
                    Button {
                        Task { await forceSyncSoul() }
                    } label: {
                        HStack {
                            Label(String(localized: "Force iCloud Sync"), systemImage: "icloud.and.arrow.up")
                            Spacer()
                            if showForceSyncDone {
                                Text(String(localized: "Queued"))
                                    .foregroundStyle(.green)
                                    .font(.caption)
                            }
                        }
                    }
                }
            }

            if let saveError {
                Section {
                    Text(saveError)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle(String(localized: "Soul"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(String(localized: "Save")) { save() }
                    .disabled(!isDirty || isBodyOverLimit)
            }
        }
        .onAppear(perform: reload)
        // Using .alert (not .confirmationDialog) so the dialog stays
        // centered on iPad / Mac. confirmationDialog without a source
        // rect renders as a popover anchored to the screen's top edge
        // on regular-width size classes.
        .alert(
            String(localized: "Restore Default"),
            isPresented: $showRestoreConfirm
        ) {
            Button(String(localized: "Restore Default"), role: .destructive, action: restoreDefault)
            Button(String(localized: "Cancel"), role: .cancel) {}
        } message: {
            Text(String(localized: "Restore default SOUL.md? Your current personality will be replaced."))
        }
        .overlay(alignment: .bottom) {
            if didJustSave {
                Text(String(localized: "Saved"))
                    .font(.footnote.weight(.medium))
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(Color.green.opacity(0.85), in: Capsule())
                    .foregroundStyle(.white)
                    .padding(.bottom, 24)
                    .transition(.opacity)
            }
        }
    }

    // MARK: - Subviews

    // Standard Form row — the insetGrouped section provides the rounded
    // card chrome automatically, so we only render content here. Matches
    // the visual width of every other section on the page.
    private var previewCard: some View {
        HStack(alignment: .center, spacing: 12) {
            // Header preview always shows the canonical sparkles glyph;
            // user-customized emoji was removed in T-soul-md follow-up.
            Text(SoulMetadata.default.displayEmoji)
                .font(.system(size: 32))
            VStack(alignment: .leading, spacing: 2) {
                Text(name.isEmpty ? "Minis" : name)
                    .font(.title3.weight(.semibold))
                if !style.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text(style)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
    }

    private var personalityEditor: some View {
        ZStack(alignment: .topLeading) {
            TextEditor(text: $bodyText)
                .frame(minHeight: 220)
                .font(.system(.body, design: .monospaced))
                .scrollContentBackground(.hidden)
            // SwiftUI's TextEditor has no native placeholder. We render
            // a greyed hint on top when the body is empty + not being
            // typed into. allowsHitTesting(false) so taps fall through
            // to the editor below.
            if bodyText.isEmpty {
                Text(String(localized: "Describe the personality and voice you want for your agent"))
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .padding(.top, 8)
                    .padding(.leading, 5)
                    .allowsHitTesting(false)
            }
        }
    }

    /// Footer under the personality editor. Renders a green count when the
    /// body is within budget and a red over-limit message when it isn't.
    /// Save is disabled in the over-limit branch.
    private var bodyLengthFooter: some View {
        let check = SoulStore.isOverLimit(bodyText)
        return HStack(spacing: 6) {
            if check.isOverLimit {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            }
            switch check {
            case .ok:
                Text(soulBodyCountText(bodyText))
                    .foregroundStyle(.secondary)
            case .overLimit(let count, let cap):
                Text(String(localized: "Over limit: \(count) / \(cap) tokens. Each CJK character and each Latin word counts as one."))
                    .foregroundStyle(.red)
            }
        }
        .font(.footnote)
    }

    /// Counter shown when the body is within budget.
    private func soulBodyCountText(_ body: String) -> String {
        let count = SoulStore.tokenCount(body)
        return String(localized: "\(count) / \(SoulStore.bodyTokenLimit) tokens")
    }

    private var isBodyOverLimit: Bool {
        SoulStore.isOverLimit(bodyText).isOverLimit
    }

    // MARK: - Persistence

    private var currentFile: SoulFile {
        SoulFile(
            metadata: SoulMetadata(
                name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                // Round-trip the on-disk emoji untouched — UI no longer
                // edits this field, but a SOUL.md authored elsewhere
                // (other device / hand-edit) should not have its emoji
                // rewritten on save.
                emoji: rawEmoji,
                style: style,
                lang: lang
            ),
            body: bodyText
        )
    }

    private var isDirty: Bool {
        currentFile != loadedRef.value
    }

    private func reload() {
        let file = SoulStore.load() ?? SoulFile(metadata: .default, body: "")
        name = file.metadata.name
        rawEmoji = file.metadata.emoji
        style = file.metadata.style
        lang = file.metadata.lang
        bodyText = file.body
        loadedRef.value = file
        saveError = nil
    }

    private func save() {
        do {
            let f = currentFile
            try SoulStore.save(f)
            loadedRef.value = f
            saveError = nil
            withAnimation { didJustSave = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                withAnimation { didJustSave = false }
            }
        } catch {
            saveError = "Save failed: \(error.localizedDescription)"
        }
    }

    /// Bidirectional Soul sync: push local SOUL.md up and pull the
    /// latest remote SoulV2 down. Mirrors `ProviderInstancesView`'s
    /// Force iCloud Sync entry (which uses the same `bidirectionalSync`
    /// helper). iOS-17 gated because the v2 sync surface is.
    @available(iOS 17.0, *)
    @MainActor
    private func forceSyncSoul() async {
        // 1. Re-mark local SOUL.md dirty (if present) so the upload
        //    side ships our copy.
        _ = await ForceSyncHelper.markSoulDirty()
        // 2. Run a full sendNow + fullFetchAndReconcile cycle so any
        //    peer-newer SoulV2 lands and the merger overwrites local
        //    via SoulStore.applyRemoteContent (LWW by mtime).
        await ForceSyncHelper.bidirectionalSync(recordTypes: ["SoulV2"])
        // 3. Re-read the on-disk file in case the merger just replaced
        //    it with a peer's newer copy — otherwise the form stays
        //    showing the pre-sync values.
        reload()
        showForceSyncDone = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { showForceSyncDone = false }
    }

    private func restoreDefault() {
        let parsed = SoulMDParser.parse(SoulStore.defaultContent)
        name = parsed.metadata.name
        rawEmoji = parsed.metadata.emoji
        style = parsed.metadata.style
        lang = parsed.metadata.lang
        bodyText = parsed.body
        save()
    }

    private final class LoadedFileRef: ObservableObject {
        var value: SoulFile = SoulFile(metadata: .default, body: "")
    }
}
