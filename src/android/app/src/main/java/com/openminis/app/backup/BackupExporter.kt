package com.openminis.app.backup

import android.content.Context
import com.openminis.app.data.db.AppDatabase
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.db.CompactMarkerEntity
import com.openminis.app.data.db.FolderEntity
import com.openminis.app.data.db.MessageEntity
import com.openminis.app.logging.AppLogger
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import java.util.UUID

/**
 * Builds a `.minisbak` package on Android (docs/backup-restore-design.md §2,
 * §9 stage 4), mirroring `src/ios/Agent/Backup/BackupExporter.swift`.
 *
 * Shape: stage everything into a scratch directory, then zip that directory
 * once. Staging rather than streaming straight into an archive means a failure
 * part-way leaves no half-written package at the destination — the same
 * approach ChatExporter already uses here, and BackupExporter uses on iOS.
 *
 * Record field names are the cross-platform contract. iOS writes its Swift
 * models with the synthesized Codable encoder, so they are camelCase with
 * ISO-8601 dates, and this reproduces that exactly — the manifest's snake_case
 * (§2.1) applies to the manifest alone, not to the JSONL records inside it.
 * Deviating in either direction makes packages mutually unreadable, which §5.4
 * explicitly forbids.
 */
class BackupExporter(
    private val context: Context,
    private val db: AppDatabase,
) {

    data class Options(
        val categories: Set<BackupCategory> = BackupCategory.backupable.toSet(),
        /** §3.4 — null means unlimited, which is the DEFAULT. */
        val maxFileBytes: Long? = null,
        /**
         * §3.3: credentials ship WITH the Providers category by default, so a
         * restored provider actually works. False produces the "export copy
         * without credentials" share package.
         */
        val includeCredentials: Boolean = true,
        /** null/empty = unencrypted package. */
        val passphrase: String? = null,
        /**
         * Data cut-off for this export. Everything the package contains is the
         * state as of this instant; rows updated after it, and files modified
         * after it, are excluded. Without a cut-off the export is not a
         * snapshot — a session written between the index pass and the blob copy
         * lands in files.index while its content never gets stored, producing a
         * package that references content it does not contain.
         */
        val snapshotAtMillis: Long = System.currentTimeMillis(),
    )

    data class Summary(
        val packageFile: File,
        val backupId: String,
        val totalBytes: Long,
        val categories: Map<String, BackupManifest.CategoryStat>,
        val skippedFiles: Int,
        val skippedBytes: Long,
        val skippedPaths: List<BackupBlobStore.SkippedPath>,
        val durationMillis: Long,
    )

    /**
     * Export a package.
     *
     * Serialised process-wide: a second export (or an export racing a restore)
     * would read the same stores while the other mutates them, so the two are
     * refused rather than interleaved — the same rule as iOS's
     * BackupActivityLock (review I3).
     */
    suspend fun export(
        options: Options = Options(),
        onProgress: ((String) -> Unit)? = null,
    ): Summary = activityLock.withLock { exportBody(options, onProgress) }

    private suspend fun exportBody(options: Options, onProgress: ((String) -> Unit)?): Summary {
        // §3.3 / §5.4: a package that carries credentials MUST be encrypted.
        // Enforced here rather than only in the UI, so no caller — a debug RPC,
        // a future scheduler, anything — can produce a plaintext copy of the
        // user's API keys by omitting a passphrase.
        val wantsCredentials =
            options.includeCredentials && BackupCategory.PROVIDERS in options.categories
        if (wantsCredentials && options.passphrase.isNullOrEmpty()) {
            throw BackupException(
                "Refusing to export credentials without a passphrase. Set one, or pass " +
                    "includeCredentials=false for a share copy."
            )
        }

        val started = System.currentTimeMillis()
        val backupId = UUID.randomUUID().toString()

        // Staging lives in filesDir, not cacheDir: the system may evict the
        // cache mid-export, and a multi-GB staging tree disappearing underneath
        // the writer is a failure mode worth designing out.
        val staging = File(context.filesDir, "backup-staging/$backupId")
        staging.mkdirs()
        try {
            val dataDir = File(staging, "data").apply { mkdirs() }
            val blobStore = BackupBlobStore(staging, options.maxFileBytes)
            val stats = mutableMapOf<String, BackupManifest.CategoryStat>()

            BackupFileIndexWriter(File(staging, "files.index.jsonl")).use { fileIndex ->
                val trees = BackupFileTreeExporter(blobStore, fileIndex, options.snapshotAtMillis)

                if (BackupCategory.CHATS in options.categories) {
                    onProgress?.invoke("Exporting chats…")
                    stats[BackupCategory.CHATS.key] =
                        exportChats(dataDir, trees, options.snapshotAtMillis)
                }
                if (BackupCategory.SHARED_FILES in options.categories) {
                    onProgress?.invoke("Exporting shared files…")
                    stats[BackupCategory.SHARED_FILES.key] = exportSharedFiles(trees)
                }
                if (BackupCategory.SKILLS in options.categories) {
                    onProgress?.invoke("Exporting skills…")
                    stats[BackupCategory.SKILLS.key] = exportSkills(trees)
                }
                if (BackupCategory.MEMORY in options.categories) {
                    onProgress?.invoke("Exporting memory…")
                    stats[BackupCategory.MEMORY.key] = exportMemory(dataDir)
                }
                if (BackupCategory.MCP_SERVERS in options.categories) {
                    onProgress?.invoke("Exporting MCP servers…")
                    exportMcpServers(dataDir)?.let { stats[BackupCategory.MCP_SERVERS.key] = it }
                }
            }

            // Blob index last — it is only complete once every category has
            // offered its files.
            writeBlobIndex(blobStore.blobIndex, staging)

            // Encryption happens BEFORE the manifest is built, because §5.3
            // says `integrity` records the CIPHERTEXT hash — that is what lets
            // a reader verify completeness without holding the passphrase.
            var encryption: BackupManifest.Encryption? = null
            var keys: BackupCrypto.Keys? = null
            if (!options.passphrase.isNullOrEmpty()) {
                onProgress?.invoke("Encrypting…")
                val salt = BackupCrypto.makeSalt()
                val kdf = BackupCrypto.currentKDF(salt)
                val derived = BackupCrypto.deriveKeys(options.passphrase, kdf)
                encryptStagedMembers(staging, derived)
                encryption = BackupManifest.Encryption(BackupCrypto.SCHEME, kdf, derived.verifier)
                keys = derived
                // Every category's bytes are now ciphertext, so the per-category
                // flag must say so rather than keeping the plaintext `false`.
                stats.replaceAll { _, v -> v.copy(encrypted = true) }
            }

            onProgress?.invoke("Writing manifest…")
            val manifest = buildManifest(backupId, stats, blobStore, staging, encryption, options)
            val manifestFile = File(staging, "manifest.json")
            manifestFile.writeText(
                BackupFormat.json.encodeToString(BackupManifest.serializer(), manifest)
            )
            if (keys != null) {
                // Sidecar MAC over the file's exact bytes. Android does not
                // write the embedded `manifest_mac`: that field authenticates a
                // Swift re-encoding of the decoded struct, which cannot be
                // reproduced byte-exactly here, and a MAC that only one
                // platform can compute is worse than none. Both importers
                // prefer this sidecar.
                File(staging, "manifest.mac")
                    .writeText(BackupCrypto.manifestMac(manifestFile.readBytes(), keys.macKey))
                keys.destroy()
            }

            onProgress?.invoke("Packaging…")
            val packageFile = archive(staging, backupId)
            val duration = System.currentTimeMillis() - started
            AppLogger.info(
                TAG,
                "[Backup] done id=$backupId bytes=${packageFile.length()} " +
                    "skipped=${blobStore.skippedFiles} in ${duration}ms"
            )

            return Summary(
                packageFile = packageFile,
                backupId = backupId,
                totalBytes = packageFile.length(),
                categories = stats,
                skippedFiles = blobStore.skippedFiles,
                skippedBytes = blobStore.skippedBytes,
                skippedPaths = blobStore.skippedPaths.toList(),
                durationMillis = duration,
            )
        } finally {
            // The archive is the deliverable; the staging tree is scratch and
            // can be several GB. Always clear it, including on failure.
            staging.deleteRecursively()
            File(context.filesDir, "backup-staging").takeIf {
                it.listFiles()?.isEmpty() == true
            }?.delete()
        }
    }

    // MARK: - Chats

    private suspend fun exportChats(
        dataDir: File,
        trees: BackupFileTreeExporter,
        snapshotAtMillis: Long,
    ): BackupManifest.CategoryStat {
        val dao = db.chatDao()
        var messageCount = 0
        var fileCount = 0
        var fileBytes = 0L
        var jsonlBytes = 0L

        BackupJsonlWriter(dataDir, "sessions").use { sessions ->
            BackupJsonlWriter(dataDir, "messages").use { messages ->
                BackupJsonlWriter(dataDir, "compact_markers").use { markers ->
                    BackupJsonlWriter(dataDir, "folders").use { folders ->
                        for (session in dao.listSessions()) {
                            // Snapshot cut-off: a session updated after the user
                            // pressed Create Backup is not part of this backup's
                            // view. Excluding the WHOLE session rather than
                            // trimming its messages keeps the package internally
                            // consistent — a session row is never written without
                            // the messages that belong to it.
                            if (session.updatedAt > snapshotAtMillis) {
                                AppLogger.info(
                                    TAG, "[Backup] skip session newer than snapshot: ${session.id}"
                                )
                                continue
                            }
                            sessions.write("SessionV2", 1, sessionRecord(session))

                            for (msg in dao.loadMessages(session.id)) {
                                if (msg.createdAt > snapshotAtMillis) continue
                                messages.write("MessageV2", 1, messageRecord(msg))
                                messageCount += 1
                            }
                            for (marker in dao.listCompactMarkers(session.id)) {
                                markers.write("CompactMarkerV2", 1, markerRecord(marker))
                            }

                            // The session's whole on-disk tree: attachments /
                            // offloads / workspace / browser.
                            val dir = File(context.filesDir, "minis-sessions/${session.id}")
                            val r = trees.export(
                                dir, "chats/${session.id}", BackupCategory.CHATS, session.id
                            )
                            fileCount += r.filesIncluded
                            fileBytes += r.bytesIncluded
                        }

                        for (folder in dao.listFolders()) {
                            folders.write("FolderV2", 1, folderRecord(folder))
                        }
                        jsonlBytes = sessions.totalBytes + messages.totalBytes +
                            markers.totalBytes + folders.totalBytes
                    }
                }
            }
        }

        return BackupManifest.CategoryStat(
            entries = messageCount + fileCount,
            bytes = jsonlBytes + fileBytes,
            encrypted = false,
            messages = messageCount,
            files = fileCount,
        )
    }

    /**
     * The session row as iOS writes it.
     *
     * Field names and date format follow iOS's `ChatSession` under the
     * synthesized Codable encoder (camelCase, ISO-8601), plus the two extras
     * iOS keeps alongside it in `SessionRecord`. Android-only columns with no
     * iOS counterpart (`editCount`, `thinkingOverride`) are carried too: §2.2
     * rule 4 says platform-specific data is preserved and ignored by the other
     * side, which is strictly better than dropping a user's per-session
     * thinking override on a same-platform restore.
     *
     * Device-local fields are deliberately absent — see [messageRecord].
     */
    private fun sessionRecord(s: ChatSessionEntity): JsonElement = buildJsonObject {
        put("id", JsonPrimitive(s.id))
        put("title", s.title?.let(::JsonPrimitive) ?: JsonNull)
        put("category", s.category?.let(::JsonPrimitive) ?: JsonNull)
        put("modelId", JsonPrimitive(s.modelId))
        put("createdAt", JsonPrimitive(iso8601(s.createdAt)))
        put("updatedAt", JsonPrimitive(iso8601(s.updatedAt)))
        put("lastMessage", s.lastMessage?.let(::JsonPrimitive) ?: JsonNull)
        put("source", s.source?.let(::JsonPrimitive) ?: JsonNull)
        put("pinnedAt", s.pinnedAt?.let { JsonPrimitive(iso8601(it)) } ?: JsonNull)
        put("folderId", s.folderId?.let(::JsonPrimitive) ?: JsonNull)
        // iOS's SessionRecord wrapper fields.
        put("memoryEnabled", JsonPrimitive(s.memoryEnabled != 0))
        put("modelBinding", s.modelBinding?.let(::JsonPrimitive) ?: JsonNull)
        // Android-only, preserved per §2.2 rule 4.
        put("editCount", JsonPrimitive(s.editCount))
        put("thinkingOverride", s.thinkingOverride?.let(::JsonPrimitive) ?: JsonNull)
    }

    /**
     * The message row as iOS writes it.
     *
     * `parts` is spliced in as pre-parsed JSON rather than re-encoded: the
     * column already holds the exact `[ContentPart]` array iOS's ContentPart
     * encoder produces (`{"type":…,"value":…}`), so passing it through keeps
     * MediaRef paths and tool payloads byte-identical. Re-encoding through a
     * Kotlin model would risk reordering or dropping a field the Android model
     * doesn't know about.
     *
     * `errorInfo` is NOT written. §0.2 lists it with `part_flags` as a
     * device-local field the portable record excludes: an error sticker for a
     * failed turn on the old device is meaningless on the new one, and
     * restoring it would resurrect a red error badge against a message that
     * never failed for this install.
     */
    private fun messageRecord(m: MessageEntity): JsonElement = buildJsonObject {
        put("id", JsonPrimitive(m.id))
        put("sessionId", JsonPrimitive(m.sessionId))
        put("role", JsonPrimitive(m.role))
        put("parts", parseParts(m.partsJson))
        put("createdAt", JsonPrimitive(iso8601(m.createdAt)))
        put("tokenUsage", m.tokenUsage?.let { parseJsonOrNull(it) } ?: JsonNull)
        put("reasoningContent", m.reasoningContent?.let(::JsonPrimitive) ?: JsonNull)
        put("streamInterruptCount", JsonPrimitive(m.streamInterruptCount))
        put("sortOrder", JsonPrimitive(m.sortOrder))
    }

    private fun markerRecord(c: CompactMarkerEntity): JsonElement = buildJsonObject {
        put("id", JsonPrimitive(c.id))
        put("sessionId", JsonPrimitive(c.sessionId))
        put("summary", JsonPrimitive(c.summary))
        put("firstKeptSortOrder", JsonPrimitive(c.firstKeptSortOrder))
        put("compactedCount", JsonPrimitive(c.compactedCount))
        put("createdAt", JsonPrimitive(iso8601(c.createdAt)))
        put("uiBoundarySortOrder", c.uiBoundarySortOrder?.let(::JsonPrimitive) ?: JsonNull)
        put("boundaryMessageId", c.boundaryMessageId?.let(::JsonPrimitive) ?: JsonNull)
        put("firstKeptMessageId", c.firstKeptMessageId?.let(::JsonPrimitive) ?: JsonNull)
        put("lastCompactedMessageId", c.lastCompactedMessageId?.let(::JsonPrimitive) ?: JsonNull)
    }

    private fun folderRecord(f: FolderEntity): JsonElement = buildJsonObject {
        put("id", JsonPrimitive(f.id))
        put("name", JsonPrimitive(f.name))
        put("icon", f.icon?.let(::JsonPrimitive) ?: JsonNull)
        put("color", f.color?.let(::JsonPrimitive) ?: JsonNull)
        put("origin", JsonPrimitive(f.origin))
        put("sortIndex", JsonPrimitive(f.sortIndex))
        put("pinnedAt", f.pinnedAt?.let { JsonPrimitive(iso8601(it)) } ?: JsonNull)
        put("description", f.description?.let(::JsonPrimitive) ?: JsonNull)
        put("createdAt", JsonPrimitive(iso8601(f.createdAt)))
        // Record edits only (rename / pin / icon) — a session moving in or out
        // of the group must not touch it, so this is a stable merge key.
        put("updatedAt", JsonPrimitive(iso8601(f.updatedAt)))
    }

    // MARK: - Shared files / Skills / Memory

    /**
     * §3.2 — the cross-session `/var/minis/shared` bucket. Host-side this is
     * `<filesDir>/minis-global/shared`, NOT anything inside the rootfs.
     */
    private fun exportSharedFiles(trees: BackupFileTreeExporter): BackupManifest.CategoryStat {
        val r = trees.export(
            File(context.filesDir, "minis-global/shared"), "shared", BackupCategory.SHARED_FILES
        )
        return BackupManifest.CategoryStat(r.filesIncluded, r.bytesIncluded, encrypted = false)
    }

    private fun exportSkills(trees: BackupFileTreeExporter): BackupManifest.CategoryStat {
        val r = trees.export(
            File(context.filesDir, "minis-global/skills"), "skills", BackupCategory.SKILLS
        )
        return BackupManifest.CategoryStat(r.filesIncluded, r.bytesIncluded, encrypted = false)
    }

    /** `GLOBAL.md` / `SOUL.md` / daily notes, copied verbatim into `data/memory/`. */
    private fun exportMemory(dataDir: File): BackupManifest.CategoryStat {
        val source = File(context.filesDir, "minis-global/memory")
        val dest = File(dataDir, "memory").apply { mkdirs() }
        var entries = 0
        var bytes = 0L
        if (source.isDirectory) {
            for (file in source.walkTopDown().filter { it.isFile }) {
                val rel = file.relativeTo(source).path.replace(File.separatorChar, '/')
                val out = File(dest, rel).apply { parentFile?.mkdirs() }
                file.copyTo(out, overwrite = true)
                entries += 1
                bytes += file.length()
            }
        }
        return BackupManifest.CategoryStat(entries, bytes, encrypted = false)
    }

    /**
     * `servers.json` verbatim. Returns null when there is nothing to write, so
     * an absent MCP config contributes no category rather than an empty one.
     */
    private fun exportMcpServers(dataDir: File): BackupManifest.CategoryStat? {
        val source = File(context.filesDir, "minis-global/mcp-servers/servers.json")
        if (!source.isFile) return null
        val dest = File(dataDir, "mcp_servers.json")
        source.copyTo(dest, overwrite = true)
        return BackupManifest.CategoryStat(1, source.length(), encrypted = false)
    }

    // MARK: - Package assembly

    /**
     * Encrypt every staged member in place, appending `.enc` to its name (§5.3).
     *
     * `manifest.json` is excluded — §2.1 requires it plaintext so the user can
     * see what a package holds before being asked for a passphrase.
     * `secrets.json` gets `K_secrets` rather than `K_data`; that separate
     * subkey is what makes "strip the credentials" a file deletion instead of a
     * re-encrypt of everything else (§5.4).
     */
    private fun encryptStagedMembers(staging: File, keys: BackupCrypto.Keys) {
        val base = staging.canonicalFile
        val members = base.walkTopDown()
            .filter { it.isFile && it.name != "manifest.json" }
            .toList()
        for (file in members) {
            val rel = file.relativeTo(base).path.replace(File.separatorChar, '/')
            val key = if (rel == "secrets.json") keys.secretsKey else keys.dataKey
            val dest = File(file.parentFile, "${file.name}.enc")
            // The AAD is the member's path INCLUDING the .enc suffix, i.e. the
            // name it actually ships under, so the importer binds to exactly
            // what it reads off disk.
            BackupCrypto.encryptFile(file, dest, key, "$rel.enc")
            file.delete()
        }
        AppLogger.info(TAG, "[Backup] encrypted ${members.size} member(s)")
    }

    private fun writeBlobIndex(entries: List<BackupBlobIndexEntry>, staging: File) {
        File(staging, "blobs.index.jsonl").outputStream().buffered().use { out ->
            for (e in entries) {
                val line = BackupFormat.json
                    .encodeToString(BackupBlobIndexEntry.serializer(), e) + "\n"
                out.write(line.toByteArray(Charsets.UTF_8))
            }
        }
    }

    private fun buildManifest(
        backupId: String,
        categories: Map<String, BackupManifest.CategoryStat>,
        blobStore: BackupBlobStore,
        staging: File,
        encryption: BackupManifest.Encryption?,
        options: Options,
    ): BackupManifest {
        // Integrity covers every packaged file, hashed over whatever bytes
        // actually ship — ciphertext once encryption has run (§5.3).
        val base = staging.canonicalFile
        val integrity = base.walkTopDown()
            .filter { it.isFile && it.name != "manifest.json" } // can't hash itself
            .associate { file ->
                file.relativeTo(base).path.replace(File.separatorChar, '/') to
                    BackupBlobStore.sha256OfFile(file)
            }

        return BackupManifest(
            createdAt = iso8601(System.currentTimeMillis()),
            snapshotAt = iso8601(options.snapshotAtMillis),
            app = BackupManifest.AppInfo(
                platform = "android",
                version = appVersion(),
                build = appBuild(),
            ),
            deviceName = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}".trim(),
            backupId = backupId,
            categories = categories,
            limits = BackupManifest.Limits(
                maxFileBytes = blobStore.maxFileBytesForManifest,
                skippedFiles = blobStore.skippedFiles,
                skippedBytes = blobStore.skippedBytes,
            ),
            encryption = encryption,
            integrity = integrity,
            // Deliberately null — see the sidecar note in exportBody.
            manifestMac = null,
        )
    }

    private fun archive(staging: File, backupId: String): File {
        val stamp = SimpleDateFormat("yyyyMMdd-HHmm", Locale.US).format(System.currentTimeMillis())
        // Minute-resolution alone collides when two exports run in the same
        // minute (trivially reachable when testing, or when a user retries with
        // a different selection) — the second would silently replace the first.
        val short = backupId.take(6).lowercase()
        val out = File(backupsDirectory(context), "backup-$stamp-$short.${BackupFormat.FILE_EXTENSION}")
        out.parentFile?.mkdirs()
        out.delete()

        // Write to a `.partial` sibling and rename on success. A kill or a full
        // disk mid-write would otherwise leave a TRUNCATED file carrying a
        // perfectly valid `.minisbak` name, which then shows up in the restore
        // picker with a plausible size and date — discovered only when the
        // restore fails, plausibly on a new device after wiping the old one.
        val partial = File(out.parentFile, ".${out.name}.partial")
        partial.delete()
        try {
            BackupZip.archive(staging, partial)
            if (!partial.renameTo(out)) {
                throw BackupException("Could not finalise the backup package.")
            }
        } catch (e: Exception) {
            partial.delete()
            throw e
        }
        return out
    }

    // MARK: - Helpers

    private fun parseParts(partsJson: String): JsonElement =
        parseJsonOrNull(partsJson) ?: BackupFormat.json.parseToJsonElement("[]")

    private fun parseJsonOrNull(raw: String): JsonElement? =
        runCatching { BackupFormat.json.parseToJsonElement(raw) }.getOrNull()

    private fun appVersion(): String = runCatching {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "?"
    }.getOrDefault("?")

    private fun appBuild(): String = runCatching {
        @Suppress("DEPRECATION")
        context.packageManager.getPackageInfo(context.packageName, 0).versionCode.toString()
    }.getOrDefault("?")

    companion object {
        private const val TAG = "Backup"

        /**
         * Process-wide export/restore lock. Both read the same stores, and a
         * restore mutates them, so they must never overlap (iOS review I3).
         */
        private val activityLock = Mutex()

        /**
         * Where finished packages live. A sibling of the agent-visible
         * directories, NOT inside `minis-global/shared` — that path is
         * bind-mounted into the guest at `/var/minis/shared`, so a package
         * (possibly holding API keys) would be readable and deletable by the
         * agent from a shell, and the next backup would sweep the previous one
         * in as user data, nesting packages without bound (§6.2.4).
         */
        fun backupsDirectory(context: Context): File =
            File(context.filesDir, BackupFileTreeExporter.BACKUPS_DIR_NAME).apply { mkdirs() }

        /** ISO-8601 in UTC, matching Swift's `.iso8601` date encoding strategy. */
        fun iso8601(millis: Long): String = SimpleDateFormat(
            "yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US
        ).apply { timeZone = TimeZone.getTimeZone("UTC") }.format(millis)
    }
}
