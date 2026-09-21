import SwiftUI

/// Detail view for a single ProviderInstance.
/// Allows editing label, managing credential, viewing/hiding models, and deleting.
struct ProviderInstanceDetailView: View {
    let instanceId: String
    @ObservedObject private var store = ProviderConfigStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var editingLabel = ""
    @State private var showKimiLogin = false
    @State private var keyInputText = ""
    @State private var isFetchingModels = false
    @State private var fetchError: String?
    @State private var fetchWarnings: [String] = []
    @State private var fetchSource: String?
    @State private var showDeleteConfirm = false
    @State private var showExportShare = false
    @State private var showAddCustomModel = false
    @State private var oauthRefreshTrigger = false
    @State private var editingCustomBaseURL = ""
    @State private var editingCustomUserAgent = ""
    @State private var showManualTokenInput = false
    @State private var manualTokenInputText = ""
    @State private var editingModelEntry: ModelEntry?
    @State private var pendingDeleteModelEntry: ModelEntry?
    @State private var showKeyRevealed = false

    private var instance: ProviderInstance? {
        store.instance(for: instanceId)
    }

    var body: some View {
        Group {
            if let instance = instance {
                instanceContent(instance)
            } else {
                Text("Instance not found")
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle(instance?.label ?? "Provider")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    showExportShare = true
                } label: {
                    Image(systemName: "square.and.arrow.up")
                }
            }
        }
        .sheet(isPresented: $showAddCustomModel) {
            if let instance = instance {
                AddCustomModelSheet(instanceId: instance.id)
            }
        }
        .sheet(item: $editingModelEntry) { entry in
            ModelEntryDetailSheet(entry: entry)
        }
        .sheet(isPresented: $showKimiLogin) {
            if let instance = instance {
                KimiDeviceLoginSheet(instanceId: instance.id) { _ in
                    oauthRefreshTrigger.toggle()
                }
            }
        }
        .sheet(isPresented: $showManualTokenInput) {
            NavigationStack {
                Form {
                    Section {
                        SecureField("Bearer token", text: $manualTokenInputText)
                            .font(.system(.body, design: .monospaced))
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    } footer: {
                        Text("Paste the bearer token. Whitespace and newlines will be stripped automatically.")
                    }
                }
                .navigationTitle("Manual Bearer Token")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("Cancel") {
                            showManualTokenInput = false
                            manualTokenInputText = ""
                        }
                    }
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Save") {
                            let cleaned = manualTokenInputText.components(separatedBy: .whitespacesAndNewlines).joined()
                            ProviderKeychainHelper.saveOAuthString(cleaned, instanceId: instanceId, account: "manual-oauth-token")
                            manualTokenInputText = ""
                            showManualTokenInput = false
                            oauthRefreshTrigger.toggle()
                        }
                        .disabled(manualTokenInputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
            }
            .presentationDetents([.medium])
        }
        .alert("Delete Provider", isPresented: $showDeleteConfirm) {
            Button("Delete", role: .destructive) {
                store.removeInstance(instanceId)
                dismiss()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will remove the provider and all its model entries. API keys will be deleted from the Keychain.")
        }
        .alert(
            String(localized: "Delete Model"),
            isPresented: Binding(
                get: { pendingDeleteModelEntry != nil },
                set: { if !$0 { pendingDeleteModelEntry = nil } }
            ),
            presenting: pendingDeleteModelEntry
        ) { entry in
            Button("Delete", role: .destructive) {
                store.removeEntry(entry.id)
                pendingDeleteModelEntry = nil
            }
            Button("Cancel", role: .cancel) {
                pendingDeleteModelEntry = nil
            }
        } message: { entry in
            Text("Are you sure you want to delete \"\(entry.model.displayName)\"? This action cannot be undone.")
        }
    }

    @ViewBuilder
    private func instanceContent(_ instance: ProviderInstance) -> some View {
        List {
            // MARK: Label
            Section("Label") {
                TextField("Label", text: $editingLabel)
                    .textContentType(.none)
                    .onAppear { editingLabel = instance.label }
                    .onSubmit { saveLabel(instance) }
                    .onChange(of: editingLabel) { _ in saveLabel(instance) }
            }

            // MARK: Credential
            Section {
                credentialSection(instance)
            } header: {
                Text("Credential")
            } footer: {
                Text(instance.credentialType == .apiKey
                     ? "API key is stored securely in the iOS Keychain."
                     : "OAuth tokens are stored per-instance in the iOS Keychain.")
            }

            // MARK: Custom Base URL
            customBaseURLSection(instance)

            // [T-mimo-shadow-voice] These LLM-config fields are gated by their own
            // providerType/capability checks (supportsCustomUserAgent, API-format
            // = OpenAI, supportsAzureMode, supportsImageEndpointSetting), so they
            // already show only where relevant. The old `!isVoiceOnlyProvider`
            // wrapper is removed: an instance is no longer classified voice-only,
            // and a mixed vendor (MiMo) is a normal OpenAI-compat provider that
            // should expose these settings.

            // MARK: Custom User-Agent (custom-base OpenAI/Anthropic-compat only)
            if instance.supportsCustomUserAgent {
                customUserAgentSection(instance)
            }

            // MARK: API Format (OpenAI only)
            if (instance.providerType == .openAI || instance.providerType == .openAIResponses)
                && instance.credentialType == .apiKey {
                Section {
                    Picker("API Format", selection: Binding(
                        get: { instance.providerType == .openAIResponses },
                        set: { useResponses in
                            // Swap between .openAI and .openAIResponses
                            // This requires recreating the instance since providerType is let.
                            // Carry ALL other fields forward — otherwise switching the
                            // format would silently reset imageEndpointMode / customUserAgent
                            // / azureMode to their defaults. [T-ios-azure-openai]
                            let newInstance = ProviderInstance(
                                id: instance.id,
                                label: instance.label,
                                providerType: useResponses ? .openAIResponses : .openAI,
                                credentialType: instance.credentialType,
                                isEnabled: instance.isEnabled,
                                createdAt: instance.createdAt,
                                customBaseURL: instance.customBaseURL,
                                appendV1Suffix: instance.appendV1Suffix,
                                imageEndpointMode: instance.imageEndpointMode,
                                imageEndpointResolved: instance.imageEndpointResolved,
                                customUserAgent: instance.customUserAgent,
                                azureMode: instance.azureMode
                            )
                            store.updateInstance(newInstance)
                        }
                    )) {
                        Text("Chat Completions").tag(false)
                        Text("Responses API").tag(true)
                    }
                } footer: {
                    Text(instance.providerType == .openAIResponses
                        ? "Uses /v1/responses endpoint format."
                        : "Standard /v1/chat/completions format.")
                }
            }

            // MARK: Azure OpenAI [T-ios-azure-openai]
            if instance.supportsAzureMode {
                azureModeSection(instance)
            }

            // MARK: Image Generation Endpoint (OpenAI-compatible providers)
            // Lets the user override the auto-probe choice between
            // /v1/images/generations and /v1/chat/completions for image output.
            if instance.supportsImageEndpointSetting {
                imageEndpointSection(instance)
            }

            // MARK: Manual OAuth Token (for OAuth instances with manual token)
            if instance.credentialType == .oauth && instance.providerType != .antigravity {
                manualOAuthTokenSection(instance)
            }

            // MARK: Status
            Section("Status") {
                Toggle("Enabled", isOn: Binding(
                    get: { instance.isEnabled },
                    set: { newValue in
                        let hasApiKey = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) != nil
                        let hasOAuth = ProviderKeychainHelper.loadOAuthString(instanceId: instance.id, account: "manual-oauth-token") != nil
                            || (instance.providerType == .anthropic && ClaudeOAuthManager.shared.isAuthenticated(instanceId: instance.id))
                        AppLogger(category: "Provider").info("toggleEnabled instanceId=\(instance.id.prefix(8)) type=\(instance.providerType.rawValue) old=\(instance.isEnabled) new=\(newValue) hasApiKey=\(hasApiKey) hasOAuth=\(hasOAuth)")
                        var updated = instance
                        updated.isEnabled = newValue
                        store.updateInstance(updated)
                    }
                ))
            }

            // MARK: Models
            Section {
                modelListSection(instance)
            } header: {
                HStack {
                    Text("Models")
                    Spacer()
                    // [T-mimo-shadow-voice] Refresh always available now — the
                    // fetch never wipes voice seed entries (replaceEntries
                    // preserves them), so even a vendor whose /v1/models omits its
                    // voice models can safely refresh to pull its text models.
                    do {
                        Button {
                            refreshModels(instance)
                        } label: {
                            if isFetchingModels {
                                ProgressView()
                                    .controlSize(.small)
                            } else {
                                HStack(spacing: 4) {
                                    Image(systemName: "arrow.clockwise")
                                    Text("Refresh")
                                }
                                .font(.caption)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 3)
                                .background(Color.secondary.opacity(0.15), in: Capsule())
                            }
                        }
                        .disabled(isFetchingModels)
                    }
                }
            } footer: {
                VStack(alignment: .leading, spacing: 4) {
                    // Source info (green)
                    if let source = fetchSource {
                        Label("Loaded from \(source)", systemImage: "checkmark.circle")
                            .font(.caption)
                            .foregroundStyle(.green)
                    }
                    // Warnings (yellow) — diagnostic tips for each fallback step
                    ForEach(fetchWarnings, id: \.self) { warning in
                        Label(warning, systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                            .textSelection(.enabled)
                    }
                    // Error (red)
                    if let error = fetchError {
                        let lines = error.components(separatedBy: .newlines)
                        let truncated = lines.prefix(4).joined(separator: "\n")
                            + (lines.count > 4 ? "\n…" : "")
                        Text(truncated)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .textSelection(.enabled)
                        Text(String(localized: "You may need to add the model ID manually."))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            // MARK: Custom Model
            Section {
                Button("Add Custom Model") {
                    showAddCustomModel = true
                }
            }

            // MARK: Voice Service (shadow)
            if store.hasVoiceModels(for: instance.id) {
                Section {
                    NavigationLink {
                        ShadowVoiceProviderDetailView(instanceId: instance.id)
                    } label: {
                        HStack {
                            Label("Voice Service", systemImage: "waveform")
                            Spacer()
                            if store.isVoiceShadowDisabled(instance.id) {
                                Text("Hidden", comment: "Voice shadow disabled badge")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                } footer: {
                    Text("Manage ASR/TTS models and Voice Services visibility.",
                         comment: "Voice service section footer")
                }
            }

            // MARK: Danger Zone
            Section {
                Button("Delete Provider", role: .destructive) {
                    showDeleteConfirm = true
                }
            }
        }
        .sheet(isPresented: $showExportShare) {
            if let json = store.exportInstanceJSON(instanceId) {
                let label = store.instance(for: instanceId).map(\.label) ?? "provider"
                let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent("\(label).json")
                let _ = try? json.write(to: tempURL, atomically: true, encoding: .utf8)
                ProviderShareSheet(url: tempURL)
                    .presentationDetents([.medium])
            } else {
                Text("Failed to export provider configuration.")
                    .foregroundStyle(.secondary)
                    .presentationDetents([.medium])
            }
        }
    }

    // MARK: - Credential Section

    @ViewBuilder
    private func credentialSection(_ instance: ProviderInstance) -> some View {
        switch instance.credentialType {
        case .apiKey:
            apiKeyCredentialView(instance)
        case .oauth:
            oauthCredentialView(instance)
        }
    }

    @ViewBuilder
    private func apiKeyCredentialView(_ instance: ProviderInstance) -> some View {
        let rawKey = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)

        HStack {
            // Always use TextField to keep the normal keyboard (SecureField
            // switches to a password keyboard that blocks some characters).
            // When hidden, overlay bullet characters to mask the value.
            ZStack(alignment: .leading) {
                TextField(keyPlaceholder(instance.providerType), text: $keyInputText)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .opacity(showKeyRevealed ? 1 : 0)

                if !showKeyRevealed {
                    // Show bullet mask over the invisible text field
                    Text(keyInputText.isEmpty ? "" : String(repeating: "•", count: keyInputText.count))
                        .foregroundStyle(.primary)
                        .allowsHitTesting(false)
                }
            }
            .font(.system(.body, design: .monospaced))
            .onAppear {
                AppLogger(category: "Provider").info("apiKeyTextField onAppear instanceId=\(instance.id.prefix(8)) rawKeyHit=\(rawKey != nil) rawKeyLen=\(rawKey?.count ?? 0) prevTextLen=\(keyInputText.count)")
                keyInputText = rawKey ?? ""
            }
            .onChange(of: keyInputText) { newValue in
                let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.isEmpty {
                    AppLogger(category: "Provider").warning("apiKeyTextField onChange→DELETE instanceId=\(instance.id.prefix(8)) prevRawKeyHit=\(rawKey != nil) prevRawKeyLen=\(rawKey?.count ?? 0) newLen=\(newValue.count)")
                    ProviderKeychainHelper.deleteAPIKey(instanceId: instance.id)
                } else {
                    AppLogger(category: "Provider").info("apiKeyTextField onChange→SAVE instanceId=\(instance.id.prefix(8)) newLen=\(trimmed.count)")
                    ProviderKeychainHelper.saveAPIKey(trimmed, instanceId: instance.id)
                }
            }

            Button {
                showKeyRevealed.toggle()
            } label: {
                Image(systemName: showKeyRevealed ? "eye.slash" : "eye")
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
        }
        .contextMenu {
            if let key = rawKey {
                Button {
                    UIPasteboard.general.string = key
                } label: {
                    Label("Copy API Key", systemImage: "doc.on.doc")
                }
            }
        }
    }

    @ViewBuilder
    private func oauthCredentialView(_ instance: ProviderInstance) -> some View {
        let isAuth = oauthIsAuthenticated(instance)
        let detail = oauthDetail(instance)
        // Subscribe to auth state changes (Keychain token save/delete)
        let _ = oauthRefreshTrigger
        let _ = store.authRevision

        VStack(alignment: .leading, spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("OAuth")
                        .font(.body)
                    Text(detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if isAuth {
                    Circle()
                        .fill(Color.green)
                        .frame(width: 8, height: 8)
                }
            }

            HStack(spacing: 12) {
                if isAuth {
                    Button(String(localized: "Copy Token")) {
                        Task { await oauthCopyToken(instance) }
                    }
                    .font(.caption.weight(.medium))
                    Button(String(localized: "Sign Out"), role: .destructive) {
                        oauthLogout(instance)
                        oauthRefreshTrigger.toggle()
                    }
                    .font(.caption.weight(.medium))
                } else {
                    Button(oauthSignInLabel(instance)) {
                        // Kimi uses the RFC 8628 device-code sheet; others run inline.
                        if instance.providerType == .kimiCode {
                            showKimiLogin = true
                        } else {
                            Task {
                                await oauthLogin(instance)
                                await MainActor.run {
                                    oauthRefreshTrigger.toggle()
                                }
                            }
                        }
                    }
                    .font(.caption.weight(.medium))
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
        .id(oauthRefreshTrigger)
    }

    // MARK: - Custom Base URL

    private func customBaseURLPlaceholder(_ instance: ProviderInstance) -> String {
        switch instance.providerType {
        case .anthropic: return "https://api.anthropic.com/v1"
        case .openAI:    return "https://api.openai.com/v1"
        case .gemini:    return "https://generativelanguage.googleapis.com/v1beta"
        case .antigravity: return String(localized: "Default")
        case .openRouter: return "https://openrouter.ai/api/v1"
        case .openAIResponses: return "https://api.openai.com/v1"
        case .xAI: return "https://api.x.ai/v1"
        case .kimiCode: return "https://api.kimi.com/coding"
        case .unsupported: return "—"
        }
    }

    @ViewBuilder
    private func customBaseURLSection(_ instance: ProviderInstance) -> some View {
        Section {
            TextField(customBaseURLPlaceholder(instance), text: $editingCustomBaseURL)
                .font(.system(.body, design: .monospaced))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .onAppear { editingCustomBaseURL = instance.customBaseURL ?? "" }
                .onSubmit { saveCustomBaseURL(instance) }
                .onDisappear { saveCustomBaseURL(instance) }

            // [T-mimo-shadow-voice] /v1 toggle always shown — instances are no
            // longer classified voice-only; this is a normal endpoint setting.
            Toggle("Auto Append \"/v1\"", isOn: Binding(
                get: { instance.appendV1Suffix },
                set: { newValue in
                    var updated = instance
                    updated.appendV1Suffix = newValue
                    store.updateInstance(updated)
                }
            ))
        } header: {
            Text("Custom API Base")
        } footer: {
            Text(instance.appendV1Suffix
                 ? "Leave empty to use the default endpoint. \"/v1\" is appended automatically — enter the base host only."
                 : "The URL is used verbatim. Include the full path up to (but not including) the endpoint, e.g. \"/chat/completions\".")
        }
    }

    // MARK: - Custom User-Agent

    @ViewBuilder
    // [T-ios-azure-openai] Azure OpenAI toggle. Orthogonal to the API Format
    // (Chat / Responses) picker above — Azure changes only the auth header
    // (api-key:) and URL style (the user pastes the full Azure endpoint, incl.
    // ?api-version, into Custom API Base). Off by default.
    private func azureModeSection(_ instance: ProviderInstance) -> some View {
        Section {
            Toggle(String(localized: "Azure OpenAI"), isOn: Binding(
                get: { instance.azureMode },
                set: { on in
                    var updated = instance
                    updated.azureMode = on
                    store.updateInstance(updated)
                }
            ))
        } footer: {
            Text(String(localized: "Use Azure OpenAI authentication (api-key header). Paste your full Azure endpoint into Custom API Base above, including the ?api-version=… query. Works with both API formats."))
        }
    }

    private func customUserAgentSection(_ instance: ProviderInstance) -> some View {
        Section {
            TextField(String(localized: "Default"), text: $editingCustomUserAgent)
                .font(.system(.body, design: .monospaced))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onAppear { editingCustomUserAgent = instance.customUserAgent ?? "" }
                .onSubmit { saveCustomUserAgent(instance) }
                .onDisappear { saveCustomUserAgent(instance) }
        } header: {
            Text(String(localized: "Custom User-Agent"))
        } footer: {
            Text(String(localized: "Override the User-Agent header sent to this endpoint. Leave empty to use the Minis default. Useful for relays that only accept specific clients (e.g. \"claude-cli/1.0\")."))
        }
    }

    private func saveCustomUserAgent(_ instance: ProviderInstance) {
        let current = instance.customUserAgent ?? ""
        let trimmed = editingCustomUserAgent.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed != current else { return }
        var updated = instance
        updated.customUserAgent = trimmed.isEmpty ? nil : trimmed
        store.updateInstance(updated)
    }

    // MARK: - Image Generation Endpoint

    @ViewBuilder
    private func imageEndpointSection(_ instance: ProviderInstance) -> some View {
        Section {
            Picker(selection: Binding(
                get: { instance.imageEndpointMode },
                set: { newMode in
                    var updated = instance
                    updated.imageEndpointMode = newMode
                    // User-forced mode supersedes any cached probe result.
                    if newMode != .auto {
                        updated.imageEndpointResolved = nil
                    }
                    store.updateInstance(updated)
                }
            )) {
                Text("Auto").tag(ImageEndpointMode.auto)
                Text("Images Generations").tag(ImageEndpointMode.imagesGenerations)
                Text("Chat Completions").tag(ImageEndpointMode.chatCompletions)
            } label: {
                Text(String(localized: "Image Endpoint"))
            }
        } header: {
            Text(String(localized: "Image Generation"))
        } footer: {
            imageEndpointFooter(instance)
        }
    }

    @ViewBuilder
    private func imageEndpointFooter(_ instance: ProviderInstance) -> some View {
        switch instance.imageEndpointMode {
        case .auto:
            if let resolved = instance.imageEndpointResolved {
                let resolvedLabel = resolved == .imagesGenerations
                    ? "/v1/images/generations"
                    : "/v1/chat/completions"
                Text(String(localized: "Auto: tries /v1/images/generations first, falls back to /v1/chat/completions. Last successful endpoint: \(resolvedLabel)."))
            } else {
                Text(String(localized: "Auto: tries /v1/images/generations first, falls back to /v1/chat/completions. Caches the working endpoint after the first call."))
            }
        case .imagesGenerations:
            Text(String(localized: "Always use /v1/images/generations."))
        case .chatCompletions:
            Text(String(localized: "Always use /v1/chat/completions (multimodal output)."))
        }
    }

    // MARK: - Manual OAuth Token

    @ViewBuilder
    private func manualOAuthTokenSection(_ instance: ProviderInstance) -> some View {
        let hasManualToken = ProviderKeychainHelper.loadOAuthString(instanceId: instance.id, account: "manual-oauth-token") != nil

        Section {
            if hasManualToken {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Manual Bearer Token")
                            .font(.body)
                        Text("Configured")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Circle()
                        .fill(Color.green)
                        .frame(width: 8, height: 8)
                }

                HStack(spacing: 12) {
                    Button("Change Token") {
                        manualTokenInputText = ""
                        showManualTokenInput = true
                    }
                    .font(.caption.weight(.medium))

                    Button("Remove", role: .destructive) {
                        ProviderKeychainHelper.deleteOAuthString(instanceId: instance.id, account: "manual-oauth-token")
                        oauthRefreshTrigger.toggle()
                    }
                    .font(.caption.weight(.medium))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            } else {
                Button("Set Manual Bearer Token") {
                    manualTokenInputText = ""
                    showManualTokenInput = true
                }
                .font(.caption.weight(.medium))
            }
        } header: {
            Text("Manual Token")
        } footer: {
            Text("Use a static bearer token instead of the OAuth sign-in flow. Useful with custom proxy endpoints.")
        }
    }

    // MARK: - Model List

    @ViewBuilder
    private func modelListSection(_ instance: ProviderInstance) -> some View {
        let entries = store.entries(for: instance.id)

        if entries.isEmpty {
            VStack(spacing: 8) {
                Text("No models")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Button {
                    showAddCustomModel = true
                } label: {
                    Label("Add Custom Model", systemImage: "plus.circle")
                        .font(.subheadline)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
        }

        ForEach(entries) { entry in
            modelEntryRow(entry, isHidden: entry.isHidden)
        }
    }

    private func modelEntryRow(_ entry: ModelEntry, isHidden: Bool) -> some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(entry.model.displayName)
                        .font(.subheadline)
                        .foregroundStyle(isHidden ? .secondary : .primary)
                    modalityIcons(for: entry.model)
                }
                HStack(spacing: 4) {
                    Text(entry.model.id)
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                    if entry.isCustom {
                        Text("Custom")
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(.orange)
                    }
                }
            }
            Spacer()
            Button {
                var updated = entry
                updated.isHidden = !entry.isHidden
                store.updateEntry(updated)
            } label: {
                Image(systemName: entry.isHidden ? "eye.slash" : "eye")
                    .font(.caption)
                    .foregroundStyle(entry.isHidden ? .tertiary : .secondary)
            }
            .buttonStyle(.plain)
            .frame(minWidth: 22, minHeight: 22)

            Button {
                pendingDeleteModelEntry = entry
            } label: {
                Image(systemName: "trash")
                    .font(.caption)
                    .foregroundStyle(.red)
            }
            .buttonStyle(.plain)
            .frame(minWidth: 22, minHeight: 22)

            Image(systemName: "chevron.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
        .onTapGesture {
            editingModelEntry = entry
        }
        .contextMenu {
            Button {
                UIPasteboard.general.string = "entry:\(entry.compositeKey)"
                MinisToast.show(String(localized: "Copied: \(entry.model.displayName)"))
            } label: {
                Label(String(localized: "Copy Shortcut Model ID"), systemImage: "link")
            }
        }
    }

    private func modalityIcons(for model: LLMModel) -> some View {
        let modality = model.modalityOverride ?? model.capabilities.supportedModalities
        // [T-ios-model-capability-output-tags] (XIN msg 38847) The list only
        // rendered INPUT modalities (image/pdf/audio/video _input) — output
        // modalities were never iterated, so a generator like gpt-image-2
        // (image_output) or an audio_output model showed no capability badge.
        // Render both directions. Output badges use a "generate"-style glyph
        // (arrow.up.* / *.badge.plus) + tint so they read distinctly from the
        // muted input badges. Accessibility labels are localized.
        return HStack(spacing: 3) {
            // Input modalities (muted/secondary).
            if modality.contains(.imageInput) {
                Image(systemName: "photo")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel(String(localized: "Image input"))
            }
            if modality.contains(.pdfInput) {
                Image(systemName: "doc")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel(String(localized: "PDF input"))
            }
            if modality.contains(.audioInput) {
                Image(systemName: "waveform")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel(String(localized: "Audio input"))
            }
            if modality.contains(.videoInput) {
                Image(systemName: "video")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel(String(localized: "Video input"))
            }
            // Output modalities (tinted, generate-style glyphs).
            if modality.contains(.imageOutput) {
                Image(systemName: "photo.badge.plus")
                    .font(.caption2)
                    .foregroundStyle(.tint)
                    .accessibilityLabel(String(localized: "Image output"))
            }
            if modality.contains(.audioOutput) {
                Image(systemName: "speaker.wave.2")
                    .font(.caption2)
                    .foregroundStyle(.tint)
                    .accessibilityLabel(String(localized: "Audio output"))
            }
            if modality.contains(.videoOutput) {
                Image(systemName: "video.badge.plus")
                    .font(.caption2)
                    .foregroundStyle(.tint)
                    .accessibilityLabel(String(localized: "Video output"))
            }
        }
    }

    // MARK: - Actions

    private func refreshModels(_ instance: ProviderInstance) {
        // Save any pending edits (e.g. custom base URL) before refreshing
        saveCustomBaseURL(instance)
        // Re-read from store so we use the just-saved values
        guard let freshInstance = store.instance(for: instance.id) else { return }
        isFetchingModels = true
        fetchError = nil
        fetchWarnings = []
        fetchSource = nil
        Task {
            defer { isFetchingModels = false }
            do {
                let result = try await ProviderConfigStore.fetchModelsWithFallback(freshInstance, forceRefresh: true)
                store.replaceEntries(for: freshInstance.id, models: result.models)
                fetchWarnings = result.warnings
                fetchSource = result.source
            } catch {
                fetchError = error.localizedDescription
            }
        }
    }


    // MARK: - OAuth Helpers

    private func oauthIsAuthenticated(_ instance: ProviderInstance) -> Bool {
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

    private func oauthDetail(_ instance: ProviderInstance) -> String {
        // Manual OAuth token — show masked token
        if ProviderKeychainHelper.loadOAuthString(instanceId: instance.id, account: "manual-oauth-token") != nil {
            return String(localized: "Authenticated (manual token)")
        }
        switch instance.providerType {
        case .anthropic:
            if ClaudeOAuthManager.shared.isAuthenticated(instanceId: instance.id) {
                return ClaudeOAuthManager.shared.maskedToken(instanceId: instance.id) ?? String(localized: "Authenticated")
            }
            return String(localized: "Not authenticated")
        case .gemini:
            if GeminiOAuthManager.shared.isAuthenticated(instanceId: instance.id) {
                let parts = [
                    GeminiOAuthManager.shared.userEmail(instanceId: instance.id),
                    GeminiOAuthManager.shared.gcpProjectID(instanceId: instance.id)
                ].compactMap { $0 }
                return parts.isEmpty ? String(localized: "Authenticated") : parts.joined(separator: " · ")
            }
            return String(localized: "Not authenticated")
        case .openAI:
            if CodexOAuthManager.shared.isAuthenticated(instanceId: instance.id) {
                let parts = [
                    CodexOAuthManager.shared.planType(instanceId: instance.id),
                    CodexOAuthManager.shared.accountId(instanceId: instance.id).map { "ID: \(String($0.prefix(8)))..." }
                ].compactMap { $0 }
                return parts.isEmpty ? String(localized: "Authenticated") : parts.joined(separator: " · ")
            }
            return String(localized: "Not authenticated")
        case .antigravity:
            if AntigravityOAuthManager.shared.isAuthenticated(instanceId: instance.id) {
                let parts = [
                    AntigravityOAuthManager.shared.userEmail(instanceId: instance.id),
                    AntigravityOAuthManager.shared.projectID(instanceId: instance.id)
                ].compactMap { $0 }
                return parts.isEmpty ? String(localized: "Authenticated") : parts.joined(separator: " · ")
            }
            return String(localized: "Not authenticated")
        case .openRouter:
            if OpenRouterOAuthManager.shared.isAuthenticated(instanceId: instance.id) {
                return OpenRouterOAuthManager.shared.maskedToken(instanceId: instance.id) ?? String(localized: "Authenticated")
            }
            return String(localized: "Not authenticated")
        case .openAIResponses:
            return String(localized: "Not applicable") // API key only
        case .xAI:
            if XAIOAuthManager.shared.isAuthenticated(instanceId: instance.id) {
                let parts = [
                    XAIOAuthManager.shared.email(instanceId: instance.id),
                    XAIOAuthManager.shared.accountId(instanceId: instance.id).map { "ID: \(String($0.prefix(8)))..." }
                ].compactMap { $0 }
                return parts.isEmpty ? String(localized: "Authenticated") : parts.joined(separator: " · ")
            }
            return String(localized: "Not authenticated")
        case .kimiCode:
            return KimiOAuthManager.shared.isAuthenticated(instanceId: instance.id)
                ? String(localized: "Authenticated") : String(localized: "Not authenticated")
        case .unsupported:
            return String(localized: "Unsupported in this app version")
        }
    }

    private func oauthSignInLabel(_ instance: ProviderInstance) -> String {
        switch instance.providerType {
        case .anthropic: return String(localized: "Sign in with Claude")
        case .gemini: return String(localized: "Sign in with Google")
        case .openAI: return String(localized: "Sign in with OpenAI")
        case .antigravity: return String(localized: "Sign in with Google")
        case .openRouter: return String(localized: "Sign in with OpenRouter")
        case .openAIResponses: return String(localized: "Sign In")
        case .xAI: return String(localized: "Sign in with xAI")
        case .kimiCode: return String(localized: "Sign in with Kimi Code")
        case .unsupported: return String(localized: "Sign In")
        }
    }

    private func oauthLogin(_ instance: ProviderInstance) async {
        do {
            switch instance.providerType {
            case .anthropic: try await ClaudeOAuthManager.shared.login(instanceId: instance.id)
            case .gemini: try await GeminiOAuthManager.shared.login(instanceId: instance.id)
            case .openAI: try await CodexOAuthManager.shared.login(instanceId: instance.id)
            case .antigravity: try await AntigravityOAuthManager.shared.login(instanceId: instance.id)
            case .openRouter: try await OpenRouterOAuthManager.shared.login(instanceId: instance.id)
            case .openAIResponses: break
            case .xAI: try await XAIOAuthManager.shared.login(instanceId: instance.id)
            case .kimiCode: break // device-code flow runs in KimiDeviceLoginSheet
            case .unsupported: break
            }
        } catch {
            await MainActor.run {
                fetchError = error.localizedDescription
            }
        }
    }

    private func oauthLogout(_ instance: ProviderInstance) {
        switch instance.providerType {
        case .anthropic: ClaudeOAuthManager.shared.logout(instanceId: instance.id)
        case .gemini: GeminiOAuthManager.shared.logout(instanceId: instance.id)
        case .openAI: CodexOAuthManager.shared.logout(instanceId: instance.id)
        case .antigravity: AntigravityOAuthManager.shared.logout(instanceId: instance.id)
        case .openRouter: OpenRouterOAuthManager.shared.logout(instanceId: instance.id)
        case .openAIResponses: break // API key only
        case .xAI: XAIOAuthManager.shared.logout(instanceId: instance.id)
        case .kimiCode: KimiOAuthManager.shared.logout(instanceId: instance.id)
        case .unsupported: break
        }
    }

    private func oauthCopyToken(_ instance: ProviderInstance) async {
        let token: String?
        switch instance.providerType {
        case .anthropic:
            token = try? await ClaudeOAuthManager.shared.validAccessToken(instanceId: instance.id)
        case .gemini:
            token = try? await GeminiOAuthManager.shared.validAccessToken(instanceId: instance.id)
        case .openAI:
            token = try? await CodexOAuthManager.shared.validAccessToken(instanceId: instance.id)
        case .antigravity:
            token = try? await AntigravityOAuthManager.shared.validAccessToken(instanceId: instance.id)
        case .openRouter:
            token = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)
        case .openAIResponses:
            token = nil
        case .xAI:
            token = try? await XAIOAuthManager.shared.validAccessToken(instanceId: instance.id)
        case .kimiCode:
            token = try? await KimiOAuthManager.shared.validAccessToken(instanceId: instance.id)
        case .unsupported:
            token = nil
        }
        guard let token, !token.isEmpty else { return }
        await MainActor.run { UIPasteboard.general.string = token }
    }

    // MARK: - Helpers

    private func keyPlaceholder(_ type: ProviderType) -> String {
        switch type {
        case .anthropic: return "sk-ant-..."
        case .gemini: return "Gemini API Key..."
        case .openAI: return "sk-..."
        case .xAI: return "xai-..."
        case .kimiCode: return "" // OAuth only
        case .antigravity: return "API Key..."
        case .openRouter: return "sk-or-..."
        case .openAIResponses: return "sk-..."
        case .unsupported: return ""
        }
    }

    private func saveLabel(_ instance: ProviderInstance) {
        let trimmed = editingLabel.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty, trimmed != instance.label else { return }
        var updated = instance
        updated.label = trimmed
        store.updateInstance(updated)
    }

    private func saveCustomBaseURL(_ instance: ProviderInstance) {
        let current = instance.customBaseURL ?? ""
        let trimmed = editingCustomBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed != current else { return }
        var updated = instance
        updated.customBaseURL = trimmed.isEmpty ? nil : trimmed
        store.updateInstance(updated)
    }

    private func maskKey(_ key: String) -> String {
        guard key.count > 8 else { return "••••" }
        let prefixLen = min(key.count / 4, 10)
        let suffixLen = min(key.count / 4, 6)
        return String(key.prefix(prefixLen)) + "..." + String(key.suffix(suffixLen))
    }
}

// MARK: - Add Custom Model Sheet

struct AddCustomModelSheet: View {
    let instanceId: String
    @ObservedObject private var store = ProviderConfigStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var modelId = ""
    @State private var displayName = ""
    @State private var imageInput = false
    @State private var audioInput = false
    @State private var videoInput = false
    @State private var pdfInput = false
    @State private var imageOutput = false
    @State private var audioOutput = false
    @State private var contextWindowText = ""
    @State private var supportsThinking = false
    @State private var duplicateError: String?

    private var instance: ProviderInstance? { store.instance(for: instanceId) }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Model ID (e.g. claude-3-opus-latest)", text: $modelId)
                        .font(.system(.subheadline, design: .monospaced))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onChange(of: modelId) { _ in duplicateError = nil }

                    TextField("Display name (optional)", text: $displayName)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Model")
                } footer: {
                    if let duplicateError {
                        Text(duplicateError)
                            .foregroundColor(.red)
                    } else {
                        Text("Leave display name empty to use the model ID.")
                    }
                }

                Section {
                    HStack {
                        Text(String(localized: "Context Window"))
                        Spacer()
                        TextField("128000", text: $contextWindowText)
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: 120)
                    }
                    Toggle(String(localized: "Thinking"), isOn: $supportsThinking)
                } header: {
                    Text(String(localized: "Capabilities"))
                } footer: {
                    Text(String(localized: "Context window size in tokens. Leave empty for default."))
                }

                Section {
                    Toggle("Image input", isOn: $imageInput)
                    Toggle("PDF input", isOn: $pdfInput)
                    Toggle("Audio input", isOn: $audioInput)
                    Toggle("Video input", isOn: $videoInput)
                } header: {
                    Text("Input Modality")
                } footer: {
                    Text("Text input is always supported. Disable modalities the model doesn't actually support to prevent sending unsupported attachments.")
                }

                Section {
                    Toggle("Image output", isOn: $imageOutput)
                    Toggle("Audio output", isOn: $audioOutput)
                } header: {
                    Text("Output Modality")
                } footer: {
                    Text("Enable for models that generate images (e.g. gpt-image-1, dall-e-3, flux) or audio (e.g. TTS models). Text output is always enabled.")
                }
            }
            .navigationTitle("Add Custom Model")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Add") { addModel() }
                        .font(.body.weight(.semibold))
                        .disabled(modelId.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear { initializeModalityFromProvider() }
        }
    }

    private func initializeModalityFromProvider() {
        guard let instance else { return }
        let defaultModality = instance.providerType.defaultModality
        imageInput = defaultModality.contains(.imageInput)
        pdfInput = false  // Default off for custom models — most don't support PDF
        audioInput = defaultModality.contains(.audioInput)
        videoInput = defaultModality.contains(.videoInput)
        imageOutput = defaultModality.contains(.imageOutput)
        audioOutput = defaultModality.contains(.audioOutput)
    }

    private func addModel() {
        guard let instance else { return }
        let trimmedId = modelId.trimmingCharacters(in: .whitespaces)
        guard !trimmedId.isEmpty else { return }
        let name = displayName.trimmingCharacters(in: .whitespaces)

        var modality: ModelModality = [.textInput, .textOutput]
        if imageInput { modality.insert(.imageInput) }
        if pdfInput { modality.insert(.pdfInput) }
        if audioInput { modality.insert(.audioInput) }
        if videoInput { modality.insert(.videoInput) }
        if imageOutput { modality.insert(.imageOutput) }
        if audioOutput { modality.insert(.audioOutput) }

        let parsedContextWindow = Int(contextWindowText.trimmingCharacters(in: .whitespaces))

        let model = LLMModel(
            id: trimmedId,
            displayName: name.isEmpty ? trimmedId : name,
            provider: instance.providerType.displayName,
            modalityOverride: modality,
            contextWindow: parsedContextWindow,
            supportsReasoning: supportsThinking
        )
        let entry = ModelEntry(providerInstanceId: instance.id, model: model, isCustom: true)
        if store.addEntry(entry) {
            dismiss()
        } else {
            duplicateError = String(localized: "Model ID \"\(trimmedId)\" already exists.")
        }
    }
}

// MARK: - Model Entry Detail Sheet

struct ModelEntryDetailSheet: View {
    let entry: ModelEntry
    @ObservedObject private var store = ProviderConfigStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var displayName: String = ""
    @State private var modelId: String = ""
    @State private var isHidden: Bool = false
    @State private var imageInput: Bool = false
    @State private var pdfInput: Bool = false
    @State private var audioInput: Bool = false
    @State private var videoInput: Bool = false
    @State private var imageOutput: Bool = false
    @State private var audioOutput: Bool = false
    @State private var contextWindowText: String = ""
    @State private var supportsThinking: Bool = false
    @State private var maxTokensText: String = ""
    /// [T-ios-model-quick-test] Presents the modality-matched Quick Test sheet.
    @State private var showQuickTest: Bool = false
    @State private var showForceThinkingAlert: Bool = false
    @State private var showResetAlert: Bool = false

    var body: some View {
        NavigationStack {
            List {
                Section("Identity") {
                    HStack {
                        Text("Model ID")
                            .foregroundStyle(.secondary)
                        Spacer()
                        if entry.isCustom {
                            // axis: .vertical lets long IDs wrap so the cursor
                            // stays visible while editing. Single-line +
                            // trailing alignment lost the cursor past the row
                            // edge with no horizontal autoscroll.
                            TextField("model-id", text: $modelId, axis: .vertical)
                                .font(.system(.body, design: .monospaced))
                                .multilineTextAlignment(.trailing)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                        } else {
                            Text(entry.model.id)
                                .font(.system(.body, design: .monospaced))
                                .foregroundStyle(.secondary)
                                .textSelection(.enabled)
                        }
                    }

                    HStack {
                        Text("Display Name")
                            .foregroundStyle(.secondary)
                        Spacer()
                        TextField("Display name", text: $displayName)
                            .multilineTextAlignment(.trailing)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }

                    HStack {
                        Text("Provider")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(entry.model.provider)
                            .foregroundStyle(.secondary)
                    }

                    if entry.isCustom {
                        HStack {
                            Text("Type")
                                .foregroundStyle(.secondary)
                            Spacer()
                            Text("Custom")
                                .font(.caption.weight(.medium))
                                .foregroundStyle(.orange)
                        }
                    }
                }

                if entry.isCustom {
                    Section {
                        HStack {
                            Text(String(localized: "Context Window"))
                            Spacer()
                            TextField("128000", text: $contextWindowText)
                                .keyboardType(.numberPad)
                                .multilineTextAlignment(.trailing)
                                .frame(maxWidth: 120)
                        }
                        maxTokensField()
                        Toggle(String(localized: "Thinking"), isOn: $supportsThinking)
                    } header: {
                        Text(String(localized: "Capabilities"))
                    } footer: {
                        Text(String(localized: "Context window and max output tokens in tokens. Leave empty for default."))
                    }
                } else {
                    Section {
                        HStack {
                            Text(String(localized: "Context Window"))
                            Spacer()
                            TextField(
                                "\(entry.baseModel.contextWindowTokens)",
                                text: $contextWindowText
                            )
                            .keyboardType(.numberPad)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: 120)
                        }

                        maxTokensField()

                        HStack {
                            Text(String(localized: "Thinking"))
                                .foregroundStyle(.secondary)
                            Spacer()
                            if supportsThinking {
                                Label(String(localized: "Supported"), systemImage: "checkmark.circle.fill")
                                    .foregroundStyle(.green)
                                    .labelStyle(.titleAndIcon)
                            } else if entry.baseModel.supportsReasoning == false {
                                Text(String(localized: "Not Supported"))
                                    .foregroundStyle(.secondary)
                            } else {
                                Text(String(localized: "Unknown"))
                                    .foregroundStyle(.tertiary)
                                Button(String(localized: "Force Enable")) {
                                    showForceThinkingAlert = true
                                }
                                .font(.caption)
                                .buttonStyle(.bordered)
                                .controlSize(.mini)
                            }
                        }
                    } header: {
                        Text(String(localized: "Capabilities"))
                    } footer: {
                        Text(String(localized: "Leave Context Window empty to use auto-detected value. Leave Max Output Tokens empty to follow the provider default."))
                    }
                }

                Section {
                    Toggle("Hidden", isOn: $isHidden)
                } footer: {
                    Text("Hidden models won't appear in the model picker.")
                }

                Section {
                    Toggle("Image input", isOn: $imageInput)
                    Toggle("PDF input", isOn: $pdfInput)
                    Toggle("Audio input", isOn: $audioInput)
                    Toggle("Video input", isOn: $videoInput)
                } header: {
                    Text("Input Modality")
                } footer: {
                    Text("Text input is always enabled. Configure which additional input modalities this model supports.")
                }

                Section {
                    Toggle("Image output", isOn: $imageOutput)
                    Toggle("Audio output", isOn: $audioOutput)
                } header: {
                    Text("Output Modality")
                } footer: {
                    Text("Enable for models that generate images (e.g. gpt-image-1, dall-e-3, flux) or audio (e.g. TTS models). Text output is always enabled.")
                }

                if !entry.isCustom && !entry.overrides.isEmpty {
                    Section {
                        Button(role: .destructive) {
                            showResetAlert = true
                        } label: {
                            HStack {
                                Image(systemName: "arrow.counterclockwise")
                                Text(String(localized: "Reset to Default"))
                            }
                        }
                    } footer: {
                        Text(String(localized: "Clear your customizations and restore the values reported by the provider."))
                    }
                }

                // [T-ios-model-quick-test] Quick Test button at the bottom —
                // standard tinted Section-row style (matches Add Custom Model /
                // Delete Provider), fires a modality-matched smoke test.
                Section {
                    Button {
                        AppLogger(category: "QuickTest").info("[QuickTest] button tapped model=\(entry.model.id)")
                        showQuickTest = true
                    } label: {
                        Label(String(localized: "Quick Test"), systemImage: "bolt.badge.checkmark")
                    }
                    .buttonStyle(.borderless)
                } footer: {
                    Text(String(localized: "Run a quick test matching this model's main capability."))
                }
            }
            .navigationTitle("Model Details")
            .navigationBarTitleDisplayMode(.inline)
            .scrollDismissesKeyboard(.interactively)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") { save() }
                        .font(.body.weight(.semibold))
                }
            }
            .onAppear { loadFromEntry() }
            .sheet(isPresented: $showQuickTest) {
                // [T-quicktest-stale-session] Fresh identity per model — this
                // detail view's entry is fixed, but keep the same pattern as
                // the list-driven sites so a reused sheet identity can never
                // pin a stale TestSession.
                ModelQuickTestSheet(entry: entry)
                    .id(entry.id)
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
            }
            .alert(
                String(localized: "Force Enable Thinking"),
                isPresented: $showForceThinkingAlert
            ) {
                Button(String(localized: "Enable"), role: .destructive) {
                    supportsThinking = true
                }
                Button(String(localized: "Cancel"), role: .cancel) {}
            } message: {
                Text(String(localized: "The provider has not declared whether this model supports thinking. Force-enabling may cause errors — you can disable it or retry if needed."))
            }
            .alert(
                String(localized: "Reset Model Settings"),
                isPresented: $showResetAlert
            ) {
                Button(String(localized: "Reset"), role: .destructive) {
                    resetToDefault()
                }
                Button(String(localized: "Cancel"), role: .cancel) {}
            } message: {
                Text(String(localized: "This will clear all customizations (including force-enabled thinking) and restore the provider's default values."))
            }
        }
    }

    /// Format token count into a human-readable string (e.g. "200K tokens", "1M tokens").
    private static func formatContextWindow(_ tokens: Int) -> String {
        if tokens >= 1_000_000 && tokens % 1_000_000 == 0 {
            return "\(tokens / 1_000_000)M tokens"
        } else if tokens >= 1_000_000 {
            let value = Double(tokens) / 1_000_000.0
            return String(format: "%.1fM tokens", value)
        } else if tokens >= 1_000 {
            return "\(tokens / 1_000)K tokens"
        }
        return "\(tokens) tokens"
    }

    /// Placeholder text for the Max Output Tokens field — shows the API-reported value
    /// if one exists so users know what they'd get by leaving the field empty.
    private var maxTokensPlaceholder: String {
        if let apiMax = entry.baseModel.maxOutputTokens {
            return "\(apiMax)"
        }
        return String(localized: "Default")
    }

    /// True when the user has typed a value that exceeds the API-reported maximum.
    /// UI-only check: the data layer accepts any value. Only meaningful for non-custom
    /// entries where `baseModel.maxOutputTokens` reflects real API truth.
    private var maxTokensExceedsApiLimit: Bool {
        guard !entry.isCustom,
              let apiMax = entry.baseModel.maxOutputTokens,
              let typed = Int(maxTokensText.trimmingCharacters(in: .whitespaces)) else {
            return false
        }
        return typed > apiMax
    }

    @ViewBuilder
    private func maxTokensField() -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(String(localized: "Max Output Tokens"))
                Spacer()
                TextField(maxTokensPlaceholder, text: $maxTokensText)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.trailing)
                    .frame(maxWidth: 120)
            }
            if maxTokensExceedsApiLimit, let apiMax = entry.baseModel.maxOutputTokens {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill")
                    Text(String(
                        localized: "Above the provider's reported limit of \(apiMax) — the API may reject requests."
                    ))
                }
                .font(.caption)
                .foregroundStyle(.orange)
            }
        }
    }

    private func loadFromEntry() {
        // Show the effective (user-visible) name — this is `baseModel.displayName` overlaid
        // with any existing displayName override.
        displayName = entry.model.displayName
        modelId = entry.baseModel.id
        isHidden = entry.isHidden
        // Use `entry.model` (overrides overlaid on baseModel) so the sheet shows the user's
        // last-saved values for every editable field — modality, contextWindow, supportsReasoning.
        // Reading straight from baseModel hid prior overrides and made the sheet appear to
        // "revert" right after save.
        let effective = entry.model
        let base = entry.baseModel
        let modality = effective.modalityOverride
            ?? base.capabilities.supportedModalities
        imageInput = modality.contains(.imageInput)
        pdfInput = modality.contains(.pdfInput)
        audioInput = modality.contains(.audioInput)
        videoInput = modality.contains(.videoInput)
        imageOutput = modality.contains(.imageOutput)
        audioOutput = modality.contains(.audioOutput)
        if let ctx = effective.contextWindow {
            contextWindowText = "\(ctx)"
        }
        supportsThinking = effective.supportsReasoning ?? false
        // Max tokens text is populated only from the user override — leaving empty
        // means "follow the API/provider default" (shown as placeholder).
        if let mt = entry.overrides.maxOutputTokens {
            maxTokensText = "\(mt)"
        } else {
            maxTokensText = ""
        }
    }

    private func resetToDefault() {
        var cleared = entry
        cleared.overrides = ModelOverrides()
        store.updateEntry(cleared)

        let base = entry.baseModel
        displayName = base.displayName
        supportsThinking = base.supportsReasoning ?? false
        maxTokensText = ""
        if let ctx = base.contextWindow {
            contextWindowText = "\(ctx)"
        } else {
            contextWindowText = ""
        }
        let modality = base.modalityOverride
            ?? base.capabilities.supportedModalities
        imageInput = modality.contains(.imageInput)
        pdfInput = modality.contains(.pdfInput)
        audioInput = modality.contains(.audioInput)
        videoInput = modality.contains(.videoInput)
        imageOutput = modality.contains(.imageOutput)
        audioOutput = modality.contains(.audioOutput)
    }

    private func save() {
        let trimmedName = displayName.trimmingCharacters(in: .whitespaces)
        let trimmedId = modelId.trimmingCharacters(in: .whitespaces)
        let trimmedMaxTokens = maxTokensText.trimmingCharacters(in: .whitespaces)
        let parsedMaxTokens: Int? = trimmedMaxTokens.isEmpty ? nil : Int(trimmedMaxTokens)

        var modality: ModelModality = [.textInput, .textOutput]
        if imageInput { modality.insert(.imageInput) }
        if pdfInput { modality.insert(.pdfInput) }
        if audioInput { modality.insert(.audioInput) }
        if videoInput { modality.insert(.videoInput) }
        if imageOutput { modality.insert(.imageOutput) }
        if audioOutput { modality.insert(.audioOutput) }

        // Every user-edited field flows through `overrides`. baseModel is left as API truth
        // (or, for custom entries, as the user-authored skeleton) and is never updated here.
        // Reason: replaceEntries() runs `withInferredModality()` → models.dev `applyDevData`
        // on EVERY refresh, including the custom-entry path, and that pass overwrites
        // baseModel's contextWindow / maxOutputTokens / supportsReasoning / modality from
        // models.dev whenever the model ID is recognized. Anything written into baseModel
        // by save() therefore survived only until the next refresh hit a known ID. Routing
        // through `overrides` (which replaceEntries preserves verbatim) is the only durable
        // place to put user intent.
        let finalId = entry.isCustom && !trimmedId.isEmpty ? trimmedId : entry.baseModel.id
        let trimmedContextWindow = contextWindowText.trimmingCharacters(in: .whitespaces)
        let typedContextWindow: Int? = trimmedContextWindow.isEmpty ? nil : Int(trimmedContextWindow)

        let updatedBaseModel = LLMModel(
            id: finalId,
            displayName: entry.baseModel.displayName,
            provider: entry.baseModel.provider,
            modalityOverride: entry.baseModel.modalityOverride,
            contextWindow: entry.baseModel.contextWindow,
            maxOutputTokens: entry.baseModel.maxOutputTokens,
            supportsReasoning: entry.baseModel.supportsReasoning,
            interleavedReasoningField: entry.baseModel.interleavedReasoningField
        )

        // Build overrides: only record a field when the user's choice diverges from the
        // baseModel/API value, so future provider-side capability bumps can still flow
        // through for fields the user hasn't touched.
        var newOverrides = ModelOverrides()

        let effectiveTypedName = trimmedName.isEmpty ? updatedBaseModel.displayName : trimmedName
        if effectiveTypedName != updatedBaseModel.displayName {
            newOverrides.displayName = effectiveTypedName
        }

        newOverrides.maxOutputTokens = parsedMaxTokens

        let baselineModality = entry.baseModel.modalityOverride
            ?? entry.baseModel.capabilities.supportedModalities
        if modality != baselineModality {
            newOverrides.modalityOverride = modality
        }

        if typedContextWindow != entry.baseModel.contextWindow {
            newOverrides.contextWindow = typedContextWindow
        }

        if supportsThinking != (entry.baseModel.supportsReasoning ?? false) {
            newOverrides.supportsReasoning = supportsThinking
        }

        let updatedEntry = ModelEntry(
            uuid: entry.uuid,
            providerInstanceId: entry.providerInstanceId,
            model: updatedBaseModel,
            overrides: newOverrides,
            isCustom: entry.isCustom,
            isHidden: isHidden,
            userModifiedAt: newOverrides.isEmpty && !isHidden ? nil : Date()
        )
        store.updateEntry(updatedEntry)
        dismiss()
    }
}

// MARK: - Share Sheet

private struct ProviderShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}

