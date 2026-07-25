import SwiftUI
import UniformTypeIdentifiers

// MARK: - AI Data Sharing Consent

private let aiDataSharingConsentKey = "aiDataSharingConsentAccepted"

/// Full-screen consent view shown before the user can add their first AI provider.
struct AIDataSharingConsentView: View {
    var onAccept: () -> Void
    var onDecline: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    VStack(alignment: .leading, spacing: 8) {
                        Label("AI Data Sharing Notice", systemImage: "hand.raised.fill")
                            .font(.title2.bold())
                        Text("Please review how your data is handled before adding an AI provider.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }

                    GroupBox {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("We Do Not Collect Your Data")
                                .font(.headline)
                            Text("Minis does not operate any server and does not collect, store, or process any of your personal data. All data stays on your device.")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                            Text("However, when you add a third-party AI provider and use it for conversations, the following data may be sent directly from your device to that provider's servers:")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)

                            VStack(alignment: .leading, spacing: 6) {
                                dataItem("Your chat messages and conversation history")
                                dataItem("Files, images, and documents you attach or share")
                                dataItem("System information you authorize (calendar, health, contacts, etc.) when using agent features")
                            }
                        }
                    }

                    GroupBox {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Third-Party AI Providers")
                                .font(.headline)
                            Text("Depending on which provider you configure, your data will be sent directly to one or more of the following third-party services:")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)

                            VStack(alignment: .leading, spacing: 8) {
                                providerRow("Anthropic", description: "Claude models (anthropic.com)", color: .purple)
                                providerRow("OpenAI", description: "GPT and o-series models (openai.com)", color: .green)
                                providerRow("Google", description: "Gemini models (google.com)", color: .blue)
                                providerRow("OpenRouter", description: "Multi-provider routing (openrouter.ai)", color: .cyan)
                                providerRow("Custom Endpoints", description: "Self-hosted or third-party compatible APIs you configure", color: .gray)
                            }

                            Text("Each provider has its own privacy policy and terms of service that govern how they handle your data.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }

                    GroupBox {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Your Control")
                                .font(.headline)

                            VStack(alignment: .leading, spacing: 6) {
                                dataItem("API keys and tokens are stored only in the iOS Keychain on your device and are never sent to us")
                                dataItem("Data is sent only to the specific provider you choose for each conversation")
                                dataItem("You can remove any provider and its credentials at any time from Settings")
                                dataItem("No data is shared with Minis or any other party beyond the provider you select")
                            }
                        }
                    }

                    Link("Read our full Privacy Policy", destination: URL(string: "https://openminis.github.io/privacy-policy.html")!)
                        .font(.footnote)

                    Spacer(minLength: 80)
                }
                .padding()
            }
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 10) {
                    Button {
                        UserDefaults.standard.set(true, forKey: aiDataSharingConsentKey)
                        onAccept()
                    } label: {
                        Text("I Understand & Agree")
                            .font(.body.weight(.semibold))
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)

                    Button("Cancel", role: .cancel) {
                        onDecline()
                    }
                    .font(.body)
                }
                .padding()
                .background(.bar)
            }
        }
    }

    private func dataItem(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text("•")
                .foregroundStyle(.secondary)
            Text(text)
                .font(.subheadline)
        }
    }

    private func providerRow(_ name: String, description: String, color: Color) -> some View {
        HStack(spacing: 10) {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
            VStack(alignment: .leading, spacing: 1) {
                Text(name)
                    .font(.subheadline.weight(.medium))
                Text(description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

/// Flow to add a new provider instance: pick type → credential → enter key/OAuth → done.
struct AddProviderView: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var selectedType: ProviderType?
    @State private var selectedCredential: ProviderCredential?
    @State private var apiKeyInput = ""
    @State private var showApiKeyPlaintext = false
    @State private var labelInput = ""
    /// True once the user has manually edited the label. We use this to
    /// stop `defaultLabel(for:)` from clobbering a label the user just
    /// typed (often a Chinese / non-ASCII name) when they go back and
    /// re-tap the provider-type row. The Telegram report
    /// `T-provider-name-chinese-34602` originated from this footgun:
    /// users perceived the new-instance label as "ASCII only" because
    /// re-touching the provider type silently overwrote whatever they
    /// had typed.
    @State private var labelEdited = false
    /// True when the configure step was entered via a Voice Chat Provider
    /// template (credential picker was skipped). Back should then return
    /// straight to the type list, not to a credential step the user never saw.
    @State private var enteredViaVoiceTemplate = false
    @State private var customBaseURLInput = ""
    @State private var appendV1SuffixInput = true
    @State private var useResponsesAPI = false
    @State private var manualOAuthTokenInput = ""
    @State private var isSaving = false
    @State private var errorMessage: String?
    @State private var pendingInstanceId = UUID().uuidString
    @State private var pendingOAuthDone = false
    @State private var oauthMaskedToken: String?
    // [T-kimi-oauth] Present the device-code login sheet (user code +
    // verification URL + polling) for Kimi's RFC 8628 flow.
    @State private var showKimiLogin = false
    @State private var oauthAuthTime: Date?
    @State private var showDataSharingConsent = false
    @State private var showImportFile = false
    @State private var importMessage: String?
    @State private var showImportResult = false
    @State private var importSucceeded = false

    /// Whether the data-sharing consent has been accepted (persisted in UserDefaults).
    private var consentAccepted: Bool {
        UserDefaults.standard.bool(forKey: aiDataSharingConsentKey)
    }

    private enum Step: Int { case type = 0, credential = 1, configure = 2 }
    private var currentStep: Step {
        if selectedType == nil { return .type }
        if selectedCredential == nil { return .credential }
        return .configure
    }

    @ViewBuilder
    private var steppedContent: some View {
        Group {
            if selectedType == nil {
                typePickerSection
            } else if selectedCredential == nil {
                credentialPickerSection
            } else {
                configureSection
            }
        }
        .transition(.asymmetric(
            insertion: .move(edge: .trailing).combined(with: .opacity),
            removal: .move(edge: .leading).combined(with: .opacity)
        ))
        .id(currentStep)
    }

    var body: some View {
        List {
            steppedContent
        }
        .animation(.spring(response: 0.35, dampingFraction: 0.88), value: currentStep)
        .navigationTitle(navigationTitle)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                if selectedType != nil {
                    Button("Back") { goBack() }
                } else {
                    Button("Cancel") { cleanupAndDismiss() }
                }
            }
        }
        .sheet(isPresented: $showDataSharingConsent) {
            AIDataSharingConsentView(
                onAccept: {
                    showDataSharingConsent = false
                },
                onDecline: {
                    showDataSharingConsent = false
                    cleanupAndDismiss()
                }
            )
            .interactiveDismissDisabled()
        }
        .sheet(isPresented: $showKimiLogin) {
            // [T-kimi-oauth] RFC 8628 device-code login. On success, mark the
            // OAuth step done + surface the masked token, matching startOAuth().
            KimiDeviceLoginSheet(instanceId: pendingInstanceId) { success in
                if success {
                    oauthAuthTime = Date()
                    oauthMaskedToken = loadMaskedToken(type: .kimiCode)
                    pendingOAuthDone = true
                }
            }
        }
        .fileImporter(isPresented: $showImportFile, allowedContentTypes: [.json]) { result in
            handleImport(result)
        }
        .alert(String(localized: "Import"), isPresented: $showImportResult) {
            Button("OK") {
                if importSucceeded { dismiss() }
            }
        } message: {
            if let msg = importMessage { Text(msg) }
        }
        .onAppear {
            if !consentAccepted && store.instances.isEmpty {
                showDataSharingConsent = true
            }
        }
    }

    private func handleImport(_ result: Result<URL, Error>) {
        importSucceeded = false
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
                importSucceeded = true
            } else {
                importMessage = String(localized: "Invalid provider configuration file.")
            }
            showImportResult = true
        case .failure:
            break
        }
    }

    private var navigationTitle: String {
        if let type = selectedType, selectedCredential != nil {
            return String(localized: "Configure \(type.displayName)")
        } else if selectedType != nil {
            return String(localized: "Auth Method")
        }
        return String(localized: "Add Provider")
    }

    // MARK: - Step 1: Pick Provider Type

    private var visibleProviderTypes: [ProviderType] {
        ProviderType.allCases.filter {
            $0 != .openAIResponses && $0 != .antigravity
                && !$0.isUnsupported
        }
    }

    @ViewBuilder
    private var typePickerSection: some View {
        Section {
            ForEach(visibleProviderTypes, id: \.self) { type in
                Button {
                    selectedType = type
                    // Only seed the label when the user hasn't typed
                    // their own. Without this guard, switching back and
                    // forth between provider types silently overwrites
                    // a Chinese / custom label the user just entered.
                    if !labelEdited {
                        labelInput = defaultLabel(for: type)
                    }
                } label: {
                    HStack(spacing: 12) {
                        providerIcon(type)
                            .frame(width: 32, height: 32)
                            .background(providerColor(type).opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 8))

                        VStack(alignment: .leading, spacing: 2) {
                            Text(providerPickerLabel(type))
                                .font(.body.weight(.medium))
                                .foregroundStyle(Color(UIColor.label))
                            Text(type.pickerSubtitle)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
        } header: {
            Text("Choose Provider")
        } footer: {
            VStack(alignment: .leading, spacing: 4) {
                Text("You can add multiple instances of the same provider (e.g. work and personal accounts).")
                Text("OpenAI and Anthropic also work with compatible third-party endpoints — set a custom API Base URL after choosing the matching protocol.")
            }
        }

        voiceProviderSection

        Section {
            Button {
                showImportFile = true
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "square.and.arrow.down")
                        .font(.body)
                        .frame(width: 32, height: 32)
                        .foregroundStyle(Color.accentColor)
                        .background(Color.accentColor.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: 8))

                    Text("Or Import Provider from File")
                        .font(.body.weight(.medium))
                        .foregroundStyle(Color(UIColor.label))

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                }
            }
        } footer: {
            Text("Import a provider configuration that was exported from another device.")
        }
    }

    /// Voice-specialised vendor templates. Tapping one preseeds the standard
    /// add-provider flow (underlying type + base URL) and jumps to the key step.
    @ViewBuilder
    private var voiceProviderSection: some View {
        let templates = VoiceProviderTemplate.all
        let notes = templates.compactMap { $0.note }
        Section {
            ForEach(templates) { template in
                Button {
                    applyVoiceTemplate(template)
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: template.symbol)
                            .font(.body)
                            .foregroundStyle(template.tint)
                            .frame(width: 32, height: 32)
                            .background(template.tint.opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 8))

                        VStack(alignment: .leading, spacing: 2) {
                            Text(template.name)
                                .font(.body.weight(.medium))
                                .foregroundStyle(Color(UIColor.label))
                            Text(template.capability)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        Spacer()

                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                }
            }
        } header: {
            Text("Voice Chat Providers")
        } footer: {
            VStack(alignment: .leading, spacing: 4) {
                Text("Speech-to-text and text-to-speech vendors. The provider type and base URL are prefilled — just add your API key.")
                ForEach(notes, id: \.self) { note in
                    Text(note)
                }
            }
        }
    }

    /// Preseed the flow from a voice template: pick the underlying protocol,
    /// prefill the base URL / label, and advance straight to the configure step.
    private func applyVoiceTemplate(_ template: VoiceProviderTemplate) {
        selectedType = template.providerType
        customBaseURLInput = template.baseURL
        appendV1SuffixInput = template.appendV1
        if !labelEdited {
            labelInput = template.name
            labelEdited = true   // keep the vendor name from being overwritten by defaultLabel
        }
        selectedCredential = .apiKey
        enteredViaVoiceTemplate = true
    }

    // MARK: - Step 2: Pick Credential Type

    private var credentialPickerSection: some View {
        Group {
            Section {
                if let type = selectedType {
                    let creds = availableCredentials(for: type)
                    ForEach(creds, id: \.self) { cred in
                        Button {
                            selectedCredential = cred
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: cred == .apiKey ? "key" : "person.badge.shield.checkmark")
                                    .font(.body)
                                    .frame(width: 28)
                                    .foregroundStyle(Color(UIColor.label))

                                VStack(alignment: .leading, spacing: 2) {
                                    Text(cred == .apiKey ? "API Key" : "OAuth")
                                        .font(.body.weight(.medium))
                                        .foregroundStyle(Color(UIColor.label))
                                    Text(credentialDescription(type: type, credential: cred))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }

                                Spacer()

                                Image(systemName: "chevron.right")
                                    .font(.caption)
                                    .foregroundStyle(.tertiary)
                            }
                        }
                    }
                }
            } header: {
                Text("Authentication")
            }

            // "Responses API" is now integrated as API Format picker in Step 3
        }
    }

    // MARK: - Step 3: Configure

    private var configureSection: some View {
        Group {
            Section("Label") {
                TextField("Provider label", text: $labelInput)
                    .textContentType(.none)
                    .onChange(of: labelInput) { _ in
                        // Mark the field as user-edited so subsequent
                        // provider-type taps no longer clobber it.
                        labelEdited = true
                    }
            }

            if selectedCredential == .apiKey {
                apiKeySection
            } else {
                oauthSection
            }

            if let error = errorMessage {
                Section {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private var apiKeySection: some View {
        Group {
            Section {
                    HStack {
                        if showApiKeyPlaintext {
                            TextField(keyPlaceholder, text: $apiKeyInput)
                                .font(.system(.body, design: .monospaced))
                        } else {
                            SecureField(keyPlaceholder, text: $apiKeyInput)
                        }
                        Button {
                            showApiKeyPlaintext.toggle()
                        } label: {
                            Image(systemName: showApiKeyPlaintext ? "eye.slash" : "eye")
                                .foregroundStyle(.secondary)
                        }
                        .buttonStyle(.plain)
                    }
                } header: {
                    Text("API Key")
                } footer: {
                    Text("Your key is stored securely in the iOS Keychain and never leaves the device.")
                }

            if selectedType != .antigravity {
                customBaseURLSection
            }

            // API Format picker for OpenAI provider (hidden for voice-only templates)
            if !enteredViaVoiceTemplate, selectedType == .openAI || selectedType == .openAIResponses {
                Section {
                    Picker("API Format", selection: $useResponsesAPI) {
                        Text("Chat Completions").tag(false)
                        Text("Responses API").tag(true)
                    }
                } footer: {
                    Text(useResponsesAPI
                        ? "Uses /v1/responses endpoint format. Required for some Responses-API-only services."
                        : "Standard /v1/chat/completions format. Compatible with most OpenAI-compatible services.")
                }
            }

            Section {
                Button {
                    saveApiKeyInstance()
                } label: {
                    HStack {
                        Spacer()
                        if isSaving {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Text("Add Provider")
                                .font(.body.weight(.semibold))
                        }
                        Spacer()
                    }
                }
                .disabled(apiKeyInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isSaving)
            }
        }
    }

    @ViewBuilder
    private var oauthSection: some View {
        Section {
            if pendingOAuthDone {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text("Authenticated")
                        .font(.body.weight(.medium))
                }

                if let masked = oauthMaskedToken {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Token")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(masked)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(.secondary)
                    }
                }

                if let authTime = oauthAuthTime {
                    HStack {
                        Text("Authorized")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(authTime, style: .date)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(authTime, style: .time)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            } else {
                Button {
                    // Kimi uses a device-code sheet (RFC 8628); every other
                    // provider drives its redirect/PKCE flow inline via startOAuth.
                    if selectedType == .kimiCode {
                        showKimiLogin = true
                    } else {
                        Task { await startOAuth() }
                    }
                } label: {
                    HStack {
                        Spacer()
                        Text(oauthSignInLabel)
                            .font(.body.weight(.semibold))
                        Spacer()
                    }
                }
            }
        } header: {
            Text("OAuth")
        }

        // Manual OAuth entry — available for all providers (supports proxy services, Coding Plan tokens, etc.)
        if selectedType != .antigravity && !pendingOAuthDone {
            Section {
                TextField(defaultBaseURL, text: $customBaseURLInput)
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)

                SecureField("Bearer Token", text: $manualOAuthTokenInput)
                    .font(.system(.body, design: .monospaced))

                Button {
                    saveManualOAuthInstance()
                } label: {
                    HStack {
                        Spacer()
                        Text("Add Provider")
                            .font(.body.weight(.semibold))
                        Spacer()
                    }
                }
                .disabled(manualOAuthTokenInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } header: {
                Text("Or Configure Manually")
            } footer: {
                Text("For third-party Coding Plans (e.g. MiniMax, Kimi) or compatible proxy endpoints, enter the API base URL and bearer token manually.")
            }
        }

        if pendingOAuthDone {
            Section {
                Button {
                    saveOAuthInstance()
                } label: {
                    HStack {
                        Spacer()
                        Text("Save Provider")
                            .font(.body.weight(.semibold))
                        Spacer()
                    }
                }
            }
        }
    }

    // MARK: - Custom Base URL Section

    private var customBaseURLSection: some View {
        Section {
            TextField(defaultBaseURL, text: $customBaseURLInput)
                .font(.system(.body, design: .monospaced))
                .foregroundStyle(.secondary)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)

            if !enteredViaVoiceTemplate, selectedType != .gemini {
                Toggle("Auto Append \"/v1\"", isOn: $appendV1SuffixInput)
            }
        } header: {
            Text("Custom API Base (Optional)")
        } footer: {
            if enteredViaVoiceTemplate {
                Text("The voice service endpoint URL.")
            } else if selectedType == .gemini {
                Text("Leave empty to use the default Google endpoint. Enter the full base URL including version path.")
            } else {
                Text(appendV1SuffixInput
                     ? "Leave empty to use the default endpoint. \"/v1\" is appended automatically — enter the base host only."
                     : "The URL is used verbatim. Include the full path up to (but not including) the endpoint.")
            }
        }
    }

    private var defaultBaseURL: String {
        switch selectedType {
        case .anthropic: return "https://api.anthropic.com"
        case .openAI: return "https://api.openai.com"
        case .gemini: return "https://generativelanguage.googleapis.com/v1beta"
        case .openRouter: return "https://openrouter.ai/api/v1"
        case .openAIResponses: return "https://api.openai.com"
        case .xAI: return "https://api.x.ai/v1"
        case .kimiCode: return "https://api.kimi.com/coding"
        default: return "https://api.example.com"
        }
    }

    // MARK: - Actions

    private func saveApiKeyInstance() {
        guard let type = selectedType else { return }
        let trimmedKey = apiKeyInput.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedLabel = labelInput.trimmingCharacters(in: .whitespaces)
        let trimmedBase = customBaseURLInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedKey.isEmpty else { return }

        // Map OpenAI + Responses API format to .openAIResponses provider type
        let effectiveType: ProviderType = (type == .openAI && useResponsesAPI) ? .openAIResponses : type

        isSaving = true
        let base = trimmedBase.isEmpty ? nil : trimmedBase
        let instance = ProviderInstance(
            label: trimmedLabel.isEmpty ? defaultLabel(for: effectiveType) : trimmedLabel,
            providerType: effectiveType,
            credentialType: .apiKey,
            customBaseURL: base,
            appendV1Suffix: appendV1SuffixInput
        )
        ProviderKeychainHelper.saveAPIKey(trimmedKey, instanceId: instance.id)
        store.addInstance(instance)
        isSaving = false
        dismiss()
    }

    private func saveOAuthInstance() {
        guard let type = selectedType else { return }
        let trimmedLabel = labelInput.trimmingCharacters(in: .whitespaces)

        let instance = ProviderInstance(
            id: pendingInstanceId,
            label: trimmedLabel.isEmpty ? defaultLabel(for: type) : trimmedLabel,
            providerType: type,
            credentialType: .oauth
        )
        store.addInstance(instance)
        dismiss()
    }

    private func saveManualOAuthInstance() {
        guard let type = selectedType else { return }
        let trimmedToken = manualOAuthTokenInput.components(separatedBy: .whitespacesAndNewlines).joined()
        let trimmedLabel = labelInput.trimmingCharacters(in: .whitespaces)
        let trimmedBase = customBaseURLInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedToken.isEmpty else { return }

        let instance = ProviderInstance(
            id: pendingInstanceId,
            label: trimmedLabel.isEmpty ? defaultLabel(for: type) : trimmedLabel,
            providerType: type,
            credentialType: .oauth,
            customBaseURL: trimmedBase.isEmpty ? nil : trimmedBase,
            appendV1Suffix: appendV1SuffixInput
        )
        ProviderKeychainHelper.saveOAuthString(trimmedToken, instanceId: instance.id, account: "manual-oauth-token")
        store.addInstance(instance)
        dismiss()
    }

    @MainActor
    private func startOAuth() async {
        guard let type = selectedType else { return }
        errorMessage = nil
        do {
            switch type {
            case .anthropic: try await ClaudeOAuthManager.shared.login(instanceId: pendingInstanceId)
            case .gemini: try await GeminiOAuthManager.shared.login(instanceId: pendingInstanceId)
            case .openAI: try await CodexOAuthManager.shared.login(instanceId: pendingInstanceId)
            case .antigravity: try await AntigravityOAuthManager.shared.login(instanceId: pendingInstanceId)
            case .openRouter: try await OpenRouterOAuthManager.shared.login(instanceId: pendingInstanceId)
            case .openAIResponses: break // API key only, no OAuth
            case .xAI: try await XAIOAuthManager.shared.login(instanceId: pendingInstanceId)
            case .kimiCode: break // device-code flow runs in KimiDeviceLoginSheet, not here
            case .unsupported: break // free / unsupported — no OAuth
            }
            oauthAuthTime = Date()
            oauthMaskedToken = loadMaskedToken(type: type)
            pendingOAuthDone = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Loads the access token from Keychain and masks the middle third.
    private func loadMaskedToken(type: ProviderType) -> String? {
        let token: String?
        switch type {
        case .anthropic:
            token = ProviderKeychainHelper.loadOAuthToken(instanceId: pendingInstanceId, as: ClaudeTokenStorage.self)?.accessToken
        case .gemini:
            token = ProviderKeychainHelper.loadOAuthToken(instanceId: pendingInstanceId, as: GeminiTokenStorage.self)?.accessToken
        case .openAI:
            token = ProviderKeychainHelper.loadOAuthToken(instanceId: pendingInstanceId, as: CodexTokenStorage.self)?.accessToken
        case .antigravity:
            token = ProviderKeychainHelper.loadOAuthToken(instanceId: pendingInstanceId, as: AntigravityTokenStorage.self)?.accessToken
        case .openRouter:
            // OpenRouter OAuth produces a permanent API key, not an OAuth token
            token = ProviderKeychainHelper.loadAPIKey(instanceId: pendingInstanceId)
        case .openAIResponses:
            token = nil // API key only, no OAuth
        case .xAI:
            token = ProviderKeychainHelper.loadOAuthToken(instanceId: pendingInstanceId, as: XAITokenStorage.self)?.accessToken
        case .kimiCode:
            token = ProviderKeychainHelper.loadOAuthToken(instanceId: pendingInstanceId, as: KimiTokenStorage.self)?.accessToken
        case .unsupported:
            token = nil // free / unsupported — no token
        }
        guard let t = token, !t.isEmpty else { return nil }
        return ClaudeOAuthManager.maskToken(t)
    }

    private func goBack() {
        // Voice-template entry skipped the credential step, so Back returns
        // all the way to the type list (and clears the prefilled fields) rather
        // than dropping the user onto a credential picker they never saw.
        if enteredViaVoiceTemplate {
            enteredViaVoiceTemplate = false
            selectedType = nil
            selectedCredential = nil
            apiKeyInput = ""
            customBaseURLInput = ""
            appendV1SuffixInput = true
            labelInput = ""
            labelEdited = false
            errorMessage = nil
            return
        }
        if selectedCredential != nil {
            // If we started OAuth but haven't saved, clean up the pending token
            if selectedCredential == .oauth && pendingOAuthDone {
                ProviderKeychainHelper.deleteOAuthToken(instanceId: pendingInstanceId)
                ProviderKeychainHelper.deleteOAuthString(instanceId: pendingInstanceId, account: "oauth-email")
                ProviderKeychainHelper.deleteOAuthString(instanceId: pendingInstanceId, account: "oauth-gcp-project")
                ProviderKeychainHelper.deleteOAuthString(instanceId: pendingInstanceId, account: "manual-oauth-token")
                // OpenRouter OAuth stores a permanent API key, not an OAuth token
                if selectedType == .openRouter {
                    ProviderKeychainHelper.deleteAPIKey(instanceId: pendingInstanceId)
                }
                pendingOAuthDone = false
                oauthMaskedToken = nil
                oauthAuthTime = nil
                pendingInstanceId = UUID().uuidString
            }
            selectedCredential = nil
            useResponsesAPI = false
            apiKeyInput = ""
            customBaseURLInput = ""
            manualOAuthTokenInput = ""
            errorMessage = nil
        } else {
            selectedType = nil
            selectedCredential = nil
        }
    }

    private func cleanupAndDismiss() {
        // If we started OAuth but never saved, clean up
        if pendingOAuthDone {
            ProviderKeychainHelper.deleteOAuthToken(instanceId: pendingInstanceId)
            ProviderKeychainHelper.deleteOAuthString(instanceId: pendingInstanceId, account: "oauth-email")
            ProviderKeychainHelper.deleteOAuthString(instanceId: pendingInstanceId, account: "oauth-gcp-project")
            if selectedType == .openRouter {
                ProviderKeychainHelper.deleteAPIKey(instanceId: pendingInstanceId)
            }
            ProviderKeychainHelper.deleteOAuthString(instanceId: pendingInstanceId, account: "manual-oauth-token")
        }
        dismiss()
    }

    // MARK: - Helpers

    private var oauthSignInLabel: String {
        guard let type = selectedType else { return String(localized: "Sign In") }
        switch type {
        case .anthropic: return String(localized: "Sign in with Claude")
        case .gemini: return String(localized: "Sign in with Google")
        case .openAI: return String(localized: "Sign in with OpenAI")
        case .antigravity: return String(localized: "Sign in with Google")
        case .openRouter: return String(localized: "Sign in with OpenRouter")
        case .openAIResponses: return String(localized: "Sign In") // Not reachable — API key only
        case .xAI: return String(localized: "Sign in with xAI")
        case .kimiCode: return String(localized: "Sign in with Kimi Code")
        case .unsupported: return String(localized: "Sign In")
        }
    }

    private var keyPlaceholder: String {
        guard let type = selectedType else { return "API Key" }
        switch type {
        case .anthropic: return "sk-ant-..."
        case .gemini: return "Gemini API Key..."
        case .openAI: return "sk-..."
        case .antigravity: return "API Key..."
        case .openRouter: return "sk-or-..."
        case .openAIResponses: return "sk-..."
        case .xAI: return "xai-..."
        case .kimiCode: return "" // OAuth only
        case .unsupported: return ""
        }
    }

    private func providerPickerLabel(_ type: ProviderType) -> String {
        switch type {
        case .anthropic: return String(localized: "Anthropic / Compatible API")
        case .openAI:    return String(localized: "OpenAI / Compatible API")
        case .gemini:    return type.displayName
        case .antigravity: return type.displayName
        case .openRouter: return "OpenRouter"
        case .openAIResponses: return "Responses API"
        case .xAI: return "xAI (Grok)"
        case .kimiCode: return "Kimi Code"
        case .unsupported: return String(localized: "Unsupported")
        }
    }

    private func defaultLabel(for type: ProviderType) -> String {
        let existingCount = store.instances.filter { $0.providerType == type }.count
        if existingCount == 0 {
            return type.displayName
        }
        return "\(type.displayName) \(existingCount + 1)"
    }

    private func availableCredentials(for type: ProviderType) -> [ProviderCredential] {
        switch type {
        case .antigravity:
            return [.oauth]
        case .openAIResponses, .gemini:
            return [.apiKey]
        default:
            return [.apiKey, .oauth]
        }
    }

    private func credentialDescription(type: ProviderType, credential: ProviderCredential) -> String {
        switch (type, credential) {
        case (.openAI, .apiKey):
            return String(localized: "Supports OpenAI official API and third-party services like OpenRouter, MiniMax, etc.")
        case (.openAIResponses, .apiKey):
            return String(localized: "Use an API key for a Responses API endpoint")
        case (_, .apiKey):
            return String(localized: "Use an API key from your \(type.displayName) account")
        case (.anthropic, .oauth):
            return String(localized: "Sign in with your Claude account")
        case (.gemini, .oauth):
            return String(localized: "Sign in with Google for Cloud Code Assist")
        case (.openAI, .oauth):
            return String(localized: "Sign in with OpenAI Codex")
        case (.antigravity, .oauth):
            return String(localized: "Sign in with Google for Antigravity Cloud Code")
        case (.openRouter, .oauth):
            return String(localized: "Sign in with your OpenRouter account")
        case (.openAIResponses, .oauth):
            return "" // Not reachable — API key only
        case (.xAI, .oauth):
            return String(localized: "Sign in with your SuperGrok / X Premium+ subscription. xAI may restrict API access on some plans — if you hit HTTP 403, switch to an API key.")
        case (.kimiCode, .oauth):
            return String(localized: "Sign in with your Kimi Code / Coding Plan subscription.")
        case (.kimiCode, .apiKey):
            return String(localized: "Use a Kimi Coding API key.")
        case (.unsupported, _):
            return String(localized: "This provider isn't supported in this app version.")
        }
    }

    @ViewBuilder
    private func providerIcon(_ type: ProviderType) -> some View {
        switch type {
        case .anthropic:
            Image(systemName: "sparkles")
                .foregroundStyle(.purple)
        case .gemini:
            Image(systemName: "diamond")
                .foregroundStyle(.blue)
        case .openAI:
            Image(systemName: "circle.hexagongrid")
                .foregroundStyle(.green)
        case .antigravity:
            Image(systemName: "ant")
                .foregroundStyle(.orange)
        case .openRouter:
            Image(systemName: "arrow.triangle.branch")
                .foregroundStyle(.cyan)
        case .openAIResponses:
            Image(systemName: "arrow.trianglehead.2.counterclockwise")
                .foregroundStyle(.mint)
        case .xAI:
            Image(systemName: "x.circle")
                .foregroundStyle(.gray)
        case .kimiCode:
            Image(systemName: "moon.stars")
                .foregroundStyle(.indigo)
        case .unsupported:
            Image(systemName: "questionmark.circle")
                .foregroundStyle(.gray)
        }
    }

    private func providerColor(_ type: ProviderType) -> Color {
        switch type {
        case .anthropic: return .purple
        case .gemini: return .blue
        case .openAI: return .green
        case .antigravity: return .orange
        case .openRouter: return .cyan
        case .openAIResponses: return .mint
        case .xAI: return .gray
        case .kimiCode: return .indigo
        case .unsupported: return .gray
        }
    }
}

