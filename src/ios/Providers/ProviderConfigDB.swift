import Foundation
import SQLite3

private let logger = AppLogger(category: "ProviderConfigDB")

/// SQLite-backed persistence for ProviderConfig (v3 sync architecture).
///
/// Replaces the file-level last-write-wins of `provider-config.json` with
/// per-row storage so each instance / entry / group can be synced as its
/// own CloudKit record. Deletes propagate via CKRecord `op="delete"`
/// instead of application-layer tombstones — a deleted row is gone for
/// good and cannot be resurrected by a peer's stale snapshot.
///
/// **Downgrade safety**: `provider-config.json` is kept side-by-side and
/// rewritten on every mutate so a user reverting to a v2 build sees a
/// fully-current ProviderConfig snapshot. The JSON is read-only-by-v3
/// after the initial migration; SQLite is authoritative.
///
/// **Threading**: this is an `actor`, so callers must `await` mutates.
/// `ProviderConfigStore` (the `@MainActor` ObservableObject) keeps an
/// in-memory cache that UI reads synchronously; mutates kick off
/// `Task { await db.* }` for the DB write. See S3 for the wire-up.
actor ProviderConfigDB {

    // MARK: - File locations

    /// Default DB path: same MinisChat folder as `provider-config.json`.
    static func defaultURL() -> URL {
        let library = FileManager.default
            .urls(for: .libraryDirectory, in: .userDomainMask)[0]
        let base = library.appendingPathComponent("MinisChat", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("provider-config.db")
    }

    static let schemaVersion: Int32 = 2

    private let dbURL: URL
    private var db: OpaquePointer?

    // MARK: - Init / schema

    init(url: URL? = nil) throws {
        let resolvedURL = url ?? Self.defaultURL()
        self.dbURL = resolvedURL

        var handle: OpaquePointer?
        let flags = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE | SQLITE_OPEN_FULLMUTEX
        let rc = sqlite3_open_v2(resolvedURL.path, &handle, flags, nil)
        guard rc == SQLITE_OK, let handle else {
            sqlite3_close(handle)
            throw ProviderConfigDBError.openFailed(path: resolvedURL.path, code: rc)
        }
        self.db = handle

        // WAL mode: same as minis.db. Tolerates concurrent reads while we
        // upsert per-row from the sync inbound path.
        Self.exec(db: handle, "PRAGMA journal_mode = WAL")
        Self.exec(db: handle, "PRAGMA foreign_keys = ON")
        Self.exec(db: handle, "PRAGMA synchronous = NORMAL")

        try Self.runMigrations(db: handle)

        logger.info("[v3] ProviderConfigDB opened at \(resolvedURL.path)")
    }

    deinit {
        if let db { sqlite3_close(db) }
    }

    // MARK: - Schema (DDL)

    /// Applies any pending schema migrations up to `schemaVersion`. Idempotent.
    /// Tracks current version via `PRAGMA user_version`. Each upgrade step is
    /// a single TRANSACTION so a crash partway leaves the DB at the previous
    /// version (which the next launch re-attempts cleanly).
    private static func runMigrations(db: OpaquePointer) throws {
        var current: Int32 = 0
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, "PRAGMA user_version", -1, &stmt, nil) == SQLITE_OK,
           sqlite3_step(stmt) == SQLITE_ROW {
            current = sqlite3_column_int(stmt, 0)
        }
        sqlite3_finalize(stmt)

        // [T-provider-custom-user-agent-persist] Idempotent column backstops MUST
        // run on EVERY open, BEFORE the version-gated early return below. The
        // `custom_user_agent` column was added WITHOUT a schemaVersion bump, so a
        // DB already at the current user_version (the common case for existing
        // installs) would hit the early return and never gain the column — then
        // the SELECT/INSERT that reference it fail to prepare, loadAllInstanceRows
        // returns [], and EVERY provider silently disappears. Running the ensure
        // here repairs any DB regardless of user_version. (The group-tombstone
        // backstop also belongs here for the same reason; kept idempotent.)
        Self.ensureInstanceCustomUAColumn(db: db)
        Self.ensureGroupTombstoneColumns(db: db)

        if current >= schemaVersion {
            logger.info("[v3] schema up-to-date at version \(current)")
            return
        }

        logger.info("[v3] migrating schema \(current) → \(schemaVersion)")
        exec(db: db, "BEGIN IMMEDIATE")

        if current < 1 {
            // ── v1: initial schema ──
            //
            // Sync-domain tables: one row per CloudKit V3 record. updated_at
            // drives LWW. extras_json carries unknown fields from newer
            // builds so we don't round-trip-strip them (the exact failure
            // mode that pinned v2 into a ping-pong loop when a stale build
            // dropped the deletedInstances field).

            exec(db: db, """
                CREATE TABLE provider_instances (
                    id                       TEXT PRIMARY KEY,
                    label                    TEXT NOT NULL,
                    provider_type            TEXT NOT NULL,
                    credential_type          TEXT,
                    custom_base_url          TEXT,
                    append_v1_suffix         INTEGER NOT NULL DEFAULT 1,
                    image_endpoint_mode      TEXT,
                    image_endpoint_resolved  TEXT,
                    custom_user_agent        TEXT,
                    azure_mode               INTEGER NOT NULL DEFAULT 0,
                    is_enabled               INTEGER NOT NULL DEFAULT 1,
                    sort_order               INTEGER NOT NULL DEFAULT 0,
                    secret_blob              TEXT,
                    secret_kind              TEXT,
                    secret_updated_at        REAL,
                    created_at               REAL NOT NULL,
                    updated_at               REAL NOT NULL,
                    extras_json              TEXT
                )
            """)

            exec(db: db, """
                CREATE TABLE provider_model_entries (
                    id                       TEXT PRIMARY KEY,
                    provider_instance_id     TEXT NOT NULL,
                    base_model_json          TEXT NOT NULL,
                    overrides_json           TEXT,
                    is_custom                INTEGER NOT NULL DEFAULT 0,
                    is_hidden                INTEGER NOT NULL DEFAULT 0,
                    user_modified_at         REAL,
                    sort_order               INTEGER NOT NULL DEFAULT 0,
                    updated_at               REAL NOT NULL,
                    extras_json              TEXT,
                    FOREIGN KEY(provider_instance_id) REFERENCES provider_instances(id) ON DELETE CASCADE
                )
            """)
            exec(db: db, "CREATE INDEX idx_entries_instance ON provider_model_entries(provider_instance_id)")

            exec(db: db, """
                CREATE TABLE provider_model_groups (
                    id                       TEXT PRIMARY KEY,
                    name                     TEXT NOT NULL,
                    strategy                 TEXT NOT NULL,
                    fallback_strategy        TEXT NOT NULL,
                    default_thinking_level   TEXT,
                    context_limit_tokens     INTEGER,
                    context_limit_remembered INTEGER,
                    member_entry_ids_json    TEXT NOT NULL,
                    sort_order               INTEGER NOT NULL DEFAULT 0,
                    updated_at               REAL NOT NULL,
                    extras_json              TEXT
                )
            """)

            // ── local-only tables (NOT synced, per-device state) ──

            exec(db: db, """
                CREATE TABLE provider_local_kv (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            exec(db: db, """
                CREATE TABLE provider_session_bindings (
                    session_id    TEXT PRIMARY KEY,
                    binding_json  TEXT NOT NULL,
                    updated_at    REAL NOT NULL
                )
            """)

            exec(db: db, """
                CREATE TABLE provider_session_inference_configs (
                    session_id    TEXT PRIMARY KEY,
                    config_json   TEXT NOT NULL,
                    updated_at    REAL NOT NULL
                )
            """)

            exec(db: db, """
                CREATE TABLE provider_agent_loop_ids (
                    kind       TEXT NOT NULL,
                    target_id  TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    PRIMARY KEY (kind, target_id)
                )
            """)
        }

        if current < 2 {
            // ── v2: member-level add/remove tombstones on groups ──
            //
            // [T-icloud-provider-sync-consistency] Group memberEntryIds are
            // merged as a per-member timestamp CRDT on inbound (two devices
            // each adding a model never clobber each other). added_members_json
            // / removed_members_json map entryId → epoch seconds. Both columns
            // are added idempotently below.
            //
            // IMPORTANT: these ALTERs run via ensureGroupTombstoneColumns(),
            // NOT inline, because an earlier build of this migration added ONLY
            // removed_members_json and then bumped user_version to 2 — on those
            // DBs `current >= 2` skips this block entirely, leaving
            // added_members_json missing forever. A SELECT that lists the
            // missing column then fails to prepare and returns ZERO group rows,
            // which save() promptly persisted back as "no groups" and pushed to
            // iCloud — wiping every group. The fix is to make column creation
            // idempotent AND run it unconditionally on every open (below),
            // independent of user_version.
        }

        exec(db: db, "PRAGMA user_version = \(schemaVersion)")
        exec(db: db, "COMMIT")
        logger.info("[v3] schema migration complete")

        // Both idempotent column backstops now run UNCONDITIONALLY at the top of
        // this function (before the version-gated early return), so they are not
        // repeated here. See the note there.
    }

    /// Add `custom_user_agent` to provider_instances if absent. Idempotent —
    /// safe to call on every DB open. The column was introduced after the
    /// original v1 schema, so any DB created by an earlier build lacks it; a
    /// SELECT/INSERT that references the missing column would otherwise fail to
    /// prepare and silently drop the per-provider custom UA (it round-trips
    /// only through in-memory + JSON mirror, so it looked set until a cold
    /// start reloaded from this DB and read it back as nil → "UA reverts to
    /// default after a while"). [T-provider-custom-user-agent-persist]
    private static func ensureInstanceCustomUAColumn(db: OpaquePointer) {
        var existing = Set<String>()
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, "PRAGMA table_info(provider_instances)", -1, &stmt, nil) == SQLITE_OK {
            while sqlite3_step(stmt) == SQLITE_ROW {
                if let c = sqlite3_column_text(stmt, 1) { existing.insert(String(cString: c)) }
            }
        }
        sqlite3_finalize(stmt)
        // Empty set = table doesn't exist yet (brand-new DB, before the v1
        // CREATE TABLE runs — which already includes the column). Skip the ALTER
        // so we don't log a spurious "no such table" error; nothing to repair.
        guard !existing.isEmpty else { return }
        if !existing.contains("custom_user_agent") {
            exec(db: db, "ALTER TABLE provider_instances ADD COLUMN custom_user_agent TEXT")
            logger.info("[v3] schema repair: added missing column custom_user_agent")
        }
        // [T-ios-azure-openai] Same idempotent backstop for the azure_mode column
        // (added after v1 schema, no schemaVersion bump). Without it, a DB at the
        // current user_version never gains the column → the instance SELECT/INSERT
        // that reference it fail to prepare and every provider disappears.
        if !existing.contains("azure_mode") {
            exec(db: db, "ALTER TABLE provider_instances ADD COLUMN azure_mode INTEGER NOT NULL DEFAULT 0")
            logger.info("[v3] schema repair: added missing column azure_mode")
        }
    }

    /// Add `removed_members_json` / `added_members_json` to provider_model_groups
    /// if absent. Idempotent — safe to call on every DB open. Guards against a
    /// partial earlier migration that left only one of the two columns.
    private static func ensureGroupTombstoneColumns(db: OpaquePointer) {
        var existing = Set<String>()
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, "PRAGMA table_info(provider_model_groups)", -1, &stmt, nil) == SQLITE_OK {
            while sqlite3_step(stmt) == SQLITE_ROW {
                if let c = sqlite3_column_text(stmt, 1) { existing.insert(String(cString: c)) }
            }
        }
        sqlite3_finalize(stmt)
        if !existing.contains("removed_members_json") {
            exec(db: db, "ALTER TABLE provider_model_groups ADD COLUMN removed_members_json TEXT NOT NULL DEFAULT '{}'")
            logger.info("[v3] schema repair: added missing column removed_members_json")
        }
        if !existing.contains("added_members_json") {
            exec(db: db, "ALTER TABLE provider_model_groups ADD COLUMN added_members_json TEXT NOT NULL DEFAULT '{}'")
            logger.info("[v3] schema repair: added missing column added_members_json")
        }
    }

    // MARK: - Member-timestamp map JSON codec
    // [T-icloud-provider-sync-consistency] addedMembers/removedMembers travel
    // as a JSON object {entryId: epochSeconds}. Decoding tolerates nil/empty/
    // malformed input (returns [:]) so a pre-v2 group or a corrupt blob never
    // throws inside the sync hot path.

    static func decodeMemberTimestamps(_ json: String?) -> [String: Date] {
        guard let json, !json.isEmpty, json != "{}",
              let data = json.data(using: .utf8),
              let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Double]
        else { return [:] }
        var out: [String: Date] = [:]
        for (k, v) in raw { out[k] = Date(timeIntervalSince1970: v) }
        return out
    }

    static func encodeMemberTimestamps(_ map: [String: Date]) -> String {
        guard !map.isEmpty else { return "{}" }
        var raw: [String: Double] = [:]
        for (k, v) in map { raw[k] = v.timeIntervalSince1970 }
        guard let data = try? JSONSerialization.data(withJSONObject: raw, options: [.sortedKeys]),
              let s = String(data: data, encoding: .utf8)
        else { return "{}" }
        return s
    }

    @discardableResult
    private static func exec(db: OpaquePointer, _ sql: String) -> Int32 {
        var err: UnsafeMutablePointer<CChar>?
        let rc = sqlite3_exec(db, sql, nil, nil, &err)
        if rc != SQLITE_OK {
            let msg = err.map { String(cString: $0) } ?? "unknown"
            logger.error("[v3] sqlite_exec failed (\(rc)): \(msg) — SQL: \(sql.prefix(120))")
            sqlite3_free(err)
        }
        return rc
    }

    // MARK: - Read API (used by ProviderConfigStore cache hydration in S3)

    /// Whether the DB has been populated. False = newly created, expects
    /// migration from `provider-config.json` next (Stage S2).
    func isEmpty() -> Bool {
        guard let db else { return true }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM provider_instances", -1, &stmt, nil) == SQLITE_OK else {
            return true
        }
        guard sqlite3_step(stmt) == SQLITE_ROW else { return true }
        return sqlite3_column_int(stmt, 0) == 0
    }

    /// Fetch every row in `provider_instances` ordered by `sort_order`,
    /// returning the raw SQL row dicts. The caller (ProviderConfigStore in
    /// S3) maps these into `ProviderInstance` values. Returning dicts here
    /// rather than typed structs lets the read-only API stay decoupled
    /// from the model layer for now — S3 wires the mapping.
    func loadAllInstanceRows() -> [[String: Any]] {
        guard let db else { return [] }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = """
            SELECT id, label, provider_type, credential_type, custom_base_url,
                   append_v1_suffix, image_endpoint_mode, image_endpoint_resolved,
                   is_enabled, sort_order, secret_blob, secret_kind,
                   secret_updated_at, created_at, updated_at, extras_json,
                   custom_user_agent, azure_mode
            FROM provider_instances
            ORDER BY sort_order ASC, created_at ASC
        """
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        var rows: [[String: Any]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            rows.append([
                "id": Self.text(stmt, 0),
                "label": Self.text(stmt, 1),
                "provider_type": Self.text(stmt, 2),
                "credential_type": Self.optText(stmt, 3) as Any,
                "custom_base_url": Self.optText(stmt, 4) as Any,
                "append_v1_suffix": sqlite3_column_int(stmt, 5) != 0,
                "image_endpoint_mode": Self.optText(stmt, 6) as Any,
                "image_endpoint_resolved": Self.optText(stmt, 7) as Any,
                "is_enabled": sqlite3_column_int(stmt, 8) != 0,
                "sort_order": Int(sqlite3_column_int(stmt, 9)),
                "secret_blob": Self.optText(stmt, 10) as Any,
                "secret_kind": Self.optText(stmt, 11) as Any,
                "secret_updated_at": Self.optDouble(stmt, 12) as Any,
                "created_at": sqlite3_column_double(stmt, 13),
                "updated_at": sqlite3_column_double(stmt, 14),
                "extras_json": Self.optText(stmt, 15) as Any,
                "custom_user_agent": Self.optText(stmt, 16) as Any,
                "azure_mode": sqlite3_column_int(stmt, 17) != 0,
            ])
        }
        return rows
    }

    func loadAllEntryRows() -> [[String: Any]] {
        guard let db else { return [] }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = """
            SELECT id, provider_instance_id, base_model_json, overrides_json,
                   is_custom, is_hidden, user_modified_at, sort_order, updated_at, extras_json
            FROM provider_model_entries
            ORDER BY provider_instance_id, sort_order ASC
        """
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        var rows: [[String: Any]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            rows.append([
                "id": Self.text(stmt, 0),
                "provider_instance_id": Self.text(stmt, 1),
                "base_model_json": Self.text(stmt, 2),
                "overrides_json": Self.optText(stmt, 3) as Any,
                "is_custom": sqlite3_column_int(stmt, 4) != 0,
                "is_hidden": sqlite3_column_int(stmt, 5) != 0,
                "user_modified_at": Self.optDouble(stmt, 6) as Any,
                "sort_order": Int(sqlite3_column_int(stmt, 7)),
                "updated_at": sqlite3_column_double(stmt, 8),
                "extras_json": Self.optText(stmt, 9) as Any,
            ])
        }
        return rows
    }

    func loadAllGroupRows() -> [[String: Any]] {
        guard let db else { return [] }
        // [T-icloud-provider-sync-consistency] Self-heal: guarantee the two
        // member-tombstone columns exist before SELECTing them. A DB left by a
        // partial earlier migration (removed_members_json present,
        // added_members_json missing) would otherwise fail to prepare the SELECT
        // below — returning ZERO rows, which dumpProviderConfig + save() then
        // persisted as "no groups" and pushed to iCloud, wiping every group.
        Self.ensureGroupTombstoneColumns(db: db)

        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = """
            SELECT id, name, strategy, fallback_strategy, default_thinking_level,
                   context_limit_tokens, context_limit_remembered, member_entry_ids_json,
                   sort_order, updated_at, extras_json,
                   COALESCE(removed_members_json,'{}'), COALESCE(added_members_json,'{}')
            FROM provider_model_groups
            ORDER BY sort_order ASC
        """
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            // Hard defensive fallback: if the full SELECT still won't prepare,
            // read the core columns only so groups are NEVER silently dropped.
            logger.error("[v3] loadAllGroupRows: full SELECT failed to prepare — falling back to core columns to avoid dropping groups")
            return loadAllGroupRowsCore()
        }
        var rows: [[String: Any]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            rows.append([
                "id": Self.text(stmt, 0),
                "name": Self.text(stmt, 1),
                "strategy": Self.text(stmt, 2),
                "fallback_strategy": Self.text(stmt, 3),
                "default_thinking_level": Self.optText(stmt, 4) as Any,
                "context_limit_tokens": Self.optInt(stmt, 5) as Any,
                "context_limit_remembered": Self.optInt(stmt, 6) as Any,
                "member_entry_ids_json": Self.text(stmt, 7),
                "sort_order": Int(sqlite3_column_int(stmt, 8)),
                "updated_at": sqlite3_column_double(stmt, 9),
                "extras_json": Self.optText(stmt, 10) as Any,
                "removed_members_json": Self.text(stmt, 11),
                "added_members_json": Self.text(stmt, 12),
            ])
        }
        return rows
    }

    /// Minimal group read using only columns present since schema v1. Used as a
    /// last-resort fallback so a schema anomaly can never cause groups to vanish.
    private func loadAllGroupRowsCore() -> [[String: Any]] {
        guard let db else { return [] }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = """
            SELECT id, name, strategy, fallback_strategy, default_thinking_level,
                   context_limit_tokens, context_limit_remembered, member_entry_ids_json,
                   sort_order, updated_at, extras_json
            FROM provider_model_groups
            ORDER BY sort_order ASC
        """
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        var rows: [[String: Any]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            rows.append([
                "id": Self.text(stmt, 0),
                "name": Self.text(stmt, 1),
                "strategy": Self.text(stmt, 2),
                "fallback_strategy": Self.text(stmt, 3),
                "default_thinking_level": Self.optText(stmt, 4) as Any,
                "context_limit_tokens": Self.optInt(stmt, 5) as Any,
                "context_limit_remembered": Self.optInt(stmt, 6) as Any,
                "member_entry_ids_json": Self.text(stmt, 7),
                "sort_order": Int(sqlite3_column_int(stmt, 8)),
                "updated_at": sqlite3_column_double(stmt, 9),
                "extras_json": Self.optText(stmt, 10) as Any,
                "removed_members_json": "{}",
                "added_members_json": "{}",
            ])
        }
        return rows
    }

    /// Returns the value previously set via `setLocalKV` for the given key,
    /// or nil if no row exists. Used for `defaultPrimaryGroupId` etc.
    func localKV(_ key: String) -> String? {
        guard let db else { return nil }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "SELECT value FROM provider_local_kv WHERE key = ?", -1, &stmt, nil) == SQLITE_OK else {
            return nil
        }
        sqlite3_bind_text(stmt, 1, key, -1, Self.SQLITE_TRANSIENT)
        guard sqlite3_step(stmt) == SQLITE_ROW else { return nil }
        return Self.optText(stmt, 0)
    }

    // MARK: - Write API (used by migration + S3 mutate-path redirects)

    /// Bulk-replace the entire sync-domain content of the DB from a
    /// `ProviderConfig` value. Used during one-shot migration from
    /// `provider-config.json` (Stage S2) and from
    /// `ProviderConfigStore.applyMergedConfigFromSync` (Stage S3).
    ///
    /// Wraps the whole replace in a single transaction so a crash partway
    /// leaves the prior contents intact. Per-row updated_at defaults to
    /// the legacy `userModifiedAt` if present, otherwise the per-row
    /// createdAt, otherwise `now`.
    func bulkReplace(from config: ProviderConfig) {
        guard let db else { return }
        let now = Date().timeIntervalSince1970

        Self.exec(db: db, "BEGIN IMMEDIATE")
        Self.exec(db: db, "DELETE FROM provider_model_groups")
        Self.exec(db: db, "DELETE FROM provider_model_entries")
        Self.exec(db: db, "DELETE FROM provider_instances")
        Self.exec(db: db, "DELETE FROM provider_local_kv")
        Self.exec(db: db, "DELETE FROM provider_session_bindings")
        Self.exec(db: db, "DELETE FROM provider_session_inference_configs")
        Self.exec(db: db, "DELETE FROM provider_agent_loop_ids")

        // Instances (with inline secret_blob — actual secret material
        // still lives in Keychain; the blob is populated by S5 when
        // the v3 sync-emit path packages it for upload. Migration
        // only seeds the metadata; secret_blob is left NULL until a
        // mutate happens or the v3 builder runs once.).
        for (idx, inst) in config.instances.enumerated() {
            upsertInstanceRow(
                id: inst.id,
                label: inst.label,
                // Preserve the original raw type for unsupported (newer-build)
                // instances so we never overwrite it with the sentinel string.
                providerType: inst.unknownProviderTypeRaw ?? inst.providerType.rawValue,
                credentialType: inst.credentialType.rawValue,
                customBaseURL: inst.customBaseURL,
                appendV1Suffix: inst.appendV1Suffix,
                imageEndpointMode: inst.imageEndpointMode.rawValue,
                imageEndpointResolved: inst.imageEndpointResolved?.rawValue,
                isEnabled: inst.isEnabled,
                sortOrder: idx,
                secretBlob: nil,
                secretKind: nil,
                secretUpdatedAt: nil,
                createdAt: inst.createdAt.timeIntervalSince1970,
                updatedAt: now,
                extrasJson: nil,
                customUserAgent: inst.customUserAgent,
                azureMode: inst.azureMode
            )
        }

        // Entries. baseModel + overrides go in as JSON columns so the
        // row layout doesn't need to track every LLMModel/Overrides
        // field individually (those evolve independently).
        for (idx, entry) in config.modelEntries.enumerated() {
            let baseJSON = (try? Self.jsonString(entry.baseModel)) ?? "{}"
            let overridesJSON: String?
            if entry.overrides.isEmpty {
                overridesJSON = nil
            } else {
                overridesJSON = try? Self.jsonString(entry.overrides)
            }
            upsertEntryRow(
                // [T-provider-entry-composite-key] DB primary key stays the
                // random uuid (NOT entry.id, which is now the composite key).
                // Keeping the uuid in the id column means old group/binding
                // references (also uuids) still match the row, downgrade is
                // safe, and compositeKey lives only in memory + as the sync
                // record key (computed). Writing entry.id here was the bug that
                // put composite keys into the DB and orphaned every uuid
                // reference.
                id: entry.uuid,
                providerInstanceId: entry.providerInstanceId,
                baseModelJson: baseJSON,
                overridesJson: overridesJSON,
                isCustom: entry.isCustom,
                isHidden: entry.isHidden,
                userModifiedAt: entry.userModifiedAt?.timeIntervalSince1970,
                sortOrder: idx,
                updatedAt: entry.userModifiedAt?.timeIntervalSince1970 ?? now,
                extrasJson: nil
            )
        }

        // Groups. memberEntryIds → JSON array column.
        for (idx, group) in config.modelGroups.enumerated() {
            let memberJSON = (try? Self.jsonString(group.memberEntryIds)) ?? "[]"
            upsertGroupRow(
                id: group.id,
                name: group.name,
                strategy: group.strategy.rawValue,
                fallbackStrategy: group.fallbackStrategy.rawValue,
                defaultThinkingLevel: group.defaultThinkingLevel?.rawValue,
                contextLimitTokens: group.contextLimitTokens,
                contextLimitRemembered: group.lastContextLimitTokens,
                memberEntryIdsJson: memberJSON,
                sortOrder: idx,
                updatedAt: now,
                extrasJson: nil,
                removedMembersJson: Self.encodeMemberTimestamps(group.removedMembers),
                addedMembersJson: Self.encodeMemberTimestamps(group.addedMembers)
            )
        }

        // Per-device fields — never synced.
        if let v = config.defaultPrimaryGroupId {
            setLocalKVRow("defaultPrimaryGroupId", value: v)
        }
        if let v = config.defaultSubGroupId {
            setLocalKVRow("defaultSubGroupId", value: v)
        }
        // Voice group selectors — per-device, like the default group ids.
        if let v = config.voiceInputGroupId {
            setLocalKVRow("voiceInputGroupId", value: v)
        }
        if let v = config.voiceOutputGroupId {
            setLocalKVRow("voiceOutputGroupId", value: v)
        }
        for (sid, binding) in config.sessionBindings {
            if let json = try? Self.jsonString(binding) {
                upsertSessionBindingRow(sessionId: sid, bindingJson: json, updatedAt: now)
            }
        }
        for (sid, cfg) in config.sessionInferenceConfigs {
            if let json = try? Self.jsonString(cfg) {
                upsertSessionInferenceConfigRow(sessionId: sid, configJson: json, updatedAt: now)
            }
        }
        for (idx, eid) in config.agentLoopModelEntryIds.enumerated() {
            insertAgentLoopIdRow(kind: "entry", targetId: eid, sortOrder: idx)
        }
        for (idx, gid) in config.agentLoopGroupIds.enumerated() {
            insertAgentLoopIdRow(kind: "group", targetId: gid, sortOrder: idx)
        }

        Self.exec(db: db, "COMMIT")
        let c = counts()
        logger.info("[v3] bulkReplace done: instances=\(c.instances) entries=\(c.entries) groups=\(c.groups)")
    }

    /// Build a `ProviderConfig` value from the current DB contents.
    /// Used by ProviderConfigStore (S3) to (a) hydrate its in-memory
    /// cache after launch and (b) re-serialize provider-config.json as
    /// the downgrade safety mirror after every mutate.
    func dumpProviderConfig() -> ProviderConfig {
        let instanceRows = loadAllInstanceRows()
        let entryRows = loadAllEntryRows()
        let groupRows = loadAllGroupRows()

        var instances: [ProviderInstance] = []
        for row in instanceRows {
            guard let id = row["id"] as? String,
                  let label = row["label"] as? String,
                  let typeRaw = row["provider_type"] as? String else {
                // Missing the absolute primary keys (id/label/type string) —
                // an unwritable row, nothing we can salvage. Still log it so a
                // disappearance is never silent.
                logger.error("[v3] dumpProviderConfig: instance row missing id/label/provider_type — skipping (id=\((row["id"] as? String)?.prefix(8) ?? "nil"))")
                continue
            }
            // [T-icloud-provider-sync-consistency] If the provider_type string
            // is from a NEWER build this enum can't decode, do NOT drop the
            // whole instance (that's how forward-incompatible data silently
            // vanishes and — combined with sync — propagates a delete). Keep
            // the row with a best-effort fallback type so it survives the
            // round-trip; the newer build still owns the authoritative copy.
            let parsedType = ProviderType(rawValue: typeRaw)
            let providerType: ProviderType = parsedType ?? {
                logger.error("[v3] dumpProviderConfig: instance \(id.prefix(8)) has unknown provider_type='\(typeRaw)' — marking .unsupported (raw preserved) to avoid data loss")
                return .unsupported
            }()
            // Preserve the original raw type string so a re-save round-trips it
            // unchanged instead of overwriting with the sentinel.
            let unknownTypeRaw: String? = (parsedType == nil) ? typeRaw : nil
            let credentialType: ProviderCredential = {
                if let s = row["credential_type"] as? String,
                   let c = ProviderCredential(rawValue: s) {
                    return c
                }
                return .apiKey
            }()
            let imageMode: ImageEndpointMode = {
                if let s = row["image_endpoint_mode"] as? String,
                   let m = ImageEndpointMode(rawValue: s) {
                    return m
                }
                return .auto
            }()
            let imageResolved: ImageEndpointMode? = {
                if let s = row["image_endpoint_resolved"] as? String {
                    return ImageEndpointMode(rawValue: s)
                }
                return nil
            }()
            let inst = ProviderInstance(
                id: id,
                label: label,
                providerType: providerType,
                credentialType: credentialType,
                isEnabled: (row["is_enabled"] as? Bool) ?? true,
                createdAt: Date(timeIntervalSince1970: (row["created_at"] as? Double) ?? 0),
                customBaseURL: row["custom_base_url"] as? String,
                appendV1Suffix: (row["append_v1_suffix"] as? Bool) ?? true,
                imageEndpointMode: imageMode,
                imageEndpointResolved: imageResolved,
                customUserAgent: row["custom_user_agent"] as? String,
                azureMode: (row["azure_mode"] as? Bool) ?? false,
                unknownProviderTypeRaw: unknownTypeRaw
            )
            instances.append(inst)
        }

        var entries: [ModelEntry] = []
        let decoder = JSONDecoder()
        for row in entryRows {
            guard let id = row["id"] as? String,
                  let instanceId = row["provider_instance_id"] as? String,
                  let baseJSON = row["base_model_json"] as? String,
                  let baseData = baseJSON.data(using: .utf8),
                  let baseModel = try? decoder.decode(LLMModel.self, from: baseData) else {
                // [T-icloud-provider-sync-consistency] Never let an
                // unparseable base_model_json silently drop an entry without a
                // trace. The entry stays in the DB (we don't delete it here);
                // it just isn't surfaced this dump. emitV3MarkDirty no longer
                // diff-infers entry deletes, so this does NOT propagate a
                // removal — the row and its cloud record survive.
                logger.error("[v3] dumpProviderConfig: entry \((row["id"] as? String)?.prefix(8) ?? "nil") has unparseable base_model_json — preserved in DB, skipped this dump")
                continue
            }
            var overrides = ModelOverrides()
            if let ovJSON = row["overrides_json"] as? String,
               let ovData = ovJSON.data(using: .utf8),
               let ov = try? decoder.decode(ModelOverrides.self, from: ovData) {
                overrides = ov
            }
            let userModAt: Date? = {
                if let d = row["user_modified_at"] as? Double { return Date(timeIntervalSince1970: d) }
                return nil
            }()
            let entry = ModelEntry(
                uuid: id,
                providerInstanceId: instanceId,
                model: baseModel,
                overrides: overrides,
                isCustom: (row["is_custom"] as? Bool) ?? false,
                isHidden: (row["is_hidden"] as? Bool) ?? false,
                userModifiedAt: userModAt
            )
            entries.append(entry)
        }

        var groups: [ModelGroup] = []
        for row in groupRows {
            guard let id = row["id"] as? String,
                  let name = row["name"] as? String,
                  let stratRaw = row["strategy"] as? String,
                  let strategy = RoutingStrategy(rawValue: stratRaw),
                  let fbRaw = row["fallback_strategy"] as? String,
                  let fb = FallbackStrategy(rawValue: fbRaw),
                  let memberJSON = row["member_entry_ids_json"] as? String,
                  let memberData = memberJSON.data(using: .utf8),
                  let memberIds = try? decoder.decode([String].self, from: memberData) else { continue }
            let thinkingLevel: ThinkingLevel? = {
                if let s = row["default_thinking_level"] as? String {
                    return ThinkingLevel.decoded(s)
                }
                return nil
            }()
            let group = ModelGroup(
                id: id,
                name: name,
                memberEntryIds: memberIds,
                strategy: strategy,
                fallbackStrategy: fb,
                defaultThinkingLevel: thinkingLevel,
                contextLimitTokens: row["context_limit_tokens"] as? Int,
                lastContextLimitTokens: row["context_limit_remembered"] as? Int,
                addedMembers: Self.decodeMemberTimestamps(row["added_members_json"] as? String),
                removedMembers: Self.decodeMemberTimestamps(row["removed_members_json"] as? String)
            )
            groups.append(group)
        }

        // Local-only fields.
        let defaultPrimary = localKV("defaultPrimaryGroupId")
        let defaultSub = localKV("defaultSubGroupId")
        let bindings = loadAllSessionBindings()
        let inferCfgs = loadAllSessionInferenceConfigs()
        let agentLoopEntries = loadAgentLoopIds(kind: "entry")
        let agentLoopGroups = loadAgentLoopIds(kind: "group")
        let voiceInputGroup = localKV("voiceInputGroupId")
        let voiceOutputGroup = localKV("voiceOutputGroupId")

        return ProviderConfig(
            instances: instances,
            modelEntries: entries,
            modelGroups: groups,
            defaultPrimaryGroupId: defaultPrimary,
            defaultSubGroupId: defaultSub,
            sessionBindings: bindings,
            agentLoopModelEntryIds: agentLoopEntries,
            agentLoopGroupIds: agentLoopGroups,
            voiceInputGroupId: voiceInputGroup,
            voiceOutputGroupId: voiceOutputGroup,
            sessionInferenceConfigs: inferCfgs
        )
    }

    /// One-shot migration from `provider-config.json` into DB. Idempotent
    /// (gated by a UserDefaults flag — caller checks it before invoking).
    /// Called by `ProviderConfigStore` in S3 on first launch of a v3 build.
    func migrateFromLegacyJSON(at jsonURL: URL) -> Bool {
        guard let data = try? Data(contentsOf: jsonURL),
              let config = try? JSONDecoder().decode(ProviderConfig.self, from: data) else {
            logger.warning("[v3] migrateFromLegacyJSON: failed to read/decode \(jsonURL.path)")
            return false
        }
        logger.info("[v3] migrateFromLegacyJSON: ingesting \(config.instances.count) instances / \(config.modelEntries.count) entries / \(config.modelGroups.count) groups")
        bulkReplace(from: config)
        return true
    }

    // MARK: - Per-record API (used by V3 hydrator inbound merges in S5)

    /// Fetch a single instance row. Returns nil if id not present. Used by
    /// the V3 sync builder to package an outbound record.
    func instanceRow(id: String) -> [String: Any]? {
        return loadAllInstanceRows().first { ($0["id"] as? String) == id }
    }

    func entryRow(id: String) -> [String: Any]? {
        return loadAllEntryRows().first { ($0["id"] as? String) == id }
    }

    func groupRow(id: String) -> [String: Any]? {
        return loadAllGroupRows().first { ($0["id"] as? String) == id }
    }

    /// LWW-guarded upsert from an inbound V3 SyncedProviderInstanceV3.
    /// Returns true if applied, false if skipped (local row has newer
    /// updated_at). Used by mergeProviderInstanceV3 hydrator inbound.
    func upsertInstanceFromInbound(
        id: String, label: String, providerType: String,
        credentialType: String?, customBaseURL: String?, appendV1Suffix: Bool,
        imageEndpointMode: String?, imageEndpointResolved: String?,
        isEnabled: Bool, sortOrder: Int,
        secretBlob: String?, secretKind: String?, secretUpdatedAt: Double?,
        createdAt: Double, updatedAt: Double, extrasJson: String?,
        customUserAgent: String?,
        azureMode: Bool = false
    ) -> Bool {
        guard let db else { return false }
        // LWW: skip if local row has updated_at >= incoming.
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, "SELECT updated_at FROM provider_instances WHERE id = ?", -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
            if sqlite3_step(stmt) == SQLITE_ROW {
                let localTs = sqlite3_column_double(stmt, 0)
                sqlite3_finalize(stmt)
                if localTs >= updatedAt {
                    return false
                }
            } else {
                sqlite3_finalize(stmt)
            }
        }
        upsertInstanceRow(
            id: id, label: label, providerType: providerType,
            credentialType: credentialType, customBaseURL: customBaseURL,
            appendV1Suffix: appendV1Suffix,
            imageEndpointMode: imageEndpointMode, imageEndpointResolved: imageEndpointResolved,
            isEnabled: isEnabled, sortOrder: sortOrder,
            secretBlob: secretBlob, secretKind: secretKind, secretUpdatedAt: secretUpdatedAt,
            createdAt: createdAt, updatedAt: updatedAt, extrasJson: extrasJson,
            customUserAgent: customUserAgent,
            azureMode: azureMode
        )
        return true
    }

    func upsertEntryFromInbound(
        id: String, providerInstanceId: String,
        baseModelJson: String, overridesJson: String?,
        isCustom: Bool, isHidden: Bool, userModifiedAt: Double?,
        sortOrder: Int, updatedAt: Double, extrasJson: String?
    ) -> Bool {
        guard let db else { return false }
        var localTs: Double?
        var localUserModifiedAt: Double?
        var localIsHidden = false
        var localOverridesJson: String?
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, "SELECT updated_at, user_modified_at, is_hidden, overrides_json FROM provider_model_entries WHERE id = ?", -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
            if sqlite3_step(stmt) == SQLITE_ROW {
                localTs = sqlite3_column_double(stmt, 0)
                if sqlite3_column_type(stmt, 1) != SQLITE_NULL {
                    localUserModifiedAt = sqlite3_column_double(stmt, 1)
                }
                localIsHidden = sqlite3_column_int(stmt, 2) != 0
                if sqlite3_column_type(stmt, 3) != SQLITE_NULL {
                    localOverridesJson = Self.text(stmt, 3)
                }
            }
        }
        sqlite3_finalize(stmt)
        if let localTs, localTs >= updatedAt { return false }

        // [T-ios-hidden-models-restored] Overlay guard — mirror the V2 merge's
        // userModifiedAt-aware conflict resolution (CloudSyncEngine
        // mergeProviderConfig) that this V3 per-record path was missing.
        //
        // The row-level updated_at LWW above is blind to WHO made the change:
        // bulkReplace stamps updated_at = userModifiedAt ?? now, so a peer
        // device's never-touched entry re-stamps to "now" on every save and
        // perpetually looks fresher than a locally-hidden entry whose
        // updated_at is frozen at the hide time. After an app update changes
        // model metadata, the peer marks ALL its entries dirty and the inbound
        // batch stomped every local isHidden back to false — the "100+ hidden
        // models all restored" report.
        //
        // Rule: the USER-INTENT overlay (isHidden / overrides / userModifiedAt)
        // only moves forward — a remote with no userModifiedAt (never edited
        // there) or an older stamp keeps the local overlay; the remote's
        // API-truth fields (baseModelJson etc.) still apply via updated_at LWW.
        var effIsHidden = isHidden
        var effOverridesJson = overridesJson
        var effUserModifiedAt = userModifiedAt
        if let localUM = localUserModifiedAt, (userModifiedAt ?? 0) < localUM {
            effIsHidden = localIsHidden
            effOverridesJson = localOverridesJson
            effUserModifiedAt = localUM
        }

        upsertEntryRow(
            id: id, providerInstanceId: providerInstanceId,
            baseModelJson: baseModelJson, overridesJson: effOverridesJson,
            isCustom: isCustom, isHidden: effIsHidden,
            userModifiedAt: effUserModifiedAt,
            sortOrder: sortOrder, updatedAt: updatedAt, extrasJson: extrasJson
        )
        return true
    }

    /// [T-icloud-provider-sync-consistency] Inbound merge for a group record.
    ///
    /// Two independent merge tracks:
    ///   • SCALAR fields (name, strategy, limits, sortOrder) — last-write-wins
    ///     by `updatedAt`. Skipped when the local row is newer.
    ///   • MEMBER set — ALWAYS merged as a per-member timestamp CRDT, even when
    ///     the scalar LWW says "local newer". This is the core fix: a member
    ///     addition/removal from a peer is never dropped just because this
    ///     device touched the group's scalar fields more recently.
    ///
    /// Member merge:
    ///   addedMerged[m]   = max over local+inbound addedMembers[m]
    ///   removedMerged[m] = max over local+inbound removedMembers[m]
    ///   m is PRESENT  iff  added[m] (default .distantPast) >= removed[m] (default .distantPast)
    ///   final order   = local order first (kept stable), then inbound-only
    ///                   present members appended — both filtered to present.
    ///
    /// Returns true if anything (scalar or members) changed and was written.
    func upsertGroupFromInbound(
        id: String, name: String, strategy: String, fallbackStrategy: String,
        defaultThinkingLevel: String?, contextLimitTokens: Int?,
        contextLimitRemembered: Int?, memberEntryIdsJson: String,
        sortOrder: Int, updatedAt: Double, extrasJson: String?,
        inboundAddedMembers: [String: Date] = [:],
        inboundRemovedMembers: [String: Date] = [:]
    ) -> Bool {
        guard let db else { return false }

        // Read local row (scalar ts + member state) if present.
        var localTs: Double? = nil
        var localMemberJSON = "[]"
        var localAdded: [String: Date] = [:]
        var localRemoved: [String: Date] = [:]
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, "SELECT updated_at, member_entry_ids_json, added_members_json, removed_members_json FROM provider_model_groups WHERE id = ?", -1, &stmt, nil) == SQLITE_OK {
            sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
            if sqlite3_step(stmt) == SQLITE_ROW {
                localTs = sqlite3_column_double(stmt, 0)
                localMemberJSON = Self.text(stmt, 1)
                localAdded = Self.decodeMemberTimestamps(Self.text(stmt, 2))
                localRemoved = Self.decodeMemberTimestamps(Self.text(stmt, 3))
            }
        }
        sqlite3_finalize(stmt)

        let scalarIsNewer = (localTs == nil) || (updatedAt > localTs!)

        // Parse inbound member order.
        let inboundMembers: [String] = {
            guard let d = memberEntryIdsJson.data(using: .utf8),
                  let a = try? JSONDecoder().decode([String].self, from: d) else { return [] }
            return a
        }()
        let localMembers: [String] = {
            guard let d = localMemberJSON.data(using: .utf8),
                  let a = try? JSONDecoder().decode([String].self, from: d) else { return [] }
            return a
        }()

        // Backfill add timestamps for members that predate the v2 schema:
        // any member currently listed with no addedMembers entry is treated as
        // "added at distantPast" so an explicit removal (which always carries a
        // real timestamp) wins, but a bare presence on one side doesn't get
        // resurrected over a real removal on the other.
        func backfill(_ members: [String], into map: inout [String: Date]) {
            for m in members where map[m] == nil { map[m] = .distantPast }
        }
        backfill(localMembers, into: &localAdded)

        // Merge add/remove maps by max-time.
        func mergeMax(_ a: [String: Date], _ b: [String: Date]) -> [String: Date] {
            var out = a
            for (k, v) in b { if let cur = out[k] { out[k] = max(cur, v) } else { out[k] = v } }
            return out
        }
        var inboundAdded = inboundAddedMembers
        backfill(inboundMembers, into: &inboundAdded)
        let addedMerged = mergeMax(localAdded, inboundAdded)
        let removedMerged = mergeMax(localRemoved, inboundRemovedMembers)

        // Determine present members: added >= removed.
        func isPresent(_ m: String) -> Bool {
            let a = addedMerged[m] ?? .distantPast
            let r = removedMerged[m] ?? .distantPast
            return a >= r
        }
        // [T-icloud-provider-sync-consistency] Final ORDER follows the group's
        // LWW: the side with the newer group updatedAt wins the member order, so
        // a reorder on the most-recently-edited device converges on every peer
        // (fallback priority is the member order, so divergent order = divergent
        // priority — a real bug if order were just "local first"). Set MEMBERS
        // is still a union (timestamp CRDT below decides presence) so no addition
        // is lost; only the ORDERING defers to the newer side. The newer side's
        // order leads; any present member it doesn't list (a concurrent add the
        // newer side hadn't seen) is appended after, in the other side's order.
        let primaryOrder = scalarIsNewer ? inboundMembers : localMembers
        let secondaryOrder = scalarIsNewer ? localMembers : inboundMembers
        var finalMembers: [String] = []
        var seen = Set<String>()
        for m in primaryOrder where isPresent(m) && !seen.contains(m) { finalMembers.append(m); seen.insert(m) }
        for m in secondaryOrder where isPresent(m) && !seen.contains(m) { finalMembers.append(m); seen.insert(m) }
        // Defensive: any present member only in addedMerged keys (order entry
        // dropped somewhere) — appended last.
        for m in addedMerged.keys where isPresent(m) && !seen.contains(m) { finalMembers.append(m); seen.insert(m) }

        // Prune tombstones for members that are no longer referenced anywhere
        // (keeps the maps from growing unbounded). A removed member with no
        // chance of re-add reference can drop its add entry; keep removed
        // entries only while they still dominate.
        let referenced = Set(finalMembers)
        let finalAdded = addedMerged.filter { referenced.contains($0.key) }
        // Keep removed entries that are NOT present (active tombstones) so a
        // future inbound re-add is correctly arbitrated; drop those already
        // present (their removal lost).
        let finalRemoved = removedMerged.filter { !referenced.contains($0.key) }

        // Decide scalar values: newer side wins; if local newer, keep local
        // scalars (re-read not needed — only members changed).
        let memberChanged = finalMembers != localMembers
            || Self.encodeMemberTimestamps(finalAdded) != Self.encodeMemberTimestamps(localAdded.filter { referenced.contains($0.key) })
            || Self.encodeMemberTimestamps(finalRemoved) != Self.encodeMemberTimestamps(localRemoved.filter { !referenced.contains($0.key) })

        if !scalarIsNewer && !memberChanged {
            return false  // nothing to do
        }

        // Resolve scalar fields: if inbound scalar is newer use inbound,
        // otherwise preserve local scalars by re-reading them.
        var useName = name, useStrategy = strategy, useFallback = fallbackStrategy
        var useThinking = defaultThinkingLevel, useCtx = contextLimitTokens
        var useCtxRem = contextLimitRemembered, useSort = sortOrder
        var useUpdatedAt = updatedAt, useExtras = extrasJson
        if !scalarIsNewer {
            // Local scalars win; re-read them.
            var s2: OpaquePointer?
            if sqlite3_prepare_v2(db, "SELECT name, strategy, fallback_strategy, default_thinking_level, context_limit_tokens, context_limit_remembered, sort_order, updated_at, extras_json FROM provider_model_groups WHERE id = ?", -1, &s2, nil) == SQLITE_OK {
                sqlite3_bind_text(s2, 1, id, -1, Self.SQLITE_TRANSIENT)
                if sqlite3_step(s2) == SQLITE_ROW {
                    useName = Self.text(s2, 0)
                    useStrategy = Self.text(s2, 1)
                    useFallback = Self.text(s2, 2)
                    useThinking = Self.optText(s2, 3)
                    useCtx = Self.optInt(s2, 4)
                    useCtxRem = Self.optInt(s2, 5)
                    useSort = Int(sqlite3_column_int(s2, 6))
                    useUpdatedAt = sqlite3_column_double(s2, 7)
                    useExtras = Self.optText(s2, 8)
                }
            }
            sqlite3_finalize(s2)
        }

        let finalMemberJSON = (try? Self.jsonString(finalMembers)) ?? "[]"
        upsertGroupRow(
            id: id, name: useName, strategy: useStrategy, fallbackStrategy: useFallback,
            defaultThinkingLevel: useThinking,
            contextLimitTokens: useCtx,
            contextLimitRemembered: useCtxRem,
            memberEntryIdsJson: finalMemberJSON,
            sortOrder: useSort, updatedAt: useUpdatedAt, extrasJson: useExtras,
            removedMembersJson: Self.encodeMemberTimestamps(finalRemoved),
            addedMembersJson: Self.encodeMemberTimestamps(finalAdded)
        )
        return true
    }

    /// Delete a row by id. Used by V3 deletionApplier paths. Cascading FK
    /// on provider_model_entries.provider_instance_id removes dependent
    /// entries when an instance is deleted.
    func deleteInstanceRow(id: String) {
        guard let db else { return }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "DELETE FROM provider_instances WHERE id = ?", -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
        sqlite3_step(stmt)
    }

    func deleteEntryRow(id: String) {
        guard let db else { return }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "DELETE FROM provider_model_entries WHERE id = ?", -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
        sqlite3_step(stmt)
    }

    func deleteGroupRow(id: String) {
        guard let db else { return }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "DELETE FROM provider_model_groups WHERE id = ?", -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
        sqlite3_step(stmt)
    }

    // MARK: - Per-table upsert helpers (private; used by bulkReplace + S3 mutates)

    private func upsertInstanceRow(
        id: String, label: String, providerType: String,
        credentialType: String?, customBaseURL: String?, appendV1Suffix: Bool,
        imageEndpointMode: String?, imageEndpointResolved: String?,
        isEnabled: Bool, sortOrder: Int,
        secretBlob: String?, secretKind: String?, secretUpdatedAt: Double?,
        createdAt: Double, updatedAt: Double, extrasJson: String?,
        customUserAgent: String?,
        azureMode: Bool = false
    ) {
        guard let db else { return }
        let sql = """
            INSERT OR REPLACE INTO provider_instances
            (id, label, provider_type, credential_type, custom_base_url,
             append_v1_suffix, image_endpoint_mode, image_endpoint_resolved,
             is_enabled, sort_order, secret_blob, secret_kind, secret_updated_at,
             created_at, updated_at, extras_json, custom_user_agent, azure_mode)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, label, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 3, providerType, -1, Self.SQLITE_TRANSIENT)
        Self.bindOpt(stmt, 4, credentialType)
        Self.bindOpt(stmt, 5, customBaseURL)
        sqlite3_bind_int(stmt, 6, appendV1Suffix ? 1 : 0)
        Self.bindOpt(stmt, 7, imageEndpointMode)
        Self.bindOpt(stmt, 8, imageEndpointResolved)
        sqlite3_bind_int(stmt, 9, isEnabled ? 1 : 0)
        sqlite3_bind_int(stmt, 10, Int32(sortOrder))
        Self.bindOpt(stmt, 11, secretBlob)
        Self.bindOpt(stmt, 12, secretKind)
        Self.bindOptDouble(stmt, 13, secretUpdatedAt)
        sqlite3_bind_double(stmt, 14, createdAt)
        sqlite3_bind_double(stmt, 15, updatedAt)
        Self.bindOpt(stmt, 16, extrasJson)
        Self.bindOpt(stmt, 17, customUserAgent)
        sqlite3_bind_int(stmt, 18, azureMode ? 1 : 0)
        sqlite3_step(stmt)
    }

    private func upsertEntryRow(
        id: String, providerInstanceId: String,
        baseModelJson: String, overridesJson: String?,
        isCustom: Bool, isHidden: Bool, userModifiedAt: Double?,
        sortOrder: Int, updatedAt: Double, extrasJson: String?
    ) {
        guard let db else { return }
        let sql = """
            INSERT OR REPLACE INTO provider_model_entries
            (id, provider_instance_id, base_model_json, overrides_json,
             is_custom, is_hidden, user_modified_at, sort_order, updated_at, extras_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, providerInstanceId, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 3, baseModelJson, -1, Self.SQLITE_TRANSIENT)
        Self.bindOpt(stmt, 4, overridesJson)
        sqlite3_bind_int(stmt, 5, isCustom ? 1 : 0)
        sqlite3_bind_int(stmt, 6, isHidden ? 1 : 0)
        Self.bindOptDouble(stmt, 7, userModifiedAt)
        sqlite3_bind_int(stmt, 8, Int32(sortOrder))
        sqlite3_bind_double(stmt, 9, updatedAt)
        Self.bindOpt(stmt, 10, extrasJson)
        sqlite3_step(stmt)
    }

    private func upsertGroupRow(
        id: String, name: String, strategy: String, fallbackStrategy: String,
        defaultThinkingLevel: String?, contextLimitTokens: Int?,
        contextLimitRemembered: Int?, memberEntryIdsJson: String,
        sortOrder: Int, updatedAt: Double, extrasJson: String?,
        removedMembersJson: String = "{}",
        addedMembersJson: String = "{}"
    ) {
        guard let db else { return }
        let sql = """
            INSERT OR REPLACE INTO provider_model_groups
            (id, name, strategy, fallback_strategy, default_thinking_level,
             context_limit_tokens, context_limit_remembered, member_entry_ids_json,
             sort_order, updated_at, extras_json, removed_members_json, added_members_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, id, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, name, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 3, strategy, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 4, fallbackStrategy, -1, Self.SQLITE_TRANSIENT)
        Self.bindOpt(stmt, 5, defaultThinkingLevel)
        Self.bindOptInt(stmt, 6, contextLimitTokens)
        Self.bindOptInt(stmt, 7, contextLimitRemembered)
        sqlite3_bind_text(stmt, 8, memberEntryIdsJson, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_int(stmt, 9, Int32(sortOrder))
        sqlite3_bind_double(stmt, 10, updatedAt)
        Self.bindOpt(stmt, 11, extrasJson)
        sqlite3_bind_text(stmt, 12, removedMembersJson, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 13, addedMembersJson, -1, Self.SQLITE_TRANSIENT)
        sqlite3_step(stmt)
    }

    private func setLocalKVRow(_ key: String, value: String) {
        guard let db else { return }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "INSERT OR REPLACE INTO provider_local_kv (key, value) VALUES (?, ?)", -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, key, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, value, -1, Self.SQLITE_TRANSIENT)
        sqlite3_step(stmt)
    }

    /// [T-provider-entry-composite-key] Persist the legacyUuid→compositeKey map
    /// (JSON) into provider_local_kv so deferred normalization survives restarts.
    func setLegacyUuidMapKV(_ json: String) {
        setLocalKVRow("legacyUuidMap", value: json)
    }

    private func upsertSessionBindingRow(sessionId: String, bindingJson: String, updatedAt: Double) {
        guard let db else { return }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = "INSERT OR REPLACE INTO provider_session_bindings (session_id, binding_json, updated_at) VALUES (?, ?, ?)"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, sessionId, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, bindingJson, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_double(stmt, 3, updatedAt)
        sqlite3_step(stmt)
    }

    private func upsertSessionInferenceConfigRow(sessionId: String, configJson: String, updatedAt: Double) {
        guard let db else { return }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = "INSERT OR REPLACE INTO provider_session_inference_configs (session_id, config_json, updated_at) VALUES (?, ?, ?)"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, sessionId, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, configJson, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_double(stmt, 3, updatedAt)
        sqlite3_step(stmt)
    }

    private func insertAgentLoopIdRow(kind: String, targetId: String, sortOrder: Int) {
        guard let db else { return }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        let sql = "INSERT OR REPLACE INTO provider_agent_loop_ids (kind, target_id, sort_order) VALUES (?, ?, ?)"
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        sqlite3_bind_text(stmt, 1, kind, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_text(stmt, 2, targetId, -1, Self.SQLITE_TRANSIENT)
        sqlite3_bind_int(stmt, 3, Int32(sortOrder))
        sqlite3_step(stmt)
    }

    private func loadAllSessionBindings() -> [String: SessionModelBinding] {
        guard let db else { return [:] }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "SELECT session_id, binding_json FROM provider_session_bindings", -1, &stmt, nil) == SQLITE_OK else { return [:] }
        var result: [String: SessionModelBinding] = [:]
        let decoder = JSONDecoder()
        while sqlite3_step(stmt) == SQLITE_ROW {
            let sid = Self.text(stmt, 0)
            let json = Self.text(stmt, 1)
            if let data = json.data(using: .utf8),
               let binding = try? decoder.decode(SessionModelBinding.self, from: data) {
                result[sid] = binding
            }
        }
        return result
    }

    private func loadAllSessionInferenceConfigs() -> [String: SessionInferenceConfig] {
        guard let db else { return [:] }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "SELECT session_id, config_json FROM provider_session_inference_configs", -1, &stmt, nil) == SQLITE_OK else { return [:] }
        var result: [String: SessionInferenceConfig] = [:]
        let decoder = JSONDecoder()
        while sqlite3_step(stmt) == SQLITE_ROW {
            let sid = Self.text(stmt, 0)
            let json = Self.text(stmt, 1)
            if let data = json.data(using: .utf8),
               let cfg = try? decoder.decode(SessionInferenceConfig.self, from: data) {
                result[sid] = cfg
            }
        }
        return result
    }

    private func loadAgentLoopIds(kind: String) -> [String] {
        guard let db else { return [] }
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, "SELECT target_id FROM provider_agent_loop_ids WHERE kind = ? ORDER BY sort_order ASC", -1, &stmt, nil) == SQLITE_OK else { return [] }
        sqlite3_bind_text(stmt, 1, kind, -1, Self.SQLITE_TRANSIENT)
        var result: [String] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            result.append(Self.text(stmt, 0))
        }
        return result
    }

    // MARK: - Bind helpers

    private static func bindOpt(_ stmt: OpaquePointer?, _ idx: Int32, _ value: String?) {
        if let v = value {
            sqlite3_bind_text(stmt, idx, v, -1, Self.SQLITE_TRANSIENT)
        } else {
            sqlite3_bind_null(stmt, idx)
        }
    }

    private static func bindOptInt(_ stmt: OpaquePointer?, _ idx: Int32, _ value: Int?) {
        if let v = value {
            sqlite3_bind_int64(stmt, idx, Int64(v))
        } else {
            sqlite3_bind_null(stmt, idx)
        }
    }

    private static func bindOptDouble(_ stmt: OpaquePointer?, _ idx: Int32, _ value: Double?) {
        if let v = value {
            sqlite3_bind_double(stmt, idx, v)
        } else {
            sqlite3_bind_null(stmt, idx)
        }
    }

    private static func jsonString<T: Encodable>(_ value: T) throws -> String {
        let data = try JSONEncoder().encode(value)
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    /// Convenience: counts across the four sync-domain tables. Helpful for
    /// debug RPC + post-migration sanity checks.
    func counts() -> (instances: Int, entries: Int, groups: Int) {
        guard let db else { return (0, 0, 0) }
        func one(_ sql: String) -> Int {
            var stmt: OpaquePointer?
            defer { sqlite3_finalize(stmt) }
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK,
                  sqlite3_step(stmt) == SQLITE_ROW else { return 0 }
            return Int(sqlite3_column_int(stmt, 0))
        }
        return (
            one("SELECT COUNT(*) FROM provider_instances"),
            one("SELECT COUNT(*) FROM provider_model_entries"),
            one("SELECT COUNT(*) FROM provider_model_groups")
        )
    }

    // MARK: - Helpers

    private static let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private static func text(_ stmt: OpaquePointer?, _ col: Int32) -> String {
        guard let cString = sqlite3_column_text(stmt, col) else { return "" }
        return String(cString: cString)
    }

    private static func optText(_ stmt: OpaquePointer?, _ col: Int32) -> String? {
        guard sqlite3_column_type(stmt, col) != SQLITE_NULL,
              let cString = sqlite3_column_text(stmt, col) else { return nil }
        let s = String(cString: cString)
        return s.isEmpty ? nil : s
    }

    private static func optInt(_ stmt: OpaquePointer?, _ col: Int32) -> Int? {
        guard sqlite3_column_type(stmt, col) != SQLITE_NULL else { return nil }
        return Int(sqlite3_column_int64(stmt, col))
    }

    private static func optDouble(_ stmt: OpaquePointer?, _ col: Int32) -> Double? {
        guard sqlite3_column_type(stmt, col) != SQLITE_NULL else { return nil }
        return sqlite3_column_double(stmt, col)
    }
}

enum ProviderConfigDBError: Error {
    case openFailed(path: String, code: Int32)
}
