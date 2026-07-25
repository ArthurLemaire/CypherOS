import Foundation

/// Built-in field registrations. This file is the single place to add
/// or remove a setting from the agent-facing surface. Each section is
/// keyed by topic; topic names line up with the CLI subcommands.
///
/// Registration is idempotent and runs once at app launch from
/// `MinisApp.onAppear` via `ConfigRegistry.shared.registerBuiltinsIfNeeded()`.
extension ConfigRegistry {
    @MainActor
    static func registerBuiltins(into r: ConfigRegistry) {
        registerSelfMeta(into: r)
        registerAppearance(into: r)
        registerChat(into: r)
        registerFiles(into: r)
        registerBrowser(into: r)
        registerSpeech(into: r)
        registerBackground(into: r)
        registerLogs(into: r)
        registerProviderCollections(into: r)
        registerDefaults(into: r)
        registerSync(into: r)
        registerRootfsMirror(into: r)
        registerSession(into: r)
        registerSoul(into: r)
        registerMemory(into: r)
    }

    // MARK: Memory — global default toggle for the persistent memory feature
    //
    // `memory.enabled` mirrors the Settings → Memory switch
    // (MemoryManagementView, AppStorage key "memory.global.enabled").
    // It is the global DEFAULT applied to newly created sessions: a new
    // chat starts with its per-session memoryEnabled seeded from this
    // value (see ChatStore.getMemoryEnabled). It does NOT retroactively
    // flip already-open sessions — those carry their own per-session
    // toggle, changed via the /memory slash command.
    //
    // When off, new sessions skip auto-injection of GLOBAL.md + recent
    // daily logs into the system prompt AND drop the memory_get /
    // memory_write tools from the registered tool list
    // (see AIChatViewModel.makeAgentTools). So this one bool gates both
    // injection and tool access for sessions that inherit the default.

    @MainActor
    private static func registerMemory(into r: ConfigRegistry) {
        r.register(AppStorageBoolField(
            path: "memory.enabled",
            displayName: "Memory enabled (global default)",
            description: "Default for whether NEW chat sessions start with memory on. When on, a new session auto-injects GLOBAL.md + recent daily logs into the system prompt and exposes the memory_get / memory_write tools. When off, new sessions get neither. Already-open sessions keep their own per-session setting (toggle with /memory) and are not changed by this.",
            userDefaultsKey: "memory.global.enabled",
            defaultValue: true
        ))
    }

    // MARK: Soul — SOUL.md (persistent personality / identity file)
    //
    // Each field reads/writes one piece of SOUL.md (path:
    // <minisMemoryPersistentDir>/SOUL.md). The four fields below mirror
    // the SOUL Settings UI exactly; everything goes through SoulStore so
    // the on-disk file, the cached metadata, the chat bubble header, the
    // sidebar title, and the system-prompt builder all observe the same
    // .soulMdChanged notification fired by SoulStore.save().
    //
    // emoji is intentionally NOT exposed — the user-facing UI has it
    // locked to ✨ (commit 9240f58); allowing the agent to mutate the
    // on-disk emoji field would create the appearance of customization
    // without any UI surface to read it back.

    @MainActor
    private static func registerSoul(into r: ConfigRegistry) {
        // Helper: load current SOUL.md or synthesize a default-meta +
        // empty-body file so writes against a missing/blank file still
        // work (we'll create the file on first save).
        @MainActor func currentFile() -> SoulFile {
            SoulStore.load() ?? SoulFile(metadata: .default, body: "")
        }

        // Helper: rewrite SOUL.md with one of the metadata fields replaced.
        // Re-reads on every write so two consecutive set calls compose
        // (e.g. set name then style without losing the prior write).
        @MainActor func updateMetadata(_ mutate: (inout SoulMetadata) -> Void) throws {
            var file = currentFile()
            mutate(&file.metadata)
            do {
                try SoulStore.save(file)
            } catch {
                throw ConfigError.io("SOUL.md write failed: \(error.localizedDescription)")
            }
        }

        r.register(ClosureField(
            path: "soul.name",
            displayName: "Soul name",
            description: "Assistant display name. Shown in the sidebar title, chat bubble header, and substituted into the identity line of the system prompt (`You are <name>, a capable AI assistant ...`).",
            valueSchema: .string(maxLength: 64),
            risk: .normal, revertable: true,
            reader: { .string(currentFile().metadata.name) },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                let trimmed = s.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else {
                    throw ConfigError.invalidValue("name must not be empty")
                }
                try updateMetadata { $0.name = trimmed }
            }
        ))

        r.register(ClosureField(
            path: "soul.style",
            displayName: "Soul style",
            description: "Short voice / style tag shown in the SOUL.md frontmatter (e.g. \"Warm, direct, opinionated\"). Stored verbatim; not directly injected into the prompt.",
            valueSchema: .string(maxLength: 200),
            risk: .normal, revertable: true,
            reader: { .string(currentFile().metadata.style) },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                try updateMetadata { $0.style = s }
            }
        ))

        r.register(ClosureField(
            path: "soul.lang",
            displayName: "Soul language preference",
            description: "Preferred reply language hint: auto / zh / en. Stored in SOUL.md frontmatter for forward use; the agent should respect it when set non-auto.",
            valueSchema: .stringEnum(["auto", "zh", "en"]),
            risk: .normal, revertable: true,
            reader: {
                // Older SOUL.md files may have no `lang` field — surface
                // "auto" rather than whatever happens to be in the
                // SoulMetadata.default fallback so the contract matches
                // the enum.
                let raw = currentFile().metadata.lang
                let normalized = ["auto", "zh", "en"].contains(raw) ? raw : "auto"
                return .string(normalized)
            },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                try updateMetadata { $0.lang = s }
            }
        ))

        // Personality body. The Settings UI calls this the "Personality
        // Prompt" — same field, different surface. Length cap is a unified
        // 2000-token budget (CJK glyphs + CJK punctuation count one each;
        // Latin words count one each) enforced via SoulStore.isOverLimit;
        // the schema does not carry a byte-level maxLength because a fixed
        // char count would be wrong for non-ASCII text. SoulMDParser
        // injection scrubbing also runs at prompt-build time
        // (SystemPromptBuilder.identitySection), so a stored body with an
        // "ignore previous instructions" line still won't reach the model
        // — but we leave it on disk verbatim so the user can see and fix it.
        r.register(ClosureField(
            path: "soul.body",
            displayName: "Soul personality body",
            description: "Markdown body of SOUL.md — your character and voice. NOT the place for the \"You are X\" identity line (the app owns that template); write only personality / stance / tone guidance. Length cap: 2000 tokens total. CJK glyphs and CJK punctuation count one each; non-CJK text counts whitespace-delimited words. Mixed-language bodies add both kinds together.",
            valueSchema: .string(maxLength: nil),
            risk: .normal, revertable: true,
            reader: { .string(currentFile().body) },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                switch SoulStore.isOverLimit(s) {
                case .ok:
                    break
                case .overLimit(let count, let cap):
                    throw ConfigError.invalidValue("Over limit: \(count) tokens exceeds cap of \(cap). Trim the body — each CJK character and each Latin word counts as one token.")
                }
                var file = currentFile()
                file.body = s
                do {
                    try SoulStore.save(file)
                } catch {
                    throw ConfigError.io("SOUL.md write failed: \(error.localizedDescription)")
                }
            }
        ))
    }

    // MARK: Session — current chat's per-session settings
    //
    // These fields target whichever session is active when the call
    // arrives. Active session is read from `AIChatViewModel.activeSessionId`,
    // which the chat view keeps in sync as the user switches sessions.
    // Reads return null when no session is active; writes throw.
    //
    // The CLI's `--session <id>` flag is intentionally NOT used to
    // redirect target — it only labels the audit row. We don't want
    // an agent in chat A to silently mutate chat B's settings.

    @MainActor
    private static func registerSession(into r: ConfigRegistry) {
        r.register(ClosureField(
            path: "session.thinkingLevel",
            displayName: "Thinking level (current session)",
            description: "off / low / medium / high / xhigh / max / ultra. Applied to the active chat.",
            valueSchema: .stringEnum(["off", "low", "medium", "high", "xhigh", "max", "ultra"]),
            risk: .normal, revertable: true,
            reader: {
                guard let sid = AIChatViewModel.activeSessionId else { return .null }
                let level = ProviderConfigStore.shared.inferenceConfig(for: sid)?.thinkingLevel ?? .off
                return .string(level.rawValue)
            },
            writer: { v in
                guard case .string(let s) = v,
                      let level = ThinkingLevel(rawValue: s) else {
                    throw ConfigError.invalidValue("Unknown thinking level. Valid: \(ThinkingLevel.allCases.map(\.rawValue).joined(separator: ", "))")
                }
                guard let sid = AIChatViewModel.activeSessionId else {
                    throw ConfigError.invalidValue("No active session — open a chat first")
                }
                var cfg = ProviderConfigStore.shared.inferenceConfig(for: sid) ?? SessionInferenceConfig()
                cfg.thinkingLevel = level
                ProviderConfigStore.shared.setInferenceConfig(cfg, for: sid)
            }
        ))

        // Model binding: surfaced as a single string the agent sets to
        // either an entry uuid or a group id. Reader returns the active
        // primary source as `entry:<uuid>` / `group:<id>` so the value
        // round-trips losslessly through the audit log.
        r.register(ClosureField(
            path: "session.primaryModel",
            displayName: "Primary model (current session)",
            description: "Set as `entry:<uuid>` or `group:<id>` (use `models` / `groups` topics to discover ids). Empty clears the binding.",
            valueSchema: .string(maxLength: 200),
            risk: .sensitive, revertable: true,
            reader: {
                guard let sid = AIChatViewModel.activeSessionId,
                      let binding = ProviderConfigStore.shared.binding(for: sid) else {
                    return .string("")
                }
                switch binding.primarySource {
                case .directEntry(let uuid, _):
                    return .string("entry:\(uuid)")
                case .group(let gid, _):
                    return .string("group:\(gid)")
                }
            },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                guard let sid = AIChatViewModel.activeSessionId else {
                    throw ConfigError.invalidValue("No active session — open a chat first")
                }
                let store = ProviderConfigStore.shared
                if s.isEmpty {
                    store.removeBinding(for: sid)
                    return
                }
                let source = try parseModelSource(s, store: store)
                let existing = store.binding(for: sid)
                let binding = SessionModelBinding(
                    sessionId: sid,
                    primarySource: source,
                    subModelSource: existing?.subModelSource
                )
                store.setBinding(binding, for: sid)
            }
        ))

        r.register(ClosureField(
            path: "session.subModel",
            displayName: "Sub model (current session)",
            description: "Optional fallback. Format same as primaryModel. Empty clears.",
            valueSchema: .string(maxLength: 200),
            risk: .sensitive, revertable: true,
            reader: {
                guard let sid = AIChatViewModel.activeSessionId,
                      let binding = ProviderConfigStore.shared.binding(for: sid),
                      let sub = binding.subModelSource else {
                    return .string("")
                }
                switch sub {
                case .directEntry(let uuid, _):
                    return .string("entry:\(uuid)")
                case .group(let gid, _):
                    return .string("group:\(gid)")
                }
            },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                guard let sid = AIChatViewModel.activeSessionId else {
                    throw ConfigError.invalidValue("No active session — open a chat first")
                }
                let store = ProviderConfigStore.shared
                guard var binding = store.binding(for: sid) else {
                    throw ConfigError.invalidValue("No primary model bound — set session.primaryModel first")
                }
                if s.isEmpty {
                    binding.subModelSource = nil
                } else {
                    binding.subModelSource = try parseModelSource(s, store: store)
                }
                store.setBinding(binding, for: sid)
            }
        ))
    }

    /// Parse `entry:<uuid>` / `group:<id>` strings into a SessionModelSource.
    /// Verifies the referenced entry / group actually exists, since a
    /// dangling binding would silently break the chat's next request.
    @MainActor
    private static func parseModelSource(_ s: String,
                                         store: ProviderConfigStore) throws -> SessionModelSource {
        if s.hasPrefix("entry:") {
            let raw = String(s.dropFirst("entry:".count))
            // [T-ios-minis-config-entry-id-composite] Same normalize-then-
            // validate as defaults.agentLoopEntries: entry ids are composite
            // keys now, but the agent may pass a legacy random uuid. Store the
            // normalized (current) id so the binding never carries a stale ref.
            let entryId = store.normalizeEntryRef(raw)
            guard !raw.isEmpty,
                  store.config.modelEntries.contains(where: { $0.id == entryId }) else {
                throw ConfigError.invalidValue(
                    "Unknown model entry id: \(raw) (expected {instanceId}/{modelId} composite form; run `minis-config get models` for valid entry_id values)"
                )
            }
            return .directEntry(modelEntryId: entryId)
        }
        if s.hasPrefix("group:") {
            let gid = String(s.dropFirst("group:".count))
            guard !gid.isEmpty,
                  let group = store.config.modelGroups.first(where: { $0.id == gid }) else {
                throw ConfigError.invalidValue("Unknown group id: \(gid)")
            }
            // group source carries a resolvedEntryId for fast read-paths.
            // Pick the first member; consumers re-resolve at request time
            // using the group's strategy, so this is a hint, not a binding.
            let resolved = group.memberEntryIds.first ?? ""
            return .group(groupId: gid, resolvedEntryId: resolved)
        }
        throw ConfigError.invalidValue("Expected `entry:<uuid>` or `group:<id>`, got '\(s)'")
    }

    // MARK: Collections (providers / models / groups / envvars)

    @MainActor
    private static func registerProviderCollections(into r: ConfigRegistry) {
        r.register(ProvidersCollection())
        r.register(ModelsCollection())
        r.register(GroupsCollection())
        r.register(EnvVarsCollection())

        // Aggregate read-only summary so `minis-config get providers`
        // returns a useful list of configured instances. Credentials
        // (apiKey / oauthToken) are deliberately omitted — only the
        // identity / type / endpoint-config fields ship.
        r.register(ReadOnlyField(
            path: "providers",
            displayName: "LLM provider instances (summary)",
            description: "Read-only list of configured providers (id, label, type, credential type, enabled, base URL). Credentials are not included.",
            valueSchema: .json,
            reader: {
                let summaries: [ConfigValue] = ProviderConfigStore.shared.config.instances.map { inst in
                    .object([
                        "id": .string(inst.id),
                        "label": .string(inst.label),
                        "providerType": .string(inst.providerType.rawValue),
                        "credentialType": .string(String(describing: inst.credentialType)),
                        "isEnabled": .bool(inst.isEnabled),
                        "customBaseURL": inst.customBaseURL.map(ConfigValue.string) ?? .null,
                        "appendV1Suffix": .bool(inst.appendV1Suffix),
                        "hasVoiceModels": .bool(ProviderConfigStore.shared.hasVoiceModels(for: inst.id)),
                        "imageEndpointMode": .string(inst.imageEndpointMode.rawValue),
                    ])
                }
                return .array(summaries)
            }
        ))

        // Aggregate read-only summary so `minis-config get models`
        // returns every model entry along with its provider context —
        // enough for the agent to find an entry_id to feed into
        // `defaults.agentLoopEntries.append`.
        r.register(ReadOnlyField(
            path: "models",
            displayName: "Model entries (summary)",
            description: "Read-only list of every model entry (entry_id, display_name, model_id, provider).",
            valueSchema: .json,
            reader: {
                let cfg = ProviderConfigStore.shared.config
                // Lookup map; on duplicate provider ids (corrupt config /
                // mid-migration state) keep the latest so the read can't
                // trap. Dictionary(uniqueKeysWithValues:) would assert.
                let providersById = Dictionary(
                    cfg.instances.map { ($0.id, $0) },
                    uniquingKeysWith: { _, new in new }
                )
                let summaries: [ConfigValue] = cfg.modelEntries.map { entry in
                    let inst = providersById[entry.providerInstanceId]
                    return .object([
                        "entry_id": .string(entry.id),
                        "display_name": .string(entry.model.displayName),
                        "model_id": .string(entry.baseModel.id),
                        "provider_id": .string(entry.providerInstanceId),
                        "provider_label": inst.map { .string($0.label) } ?? .null,
                        "provider_type": inst.map { .string($0.providerType.rawValue) } ?? .null,
                        "is_custom": .bool(entry.isCustom),
                        "is_hidden": .bool(entry.isHidden),
                    ])
                }
                return .array(summaries)
            }
        ))

        // Aggregate read-only summary so `minis-config get envvars`
        // returns every env var key with its non-secret metadata. The
        // value (stored in Keychain) is never exposed; agents only see
        // the key, note, and createdAt.
        r.register(ReadOnlyField(
            path: "envvars",
            displayName: "Environment variables (summary)",
            description: "Read-only list of env var keys with note and createdAt. Values are never exposed.",
            valueSchema: .json,
            reader: {
                let iso = ISO8601DateFormatter()
                let summaries: [ConfigValue] = EnvVarStore.shared.entries.map { e in
                    .object([
                        "key": .string(e.key),
                        "note": .string(e.note),
                        "created_at": .string(iso.string(from: e.createdAt)),
                    ])
                }
                return .array(summaries)
            }
        ))

        // Privacy Mode toggle. Read/write so the user can ask the
        // agent to flip it without diving into Settings ("turn off
        // privacy mode for the next command"). Routed through
        // EnvVarPrivacyStore.shared so the @Published wrapper fires
        // and the SwiftUI Toggle stays in sync. Default ON; risk
        // .sensitive because turning it OFF means the next shell
        // execute can leak unmasked secrets to the model.
        r.register(ClosureField(
            path: "envvars.privacyMode",
            displayName: "Privacy Mode",
            description: "When ON, env-var values that appear in shell-execute output are masked before reaching the model. Turning OFF lets the model see raw values — only do this if the user explicitly asked.",
            valueSchema: .bool,
            risk: .sensitive,
            revertable: true,
            reader: { .bool(EnvVarPrivacyStore.shared.enabled) },
            writer: { v in
                guard case .bool(let b) = v else { throw ConfigError.typeMismatch(expected: "bool") }
                EnvVarPrivacyStore.shared.enabled = b
            }
        ))

        // Aggregate read-only summary so `minis-config get groups`
        // returns every model group with its expanded entries. Each
        // entry is enriched with display_name + provider info so the
        // agent doesn't need to cross-reference `models` to know what
        // a group's entries actually are.
        r.register(ReadOnlyField(
            path: "groups",
            displayName: "Model groups (summary)",
            description: "Read-only list of model groups with entries expanded.",
            valueSchema: .json,
            reader: {
                let cfg = ProviderConfigStore.shared.config
                // Lookup maps; tolerate duplicate ids (corrupt config /
                // mid-migration state). Dictionary(uniqueKeysWithValues:)
                // would assert and crash the read.
                let entriesById = Dictionary(
                    cfg.modelEntries.map { ($0.id, $0) },
                    uniquingKeysWith: { _, new in new }
                )
                let providersById = Dictionary(
                    cfg.instances.map { ($0.id, $0) },
                    uniquingKeysWith: { _, new in new }
                )
                let summaries: [ConfigValue] = cfg.modelGroups.map { g in
                    let entries: [ConfigValue] = g.memberEntryIds.map { entryId in
                        guard let entry = entriesById[entryId] else {
                            return .object([
                                "entry_id": .string(entryId),
                                "missing": .bool(true),
                            ])
                        }
                        let inst = providersById[entry.providerInstanceId]
                        return .object([
                            "entry_id": .string(entryId),
                            "display_name": .string(entry.model.displayName),
                            "model_id": .string(entry.baseModel.id),
                            "provider_id": .string(entry.providerInstanceId),
                            "provider_label": inst.map { .string($0.label) } ?? .null,
                        ])
                    }
                    return .object([
                        "id": .string(g.id),
                        "name": .string(g.name),
                        "strategy": .string(g.strategy.rawValue),
                        "fallback_strategy": .string(g.fallbackStrategy.rawValue),
                        "default_thinking_level": g.defaultThinkingLevel
                            .map { .string($0.rawValue) } ?? .null,
                        "context_limit_tokens": g.contextLimitTokens
                            .map { .int($0) } ?? .null,
                        "entries": .array(entries),
                    ])
                }
                return .array(summaries)
            }
        ))
    }

    // MARK: Defaults — primary/sub group + agent-loop bundles

    @MainActor
    private static func registerDefaults(into r: ConfigRegistry) {
        r.register(ClosureField(
            path: "defaults.primaryGroup",
            displayName: "Default primary group",
            description: "Group used by new sessions. Empty string clears the default.",
            valueSchema: .string(maxLength: 200),
            risk: .sensitive, revertable: true,
            reader: { .string(ProviderConfigStore.shared.defaultPrimaryGroupId ?? "") },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                let store = ProviderConfigStore.shared
                if s.isEmpty {
                    store.defaultPrimaryGroupId = nil
                } else {
                    guard store.config.modelGroups.contains(where: { $0.id == s }) else {
                        throw ConfigError.invalidValue("No group with id \(s)")
                    }
                    store.defaultPrimaryGroupId = s
                }
            }
        ))
        r.register(ClosureField(
            path: "defaults.subGroup",
            displayName: "Default sub group",
            description: "Secondary group for fallback. Empty string clears the default.",
            valueSchema: .string(maxLength: 200),
            risk: .sensitive, revertable: true,
            reader: { .string(ProviderConfigStore.shared.defaultSubGroupId ?? "") },
            writer: { v in
                guard case .string(let s) = v else { throw ConfigError.typeMismatch(expected: "string") }
                let store = ProviderConfigStore.shared
                if s.isEmpty {
                    store.defaultSubGroupId = nil
                } else {
                    guard store.config.modelGroups.contains(where: { $0.id == s }) else {
                        throw ConfigError.invalidValue("No group with id \(s)")
                    }
                    store.defaultSubGroupId = s
                }
            }
        ))
        // Agent loop members are stored as two parallel arrays
        // (entryIds + groupIds). Expose each as an array-of-strings
        // field; writes replace the whole list.
        r.register(ClosureField(
            path: "defaults.agentLoopEntries",
            displayName: "Agent loop model entries",
            description: "Model entries available via minis-model-use. Replace with full list to set.",
            valueSchema: .array(.string()),
            risk: .sensitive, revertable: true,
            // [T-ios-minis-config-entry-id-composite] Emit normalized ids so
            // the agent never sees (and round-trips) a stale legacy uuid that
            // survived in storage from before the composite-key migration.
            // [T-ios-agentloop-dirty-data-skip] Normalize, then drop any id that
            // still doesn't match a known entry (stale legacy uuid) so the agent
            // never sees an unresolvable ref it can't act on.
            reader: {
                let store = ProviderConfigStore.shared
                let validIds = Set(store.config.modelEntries.map(\.id))
                let ids = store.agentLoopModelEntryIds
                    .map { store.normalizeEntryRef($0) }
                    .filter { validIds.contains($0) }
                return .array(ids.map { .string($0) })
            },
            writer: { v in
                guard case .array(let arr) = v else { throw ConfigError.typeMismatch(expected: "array") }
                let rawIds: [String] = arr.compactMap { if case .string(let s) = $0 { return s } else { return nil } }
                // [T-ios-minis-config-entry-id-composite] Entry ids became
                // composite keys ("{instanceId}/{modelId}"); lists written by
                // the agent may still carry legacy random uuids (read from an
                // un-normalized store or older notes). Normalize each ref
                // first, then validate — only ids that are neither valid
                // composite keys nor resolvable legacy forms are rejected.
                let store = ProviderConfigStore.shared
                let normalized = rawIds.map { store.normalizeEntryRef($0) }
                let valid = Set(store.config.modelEntries.map(\.id))
                // [T-ios-agentloop-dirty-data-skip] Silently drop ids that don't
                // resolve to a known entry instead of hard-failing the whole
                // write. The config append flow ("read old list + add one →
                // write the whole new list") would otherwise let a single
                // legacy bare-uuid still sitting in storage block every valid
                // new append. Filtering self-heals the stale data while letting
                // the new entry through; a diagnostic log keeps a trace.
                let ids = normalized.filter { valid.contains($0) }
                let skipped = normalized.filter { !valid.contains($0) }
                if !skipped.isEmpty {
                    AppLogger(category: "MinisConfig").info("[MinisConfig] skipped unknown agentLoopEntries ids: \(skipped.joined(separator: ", "))")
                }
                store.agentLoopModelEntryIds = ids
            }
        ))
        r.register(ClosureField(
            path: "defaults.agentLoopGroups",
            displayName: "Agent loop groups",
            description: "Whole groups exposed via minis-model-use.",
            valueSchema: .array(.string()),
            risk: .sensitive, revertable: true,
            // [T-ios-agentloop-dirty-data-skip] Filter unknown group ids on read.
            reader: {
                let store = ProviderConfigStore.shared
                let validIds = Set(store.config.modelGroups.map(\.id))
                return .array(store.agentLoopGroupIds.filter { validIds.contains($0) }.map { .string($0) })
            },
            writer: { v in
                guard case .array(let arr) = v else { throw ConfigError.typeMismatch(expected: "array") }
                let rawIds: [String] = arr.compactMap { if case .string(let s) = $0 { return s } else { return nil } }
                let valid = Set(ProviderConfigStore.shared.config.modelGroups.map(\.id))
                // [T-ios-agentloop-dirty-data-skip] Silent-skip unknown group ids
                // (see agentLoopEntries writer) so stale ids can't block a write.
                let ids = rawIds.filter { valid.contains($0) }
                let skipped = rawIds.filter { !valid.contains($0) }
                if !skipped.isEmpty {
                    AppLogger(category: "MinisConfig").info("[MinisConfig] skipped unknown agentLoopGroups ids: \(skipped.joined(separator: ", "))")
                }
                ProviderConfigStore.shared.agentLoopGroupIds = ids
            }
        ))
    }

    // MARK: iCloud sync

    @MainActor
    private static func registerSync(into r: ConfigRegistry) {
        // The whole sync stack (CloudSyncEngine V2 + its Settings entry) is
        // iOS 17+ — ContentView doesn't even show the iCloud Sync row on
        // iOS 16. Register the same paths as UnavailableField stubs there so
        // minis-config answers with a clear feature_unavailable instead of
        // silently flipping cloudSync.* UserDefaults keys no engine will
        // ever read — or worse, keys a later OS upgrade would suddenly honor
        // without the user ever having seen a sync consent surface.
        var syncFields: [ConfigField] = []
        func reg(_ field: ConfigField) { syncFields.append(field) }

        // The master sync flag is sensitive — flipping mid-upload can
        // strand data — but recoverable, so we mark it sensitive (not
        // destructive). The CloudSyncEngine reads its UserDefaults
        // value directly on init; we update both sides here so the
        // running engine and a future cold-launch agree.
        reg(AppStorageBoolField(
            path: "sync.enabled",
            displayName: "iCloud sync enabled",
            description: "Master switch for iCloud sync.",
            userDefaultsKey: "cloudSync.enabled",
            defaultValue: false,
            risk: .sensitive
        ))
        reg(AppStorageBoolField(
            path: "sync.sessions",
            displayName: "Sync sessions",
            description: "Include chat sessions in iCloud sync.",
            userDefaultsKey: "cloudSync.syncSessions",
            defaultValue: true
        ))
        reg(AppStorageBoolField(
            path: "sync.files",
            displayName: "Sync files",
            description: "Include workspace / attachments / shared files.",
            userDefaultsKey: "cloudSync.syncFiles",
            defaultValue: true
        ))
        reg(AppStorageBoolField(
            path: "sync.skills",
            displayName: "Sync skills",
            description: "Sync custom skills across devices.",
            userDefaultsKey: "cloudSync.syncSkills",
            defaultValue: true
        ))
        reg(AppStorageBoolField(
            path: "sync.providers",
            displayName: "Sync providers",
            description: "Sync provider config (excluding credentials) across devices.",
            userDefaultsKey: "cloudSync.syncProviders",
            defaultValue: true
        ))
        reg(AppStorageBoolField(
            path: "sync.environments",
            displayName: "Sync env-var metadata",
            description: "Sync env-var keys & notes (values stay device-local in Keychain).",
            userDefaultsKey: "cloudSync.syncEnvironments",
            defaultValue: true
        ))
        reg(AppStorageIntField(
            path: "sync.maxFileSize",
            displayName: "Max sync file size (bytes)",
            description: "Files larger than this are skipped during iCloud sync.",
            userDefaultsKey: "cloudSync.maxSyncFileSize",
            defaultValue: 1_048_576,
            min: 0, max: 100_000_000
        ))

        if #available(iOS 17.0, *) {
            syncFields.forEach { r.register($0) }
        } else {
            let reason = "iCloud Sync requires iOS 17 or later and is unavailable on this device. There is no sync settings screen on this iOS version either."
            syncFields.forEach { r.register(UnavailableField(base: $0, reason: reason)) }
        }
    }

    // MARK: Rootfs mirrors (alpine / pip / npm)

    @MainActor
    private static func registerRootfsMirror(into r: ConfigRegistry) {
        // Mirror selection is keyed by category. Persisted as
        // `mirror.selected.<category>`. Empty value = use the
        // built-in default.
        for category in ["alpine", "pip", "npm"] {
            let path = "rootfs-mirror.\(category)"
            r.register(AppStorageStringField(
                path: path,
                displayName: "\(category.capitalized) mirror id",
                description: "Selected mirror for \(category). Empty = default.",
                userDefaultsKey: "mirror.selected.\(category)",
                defaultValue: "",
                maxLength: 256
            ))
        }
    }

    // MARK: Self-meta — read-only status queries

    @MainActor
    private static func registerSelfMeta(into r: ConfigRegistry) {
        // The master switch surface. Agent CAN read it (so it knows why
        // it might be denied later in the session) but CAN'T write it —
        // the writer always throws. The bridge's first-line check on
        // `MinisConfigPermissionStore.shared.enabled` will short-circuit
        // most of these calls when the switch is off; the registration
        // exists for the rare case where the agent reads while we're
        // still enabled, plus to surface the switch in topic-help.
        r.register(ClosureField(
            path: "permissions.minisConfig.enabled",
            displayName: "Allow minis-config",
            description: "Master switch. Read-only here — toggle via Settings → Permissions.",
            valueSchema: .bool,
            access: .readonly,
            risk: .destructive,
            revertable: false,
            reader: { .bool(MinisConfigPermissionStore.shared.enabled) },
            writer: { _ in
                throw ConfigError.permissionDenied(
                    reason: "Master switch — toggle via Settings → Permissions only")
            }
        ))
    }

    // MARK: Appearance & Display

    @MainActor
    private static func registerAppearance(into r: ConfigRegistry) {
        r.register(AppStorageIntCodedEnumField(
            path: "appearance.theme",
            displayName: "Theme",
            description: "Light / Dark / System color scheme.",
            userDefaultsKey: "appearanceMode",
            cases: ["system", "light", "dark"],
            defaultIndex: 0
        ))
        r.register(AppStorageIntCodedEnumField(
            path: "appearance.appIcon",
            displayName: "App icon",
            description: "Home screen icon variant.",
            userDefaultsKey: "appIconMode",
            cases: ["auto", "light", "dark", "legacy_light", "legacy_dark"],
            defaultIndex: 0
        ))
        r.register(AppStorageStringField(
            path: "appearance.language",
            displayName: "App language",
            description: "BCP-47 code (zh-Hans, en, ja, …) or empty for system.",
            userDefaultsKey: "appLanguage",
            defaultValue: "",
            maxLength: 16
        ))
        r.register(AppStorageIntCodedEnumField(
            path: "appearance.launchScreen",
            displayName: "Launch screen",
            description: "Which screen the app opens to.",
            userDefaultsKey: "launchScreen",
            cases: ["auto", "last", "new", "home"],
            defaultIndex: 0
        ))
        // Global UI font scale (settings labels, list rows, etc.).
        // Backed by FontSettings.shared.appBaseScale — do NOT touch
        // UserDefaults directly: the @Published setter posts a
        // notification + retraits all UIWindows on iOS 17+, which a
        // raw UserDefaults write would skip.
        r.register(fontScaleField(
            path: "appearance.appFontSize",
            displayName: "App font size",
            description: "Global UI font scale (xSmall / small / default / medium / large / extraLarge).",
            keyPath: \.appBaseScale,
            risk: .normal
        ))
    }

    // MARK: Chat / Input

    @MainActor
    private static func registerChat(into r: ConfigRegistry) {
        r.register(AppStorageIntCodedEnumField(
            path: "chat.returnKey",
            displayName: "Return key behavior",
            description: "What the on-screen Return key does in the chat box.",
            userDefaultsKey: "returnKeyBehavior",
            cases: ["newline", "send"],
            defaultIndex: 0
        ))
        r.register(AppStorageBoolField(
            path: "chat.keepScreenAwake",
            displayName: "Keep screen awake during tasks",
            description: "Prevents auto-lock while the agent is busy.",
            userDefaultsKey: "keepScreenAwakeDuringTasks",
            defaultValue: false
        ))
        r.register(AppStorageBoolField(
            path: "chat.toolPreview",
            displayName: "Tool preview",
            description: "Show live preview during agent tool execution.",
            userDefaultsKey: "toolPreviewEnabled",
            defaultValue: true
        ))
        r.register(AppStorageBoolField(
            path: "chat.fabOnLeft",
            displayName: "FAB on left",
            description: "Move the floating action button to the left edge.",
            userDefaultsKey: "fabOnLeft",
            defaultValue: false
        ))
        // [T-keyboard-auto-pop default flip] On by default — most users
        // want the input ready for a follow-up immediately after the
        // reply lands; turn off if you prefer to read the response first.
        // Mirrors the Settings → Chat toggle in ContentView.
        r.register(AppStorageBoolField(
            path: "chat.autoFocusAfterReply",
            displayName: "Auto-focus input after reply",
            description: "When ON, the keyboard pops up automatically ~1.5s after the model finishes a reply so the input is ready for a follow-up. Turn OFF if you prefer to read the response without an unexpected keyboard.",
            userDefaultsKey: "chat.autoFocusAfterReply",
            defaultValue: true
        ))
        // Chat font sizes — both axes route through FontSettings.shared
        // so the @Published setter fires (writes UserDefaults, posts
        // .fontSettingsMessageBaseChanged for cache invalidation, and
        // updates SwiftUI subscribers immediately).
        r.register(fontScaleField(
            path: "chat.inputFontSize",
            displayName: "Input font size",
            description: "Font size for the chat composer text editor.",
            keyPath: \.chatInputScale,
            risk: .normal
        ))
        r.register(fontScaleField(
            path: "chat.messageFontSize",
            displayName: "Message font size",
            description: "Base font size for assistant / user message bodies (markdown). Setting this invalidates rendered markdown caches.",
            keyPath: \.messageBaseScale,
            risk: .normal
        ))
    }

    // MARK: Font-scale field factory
    //
    // Builds a ClosureField that reads/writes one FontScaleLevel axis
    // on FontSettings.shared. Centralised so the three axes share
    // identical schema + serialisation, and so audit/revert round-trip
    // through the same string tokens (xSmall / small / default / …).
    @MainActor
    private static func fontScaleField(
        path: String,
        displayName: String,
        description: String,
        keyPath: ReferenceWritableKeyPath<FontSettings, FontScaleLevel>,
        risk: ConfigRisk
    ) -> ConfigField {
        let cases = FontScaleLevel.allCases.map(fontScaleToken)
        return ClosureField(
            path: path,
            displayName: displayName,
            description: description,
            valueSchema: .stringEnum(cases),
            risk: risk,
            revertable: true,
            reader: {
                .string(fontScaleToken(FontSettings.shared[keyPath: keyPath]))
            },
            writer: { value in
                guard case .string(let token) = value else {
                    throw ConfigError.typeMismatch(expected: "string")
                }
                guard let level = fontScaleFromToken(token) else {
                    throw ConfigError.invalidValue("Unknown font scale: \(token)")
                }
                FontSettings.shared[keyPath: keyPath] = level
            }
        )
    }

    /// Stable string token for a FontScaleLevel — must match exactly
    /// across read/write so audit revert works without translation.
    /// Decoupled from `label` (which is user-visible and may localise).
    private static func fontScaleToken(_ level: FontScaleLevel) -> String {
        switch level {
        case .xSmall:     return "xSmall"
        case .small:      return "small"
        case .default:    return "default"
        case .medium:     return "medium"
        case .large:      return "large"
        case .extraLarge: return "extraLarge"
        }
    }

    private static func fontScaleFromToken(_ token: String) -> FontScaleLevel? {
        switch token {
        case "xSmall":     return .xSmall
        case "small":      return .small
        case "default":    return .default
        case "medium":     return .medium
        case "large":      return .large
        case "extraLarge": return .extraLarge
        default:           return nil
        }
    }

    // MARK: File browser

    @MainActor
    private static func registerFiles(into r: ConfigRegistry) {
        r.register(AppStorageStringField(
            path: "files.sortKey",
            displayName: "Sort key",
            description: "Sort field in the in-app file browser.",
            userDefaultsKey: "fileBrowser.sortKey",
            defaultValue: "name"
        ))
        r.register(AppStorageBoolField(
            path: "files.sortAscending",
            displayName: "Sort ascending",
            description: "Sort direction in the file browser.",
            userDefaultsKey: "fileBrowser.sortAscending",
            defaultValue: true
        ))
        r.register(AppStorageBoolField(
            path: "files.foldersFirst",
            displayName: "Folders first",
            description: "List folders before files when sorting.",
            userDefaultsKey: "fileBrowser.foldersFirst",
            defaultValue: true
        ))
    }

    // MARK: Browser (browser_use tool's WebKit pool)
    //
    // Storage backs UserDefaults directly. The live BrowserTabPool
    // instance is owned by ContentView, so we don't reach into it from
    // here — instead we write the same UserDefaults keys it reads on
    // launch. The pool re-applies viewport/UA on next tab open; for an
    // immediate refresh users can dismiss/reopen the browser tab.

    @MainActor
    private static func registerBrowser(into r: ConfigRegistry) {
        r.register(AppStorageEnumField(
            path: "browser.uaProfile",
            displayName: "User-agent profile",
            description: "mobile_safari / desktop_safari / custom.",
            userDefaultsKey: "BrowserUserAgentProfile",
            cases: ["mobile_safari", "desktop_safari", "custom"],
            defaultValue: "mobile_safari"
        ))
        r.register(AppStorageStringField(
            path: "browser.customUA",
            displayName: "Custom user-agent string",
            description: "Used when uaProfile = custom. UTF-8 string up to 1 KB.",
            userDefaultsKey: "BrowserCustomUserAgentString",
            defaultValue: "",
            maxLength: 1024
        ))
        r.register(AppStorageIntField(
            path: "browser.viewportWidth",
            displayName: "Custom viewport width",
            description: "0 disables the override.",
            userDefaultsKey: "BrowserCustomViewportWidth",
            defaultValue: 0,
            min: 0, max: 4096
        ))
        r.register(AppStorageIntField(
            path: "browser.viewportHeight",
            displayName: "Custom viewport height",
            description: "0 disables the override.",
            userDefaultsKey: "BrowserCustomViewportHeight",
            defaultValue: 0,
            min: 0, max: 4096
        ))
    }

    // MARK: Speech (TTS + recognition)

    @MainActor
    private static func registerSpeech(into r: ConfigRegistry) {
        r.register(AppStorageBoolField(
            path: "speech.backgroundEnabled",
            displayName: "Background TTS enabled",
            description: "Speak agent replies aloud, even when the app is backgrounded.",
            userDefaultsKey: "backgroundSpeakEnabled",
            defaultValue: false
        ))
        r.register(AppStorageDoubleField(
            path: "speech.rate",
            displayName: "Speech rate",
            description: "0.0 (slow) to 1.0 (fast).",
            userDefaultsKey: "speechRate",
            defaultValue: 0.5,
            min: 0.0, max: 1.0
        ))
        r.register(AppStorageDoubleField(
            path: "speech.pitch",
            displayName: "Speech pitch",
            description: "0.5 (low) to 2.0 (high).",
            userDefaultsKey: "speechPitch",
            defaultValue: 1.0,
            min: 0.5, max: 2.0
        ))
        r.register(AppStorageDoubleField(
            path: "speech.volume",
            displayName: "Speech volume",
            description: "0.0 (mute) to 1.0 (full).",
            userDefaultsKey: "speechVolume",
            defaultValue: 1.0,
            min: 0.0, max: 1.0
        ))
        r.register(AppStorageStringField(
            path: "speech.voiceEn",
            displayName: "English TTS voice",
            description: "AVSpeechSynthesisVoice identifier; empty = system default.",
            userDefaultsKey: "speechVoiceEn",
            defaultValue: "",
            maxLength: 256
        ))
        r.register(AppStorageStringField(
            path: "speech.voiceZh",
            displayName: "Chinese TTS voice",
            description: "AVSpeechSynthesisVoice identifier; empty = system default.",
            userDefaultsKey: "speechVoiceZh",
            defaultValue: "",
            maxLength: 256
        ))
        r.register(AppStorageStringField(
            path: "speech.recognitionLocale",
            displayName: "Recognition locale",
            description: "BCP-47 locale used by speech-to-text.",
            userDefaultsKey: "savedLocaleKey",
            defaultValue: "",
            maxLength: 32
        ))
    }

    // MARK: Background

    @MainActor
    private static func registerBackground(into r: ConfigRegistry) {
        r.register(AppStorageBoolField(
            path: "background.enhanced",
            displayName: "Enhanced background execution",
            description: "Keep agent tasks running when the app is backgrounded.",
            userDefaultsKey: "enhancedBackgroundExecution",
            defaultValue: false,
            risk: .sensitive
        ))
        r.register(AppStorageBoolField(
            path: "background.notifications",
            displayName: "Background notifications",
            description: "Post a system notification when long-running tasks complete.",
            userDefaultsKey: "backgroundNotificationsEnabled",
            defaultValue: true
        ))
        r.register(AppStorageBoolField(
            path: "background.locationTracking",
            displayName: "Location tracking",
            description: "Use location updates to keep the agent alive in the background.",
            userDefaultsKey: "locationTrackingEnabled",
            defaultValue: false,
            risk: .sensitive
        ))

        // Mirrors Settings → Background → Live Activity, which is hidden
        // entirely on devices where ActivityKit doesn't work (iPad < iPadOS
        // 17, iOS-on-Mac, failed runtime probe — see
        // AgentLiveActivityManager.isLiveActivitySupported). Same gate here:
        // where the UI hides the toggle, minis-config returns
        // feature_unavailable instead of flipping a switch that does nothing.
        // Routed through BackgroundKeepAliveManager (not raw UserDefaults) so
        // the didSet side effects run: OFF tears down the currently displayed
        // activity, ON restores it for running sessions.
        let liveActivityField = ClosureField(
            path: "background.liveActivity",
            displayName: "Live Activity",
            description: "Show agent task progress on the Lock Screen and in the Dynamic Island. Turning this off also removes the currently displayed Live Activity.",
            valueSchema: .bool,
            risk: .normal, revertable: true,
            reader: { .bool(BackgroundKeepAliveManager.shared.liveActivityEnabled) },
            writer: { v in
                guard case .bool(let b) = v else {
                    throw ConfigError.typeMismatch(expected: "bool")
                }
                BackgroundKeepAliveManager.shared.liveActivityEnabled = b
            }
        )
        if AgentLiveActivityManager.isLiveActivitySupported {
            r.register(liveActivityField)
        } else {
            r.register(UnavailableField(
                base: liveActivityField,
                reason: "Live Activities are not supported on this device (requires ActivityKit; iPad needs iPadOS 17+). The Live Activity toggle is not shown in Settings here either."
            ))
        }
    }

    // MARK: Logs

    @MainActor
    private static func registerLogs(into r: ConfigRegistry) {
        r.register(ClosureField(
            path: "logs.enabled",
            displayName: "Logging enabled",
            description: "Capture stdout/stderr to daily log files for diagnostics.",
            valueSchema: .bool,
            risk: .normal, revertable: true,
            reader: { .bool(LoggingManager.shared.isEnabled) },
            writer: { v in
                guard case .bool(let b) = v else {
                    throw ConfigError.typeMismatch(expected: "bool")
                }
                LoggingManager.shared.isEnabled = b
            }
        ))
    }
}
