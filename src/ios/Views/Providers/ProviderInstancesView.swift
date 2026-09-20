import SwiftUI
import UniformTypeIdentifiers

/// Lists all configured provider instances grouped by provider type.
/// Replaces the old ProvidersView for the new multi-instance model.
struct ProviderInstancesView: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var showAddProvider = false
    @State private var showImportFile = false
    @State private var importMessage: String?
    @State private var showImportResult = false
    @State private var forceSyncToast: String?
    @AppStorage("cloudSync.v2.enabled") private var iCloudSyncEnabled: Bool = false

    var body: some View {
        List {
            // [T-mimo-shadow-voice] EVERY instance appears under its providerType
            // section now (no voice-only exclusion) — a mixed vendor like MiMo
            // shows its text models here AND a shadow voice row below ("dual
            // visibility"). Pure-voice vendors (ElevenLabs etc.) still appear here
            // too; they just have no usable text models, which is expected.
            ForEach(ProviderType.allCases, id: \.self) { type in
                let instancesOfType = store.instances.filter { $0.providerType == type }
                if !instancesOfType.isEmpty {
                    Section(type.displayName) {
                        ForEach(instancesOfType) { instance in
                            NavigationLink {
                                ProviderInstanceDetailView(instanceId: instance.id)
                            } label: {
                                InstanceRow(instance: instance)
                            }
                        }
                        .onMove { source, destination in
                            moveInstances(in: type, from: source, to: destination)
                        }
                    }
                }
            }
            // [T-mimo-shadow-voice] Voice Services = a read-only SHADOW view of any
            // instance that has audio-modality models, FOLDED by base URL so two
            // instances on the same host show one row (shares that instance's
            // credential/endpoint). Tapping opens the shadow detail (voice models
            // + a "disable this voice row" toggle).
            let shadows = store.shadowVoiceProviders()
            if !shadows.isEmpty {
                Section("Voice Services") {
                    if store.hasFoldedShadowDuplicates() {
                        // Non-destructive hint: same MiMo service configured twice.
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "info.circle")
                                .foregroundStyle(.secondary)
                            Text("A voice service is configured more than once. Voice is merged into a single row here; you can delete the extra provider above if you want.",
                                 comment: "Duplicate voice provider hint")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    ForEach(shadows) { shadow in
                        NavigationLink {
                            ShadowVoiceProviderDetailView(instanceId: shadow.instanceId)
                        } label: {
                            ShadowVoiceRow(shadow: shadow)
                        }
                    }
                }
            }

            if store.instances.isEmpty {
                Section {
                    VStack(spacing: 8) {
                        Image(systemName: "key.slash")
                            .font(.system(size: 32))
                            .foregroundStyle(.quaternary)
                        Text("No providers configured")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Text("Add a provider to get started.")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 20)
                }
            }
        }
        .navigationTitle("Providers")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if !store.instances.isEmpty {
                ToolbarItem(placement: .topBarLeading) {
                    EditButton()
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button {
                        showAddProvider = true
                    } label: {
                        Label(String(localized: "Add Provider"), systemImage: "plus")
                    }
                    Button {
                        showImportFile = true
                    } label: {
                        Label(String(localized: "Import Provider"), systemImage: "square.and.arrow.down")
                    }
                    if #available(iOS 17.0, *), iCloudSyncEnabled {
                        Divider()
                        Button {
                            Task { await forceSyncProviders() }
                        } label: {
                            Label(String(localized: "Force iCloud Sync"),
                                  systemImage: "arrow.triangle.2.circlepath.icloud")
                        }
                    }
                } label: {
                    Image(systemName: "plus")
                }
            }
        }
        .sheet(isPresented: $showAddProvider) {
            NavigationStack {
                AddProviderView()
            }
        }
        .fileImporter(isPresented: $showImportFile, allowedContentTypes: [.json]) { result in
            switch result {
            case .success(let url):
                guard url.startAccessingSecurityScopedResource() else {
                    importMessage = String(localized: "Cannot access the selected file.")
                    showImportResult = true
                    return
                }
                defer { url.stopAccessingSecurityScopedResource() }
                guard let data = try? Data(contentsOf: url),
                      let json = String(data: data, encoding: .utf8) else {
                    importMessage = String(localized: "Failed to read file.")
                    showImportResult = true
                    return
                }
                if let label = store.importInstanceJSON(json) {
                    importMessage = String(localized: "Imported provider \"\(label)\" successfully.")
                } else {
                    importMessage = String(localized: "Invalid provider configuration file.")
                }
                showImportResult = true
            case .failure:
                break
            }
        }
        .alert(String(localized: "Import"), isPresented: $showImportResult) {
            Button("OK") {}
        } message: {
            if let msg = importMessage { Text(msg) }
        }
        .overlay(alignment: .top) {
            if let msg = forceSyncToast {
                Text(msg)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(Color.accentColor, in: Capsule())
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.3), value: forceSyncToast)
    }

    @available(iOS 17.0, *)
    private func forceSyncProviders() async {
        _ = await ForceSyncHelper.markProvidersDirty()
        await ForceSyncHelper.bidirectionalSync(recordTypes: ["ProviderConfig", "ProviderConfigV2"])
        forceSyncToast = String(localized: "Syncing providers via iCloud")
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            forceSyncToast = nil
        }
    }

    // Section .onMove hands us section-relative indices. Map them back onto the
    // global store.instances order so the new order persists to disk and flows
    // through to SessionModelPicker.
    private func moveInstances(in type: ProviderType, from source: IndexSet, to destination: Int) {
        let all = store.instances
        // [T-ios-provider-reorder] The section's ForEach renders llmInstances
        // (voice-only providers filtered OUT into their own section), so the
        // section-relative indices from onMove address THAT list. The filter
        // here must match exactly — including voice-only instances of the same
        // providerType shifted every index and made drops land on the wrong
        // element (item jumps elsewhere / bounces back).
        // [T-mimo-shadow-voice] All instances of this type are section members
        // now (voice-only exclusion removed) — the section renders the full list.
        let isSectionMember: (ProviderInstance) -> Bool = {
            $0.providerType == type
        }
        let sectionIds = all.filter(isSectionMember).map(\.id)
        var reorderedSectionIds = sectionIds
        reorderedSectionIds.move(fromOffsets: source, toOffset: destination)

        // Rebuild global order: walk `all`, and whenever we hit a member of
        // this section, emit the next id from the reordered section list.
        var sectionIter = reorderedSectionIds.makeIterator()
        let newGlobalIds: [String] = all.map { inst in
            isSectionMember(inst) ? (sectionIter.next() ?? inst.id) : inst.id
        }
        store.reorderInstances(newGlobalIds)
    }
}

// MARK: - Instance Row

private struct InstanceRow: View {
    let instance: ProviderInstance
    @ObservedObject private var store = ProviderConfigStore.shared

    private var isConfigured: Bool {
        switch instance.credentialType {
        case .apiKey:
            return ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) != nil
        case .oauth:
            return oauthIsAuthenticated
        }
    }

    private var oauthIsAuthenticated: Bool {
        // Manual OAuth token is always considered authenticated
        if ProviderKeychainHelper.loadOAuthString(instanceId: instance.id, account: "manual-oauth-token") != nil {
            return true
        }
        switch instance.providerType {
        case .anthropic: return ClaudeOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .gemini: return GeminiOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .openAI: return CodexOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .antigravity: return AntigravityOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .openRouter: return OpenRouterOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .openAIResponses: return false // API key only
        case .xAI: return XAIOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .kimiCode: return KimiOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .unsupported: return false // synced from newer build
        }
    }

    private var credentialSummary: String {
        switch instance.credentialType {
        case .apiKey:
            if let key = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) {
                return maskKey(key)
            }
            return String(localized: "No API key")
        case .oauth:
            return oauthIsAuthenticated ? String(localized: "Authenticated") : String(localized: "Not authenticated")
        }
    }

    private var modelCount: Int {
        store.visibleEntries(for: instance.id).count
    }

    var body: some View {
        let _ = store.authRevision  // subscribe to OAuth state changes
        HStack(spacing: 12) {
            Circle()
                .fill(isConfigured && instance.isEnabled ? Color.green : Color(UIColor.quaternaryLabel))
                .frame(width: 8, height: 8)

            VStack(alignment: .leading, spacing: 2) {
                Text(instance.label)
                    .font(.body.weight(.medium))
                HStack(spacing: 6) {
                    Text(instance.credentialType == .apiKey ? "API Key" : "OAuth")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("·")
                        .font(.caption)
                        .foregroundStyle(.quaternary)
                    Text(credentialSummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if modelCount > 0 {
                    Text(String(localized: "\(modelCount) models"))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            Spacer()

            if !instance.isEnabled {
                Text("Disabled")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color(UIColor.quaternarySystemFill))
                    .clipShape(Capsule())
            }
        }
        .padding(.vertical, 2)
    }

    private func maskKey(_ key: String) -> String {
        guard key.count > 8 else { return "****" }
        return String(key.prefix(6)) + "..." + String(key.suffix(4))
    }
}

// MARK: - Shadow Voice Row [T-mimo-shadow-voice]

/// A Voice Services row backed by another instance's audio-modality models.
private struct ShadowVoiceRow: View {
    let shadow: ProviderConfigStore.ShadowVoiceProvider

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "waveform")
                .foregroundStyle(.secondary)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(shadow.displayName)
                    .font(.body)
                let asr = shadow.inputModels.count
                let tts = shadow.outputModels.count
                Text(voiceSummary(asr: asr, tts: tts))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
        }
        .padding(.vertical, 2)
    }

    private func voiceSummary(asr: Int, tts: Int) -> String {
        var parts: [String] = []
        if asr > 0 { parts.append(String(localized: "\(asr) speech-to-text", comment: "ASR model count")) }
        if tts > 0 { parts.append(String(localized: "\(tts) text-to-speech", comment: "TTS model count")) }
        return parts.joined(separator: " · ")
    }
}
