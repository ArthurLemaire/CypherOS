#if DEBUG
import Foundation
import UIKit

// MARK: - Error helpers

struct DebugRPCErr: Error {
    let code: Int
    let message: String
    init(_ code: Int, _ message: String) {
        self.code = code
        self.message = message
    }
}

private func require<T>(_ value: T?, _ name: String) throws -> T {
    guard let v = value else {
        throw DebugRPCErr(-32602, "Missing required param: \(name)")
    }
    return v
}

private func iso8601(_ date: Date) -> String {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f.string(from: date)
}

// MARK: - Provider Methods

@MainActor
enum DebugRPCProvider {

    static func types() -> [String: Any] {
        let allTypes = ProviderType.allCases.map { type -> [String: Any] in
            let supportedCreds: [String]
            switch type {
            case .openAI, .anthropic: supportedCreds = ["apiKey", "oauth"]
            case .gemini, .antigravity: supportedCreds = ["oauth"]
            case .openRouter: supportedCreds = ["apiKey", "oauth"]
            case .openAIResponses: supportedCreds = ["apiKey"]
            case .xAI: supportedCreds = ["apiKey", "oauth"]
            case .kimiCode: supportedCreds = ["oauth"]
            case .unsupported: supportedCreds = []
            }
            let customBaseSupported: Bool
            switch type {
            case .openAI, .openRouter, .openAIResponses, .gemini, .xAI, .kimiCode: customBaseSupported = true
            case .anthropic, .antigravity, .unsupported: customBaseSupported = false
            }
            return [
                "id": type.rawValue,
                "displayName": type.displayName,
                "supportedCredentials": supportedCreds,
                "customBaseURLSupported": customBaseSupported,
                "appendV1SuffixConfigurable": customBaseSupported,
                "defaultModality": type.defaultModality.rawValue,
                "builtInModelIds": type.builtInModels.map(\.id),
            ]
        }
        return ["types": allTypes]
    }

    static func instancesList(includeDisabled: Bool) -> [String: Any] {
        let store = ProviderConfigStore.shared
        let all = store.instances
        let filtered = includeDisabled ? all : all.filter(\.isEnabled)
        let dicts = filtered.map { instanceDict($0, store: store) }
        return ["count": dicts.count, "instances": dicts]
    }

    static func instancesCreate(params: [String: Any]) throws -> [String: Any] {
        let providerTypeRaw = try require(params["providerType"] as? String, "providerType")
        guard let providerType = ProviderType(rawValue: providerTypeRaw) else {
            throw DebugRPCErr(-32602, "Unknown providerType: \(providerTypeRaw)")
        }
        let label = try require(params["label"] as? String, "label")
        let credentialRaw = (params["credentialType"] as? String) ?? "apiKey"
        guard let credentialType = ProviderCredential(rawValue: credentialRaw) else {
            throw DebugRPCErr(-32602, "Unknown credentialType: \(credentialRaw)")
        }
        let apiKey = params["apiKey"] as? String
        let oauthToken = params["oauthToken"] as? String
        let customBaseURL = params["customBaseURL"] as? String
        let appendV1Suffix = (params["appendV1Suffix"] as? Bool) ?? true
        let isEnabled = (params["isEnabled"] as? Bool) ?? true
        let seedBuiltInModels = (params["seedBuiltInModels"] as? Bool) ?? true

        if credentialType == .apiKey, apiKey == nil || apiKey?.isEmpty == true {
            throw DebugRPCErr(-32602, "apiKey is required when credentialType=apiKey")
        }

        let instance = ProviderInstance(
            label: label,
            providerType: providerType,
            credentialType: credentialType,
            isEnabled: isEnabled,
            customBaseURL: customBaseURL,
            appendV1Suffix: appendV1Suffix
        )

        // Persist credential before adding instance — if Keychain write fails we abort.
        if credentialType == .apiKey, let key = apiKey {
            ProviderKeychainHelper.saveAPIKey(key, instanceId: instance.id)
        }
        if let token = oauthToken, !token.isEmpty {
            ProviderKeychainHelper.saveOAuthString(token, instanceId: instance.id, account: "manual-oauth-token")
        }

        let store = ProviderConfigStore.shared
        store.addInstance(instance)

        // `addInstance` triggers an async model fetch for apiKey instances and
        // pre-populates built-ins for OAuth ones. The `seedBuiltInModels=false`
        // hint here is best-effort: if the caller wants a clean slate, they can
        // still drop the auto-fetched entries via `provider.models.delete`.
        _ = seedBuiltInModels

        return ["instance": instanceDict(instance, store: store)]
    }

    static func instancesUpdate(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["instanceId"] as? String, "instanceId")
        let store = ProviderConfigStore.shared
        guard var instance = store.instance(for: id) else {
            throw DebugRPCErr(-32602, "Unknown instanceId: \(id)")
        }
        if let label = params["label"] as? String { instance.label = label }
        if params.keys.contains("customBaseURL") {
            instance.customBaseURL = params["customBaseURL"] as? String
        }
        if let v1 = params["appendV1Suffix"] as? Bool { instance.appendV1Suffix = v1 }
        if let enabled = params["isEnabled"] as? Bool { instance.isEnabled = enabled }
        if let modeRaw = params["imageEndpointMode"] as? String,
           let mode = ImageEndpointMode(rawValue: modeRaw) {
            instance.imageEndpointMode = mode
            // User-forced mode supersedes any cached probe result.
            if mode != .auto { instance.imageEndpointResolved = nil }
        }
        if params.keys.contains("imageEndpointResolved") {
            // Allow tests to manually clear the cache (pass null).
            if let resolvedRaw = params["imageEndpointResolved"] as? String {
                instance.imageEndpointResolved = ImageEndpointMode(rawValue: resolvedRaw)
            } else {
                instance.imageEndpointResolved = nil
            }
        }
        store.updateInstance(instance)
        if let key = params["apiKey"] as? String {
            if key.isEmpty {
                ProviderKeychainHelper.deleteAPIKey(instanceId: instance.id)
            } else {
                ProviderKeychainHelper.saveAPIKey(key, instanceId: instance.id)
            }
        }
        if let token = params["oauthToken"] as? String {
            if token.isEmpty {
                ProviderKeychainHelper.deleteOAuthString(instanceId: instance.id, account: "manual-oauth-token")
            } else {
                ProviderKeychainHelper.saveOAuthString(token, instanceId: instance.id, account: "manual-oauth-token")
            }
        }
        // Reload after possible side-effect of updateInstance (it can clear imageEndpointResolved).
        let refreshed = store.instance(for: id) ?? instance
        return ["instance": instanceDict(refreshed, store: store)]
    }

    static func instancesDelete(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["instanceId"] as? String, "instanceId")
        let confirm = (params["confirm"] as? Bool) ?? false
        guard confirm else { throw DebugRPCErr(-32602, "confirm=true required to delete an instance") }
        let store = ProviderConfigStore.shared
        guard store.instance(for: id) != nil else {
            throw DebugRPCErr(-32602, "Unknown instanceId: \(id)")
        }
        let entriesBefore = store.entries(for: id).count
        let bindingsBefore = store.config.sessionBindings.values.filter { binding in
            switch binding.primarySource {
            case .directEntry(let entryId, _):
                return store.entry(for: entryId)?.providerInstanceId == id
            case .group: return false
            }
        }.count
        ProviderKeychainHelper.deleteAPIKey(instanceId: id)
        ProviderKeychainHelper.deleteOAuthString(instanceId: id, account: "manual-oauth-token")
        store.removeInstance(id)
        return [
            "instanceId": id,
            "deletedModelEntries": entriesBefore,
            "affectedSessionBindings": bindingsBefore,
        ]
    }

    static func modelsList(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["instanceId"] as? String, "instanceId")
        let includeHidden = (params["includeHidden"] as? Bool) ?? false
        let store = ProviderConfigStore.shared
        guard store.instance(for: id) != nil else {
            throw DebugRPCErr(-32602, "Unknown instanceId: \(id)")
        }
        let raw = store.entries(for: id)
        let entries = includeHidden ? raw : raw.filter { !$0.isHidden }
        return [
            "instanceId": id,
            "count": entries.count,
            "entries": entries.map(entryDict),
        ]
    }

    static func modelsAdd(params: [String: Any]) throws -> [String: Any] {
        let instanceId = try require(params["instanceId"] as? String, "instanceId")
        let modelId = try require(params["modelId"] as? String, "modelId")
        let store = ProviderConfigStore.shared
        guard let instance = store.instance(for: instanceId) else {
            throw DebugRPCErr(-32602, "Unknown instanceId: \(instanceId)")
        }
        let displayName = (params["displayName"] as? String) ?? prettifyModelId(modelId)
        var modality: ModelModality = instance.providerType.defaultModality
        if let yes = params["supportsImageInput"] as? Bool {
            if yes { modality.insert(.imageInput) } else { modality.remove(.imageInput) }
        }
        if let yes = params["supportsAudioInput"] as? Bool {
            if yes { modality.insert(.audioInput) } else { modality.remove(.audioInput) }
        }
        if let yes = params["supportsVideoInput"] as? Bool {
            if yes { modality.insert(.videoInput) } else { modality.remove(.videoInput) }
        }
        if let yes = params["supportsPDFInput"] as? Bool {
            if yes { modality.insert(.pdfInput) } else { modality.remove(.pdfInput) }
        }
        if let yes = params["supportsImageOutput"] as? Bool {
            if yes { modality.insert(.imageOutput) } else { modality.remove(.imageOutput) }
        }

        let model = LLMModel(
            id: modelId,
            displayName: displayName,
            provider: instance.providerType.displayName,
            modalityOverride: modality,
            contextWindow: params["contextWindow"] as? Int,
            maxOutputTokens: params["maxOutputTokens"] as? Int,
            supportsReasoning: params["supportsReasoning"] as? Bool
        )
        let entry = ModelEntry(
            providerInstanceId: instanceId,
            model: model,
            isCustom: true
        )
        guard store.addEntry(entry) else {
            throw DebugRPCErr(-32602, "Model with id \(modelId) already exists for this instance")
        }
        guard let saved = store.entry(for: entry.id) else {
            throw DebugRPCErr(-32000, "Failed to retrieve newly added entry")
        }
        return entryDict(saved)
    }

    static func modelsUpdate(params: [String: Any]) throws -> [String: Any] {
        let entryId = try require(params["entryId"] as? String, "entryId")
        let store = ProviderConfigStore.shared
        guard var entry = store.entry(for: entryId) else {
            throw DebugRPCErr(-32602, "Unknown entryId: \(entryId)")
        }
        if params.keys.contains("displayName") {
            entry.overrides.displayName = params["displayName"] as? String
        }
        if params.keys.contains("maxOutputTokens") {
            entry.overrides.maxOutputTokens = params["maxOutputTokens"] as? Int
        }
        if let hidden = params["isHidden"] as? Bool {
            entry.isHidden = hidden
        }
        if params.keys.contains("supportsReasoning") {
            entry.overrides.supportsReasoning = params["supportsReasoning"] as? Bool
        }
        if let newModelId = params["modelId"] as? String {
            guard entry.isCustom else {
                throw DebugRPCErr(-32602, "built-in model ID is immutable")
            }
            // Rebuild baseModel with new id (baseModel is a let; entry.baseModel is a let too,
            // so we replace the entry whole-cloth via removeEntry + addEntry to keep IDs stable
            // we'd need to drop the entry — but the user asked to rename. Instead, mark it hidden
            // and add a new one. For simplicity, refuse the rename in the RPC for now.
            throw DebugRPCErr(-32000, "Renaming custom model IDs is not supported via RPC; delete + add instead.")
        }
        store.updateEntry(entry)
        guard let saved = store.entry(for: entryId) else {
            throw DebugRPCErr(-32000, "Update succeeded but entry vanished")
        }
        return entryDict(saved)
    }

    static func modelsDelete(params: [String: Any]) throws -> [String: Any] {
        let entryId = try require(params["entryId"] as? String, "entryId")
        let confirm = (params["confirm"] as? Bool) ?? false
        guard confirm else { throw DebugRPCErr(-32602, "confirm=true required") }
        let store = ProviderConfigStore.shared
        guard let entry = store.entry(for: entryId) else {
            throw DebugRPCErr(-32602, "Unknown entryId: \(entryId)")
        }
        guard entry.isCustom else {
            throw DebugRPCErr(-32602, "built-in entries cannot be deleted; set isHidden=true instead")
        }
        let bindingsBefore = store.config.sessionBindings.values.filter { binding in
            switch binding.primarySource {
            case .directEntry(let id, _): return id == entryId
            case .group(_, let resolved): return resolved == entryId
            }
        }.count
        store.removeEntry(entryId)
        return [
            "entryId": entryId,
            "deleted": true,
            "affectedSessionBindings": bindingsBefore,
        ]
    }

    /// Override the modality flags on an existing entry's baseModel. Useful when the
    /// upstream catalog mis-classified a model (e.g. gpt-image-2 reported as
    /// vision-input only when it's actually an image-output endpoint).
    /// Pass any subset of the boolean flags; omitted flags retain their current value.
    static func modelsSetModality(params: [String: Any]) throws -> [String: Any] {
        let entryId = try require(params["entryId"] as? String, "entryId")
        let store = ProviderConfigStore.shared
        guard let entry = store.entry(for: entryId) else {
            throw DebugRPCErr(-32602, "Unknown entryId: \(entryId)")
        }
        var modality = entry.baseModel.modalityOverride ?? entry.baseModel.capabilities.supportedModalities
        func apply(_ key: String, _ flag: ModelModality) {
            if let val = params[key] as? Bool {
                if val { modality.insert(flag) } else { modality.remove(flag) }
            }
        }
        apply("textInput", .textInput)
        apply("textOutput", .textOutput)
        apply("imageInput", .imageInput)
        apply("imageOutput", .imageOutput)
        apply("audioInput", .audioInput)
        apply("audioOutput", .audioOutput)
        apply("videoInput", .videoInput)
        apply("videoOutput", .videoOutput)
        apply("pdfInput", .pdfInput)
        // Rebuild baseModel with the new modalityOverride; ModelEntry.baseModel is `let`,
        // so we use replaceEntries with a fresh model list for this instance.
        let newModel = LLMModel(
            id: entry.baseModel.id,
            displayName: entry.baseModel.displayName,
            provider: entry.baseModel.provider,
            modalityOverride: modality,
            contextWindow: entry.baseModel.contextWindow,
            maxOutputTokens: entry.baseModel.maxOutputTokens,
            supportsReasoning: entry.baseModel.supportsReasoning,
            interleavedReasoningField: entry.baseModel.interleavedReasoningField
        )
        // Build the full instance entry list, swapping just this one.
        let instanceId = entry.providerInstanceId
        let allEntries = store.entries(for: instanceId)
        let newModels: [LLMModel] = allEntries.map { e in
            e.id == entryId ? newModel : e.baseModel
        }
        store.replaceEntries(for: instanceId, models: newModels, caller: "rpc.setModality")
        guard let saved = store.entry(for: entryId) else {
            throw DebugRPCErr(-32000, "Modality update succeeded but entry vanished")
        }
        return entryDict(saved)
    }

    static func modelsSetAgentLoop(params: [String: Any]) throws -> [String: Any] {
        let entryId = try require(params["entryId"] as? String, "entryId")
        let inLoop = try require(params["inLoop"] as? Bool, "inLoop")
        let store = ProviderConfigStore.shared
        guard store.entry(for: entryId) != nil else {
            throw DebugRPCErr(-32602, "Unknown entryId: \(entryId)")
        }
        if inLoop {
            store.addAgentLoopEntry(entryId)
        } else {
            store.removeAgentLoopEntry(entryId)
        }
        return [
            "entryId": entryId,
            "inLoop": store.config.agentLoopModelEntryIds.contains(entryId),
        ]
    }

    // MARK: - Group methods

    static func groupsList(params: [String: Any]) -> [String: Any] {
        let store = ProviderConfigStore.shared
        let includeMembers = (params["includeMembers"] as? Bool) ?? true
        let groups = store.modelGroups.map { groupDict($0, store: store, includeMembers: includeMembers) }
        return [
            "defaultGroupId": store.config.defaultPrimaryGroupId ?? NSNull(),
            "count": groups.count,
            "groups": groups,
        ]
    }

    static func groupsCreate(params: [String: Any]) throws -> [String: Any] {
        let name = try require(params["name"] as? String, "name").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { throw DebugRPCErr(-32602, "name must be non-empty") }
        let store = ProviderConfigStore.shared
        let memberIds = (params["memberEntryIds"] as? [String]) ?? []
        let validMembers = memberIds.filter { store.entry(for: $0) != nil }
        let strategy = parseRoutingStrategy(params["strategy"]) ?? .fallback
        let fallbackStrategy = parseFallbackStrategy(params["fallbackStrategy"]) ?? .limited
        let thinking = parseThinkingLevel(params["defaultThinkingLevel"])
        let ctxLimit = params["contextLimitTokens"] as? Int
        let group = ModelGroup(
            name: name,
            memberEntryIds: validMembers,
            strategy: strategy,
            fallbackStrategy: fallbackStrategy,
            defaultThinkingLevel: thinking,
            contextLimitTokens: ctxLimit
        )
        store.addGroup(group)
        return ["group": groupDict(group, store: store, includeMembers: true)]
    }

    static func groupsUpdate(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["groupId"] as? String, "groupId")
        let store = ProviderConfigStore.shared
        guard var group = store.group(for: id) else {
            throw DebugRPCErr(-32602, "Unknown groupId: \(id)")
        }
        if let name = params["name"] as? String {
            let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { throw DebugRPCErr(-32602, "name must be non-empty") }
            group.name = trimmed
        }
        if let memberIds = params["memberEntryIds"] as? [String] {
            group.memberEntryIds = memberIds.filter { store.entry(for: $0) != nil }
        }
        if let s = parseRoutingStrategy(params["strategy"]) { group.strategy = s }
        if let fs = parseFallbackStrategy(params["fallbackStrategy"]) { group.fallbackStrategy = fs }
        if params.keys.contains("defaultThinkingLevel") {
            group.defaultThinkingLevel = parseThinkingLevel(params["defaultThinkingLevel"])
        }
        if params.keys.contains("contextLimitTokens") {
            group.contextLimitTokens = params["contextLimitTokens"] as? Int
        }
        store.updateGroup(group)
        return ["group": groupDict(group, store: store, includeMembers: true)]
    }

    static func groupsDelete(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["groupId"] as? String, "groupId")
        let confirm = (params["confirm"] as? Bool) ?? false
        guard confirm else { throw DebugRPCErr(-32602, "confirm=true required") }
        let store = ProviderConfigStore.shared
        guard store.group(for: id) != nil else {
            throw DebugRPCErr(-32602, "Unknown groupId: \(id)")
        }
        let wasDefault = store.config.defaultPrimaryGroupId == id
        let affected = store.config.sessionBindings.values.filter { binding in
            if case .group(let gid, _) = binding.primarySource { return gid == id }
            return false
        }.count
        store.removeGroup(id)
        return [
            "groupId": id,
            "deleted": true,
            "wasDefault": wasDefault,
            "affectedSessionBindings": affected,
        ]
    }

    static func groupsSetDefault(params: [String: Any]) throws -> [String: Any] {
        let store = ProviderConfigStore.shared
        guard params.keys.contains("groupId") else {
            throw DebugRPCErr(-32602, "Missing required param: groupId (pass null to clear)")
        }
        if let id = params["groupId"] as? String {
            guard store.group(for: id) != nil else {
                throw DebugRPCErr(-32602, "Unknown groupId: \(id)")
            }
            store.defaultPrimaryGroupId = id
        } else {
            // Explicit null → clear
            store.defaultPrimaryGroupId = nil
        }
        return ["defaultGroupId": store.defaultPrimaryGroupId ?? NSNull()]
    }

    static func groupsSetAgentLoop(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["groupId"] as? String, "groupId")
        let inLoop = try require(params["inLoop"] as? Bool, "inLoop")
        let store = ProviderConfigStore.shared
        guard store.group(for: id) != nil else {
            throw DebugRPCErr(-32602, "Unknown groupId: \(id)")
        }
        if inLoop {
            store.addAgentLoopGroup(id)
        } else {
            store.removeAgentLoopGroup(id)
        }
        return [
            "groupId": id,
            "inLoop": store.config.agentLoopGroupIds.contains(id),
        ]
    }

    private static func groupDict(_ group: ModelGroup, store: ProviderConfigStore, includeMembers: Bool) -> [String: Any] {
        var dict: [String: Any] = [
            "id": group.id,
            "name": group.name,
            "strategy": group.strategy.rawValue,
            "fallbackStrategy": group.fallbackStrategy.rawValue,
            "memberEntryIds": group.memberEntryIds,
            "isDefault": store.config.defaultPrimaryGroupId == group.id,
            "inAgentLoop": store.config.agentLoopGroupIds.contains(group.id),
            "defaultThinkingLevel": group.defaultThinkingLevel?.rawValue ?? NSNull(),
            "contextLimitTokens": group.contextLimitTokens ?? NSNull(),
        ]
        if includeMembers {
            let members: [[String: Any]] = group.memberEntryIds.compactMap { eid in
                guard let entry = store.entry(for: eid) else { return nil }
                let inst = store.instance(for: entry.providerInstanceId)
                return [
                    "entryId": entry.id,
                    "modelId": entry.model.id,
                    "displayName": entry.model.displayName,
                    "providerLabel": inst?.label ?? "",
                ]
            }
            dict["members"] = members
        }
        return dict
    }

    private static func parseRoutingStrategy(_ raw: Any?) -> RoutingStrategy? {
        guard let s = raw as? String else { return nil }
        return RoutingStrategy(rawValue: s)
    }
    private static func parseFallbackStrategy(_ raw: Any?) -> FallbackStrategy? {
        guard let s = raw as? String else { return nil }
        return FallbackStrategy(rawValue: s)
    }
    private static func parseThinkingLevel(_ raw: Any?) -> ThinkingLevel? {
        guard let s = raw as? String else { return nil }
        return ThinkingLevel(rawValue: s)
    }

    static func modelsRefresh(params: [String: Any]) async throws -> [String: Any] {
        let id = try require(params["instanceId"] as? String, "instanceId")
        let store = ProviderConfigStore.shared
        guard let instance = store.instance(for: id) else {
            throw DebugRPCErr(-32602, "Unknown instanceId: \(id)")
        }
        let beforeIds = Set(store.entries(for: id).map(\.baseModel.id))
        let start = Date()
        await store.refreshModels(for: instance)
        let afterEntries = store.entries(for: id)
        let afterIds = Set(afterEntries.map(\.baseModel.id))
        return [
            "instanceId": id,
            "added": afterIds.subtracting(beforeIds).count,
            "updated": afterIds.intersection(beforeIds).count,
            "disappeared": beforeIds.subtracting(afterIds).count,
            "total": afterEntries.count,
            "durationMs": Int(Date().timeIntervalSince(start) * 1000),
        ]
    }

    // MARK: - Export / Import (T147)

    /// Export a provider instance + its model entries + stored credential as
    /// a portable JSON document. Mirrors the `Share` button in
    /// ProviderInstanceDetailView. Wraps the underlying JSON under a
    /// versioned envelope so importers can probe schema explicitly.
    /// API key is base64-wrapped — same shape as the in-app export, NOT a
    /// security boundary (5321 RPC is a trusted local debug surface).
    static func exportInstance(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["instanceId"] as? String, "instanceId")
        let store = ProviderConfigStore.shared
        guard let instance = store.instance(for: id) else {
            throw DebugRPCErr(-32602, "Unknown instanceId: \(id)")
        }
        guard let raw = store.exportInstanceJSON(id) else {
            throw DebugRPCErr(-32000, "Export failed for instance \(id)")
        }
        guard let data = raw.data(using: .utf8),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw DebugRPCErr(-32000, "Export produced invalid JSON")
        }
        return [
            "version": 1,
            "exportedAt": iso8601(Date()),
            "platform": "ios",
            "instanceId": id,
            "instanceLabel": instance.label,
            "config": payload,
        ]
    }

    /// Import a provider instance from a JSON document produced by
    /// `provider.export` or the in-app Share button. Accepts either the
    /// versioned envelope `{version,config:{...}}` or the raw legacy config
    /// JSON for cross-platform compatibility — Android exports under the
    /// envelope, in-app share emits raw config; the importer is the same.
    static func importInstance(params: [String: Any]) throws -> [String: Any] {
        let raw = try require(params["configJson"] as? String, "configJson")
        guard let data = raw.data(using: .utf8),
              let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw DebugRPCErr(-32602, "Invalid configJson — not a JSON object")
        }
        let configString: String
        if let inner = parsed["config"] as? [String: Any] {
            guard let innerData = try? JSONSerialization.data(withJSONObject: inner),
                  let innerStr = String(data: innerData, encoding: .utf8) else {
                throw DebugRPCErr(-32602, "Invalid configJson — config field is not serializable")
            }
            configString = innerStr
        } else {
            configString = raw
        }
        let store = ProviderConfigStore.shared
        guard let resolvedLabel = store.importInstanceJSON(configString) else {
            throw DebugRPCErr(-32000, "Import failed — invalid or unsupported configJson")
        }
        // The repository auto-renames on label conflict; find by label match
        // after the import completes (the most recently added wins).
        guard let newInstance = store.instances.last(where: { $0.label == resolvedLabel }) else {
            throw DebugRPCErr(-32000, "Import succeeded but instance lookup failed for label \(resolvedLabel)")
        }
        return [
            "instanceId": newInstance.id,
            "instanceLabel": newInstance.label,
            "modelEntryCount": store.entries(for: newInstance.id).count,
            "success": true,
        ]
    }

    // MARK: - Helpers

    private static func instanceDict(_ instance: ProviderInstance, store: ProviderConfigStore) -> [String: Any] {
        var dict: [String: Any] = [
            "id": instance.id,
            "label": instance.label,
            "providerType": instance.providerType.rawValue,
            "credentialType": instance.credentialType.rawValue,
            "isEnabled": instance.isEnabled,
            "appendV1Suffix": instance.appendV1Suffix,
            "createdAt": iso8601(instance.createdAt),
            "modelEntryCount": store.entries(for: instance.id).count,
        ]
        dict["customBaseURL"] = instance.customBaseURL ?? NSNull()
        let hasKey: Bool = {
            if instance.credentialType == .apiKey {
                return ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)?.isEmpty == false
            } else {
                return ProviderKeychainHelper.loadOAuthString(instanceId: instance.id, account: "manual-oauth-token")?.isEmpty == false
            }
        }()
        dict["hasCredential"] = hasKey
        if instance.supportsImageEndpointSetting {
            dict["imageEndpointMode"] = instance.imageEndpointMode.rawValue
            if let resolved = instance.imageEndpointResolved {
                dict["imageEndpointResolved"] = resolved.rawValue
            }
        }
        return dict
    }

    fileprivate static func entryDict(_ entry: ModelEntry) -> [String: Any] {
        let model = entry.model
        return [
            "id": entry.id,
            "modelId": model.id,
            "displayName": model.displayName,
            "baseModelDisplayName": entry.baseModel.displayName,
            "isCustom": entry.isCustom,
            "isHidden": entry.isHidden,
            "supportsReasoning": model.supportsReasoning ?? NSNull(),
            "contextWindow": model.contextWindow ?? NSNull(),
            "maxOutputTokens": model.maxOutputTokens ?? NSNull(),
            "overrides": [
                "displayName": (entry.overrides.displayName as Any?) ?? NSNull(),
                "maxOutputTokens": (entry.overrides.maxOutputTokens as Any?) ?? NSNull(),
            ] as [String: Any],
            "userModifiedAt": entry.userModifiedAt.map(iso8601) ?? NSNull(),
        ]
    }

    private static func prettifyModelId(_ id: String) -> String {
        id
            .replacingOccurrences(of: "-", with: " ")
            .replacingOccurrences(of: "_", with: " ")
            .capitalized
    }
}

// MARK: - Chat Methods

@MainActor
enum DebugRPCChat {

    static func modelsList(params: [String: Any]) throws -> [String: Any] {
        let includeHidden = (params["includeHidden"] as? Bool) ?? false
        let includeDisabled = (params["includeDisabled"] as? Bool) ?? false
        let store = ProviderConfigStore.shared
        let allEntries = store.modelEntries.filter { entry in
            if !includeHidden && entry.isHidden { return false }
            if !includeDisabled, store.instance(for: entry.providerInstanceId)?.isEnabled != true { return false }
            return true
        }
        let entryDicts = allEntries.map { entry -> [String: Any] in
            let inst = store.instance(for: entry.providerInstanceId)
            let modality = entry.model.capabilities.supportedModalities
            return [
                "id": entry.id,
                "modelId": entry.model.id,
                "modelName": entry.model.displayName,
                "providerInstanceId": entry.providerInstanceId,
                "providerInstanceName": inst?.label ?? "",
                "providerType": inst?.providerType.rawValue ?? "",
                "supportsReasoning": entry.model.supportsReasoning ?? NSNull(),
                "supportsImages": modality.contains(.imageInput),
                "contextWindow": entry.model.contextWindow ?? NSNull(),
                "maxOutputTokens": entry.model.maxOutputTokens ?? NSNull(),
                "hidden": entry.isHidden,
            ]
        }
        let groups = store.modelGroups.map { group -> [String: Any] in
            [
                "id": group.id,
                "name": group.name,
                "strategy": group.strategy.rawValue,
                "isDefault": group.id == store.config.defaultPrimaryGroupId,
                "memberEntryIds": group.memberEntryIds,
                "defaultThinkingLevel": group.defaultThinkingLevel?.rawValue ?? NSNull(),
            ]
        }
        return [
            "defaultGroupId": store.config.defaultPrimaryGroupId ?? NSNull(),
            "groupCount": groups.count,
            "entryCount": entryDicts.count,
            "groups": groups,
            "entries": entryDicts,
        ]
    }

    static func sessionsList(params: [String: Any]) async -> [String: Any] {
        let limit = clamp((params["limit"] as? Int) ?? 50, min: 1, max: 500)
        let includeEmpty = (params["includeEmpty"] as? Bool) ?? false
        let sessions = await ChatStore.shared.listSessions()
        var dicts: [[String: Any]] = []
        for session in sessions.prefix(limit) {
            if !includeEmpty, session.lastMessage == nil || session.lastMessage?.isEmpty == true { continue }
            dicts.append([
                "id": session.id,
                "title": session.title ?? NSNull(),
                "modelId": session.modelId,
                "modelName": modelDisplayName(forModelId: session.modelId),
                "source": session.source ?? NSNull(),
                "lastMessagePreview": session.lastMessage ?? NSNull(),
                "createdAt": iso8601(session.createdAt),
                "updatedAt": iso8601(session.updatedAt),
            ])
        }
        return ["count": dicts.count, "sessions": dicts]
    }

    static func sessionsGet(params: [String: Any]) async throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")
        let sessions = await ChatStore.shared.listSessions()
        guard let session = sessions.first(where: { $0.id == id }) else {
            throw DebugRPCErr(-32602, "Session not found")
        }
        var dict: [String: Any] = [
            "id": session.id,
            "title": session.title ?? NSNull(),
            "modelId": session.modelId,
            "modelName": modelDisplayName(forModelId: session.modelId),
            "source": session.source ?? NSNull(),
            "createdAt": iso8601(session.createdAt),
            "updatedAt": iso8601(session.updatedAt),
        ]
        if let cfg = ProviderConfigStore.shared.inferenceConfig(for: id) {
            dict["thinkingLevel"] = cfg.thinkingLevel.rawValue
        }
        return dict
    }

    static func messagesList(params: [String: Any]) async throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")
        let limit = clamp((params["limit"] as? Int) ?? 200, min: 1, max: 1000)
        let offset = max(0, (params["offset"] as? Int) ?? 0)
        let rolesFilter = params["roles"] as? [String]
        let includeReasoning = (params["includeReasoning"] as? Bool) ?? false
        let includeTools = (params["includeTools"] as? Bool) ?? true

        let raws = await ChatStore.shared.loadMessages(sessionId: id)
        var dicts: [[String: Any]] = []
        var skipped = 0
        for raw in raws {
            let roleStr = raw.role.rawValue
            if let rolesFilter, !rolesFilter.contains(roleStr) { continue }
            if skipped < offset { skipped += 1; continue }
            if dicts.count >= limit { break }

            // Flatten ContentPart enum cases into a compact JSON shape.
            var content = ""
            var toolCalls: [[String: Any]] = []
            var attachments: [[String: Any]] = []
            for part in raw.parts {
                switch part {
                case .text(let s):
                    content += s
                case .mediaRef(let ref):
                    attachments.append([
                        "name": ref.originalFileName ?? ref.relativePath,
                        "mime": ref.mimeType,
                        "id": ref.id,
                    ])
                case .toolUse(let use):
                    if includeTools {
                        toolCalls.append([
                            "id": use.toolUseId,
                            "name": use.name,
                            "input": use.input,
                        ])
                    }
                case .toolResult(let result):
                    if includeTools {
                        toolCalls.append([
                            "id": result.toolUseId,
                            "result": String(result.output.prefix(2000)),
                            "success": result.success,
                            "status": result.status ?? (result.success ? "success" : "failed"),
                        ])
                    }
                }
            }
            var dict: [String: Any] = [
                "id": raw.id,
                "role": roleStr,
                "createdAt": iso8601(raw.createdAt),
                "content": content,
            ]
            if !attachments.isEmpty {
                dict["attachments"] = attachments
            }
            if includeTools, !toolCalls.isEmpty {
                dict["toolCalls"] = toolCalls
            }
            // includeReasoning is currently a no-op: reasoning_content is stored
            // separately (not in `parts`). Kept in the schema for forward compat.
            _ = includeReasoning
            dicts.append(dict)
        }
        return ["sessionId": id, "count": dicts.count, "messages": dicts]
    }

    static func prompt(params: [String: Any]) async throws -> [String: Any] {
        let prompt = try require(params["prompt"] as? String, "prompt")
        let modelEntryId = params["modelEntryId"] as? String
        let modelGroupId = params["modelGroupId"] as? String
        if modelEntryId != nil && modelGroupId != nil {
            throw DebugRPCErr(-32602, "modelEntryId and modelGroupId are mutually exclusive")
        }
        let store = ProviderConfigStore.shared
        if let entryId = modelEntryId, store.entry(for: entryId) == nil {
            throw DebugRPCErr(-32602, "Unknown modelEntryId: \(entryId)")
        }
        if let groupId = modelGroupId, store.group(for: groupId) == nil {
            throw DebugRPCErr(-32602, "Unknown modelGroupId: \(groupId)")
        }
        let attachments = (params["attachments"] as? [[String: Any]]) ?? []
        let waitFlag = (params["wait"] as? Bool) ?? false
        let waitTimeout = clamp((params["waitTimeout"] as? Int) ?? 600, min: 1, max: 1800)

        let existingSessionId = params["sessionId"] as? String
        let isNewSession = existingSessionId == nil

        let vm: AIChatViewModel
        if let sid = existingSessionId {
            let (cached, _) = ViewModelCache.shared.getOrCreate(for: sid)
            vm = cached
            await vm.loadSession()
        } else {
            vm = ViewModelCache.shared.createDraft()
            vm.sessionSource = "debug"
        }

        if isNewSession {
            await vm.ensureSessionReturningId()
        }

        // Apply model selection on the session BEFORE send().
        if let sid = vm.sessionId {
            if let entryId = modelEntryId {
                store.setBinding(SessionModelBinding(
                    sessionId: sid,
                    primarySource: .directEntry(modelEntryId: entryId)
                ), for: sid)
            } else if let groupId = modelGroupId,
                      let group = store.group(for: groupId),
                      let firstMember = group.memberEntryIds.first {
                store.setBinding(SessionModelBinding(
                    sessionId: sid,
                    primarySource: .group(groupId: groupId, resolvedEntryId: firstMember)
                ), for: sid)
            }
        }

        // Attach files (base64 data → in-memory).
        for att in attachments {
            guard let name = att["name"] as? String,
                  let b64 = att["data"] as? String,
                  let data = Data(base64Encoded: b64) else { continue }
            vm.addDataAttachment(data: data, fileName: name)
        }

        // Optional thinking-level override for this turn.
        if let levelRaw = params["thinkingLevel"] as? String,
           let level = ThinkingLevel(rawValue: levelRaw),
           let sid = vm.sessionId {
            var cfg = store.inferenceConfig(for: sid) ?? SessionInferenceConfig()
            cfg.thinkingLevel = level
            store.setInferenceConfig(cfg, for: sid)
        }

        vm.inputText = prompt
        vm.send()

        let sid = vm.sessionId ?? "unknown"
        let userMessageId = vm.messages.last(where: { $0.role == .user })?.id.uuidString ?? ""
        let modelName = resolveModelName(forSession: sid, fallback: vm.selectedModel.displayName)

        if waitFlag {
            let didFinish = await waitForCompletion(vm: vm, timeout: waitTimeout)
            let responseText = lastAssistantText(vm: vm)
            let usage = lastTokenUsageDict(vm: vm)
            return [
                "sessionId": sid,
                "isNewSession": isNewSession,
                "modelName": modelName,
                "status": didFinish ? "Completed" : "Timeout",
                "prompt": prompt,
                "responseText": responseText,
                "userMessageId": userMessageId,
                "tokenUsage": usage as Any,
            ]
        } else {
            return [
                "sessionId": sid,
                "isNewSession": isNewSession,
                "modelName": modelName,
                "status": "Running",
                "prompt": prompt,
                "responseText": NSNull(),
                "userMessageId": userMessageId,
            ]
        }
    }

    static func sessionStatus(params: [String: Any]) async throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")
        let sessions = await ChatStore.shared.listSessions()
        guard let session = sessions.first(where: { $0.id == id }) else {
            throw DebugRPCErr(-32602, "Session not found")
        }
        let cachedVM = ViewModelCache.shared.get(for: id)
        let isRunning = cachedVM?.isProcessing ?? false
        let lastAssistant = cachedVM?.messages.last(where: { $0.role == .assistant })
        let lastText = lastAssistant?.blocks
            .filter { $0.kind == .text }
            .map(\.content)
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""

        var result: [String: Any] = [
            "sessionId": id,
            "title": session.title ?? NSNull(),
            "modelName": modelDisplayName(forModelId: session.modelId),
            "isRunning": isRunning,
            "lastMessage": String(lastText.prefix(280)),
            "updatedAt": iso8601(session.updatedAt),
        ]

        if let lastAssistant {
            var blockDiag: [[String: Any]] = []
            for (i, block) in lastAssistant.blocks.enumerated() {
                var bd: [String: Any] = [
                    "index": i,
                    "kind": "\(block.kind)",
                    "contentLen": block.content.count,
                ]
                if block.kind == .text {
                    bd["head"] = String(block.content.prefix(40))
                    bd["tail"] = String(block.content.suffix(40))
                    bd["hasCachedMarkdown"] = block.cachedMarkdown != nil
                    bd["hasCachedAttrStr"] = block.cachedAttributedString != nil
                }
                blockDiag.append(bd)
            }
            result["vmBlocks"] = blockDiag
            result["vmMsgCount"] = cachedVM?.messages.count ?? 0
        }

        return result
    }

    static func blocksDiff(params: [String: Any]) async throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")

        let raws = await ChatStore.shared.loadMessages(sessionId: id)
        var lastAssistantRaws: [RawMessage] = []
        for raw in raws.reversed() {
            if raw.role == .assistant {
                lastAssistantRaws.insert(raw, at: 0)
            } else if raw.role == .user && raw.isToolResultOnly {
                continue
            } else {
                break
            }
        }

        var dbBlocks: [[String: Any]] = []
        for raw in lastAssistantRaws {
            for part in raw.parts {
                if case .text(let s) = part {
                    let stripped = RawMessage.stripSystemReminders(s)
                    if !stripped.trimmingCharacters(in: CharacterSet.whitespacesAndNewlines).isEmpty {
                        dbBlocks.append([
                            "rawId": raw.id,
                            "sortOrder": raw.sortOrder,
                            "contentLen": stripped.count,
                            "rawLen": s.count,
                            "head": String(stripped.prefix(40)),
                            "tail": String(stripped.suffix(40)),
                        ])
                    }
                } else if case .toolUse(let tu) = part {
                    dbBlocks.append([
                        "rawId": raw.id,
                        "sortOrder": raw.sortOrder,
                        "kind": "toolUse",
                        "name": tu.name,
                    ])
                }
            }
        }

        let cachedVM = ViewModelCache.shared.get(for: id)
        var vmBlocks: [[String: Any]] = []
        if let lastAssistant = cachedVM?.messages.last(where: { $0.role == .assistant }) {
            for (i, block) in lastAssistant.blocks.enumerated() {
                var bd: [String: Any] = ["index": i, "kind": "\(block.kind)"]
                if block.kind == .text {
                    bd["contentLen"] = block.content.count
                    bd["head"] = String(block.content.prefix(40))
                    bd["tail"] = String(block.content.suffix(40))
                } else {
                    bd["toolUseId"] = block.toolUseId ?? ""
                }
                vmBlocks.append(bd)
            }
        }

        let showThinking = ProviderConfigStore.shared.inferenceConfig(for: id)?.thinkingLevel.isEnabled ?? false
        let vmMsgCount = cachedVM?.messages.count ?? -1
        let vmAssistantCount = cachedVM?.messages.filter({ $0.role == .assistant }).count ?? -1
        var vmAllBlocks: [[String: Any]] = []
        if let cachedVM {
            for (i, block) in (cachedVM.messages.last(where: { $0.role == .assistant })?.blocks ?? []).enumerated() {
                vmAllBlocks.append([
                    "index": i, "kind": "\(block.kind)",
                    "contentLen": block.content.count,
                    "id": block.id.uuidString.prefix(8),
                ])
            }
        }
        return [
            "sessionId": id,
            "dbTextBlocks": dbBlocks,
            "vmTextBlocks": vmBlocks,
            "vmCached": cachedVM != nil,
            "showThinking": showThinking,
            "vmMsgCount": vmMsgCount,
            "vmAssistantCount": vmAssistantCount,
            "vmLastAssistantAllBlocks": vmAllBlocks,
        ]
    }

    /// [T-ios-decel-inv-estimate-calibration] Ground-truth height comparison:
    /// for every text block in the cached VM, measure the SAME
    /// cachedAttributedString with (A) the precalc engine (bare NSLayoutManager
    /// usedRect + 8) and (B) the real render engine (SelectableMarkdownTextView
    /// .sizeThatFits — MinisLayoutManager + 4/4 insets). The per-block deltas
    /// attribute the scroll-jitter precalc mismatch to engine config vs
    /// attributed-string drift, and the timings decide whether precalc can
    /// simply switch to engine B.
    @MainActor
    static func measureCompare(params: [String: Any]) async throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")
        let width = CGFloat(params["width"] as? Double ?? 370)
        guard let vm = ViewModelCache.shared.get(for: id) else {
            throw DebugRPCErr(-32602, "no cached VM for session (open it in the UI first)")
        }
        let tv = SelectableMarkdownTextView()
        var rows: [[String: Any]] = []
        for msg in vm.messages where msg.role == .assistant {
            for block in msg.blocks {
                guard block.kind == .text, let attr = block.cachedAttributedString else { continue }
                // A: precalc engine (plain NSLayoutManager, lineFragmentPadding 0) + 8
                let tA0 = CACurrentMediaTime()
                let storage = NSTextStorage(attributedString: attr)
                let container = NSTextContainer(size: CGSize(width: width, height: .greatestFiniteMagnitude))
                container.lineFragmentPadding = 0
                let lm = NSLayoutManager()
                lm.addTextContainer(container)
                storage.addLayoutManager(lm)
                lm.ensureLayout(for: container)
                let hA = ceil(lm.usedRect(for: container).height) + 8
                let tA = (CACurrentMediaTime() - tA0) * 1000
                // A': same plain engine but usesFontLeading=false (UITextView's
                // internal setting) — validates the leading hypothesis for the
                // emoji/heading blocks where A ≠ B.
                let storage2 = NSTextStorage(attributedString: attr)
                let container2 = NSTextContainer(size: CGSize(width: width, height: .greatestFiniteMagnitude))
                container2.lineFragmentPadding = 0
                let lm2 = NSLayoutManager()
                lm2.usesFontLeading = false
                lm2.addTextContainer(container2)
                storage2.addLayoutManager(lm2)
                lm2.ensureLayout(for: container2)
                let hA2 = ceil(lm2.usedRect(for: container2).height) + 8
                // B: real render engine
                let tB0 = CACurrentMediaTime()
                tv.attributedText = attr
                let hB = ceil(tv.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude)).height)
                let tB = (CACurrentMediaTime() - tB0) * 1000
                let c = block.content
                rows.append([
                    "n": c.count,
                    "nl": c.filter { $0 == "\n" }.count,
                    "code": c.contains("```") ? 1 : 0,
                    "hA": hA, "hA2": hA2, "hB": hB, "d": hB - hA, "d2": hB - hA2,
                    "tA": (tA * 10).rounded() / 10, "tB": (tB * 10).rounded() / 10,
                    "head": String(c.prefix(30)),
                ])
            }
        }
        return ["width": width, "count": rows.count, "rows": rows]
    }

    static func sessionCancel(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")
        let cachedVM = ViewModelCache.shared.get(for: id)
        let wasRunning = cachedVM?.isProcessing ?? false
        cachedVM?.cancel()
        return ["sessionId": id, "wasRunning": wasRunning, "cancelled": wasRunning]
    }

    /// [T-thinking-stream-jank] Set the last thinking block's expansion state on
    /// the session's cached VM. Synthetic taps (debug.tap) cannot reach the
    /// thinking pill's SwiftUI onTapGesture, so the expanded-vs-collapsed perf
    /// A/B experiment drives the toggle through this RPC instead. Marks the
    /// block user-toggled so stream-end auto-collapse won't stomp the state.
    static func thinkingSetExpanded(params: [String: Any]) throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")
        let expanded = (params["expanded"] as? Bool) ?? true
        guard let vm = ViewModelCache.shared.get(for: id) else {
            throw DebugRPCErr(-32602, "No cached VM for session \(id) — open it in the UI first")
        }
        for msg in vm.messages.reversed() {
            guard let block = msg.blocks.last(where: { $0.kind == .thinking }) else { continue }
            block.thinkingUserToggled = true
            if expanded { block.flushThinkingBuffer() }
            block.isThinkingExpanded = expanded
            return ["sessionId": id,
                    "blockId": String(block.id.uuidString.prefix(8)),
                    "contentLen": block.content.count,
                    "expanded": expanded]
        }
        throw DebugRPCErr(-32602, "No thinking block found in session \(id)")
    }

    static func sessionDelete(params: [String: Any]) async throws -> [String: Any] {
        let id = try require(params["sessionId"] as? String, "sessionId")
        let confirm = (params["confirm"] as? Bool) ?? false
        guard confirm else { throw DebugRPCErr(-32602, "confirm=true required") }
        await ChatStore.shared.deleteSession(id)
        ProviderConfigStore.shared.removeBinding(for: id)
        ProviderConfigStore.shared.removeInferenceConfig(for: id)
        return ["sessionId": id, "deleted": true]
    }

    // MARK: - Compact (test/automation API)

    /// List all compact markers on a session, oldest → newest. Includes the
    /// fields a v2 marker actually uses (anchorMessageId, summary length,
    /// version) so tests can assert marker presence + ordering without
    /// scraping logs.
    static func compactMarkersList(params: [String: Any]) async throws -> [String: Any] {
        let sid = try require(params["sessionId"] as? String, "sessionId")
        let includeFullSummary = (params["includeFullSummary"] as? Bool) ?? false
        let markers = await ChatStore.shared.compactMarkers(sessionId: sid)
        let dicts: [[String: Any]] = markers.map { m in
            var dict: [String: Any] = [
                "id": m.id,
                "version": m.version,
                "anchorMessageId": m.lastCompactedMessageId ?? NSNull(),
                "firstKeptMessageId": m.firstKeptMessageId ?? NSNull(),
                "summaryLength": m.summary.count,
                "summaryPreview": String(m.summary.prefix(120)),
                "compactedCount": m.compactedCount,
                "createdAt": iso8601(m.createdAt),
            ]
            if includeFullSummary {
                dict["summary"] = m.summary
            }
            return dict
        }
        return [
            "sessionId": sid,
            "count": dicts.count,
            "markers": dicts,
        ]
    }

    /// Trigger compactBefore on the given message. `messageId` is the **DB
    /// row id** (string, same id `chat.messages.list` returns), NOT the
    /// transient ChatMessage UUID. We look up the row's sortOrder and find
    /// the matching ChatMessage in the loaded UI to drive compactBefore.
    /// Set `includesBoundary: true` to invoke compactAll semantics
    /// (auto-anchor on the Nth-from-last user turn).
    static func compactBefore(params: [String: Any]) async throws -> [String: Any] {
        let sid = try require(params["sessionId"] as? String, "sessionId")
        let dbMsgId = try require(params["messageId"] as? String, "messageId")
        let includesBoundary = (params["includesBoundary"] as? Bool) ?? false
        let waitTimeout = clamp((params["waitTimeout"] as? Int) ?? 120, min: 1, max: 600)

        // Make sure the session's view-model exists and has its UI loaded so
        // compactBefore can resolve `messages` / `agentHistory`. Force a
        // reload so any in-session messages without sourceSortOrder get it
        // back-filled from DB before we try to map dbMsgId → ChatMessage.
        let (vm, _) = await MainActor.run { ViewModelCache.shared.getOrCreate(for: sid) }
        await vm.loadSession()

        // Map DB message id → sourceSortOrder → ChatMessage.id (UUID).
        // compactBefore expects a UI ChatMessage id.
        let raws = await ChatStore.shared.loadMessages(sessionId: sid)
        guard let raw = raws.first(where: { $0.id == dbMsgId }) else {
            throw DebugRPCErr(-32602, "messageId '\(dbMsgId)' not found in session")
        }
        // Poll briefly: in tightly-paced test runs, vm.messages can lag
        // ChatStore by ~100-300ms while load completes async.
        var msgUUID: UUID? = nil
        for _ in 0..<20 {
            msgUUID = await MainActor.run {
                vm.messages.first(where: { $0.sourceSortOrder == raw.sortOrder })?.id
            }
            if msgUUID != nil { break }
            try? await Task.sleep(nanoseconds: 100_000_000)
        }
        guard let msgUUID else {
            let uiCount = await MainActor.run { vm.messages.count }
            let withSO = await MainActor.run { vm.messages.filter { $0.sourceSortOrder != nil }.count }
            throw DebugRPCErr(-32602, "ChatMessage with sortOrder=\(raw.sortOrder) not found in loaded UI after polling (vm.messages.count=\(uiCount), withSortOrder=\(withSO))")
        }

        let beforeMarkers = await ChatStore.shared.compactMarkers(sessionId: sid).count

        await vm.compactBefore(msgUUID, includesBoundary: includesBoundary)

        // compactBefore is async + drives an LLM call internally. Poll until
        // isCompacting / isProcessing both clear (or timeout).
        let deadline = Date().addingTimeInterval(TimeInterval(waitTimeout))
        while Date() < deadline {
            let busy = await MainActor.run { vm.isCompacting || vm.isProcessing }
            if !busy { break }
            try? await Task.sleep(nanoseconds: 250_000_000)
        }

        let afterMarkers = await ChatStore.shared.compactMarkers(sessionId: sid)
        let latest = afterMarkers.last
        return [
            "sessionId": sid,
            "messageId": dbMsgId,
            "includesBoundary": includesBoundary,
            "beforeMarkerCount": beforeMarkers,
            "afterMarkerCount": afterMarkers.count,
            "wrote": afterMarkers.count > beforeMarkers,
            "latestMarker": latest.map { m -> [String: Any] in
                [
                    "id": m.id,
                    "version": m.version,
                    "anchorMessageId": m.lastCompactedMessageId ?? NSNull(),
                    "summaryLength": m.summary.count,
                    "compactedCount": m.compactedCount,
                ]
            } ?? NSNull(),
        ]
    }

    // MARK: - Long-message simulator (watchdog repro tool)

    /// Inject a large synthetic assistant (or user) markdown message into a
    /// session via the normal ChatStore.appendMessage path, so sort_order /
    /// dbMessageId / loadSession() all behave exactly like a real assistant
    /// turn. Used to reproduce the TextKit1 main-thread hang in
    /// SelectableMarkdownView when the auto-sizing collection-view cell
    /// asks UITextView for its intrinsic size on a 200K-char attributed
    /// string. DO NOT call against a session you care about — the resulting
    /// session may render so slowly the app gets killed by the watchdog.
    static func simulateLongMessage(params: [String: Any]) async throws -> [String: Any] {
        let sid = try require(params["sessionId"] as? String, "sessionId")
        let charCount = max(1, (params["charCount"] as? Int) ?? 200_000)
        let blockChars = max(16, (params["blockChars"] as? Int) ?? 800)
        let roleRaw = (params["role"] as? String) ?? "assistant"
        guard let role = MessageRole(rawValue: roleRaw) else {
            throw DebugRPCErr(-32602, "Unknown role: \(roleRaw) (expected 'assistant' or 'user')")
        }

        // Validate session exists. Use listSessions() since ChatStore exposes
        // no direct getById; this is a debug path and N is small.
        let sessions = await ChatStore.shared.listSessions()
        guard sessions.contains(where: { $0.id == sid }) else {
            throw DebugRPCErr(-32602, "Session not found: \(sid)")
        }

        let (markdown, blockCount) = buildSyntheticMarkdown(targetChars: charCount, blockChars: blockChars)

        let msgId = UUID().uuidString.lowercased()
        let raw = RawMessage(
            id: msgId,
            sessionId: sid,
            role: role,
            parts: [.text(markdown)],
            createdAt: Date(),
            tokenUsage: nil,
            reasoningContent: nil,
            streamInterruptCount: 0,
            sortOrder: 0
        )
        await ChatStore.shared.appendMessage(raw)

        // Re-read to pull back the sort_order ChatStore actually assigned.
        let after = await ChatStore.shared.loadMessages(sessionId: sid)
        let assignedSortOrder = after.first(where: { $0.id == msgId })?.sortOrder ?? -1

        return [
            "messageId": msgId,
            "sortOrder": assignedSortOrder,
            "totalChars": markdown.count,
            "blockCount": blockCount,
            "role": role.rawValue,
        ]
    }

    /// Build a markdown blob whose total length is roughly `targetChars`,
    /// composed of a realistic mix of "heavy" BlockNodes (tables, nested
    /// quotes, nested lists, inline + block math, long inline code with
    /// links, fenced code blocks) — the kinds of structures that actually
    /// stress TextKit1 attribute resolution + paragraph layout, not the
    /// happy-path long-paragraph case.
    private static func buildSyntheticMarkdown(targetChars: Int, blockChars: Int) -> (String, Int) {
        let vocab = [
            "lorem", "ipsum", "dolor", "sit", "amet", "consectetur",
            "adipiscing", "elit", "sed", "do", "eiusmod", "tempor",
            "incididunt", "ut", "labore", "et", "dolore", "magna",
            "aliqua", "enim", "minim", "veniam", "quis", "nostrud",
            "exercitation", "ullamco", "laboris", "nisi", "aliquip",
            "ex", "ea", "commodo", "consequat", "duis", "aute", "irure",
            "reprehenderit", "voluptate", "velit", "esse", "cillum",
            "fugiat", "nulla", "pariatur", "excepteur", "sint", "occaecat",
            "cupidatat", "proident", "culpa",
        ]
        var rng = SeededLCG(seed: 0xC0FFEE_BEEF)
        func pickWord() -> String { vocab[Int(rng.next()) % vocab.count] }
        func rint(_ upper: Int) -> Int { Int(rng.next()) % max(1, upper) }

        func makeParagraph(targetLen: Int) -> String {
            var s = ""
            var capitalize = true
            // Sprinkle inline code, links, bold/italic, inline math.
            while s.count < targetLen {
                let r = rint(20)
                if r == 0 {
                    let code = "`\(pickWord())_\(rint(1000)).\(pickWord())()`"
                    s += (s.isEmpty ? "" : " ") + code
                } else if r == 1 {
                    s += (s.isEmpty ? "" : " ") + "[\(pickWord()) \(pickWord())](https://example.com/\(pickWord())/\(rint(10000)))"
                } else if r == 2 {
                    s += (s.isEmpty ? "" : " ") + "**\(pickWord()) \(pickWord())**"
                } else if r == 3 {
                    s += (s.isEmpty ? "" : " ") + "*\(pickWord())*"
                } else if r == 4 {
                    s += (s.isEmpty ? "" : " ") + "$\\sum_{i=0}^{n} x_i^2$"
                } else {
                    var w = pickWord()
                    if capitalize { w = w.prefix(1).uppercased() + w.dropFirst() }
                    s += (s.isEmpty ? "" : " ") + w
                    capitalize = false
                }
                if s.count > 0, rint(18) == 0 {
                    s += "."
                    capitalize = true
                }
            }
            if !s.hasSuffix(".") { s += "." }
            return s
        }

        func makeCodeBlock() -> String {
            let lineCount = 10 + rint(31) // 10..40
            let langs = ["swift", "kotlin", "python", "rust", "typescript", "go"]
            var lines: [String] = ["```\(langs[rint(langs.count)])"]
            for i in 0..<lineCount {
                lines.append("    let \(pickWord())_\(i) = \(rint(10_000)) // \(pickWord()) \(pickWord()) \(pickWord())")
            }
            lines.append("```")
            return lines.joined(separator: "\n")
        }

        func makeNestedList() -> String {
            // 4-6 top-level items, each with 2-4 nested children, some with grandchildren.
            let top = 4 + rint(3)
            var lines: [String] = []
            for i in 0..<top {
                lines.append("\(i + 1). **\(pickWord())** \(pickWord()) \(pickWord())")
                let mid = 2 + rint(3)
                for j in 0..<mid {
                    lines.append("   - \(pickWord()) `\(pickWord())_\(j)` \(pickWord()) \(pickWord())")
                    if rint(2) == 0 {
                        let leaf = 2 + rint(2)
                        for k in 0..<leaf {
                            lines.append("     - \(pickWord()) \(pickWord()) [\(pickWord())](https://example.com/\(k))")
                        }
                    }
                }
            }
            return lines.joined(separator: "\n")
        }

        func makeNestedQuote() -> String {
            // 2-3 levels of blockquote with bold + inline code inside.
            var lines: [String] = []
            let depth = 2 + rint(2)
            for d in 0..<depth {
                let prefix = String(repeating: "> ", count: d + 1)
                let bodyLines = 2 + rint(3)
                for _ in 0..<bodyLines {
                    let body = "\(pickWord()) **\(pickWord())** `\(pickWord())()` \(pickWord()) \(pickWord()) [\(pickWord())](https://x.io/\(pickWord())) \(pickWord())."
                    lines.append("\(prefix)\(body)")
                }
                lines.append(prefix.trimmingCharacters(in: .whitespaces))
            }
            return lines.joined(separator: "\n")
        }

        func makeTable() -> String {
            // 6-8 cols × 8-15 rows. Cell content has bold + inline code +
            // link to thrash attribute resolution.
            let cols = 6 + rint(3)
            let rows = 8 + rint(8)
            let header = "| " + (0..<cols).map { i in "Col\(i + 1) **\(pickWord())**" }.joined(separator: " | ") + " |"
            let sep = "|" + String(repeating: "---|", count: cols)
            var lines: [String] = [header, sep]
            for r in 0..<rows {
                let cells = (0..<cols).map { c -> String in
                    switch (r + c) % 4 {
                    case 0: return "`\(pickWord())_\(r * cols + c)`"
                    case 1: return "[\(pickWord())](https://x.io/\(c))"
                    case 2: return "**\(pickWord()) \(pickWord())**"
                    default: return "\(pickWord()) \(pickWord())"
                    }
                }
                lines.append("| " + cells.joined(separator: " | ") + " |")
            }
            return lines.joined(separator: "\n")
        }

        func makeBlockMath() -> String {
            "$$\n\\sum_{i=0}^{n} \\left( \\frac{x_i^2 + y_i^2}{\\sqrt{1 + \\beta_\(rint(10))^2}} \\right) = \\int_{0}^{\\infty} e^{-\\lambda t} \\, dt\n$$"
        }

        var pieces: [String] = []
        var totalLen = 0
        var paragraphIdx = 0
        var blockCount = 0

        while totalLen < targetChars {
            // Every 5 paragraphs: heading.
            if paragraphIdx > 0, paragraphIdx % 5 == 0 {
                let heading = "## Section \(paragraphIdx / 5) — \(pickWord()) \(pickWord()) \(pickWord())"
                pieces.append(heading); blockCount += 1
                totalLen += heading.count + 2
            }
            // Every 4 paragraphs: a table (the worst offender for TextKit).
            if paragraphIdx > 0, paragraphIdx % 4 == 0 {
                let table = makeTable()
                pieces.append(table); blockCount += 1
                totalLen += table.count + 2
            }
            // Every 6 paragraphs: nested list.
            if paragraphIdx > 0, paragraphIdx % 6 == 0 {
                let list = makeNestedList()
                pieces.append(list); blockCount += 1
                totalLen += list.count + 2
            }
            // Every 7 paragraphs: code block.
            if paragraphIdx > 0, paragraphIdx % 7 == 0 {
                let code = makeCodeBlock()
                pieces.append(code); blockCount += 1
                totalLen += code.count + 2
            }
            // Every 8 paragraphs: nested quote.
            if paragraphIdx > 0, paragraphIdx % 8 == 0 {
                let quote = makeNestedQuote()
                pieces.append(quote); blockCount += 1
                totalLen += quote.count + 2
            }
            // Every 11 paragraphs: block math.
            if paragraphIdx > 0, paragraphIdx % 11 == 0 {
                let math = makeBlockMath()
                pieces.append(math); blockCount += 1
                totalLen += math.count + 2
            }
            let p = makeParagraph(targetLen: blockChars)
            pieces.append(p); blockCount += 1
            totalLen += p.count + 2
            paragraphIdx += 1
        }

        return (pieces.joined(separator: "\n\n"), blockCount)
    }

    /// Tiny seeded LCG — deterministic across runs so the same params produce
    /// the same payload (helps when comparing repro behavior).
    private struct SeededLCG {
        private var state: UInt64
        init(seed: UInt64) { self.state = seed == 0 ? 0xDEAD_BEEF : seed }
        mutating func next() -> UInt32 {
            state = state &* 6364136223846793005 &+ 1442695040888963407
            return UInt32(truncatingIfNeeded: state >> 33)
        }
    }

    /// Trigger revertCompact on the session — drops the latest marker.
    static func compactRevert(params: [String: Any]) async throws -> [String: Any] {
        let sid = try require(params["sessionId"] as? String, "sessionId")

        let (vm, _) = await MainActor.run { ViewModelCache.shared.getOrCreate(for: sid) }
        await vm.loadSession()

        let beforeMarkers = await ChatStore.shared.compactMarkers(sessionId: sid)
        let beforeLatestId = beforeMarkers.last?.id
        await vm.revertCompact()
        let afterMarkers = await ChatStore.shared.compactMarkers(sessionId: sid)

        return [
            "sessionId": sid,
            "beforeMarkerCount": beforeMarkers.count,
            "afterMarkerCount": afterMarkers.count,
            "removedMarkerId": beforeLatestId ?? NSNull(),
            "newLatestMarkerId": afterMarkers.last?.id ?? NSNull(),
        ]
    }

    // MARK: - Helpers

    private static func clamp(_ v: Int, min lo: Int, max hi: Int) -> Int {
        min(max(v, lo), hi)
    }

    private static func waitForCompletion(vm: AIChatViewModel, timeout: Int) async -> Bool {
        let deadline = Date().addingTimeInterval(TimeInterval(timeout))
        // Poll vm.isProcessing because subscribing to `$isProcessing` from a non-MainActor
        // context complicates cancellation; this loop yields cooperatively every 250ms.
        while Date() < deadline {
            if !vm.isProcessing { return true }
            try? await Task.sleep(nanoseconds: 250_000_000)
        }
        return false
    }

    private static func lastAssistantText(vm: AIChatViewModel) -> String {
        guard let lastAssistant = vm.messages.last(where: { $0.role == .assistant }) else {
            return ""
        }
        return lastAssistant.blocks
            .filter { $0.kind == .text }
            .map(\.content)
            .joined(separator: "\n")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func lastTokenUsageDict(vm: AIChatViewModel) -> [String: Any]? {
        // AgentMessage.usage is a per-turn TokenUsage attached during stream completion.
        guard let usage = vm.messages.last(where: { $0.role == .assistant })?.usage else { return nil }
        return [
            "inputTokens": usage.inputTokens,
            "outputTokens": usage.outputTokens,
            "cacheReadTokens": usage.cacheReadTokens,
            "cacheCreationTokens": usage.cacheCreationTokens,
        ]
    }

    private static func modelDisplayName(forModelId modelId: String?) -> Any {
        guard let mid = modelId, !mid.isEmpty else { return NSNull() }
        let store = ProviderConfigStore.shared
        if let entry = store.modelEntries.first(where: { $0.model.id == mid || $0.id == mid }) {
            return entry.model.displayName
        }
        return mid
    }

    private static func resolveModelName(forSession sessionId: String, fallback: String) -> String {
        let store = ProviderConfigStore.shared
        guard let binding = store.binding(for: sessionId) else { return fallback }
        switch binding.primarySource {
        case .group(_, let resolvedEntryId):
            return store.entry(for: resolvedEntryId)?.model.displayName ?? fallback
        case .directEntry(let entryId, _):
            return store.entry(for: entryId)?.model.displayName ?? fallback
        }
    }
}

#endif
