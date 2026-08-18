package com.openminis.app.backup

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * On-the-wire types for the `.minisbak` backup package.
 *
 * Spec: `docs/backup-restore-design.md` §2 / §2.1. This is the FORMAT layer,
 * mirroring `src/ios/Agent/Backup/BackupFormat.swift` field-for-field —
 * §5.4 explicitly forbids inventing a second format, and the manifest keys
 * are sealed by `manifest_mac`, so every name here is wire-frozen.
 *
 * Two rules from §2.2 shape every type:
 *   - Unknown fields are ignored, missing fields get defaults. Every field
 *     that isn't structurally required has a default or is nullable; the
 *     shared [BackupFormat.json] instance is configured tolerant.
 *   - JSONL records carry `t` (type) and `v` (record version) so a reader can
 *     dispatch by type and migrate per record.
 */
object BackupFormat {
    /** Format major version. An unrecognised value must refuse the package. */
    const val CURRENT = "minisbak/1"

    /** File extension registered to the app for "open to import". */
    const val FILE_EXTENSION = "minisbak"

    /**
     * Cap for a single JSONL shard (§2). Beyond this the writer rolls over to
     * `messages-0002.jsonl` etc., so the importer never holds one giant file
     * in memory.
     */
    const val MAX_SHARD_BYTES = 64 * 1024 * 1024

    /**
     * Tolerant parser per §2.2 rule 2: unknown keys ignored, defaults filled,
     * `null` never emitted for absent optionals (iOS omits them entirely and
     * its hand-written decoders treat explicit null and absence the same).
     */
    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }
}

/**
 * User-facing backup categories (§3). [key] is the manifest key and the
 * on-disk directory name, so renaming one is a format change.
 */
enum class BackupCategory(val key: String) {
    CHATS("chats"),
    SHARED_FILES("shared_files"),
    SKILLS("skills"),
    MEMORY("memory"),
    PROVIDERS("providers"),
    MCP_SERVERS("mcp_servers"),
    VOICE_CORRECTIONS("voice_corrections");

    /**
     * Categories that stream file trees through the blob store — the ones the
     * §3.4 size cap applies to.
     */
    val carriesFileTree: Boolean
        get() = when (this) {
            CHATS, SHARED_FILES, SKILLS -> true
            MEMORY, PROVIDERS, MCP_SERVERS, VOICE_CORRECTIONS -> false
        }

    companion object {
        fun fromKey(key: String): BackupCategory? = entries.firstOrNull { it.key == key }

        /**
         * Categories a NEW backup may include. Voice Corrections is excluded on
         * the export side only (feature not mature enough to back up, 2026-08-15
         * decision) — the enum case stays because `voice_corrections` sections
         * exist in already-written packages and must remain decodable.
         */
        val backupable: List<BackupCategory>
            get() = entries.filter { it != VOICE_CORRECTIONS }
    }
}

/**
 * `manifest.json` — ALWAYS plaintext, even in an encrypted package (§2.1), so
 * the user can see what a package holds before being asked for a passphrase.
 *
 * Dates travel as ISO-8601 strings, exactly the bytes iOS's
 * `JSONEncoder.dateEncodingStrategy = .iso8601` writes. They are kept as
 * strings here rather than parsed eagerly: the manifest is MAC'd over raw
 * bytes, and a parse-reformat cycle is precisely what the sidecar MAC exists
 * to avoid.
 */
@Serializable
data class BackupManifest(
    val format: String = BackupFormat.CURRENT,
    @SerialName("created_at") val createdAt: String = "",
    /** Data cut-off instant; null on packages from older writers. */
    @SerialName("snapshot_at") val snapshotAt: String? = null,
    val app: AppInfo = AppInfo(),
    /** Display-only. Deliberately NOT the deviceId (§3.1). */
    @SerialName("device_name") val deviceName: String = "Unknown device",
    @SerialName("backup_id") val backupId: String = "",
    val categories: Map<String, CategoryStat> = emptyMap(),
    val limits: Limits = Limits(),
    /** Absent on unencrypted packages. */
    val encryption: Encryption? = null,
    /**
     * Path → SHA-256 of the bytes as stored in the package. For an encrypted
     * package that is the CIPHERTEXT hash, so integrity can be checked before
     * the passphrase is known (§5.3).
     */
    val integrity: Map<String, String> = emptyMap(),
    /**
     * Legacy embedded MAC over a canonical re-encoding of the manifest.
     * Android never writes it (Swift's re-encoding cannot be reproduced
     * byte-exactly here); the authoritative MAC is the raw-bytes sidecar
     * member `manifest.mac`, which both platforms' readers prefer.
     */
    @SerialName("manifest_mac") val manifestMac: String? = null,
) {
    @Serializable
    data class AppInfo(
        val platform: String = "unknown",
        val version: String = "?",
        val build: String = "?",
    )

    /** Per-category counters shown in the picker before anything is decrypted. */
    @Serializable
    data class CategoryStat(
        val entries: Int = 0,
        val bytes: Long = 0,
        val encrypted: Boolean = false,
        /** Chats only: split `entries` so the UI can say "342 messages + 1204 files". */
        val messages: Int? = null,
        val files: Int? = null,
        /** Providers only: false marks a "shared copy" with credentials stripped (§3.3). */
        @SerialName("includes_credentials") val includesCredentials: Boolean? = null,
    )

    /** §3.4. `maxFileBytes == null` means unlimited — the default. */
    @Serializable
    data class Limits(
        @SerialName("max_file_bytes") val maxFileBytes: Long? = null,
        @SerialName("skipped_files") val skippedFiles: Int = 0,
        @SerialName("skipped_bytes") val skippedBytes: Long = 0,
    )

    @Serializable
    data class Encryption(
        val scheme: String = "",
        val kdf: KDF,
        val verifier: String = "",
    ) {
        @Serializable
        data class KDF(
            /**
             * `alg` and `salt` genuinely have no safe default — a wrong guess
             * would derive the wrong key and surface as "wrong passphrase",
             * so these two stay required (decode throws when absent).
             */
            val alg: String,
            val salt: String,
            @SerialName("m_kib") val mKib: Int? = null,
            val t: Int? = null,
            val p: Int? = null,
            val iterations: Int? = null,
        )
    }
}

/**
 * One line of `files.index.jsonl` — the directory-tree index (§2).
 *
 * Exists ALONGSIDE `blobs.index.jsonl`: blobs.index is a content map and
 * structurally cannot express an empty directory, a skipped path, or the tree
 * shape itself — exactly what a restore needs to rebuild `<sid>/`.
 */
@Serializable
data class BackupFileIndexEntry(
    /** Package-relative logical path, e.g. `chats/<sid>/offloads/out.zip`. */
    val path: String,
    /** Original byte size — recorded even for skipped entries. */
    val size: Long = 0,
    /** null for directories and for size-skipped tombstones. */
    val sha256: String? = null,
    val category: String = "",
    /**
     * Why the content is absent from the package. Present ONLY on tombstones:
     * `"size"` (§3.4 cap), `"not_downloaded"` (cloud placeholder), or
     * `"unreadable"`.
     */
    val skipped: String? = null,
    val isDirectory: Boolean? = null,
) {
    companion object {
        fun file(path: String, size: Long, sha256: String, category: BackupCategory) =
            BackupFileIndexEntry(path, size, sha256, category.key)

        /**
         * A file the size cap excluded — no sha256 (the bytes aren't in the
         * package) but path and true size stay visible (§3.4 "tombstone,
         * don't silently drop").
         */
        fun sizeSkipped(path: String, size: Long, category: BackupCategory) =
            BackupFileIndexEntry(path, size, null, category.key, skipped = "size")

        fun unreadable(path: String, size: Long, category: BackupCategory) =
            BackupFileIndexEntry(path, size, null, category.key, skipped = "unreadable")

        /** Empty directories would otherwise vanish, since nothing references them. */
        fun directory(path: String, category: BackupCategory) =
            BackupFileIndexEntry(path, 0, null, category.key, isDirectory = true)
    }
}

/** One line of `blobs.index.jsonl` — content-addressed payload map (§2). */
@Serializable
data class BackupBlobIndexEntry(
    val sha256: String,
    val size: Long,
    /** First logical path this content was seen at; duplicates only add a files.index line. */
    val path: String,
    val sessionId: String? = null,
    val mime: String? = null,
)

class BackupException(message: String, cause: Throwable? = null) : Exception(message, cause)
