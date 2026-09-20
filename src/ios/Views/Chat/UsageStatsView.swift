import SwiftUI

// MARK: - ViewModel

@MainActor
class UsageStatsViewModel: ObservableObject {
    struct ModelStats {
        let modelId: String
        let displayName: String
        var inputTokens: Int = 0
        var outputTokens: Int = 0
        var cacheCreationTokens: Int = 0
        var cacheReadTokens: Int = 0
        var distinctDays: Set<String> = []
        var distinctSessions: Set<String> = []

        var totalTokens: Int { inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens }
        var dailyAvgTokens: Int {
            let days = max(distinctDays.count, 1)
            return totalTokens / days
        }
        var sessionAvgTokens: Int {
            let sessions = max(distinctSessions.count, 1)
            return totalTokens / sessions
        }
    }

    struct ProviderGroup: Identifiable {
        let id: String // provider name
        var models: [ModelStats]
        var totalTokens: Int { models.reduce(0) { $0 + $1.totalTokens } }
    }

    @Published var providers: [ProviderGroup] = []
    @Published var grandTotalInput: Int = 0
    @Published var grandTotalOutput: Int = 0
    @Published var grandTotalCacheCreation: Int = 0
    @Published var grandTotalCacheRead: Int = 0
    @Published var isLoaded = false

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    func load() async {
        let records = await ChatStore.shared.fetchUsageStats()

        // Resolve each model id to a PROVIDER-TYPE group (what the user sees in
        // the Providers list — OpenAI + its compatibles, Anthropic, Gemini, xAI,
        // OpenRouter, …). We group by ProviderType, NOT by the model's own
        // `provider` string (which is inconsistent: "Gemini"/"OpenRouter"/"doubao"
        // …). Priority for a given model id:
        //   1) a configured provider instance that owns this model → its
        //      providerType.displayName (an OpenAI-compatible vendor like DeepSeek/
        //      Groq/Doubao/Azure all correctly fold into "OpenAI").
        //   2) a static built-in model → its provider, normalized.
        //   3) neither (a since-deleted instance / renamed model) → "Other".
        let store = ProviderConfigStore.shared
        // modelId → providerType.displayName, from configured instances.
        let instanceMap = Dictionary(store.instances.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        var modelIdToProviderGroup: [String: String] = [:]
        for entry in store.modelEntries {
            if let inst = instanceMap[entry.providerInstanceId] {
                modelIdToProviderGroup[entry.model.id] = inst.providerType.displayName
            }
        }
        // Fallback map + display names from static built-in models.
        let staticLookup = Dictionary(LLMModel.allModels.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        func providerGroup(for modelId: String) -> String {
            if let g = modelIdToProviderGroup[modelId] { return g }
            if let p = staticLookup[modelId]?.provider {
                // Normalize built-in provider strings to ProviderType display names.
                switch p {
                case "Google", "Gemini", "Google Gemini": return ProviderType.gemini.displayName
                case "xAI":       return ProviderType.xAI.displayName
                case "OpenRouter": return ProviderType.openRouter.displayName
                default:          return p   // "Anthropic"/"OpenAI" already canonical
                }
            }
            return String(localized: "Other", comment: "Usage stats: unknown provider group")
        }
        let modelLookup = staticLookup.merging(
            Dictionary(store.modelEntries.map { ($0.model.id, $0.model) }, uniquingKeysWith: { a, _ in a }),
            uniquingKeysWith: { _, configured in configured })

        // Group by modelId
        var statsByModel: [String: ModelStats] = [:]
        for record in records {
            let model = modelLookup[record.modelId]
            let displayName = model?.displayName ?? record.modelId

            var stats = statsByModel[record.modelId] ?? ModelStats(
                modelId: record.modelId, displayName: displayName
            )
            stats.inputTokens += record.usage.inputTokens
            stats.outputTokens += record.usage.outputTokens
            stats.cacheCreationTokens += record.usage.cacheCreationTokens
            stats.cacheReadTokens += record.usage.cacheReadTokens
            stats.distinctDays.insert(Self.dayFormatter.string(from: record.date))
            stats.distinctSessions.insert(record.sessionId)
            statsByModel[record.modelId] = stats
        }

        // Group by PROVIDER TYPE (the Providers-list grouping).
        var providerMap: [String: [ModelStats]] = [:]
        for (modelId, stats) in statsByModel {
            providerMap[providerGroup(for: modelId), default: []].append(stats)
        }

        // Emit every group — a preferred ProviderType order first, then any
        // remaining groups (e.g. "Other") appended so NOTHING is silently dropped.
        let preferredOrder = ProviderType.allCases.map(\.displayName)
        var groups: [ProviderGroup] = []
        var emitted = Set<String>()
        func emit(_ provider: String) {
            guard !emitted.contains(provider), var models = providerMap[provider] else { return }
            emitted.insert(provider)
            models.sort { $0.totalTokens > $1.totalTokens }
            groups.append(ProviderGroup(id: provider, models: models))
        }
        for p in preferredOrder { emit(p) }
        for p in providerMap.keys.sorted() { emit(p) }   // leftovers (incl. "Other")

        grandTotalInput = statsByModel.values.reduce(0) { $0 + $1.inputTokens }
        grandTotalOutput = statsByModel.values.reduce(0) { $0 + $1.outputTokens }
        grandTotalCacheCreation = statsByModel.values.reduce(0) { $0 + $1.cacheCreationTokens }
        grandTotalCacheRead = statsByModel.values.reduce(0) { $0 + $1.cacheReadTokens }
        providers = groups
        isLoaded = true
    }
}

// MARK: - View

struct UsageStatsView: View {
    @StateObject private var vm = UsageStatsViewModel()

    var body: some View {
        List {
            if vm.isLoaded && vm.providers.isEmpty {
                Section {
                    Text("No usage data yet. Start a conversation to see token statistics here.")
                        .foregroundStyle(.secondary)
                }
            } else if vm.isLoaded {
                // Grand totals
                Section("Total Usage") {
                    let grandTotalAllInput = vm.grandTotalInput + vm.grandTotalCacheRead + vm.grandTotalCacheCreation
                    LabeledContent("Total Input (incl. Cache)", value: formatCount(grandTotalAllInput))
                    LabeledContent("Output Tokens", value: formatCount(vm.grandTotalOutput))
                    if vm.grandTotalCacheRead > 0 {
                        LabeledContent("Cache Read", value: formatCount(vm.grandTotalCacheRead))
                    }
                    if vm.grandTotalCacheCreation > 0 {
                        LabeledContent("Cache Creation", value: formatCount(vm.grandTotalCacheCreation))
                    }
                    if grandTotalAllInput > 0 && vm.grandTotalCacheRead > 0 {
                        let grandHitRate = Double(vm.grandTotalCacheRead) / Double(grandTotalAllInput) * 100
                        LabeledContent("Cache Hit Rate", value: String(format: "%.1f%%", grandHitRate))
                    }
                }

                // Per-provider sections
                ForEach(vm.providers) { provider in
                    Section(provider.id) {
                        ForEach(provider.models, id: \.modelId) { model in
                            DisclosureGroup {
                                modelDetailRows(model)
                            } label: {
                                HStack {
                                    Text(model.displayName)
                                    Spacer()
                                    let totalInputLabel = model.inputTokens + model.cacheReadTokens + model.cacheCreationTokens
                                    Text("\(formatCount(totalInputLabel)) / \(formatCount(model.outputTokens))")
                                        .foregroundStyle(.secondary)
                                }
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle("Usage")
        .task {
            await vm.load()
        }
    }

    @ViewBuilder
    private func modelDetailRows(_ model: UsageStatsViewModel.ModelStats) -> some View {
        Group {
            LabeledContent("Input", value: formatCount(model.inputTokens))
            LabeledContent("Output", value: formatCount(model.outputTokens))
            if model.cacheReadTokens > 0 {
                LabeledContent("Cache Read", value: formatCount(model.cacheReadTokens))
            }
            if model.cacheCreationTokens > 0 {
                LabeledContent("Cache Creation", value: formatCount(model.cacheCreationTokens))
            }
            let totalInputForRate = model.inputTokens + model.cacheReadTokens + model.cacheCreationTokens
            if totalInputForRate > 0 && model.cacheReadTokens > 0 {
                let hitRate = Double(model.cacheReadTokens) / Double(totalInputForRate) * 100
                LabeledContent("Cache Hit Rate", value: String(format: "%.1f%%", hitRate))
            }
            LabeledContent("Daily Avg", value: formatCount(model.dailyAvgTokens))
            LabeledContent("Per-Session Avg", value: formatCount(model.sessionAvgTokens))
            LabeledContent("Sessions", value: "\(model.distinctSessions.count)")
            LabeledContent("Active Days", value: "\(model.distinctDays.count)")
        }
        .font(.subheadline)
    }

    private func formatCount(_ count: Int) -> String {
        if count >= 1_000_000 {
            let m = Double(count) / 1_000_000.0
            return String(format: "%.1fM", m)
        }
        if count >= 1000 {
            let k = Double(count) / 1000.0
            return k.truncatingRemainder(dividingBy: 1) == 0
                ? "\(Int(k))k"
                : String(format: "%.1fk", k)
        }
        return "\(count)"
    }
}
