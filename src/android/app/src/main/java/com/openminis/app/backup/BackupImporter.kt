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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * Restores a `.minisbak` package on Android (docs/backup-restore-design.md §8),
 * mirroring `src/ios/Agent/Backup/BackupImporter.swift`.
 *
 * Scope: **Merge mode** (§8.2's default) — match by id, newer `updatedAt` wins.
 * Replace / Skip-existing are stage 5.
 *
 * Flow (§8.1): read manifest → downgrade guard → unlock → integrity →
 * per-category import → report. A category that throws is reported as failed
 * and the rest continue, per §8.3's transaction boundary: a restore that got
 * five of six categories in is meaningfully different from one that got none.
 */
class BackupImporter(
    private val context: Context,
    private val db: AppDatabase,
) {

    data class Options(
        /** null = every category present in the package. */
        val categories: Set<BackupCategory>? = null,
        /**
         * Skip the integrity pass. Diagnostics only — a normal restore must
         * verify, or a truncated package is applied half-way before anything
         * notices.
         */
        val skipIntegrityCheck: Boolean = false,
        /** Required when the package declares `encryption`; ignored otherwise. */
        val passphrase: String? = null,
    )

    data class CategoryReport(
        val category: String,
        var imported: Int = 0,
        var updated: Int = 0,
        var skipped: Int = 0,
        var unreadable: Int = 0,
        var filesWritten: Int = 0,
        var bytesWritten: Long = 0,
        var sizeSkippedInPackage: Int = 0,
        var notDownloadedInPackage: Int = 0,
        var missingBlobs: Int = 0,
        var rejectedPaths: Int = 0,
        var failed: String? = null,
    )

    data class Report(
        val backupId: String,
        val createdAt: String?,
        val sourcePlatform: String?,
        val categories: MutableList<CategoryReport> = mutableListOf(),
        var integrityChecked: Int = 0,
        var integrityFailed: List<String> = emptyList(),
        var wasEncrypted: Boolean = false,
        val warnings: MutableList<String> = mutableListOf(),
        var durationMillis: Long = 0,
    ) {
        val totalImported: Int get() = categories.sumOf { it.imported }
        val totalUpdated: Int get() = categories.sumOf { it.updated }
        val totalSkipped: Int get() = categories.sumOf { it.skipped }
        val totalMissingBlobs: Int get() = categories.sumOf { it.missingBlobs }
    }

    /**
     * Restore from an already-extracted package directory.
     *
     * Serialised process-wide with export: two concurrent restores share
     * mutable destinations (the same session directories, the same provider
     * config), so overlapping them corrupts state no rollback can describe
     * (iOS review I3).
     */
    suspend fun import(
        packageRoot: File,
        options: Options = Options(),
        onProgress: ((String) -> Unit)? = null,
    ): Report = activityLock.withLock { importBody(packageRoot, options, onProgress) }

    private suspend fun importBody(
        extractedRoot: File,
        options: Options,
        onProgress: ((String) -> Unit)?,
    ): Report {
        val started = System.currentTimeMillis()
        // iOS zips through NSFileCoordinator, which wraps the tree in an outer
        // folder, so the real root may be one level down.
        val root = BackupZip.packageRoot(extractedRoot)
        val reader = BackupPackageReader(root)
        val manifest = reader.readManifest()

        val report = Report(
            backupId = manifest.backupId,
            createdAt = manifest.createdAt.takeIf { it.isNotEmpty() },
            sourcePlatform = manifest.app.platform,
        )

        // Downgrade guard before anything else: a manifest with its
        // `encryption` block stripped would otherwise make every category read
        // zero records and report success on an empty restore.
        reader.assertNoUndeclaredEncryption(manifest)

        var keys: BackupCrypto.Keys? = null
        if (manifest.encryption != null) {
            val passphrase = options.passphrase
            if (passphrase.isNullOrEmpty()) {
                throw BackupException("This backup is encrypted. Enter its passphrase to restore.")
            }
            onProgress?.invoke("Checking passphrase…")
            // unlock() verifies the verifier AND the manifest MAC before any
            // payload is touched.
            keys = reader.unlock(passphrase, manifest)
            report.wasEncrypted = true
        }

        try {
            if (!options.skipIntegrityCheck) {
                onProgress?.invoke("Verifying integrity…")
                val failures = reader.verifyIntegrity(manifest)
                report.integrityChecked = manifest.integrity.size
                report.integrityFailed = failures
                if (failures.isNotEmpty()) {
                    throw BackupException(
                        "Integrity check failed for ${failures.size} file(s): " +
                            failures.take(3).joinToString(", ")
                    )
                }
            }

            // Decrypt every member up front. Done as one pass rather than
            // lazily per category so a wrong-key failure surfaces before any
            // data has been written to the device.
            val work = if (keys != null) {
                onProgress?.invoke("Decrypting…")
                decryptMembers(root, keys)
            } else {
                root
            }

            val fileIndex = readFileIndex(work)
            val wanted = options.categories
                ?: manifest.categories.keys.mapNotNull(BackupCategory::fromKey).toSet()

            // Order matters: chats writes sessions before the messages that
            // reference them.
            for (category in ORDER.filter { it in wanted }) {
                onProgress?.invoke("Restoring ${category.key}…")
                val categoryReport = try {
                    when (category) {
                        BackupCategory.CHATS -> importChats(work, fileIndex)
                        BackupCategory.SHARED_FILES -> importSharedFiles(work, fileIndex)
                        BackupCategory.SKILLS -> importSkills(work, fileIndex)
                        BackupCategory.MEMORY -> importMemory(work)
                        BackupCategory.MCP_SERVERS -> importMcpServers(work)
                        else -> null
                    }
                } catch (e: Exception) {
                    AppLogger.error(TAG, "[Restore] category ${category.key} failed: ${e.message}")
                    CategoryReport(category.key, failed = e.message ?: e.toString())
                }
                categoryReport?.let { report.categories.add(it) }
            }

            if (report.totalMissingBlobs > 0) {
                // Surfaced rather than buried: the user must be told their
                // package was incomplete while they still have the source
                // device to re-export from.
                report.warnings.add(
                    "${report.totalMissingBlobs} file(s) were listed in the backup but their " +
                        "content was missing from the package."
                )
            }
            report.durationMillis = System.currentTimeMillis() - started
            AppLogger.info(
                TAG,
                "[Restore] done id=${manifest.backupId} imported=${report.totalImported} " +
                    "updated=${report.totalUpdated} skipped=${report.totalSkipped} " +
                    "in ${report.durationMillis}ms"
            )
            return report
        } finally {
            keys?.destroy()
        }
    }

    // MARK: - Chats

    private suspend fun importChats(
        root: File,
        fileIndex: List<BackupFileIndexEntry>,
    ): CategoryReport {
        val report = CategoryReport(BackupCategory.CHATS.key)
        val dao = db.chatDao()
        val dataDir = File(root, "data")

        // Folders first: sessions carry a folderId, so applying folders
        // beforehand means the reference resolves immediately.
        for (rec in readJsonl(dataDir, "folders")) {
            val f = rec.obj ?: continue
            val id = f.str("id") ?: continue
            val incomingUpdated = f.millis("updatedAt") ?: 0
            // Merge by the same rule as sessions: an older backup must not undo
            // a rename the user made after taking it.
            val existing = dao.getFolder(id)
            if (existing != null && existing.updatedAt >= incomingUpdated) {
                report.skipped += 1
                continue
            }
            dao.insertFolder(
                FolderEntity(
                    id = id,
                    name = f.str("name") ?: "",
                    icon = f.str("icon"),
                    color = f.str("color"),
                    origin = f.str("origin") ?: FolderEntity.ORIGIN_MANUAL,
                    sortIndex = f.int("sortIndex") ?: 0,
                    pinnedAt = f.millis("pinnedAt"),
                    description = f.str("description"),
                    createdAt = f.millis("createdAt") ?: incomingUpdated,
                    updatedAt = incomingUpdated,
                )
            )
            if (existing == null) report.imported += 1 else report.updated += 1
        }

        // Sessions before messages — a message row needs its parent to exist,
        // and the schema enforces it with a foreign key.
        val restoredSessionIds = mutableSetOf<String>()
        for (rec in readJsonl(dataDir, "sessions")) {
            val s = rec.obj ?: continue
            val id = s.str("id")
            if (id == null) {
                report.unreadable += 1
                continue
            }
            val incomingUpdated = s.millis("updatedAt") ?: 0
            val existing = dao.getSession(id)
            // Merge (§8.2): newer updatedAt wins. Without this comparison an
            // older backup would silently overwrite work the user did after it
            // was taken.
            if (existing != null && existing.updatedAt >= incomingUpdated) {
                report.skipped += 1
                restoredSessionIds.add(id)
                continue
            }
            dao.insertSession(
                ChatSessionEntity(
                    id = id,
                    title = s.str("title"),
                    modelId = s.str("modelId") ?: existing?.modelId ?: "",
                    createdAt = s.millis("createdAt") ?: incomingUpdated,
                    updatedAt = incomingUpdated,
                    category = s.str("category"),
                    lastMessage = s.str("lastMessage"),
                    modelBinding = s.str("modelBinding"),
                    source = s.str("source"),
                    memoryEnabled = if (s.bool("memoryEnabled") != false) 1 else 0,
                    pinnedAt = s.millis("pinnedAt"),
                    editCount = s.int("editCount") ?: 0,
                    thinkingOverride = s.str("thinkingOverride"),
                    folderId = s.str("folderId"),
                )
            )
            if (existing == null) report.imported += 1 else report.updated += 1
            restoredSessionIds.add(id)
        }

        for (rec in readJsonl(dataDir, "messages")) {
            val m = rec.obj ?: continue
            val id = m.str("id")
            val sessionId = m.str("sessionId")
            if (id == null || sessionId == null) {
                report.unreadable += 1
                continue
            }
            // A message whose session was skipped as locally-newer still
            // belongs to a session that exists; one whose session is absent
            // entirely would violate the foreign key.
            if (dao.getSession(sessionId) == null) {
                report.skipped += 1
                continue
            }
            val createdAt = m.millis("createdAt") ?: 0
            dao.insertMessage(
                MessageEntity(
                    id = id,
                    sessionId = sessionId,
                    role = m.str("role") ?: "user",
                    // Re-serialised from the parsed element, so any part type
                    // this build doesn't model is preserved verbatim.
                    partsJson = (m["parts"]?.toString()) ?: "[]",
                    createdAt = createdAt,
                    tokenUsage = m["tokenUsage"]?.takeIf { it.toString() != "null" }?.toString(),
                    sortOrder = m.int("sortOrder") ?: 0,
                    reasoningContent = m.str("reasoningContent"),
                    streamInterruptCount = m.int("streamInterruptCount") ?: 0,
                    updatedAt = createdAt,
                    // errorInfo is device-local (§0.2) and is never restored.
                    errorInfo = null,
                )
            )
            report.imported += 1
        }

        for (rec in readJsonl(dataDir, "compact_markers")) {
            val c = rec.obj ?: continue
            val id = c.str("id") ?: continue
            val sessionId = c.str("sessionId") ?: continue
            if (dao.getSession(sessionId) == null) {
                report.skipped += 1
                continue
            }
            // insertCompactMarker is ABORT-on-conflict, so a re-run would throw
            // on rows that already exist. Merge must be idempotent.
            runCatching {
                dao.insertCompactMarker(
                    CompactMarkerEntity(
                        id = id,
                        sessionId = sessionId,
                        summary = c.str("summary") ?: "",
                        firstKeptSortOrder = c.int("firstKeptSortOrder") ?: 0,
                        compactedCount = c.int("compactedCount") ?: 0,
                        createdAt = c.millis("createdAt") ?: 0,
                        uiBoundarySortOrder = c.int("uiBoundarySortOrder"),
                        boundaryMessageId = c.str("boundaryMessageId"),
                        firstKeptMessageId = c.str("firstKeptMessageId"),
                        lastCompactedMessageId = c.str("lastCompactedMessageId"),
                    )
                )
                report.imported += 1
            }.onFailure { report.skipped += 1 }
        }

        // The session file trees. Containment root is the sessions directory:
        // a path in the index that escapes it is refused outright.
        val sessionsRoot = File(context.filesDir, "minis-sessions")
        val files = BackupRestoreFiles.restore(
            packageRoot = root,
            fileIndex = fileIndex,
            category = BackupCategory.CHATS,
            containmentRoot = sessionsRoot,
        ) { path ->
            // "chats/<sid>/<rest…>"
            val parts = path.split('/')
            if (parts.size < 3 || parts[0] != "chats") null
            else File(sessionsRoot, parts.drop(1).joinToString("/"))
        }
        applyFileResult(report, files)
        return report
    }

    // MARK: - Shared files / Skills / Memory / MCP

    private fun importSharedFiles(
        root: File,
        fileIndex: List<BackupFileIndexEntry>,
    ): CategoryReport {
        val report = CategoryReport(BackupCategory.SHARED_FILES.key)
        val dest = File(context.filesDir, "minis-global/shared")
        val files = BackupRestoreFiles.restore(
            root, fileIndex, BackupCategory.SHARED_FILES, dest
        ) { path ->
            if (!path.startsWith("shared/")) null
            else File(dest, path.removePrefix("shared/"))
        }
        applyFileResult(report, files)
        // Per §3.2 no meta.db equivalent is needed here: PRoot bind-mounts this
        // directory, so the guest sees the files on the next boot.
        return report
    }

    private fun importSkills(root: File, fileIndex: List<BackupFileIndexEntry>): CategoryReport {
        val report = CategoryReport(BackupCategory.SKILLS.key)
        val dest = File(context.filesDir, "minis-global/skills")
        val files = BackupRestoreFiles.restore(root, fileIndex, BackupCategory.SKILLS, dest) { path ->
            if (!path.startsWith("skills/")) null
            else File(dest, path.removePrefix("skills/"))
        }
        applyFileResult(report, files)
        return report
    }

    private fun importMemory(root: File): CategoryReport {
        val report = CategoryReport(BackupCategory.MEMORY.key)
        val src = File(root, "data/memory")
        if (!src.isDirectory) return report
        val dest = File(context.filesDir, "minis-global/memory").apply { mkdirs() }
        val destRoot = dest.canonicalFile
        for (file in src.walkTopDown().filter { it.isFile }) {
            val rel = file.relativeTo(src).path.replace(File.separatorChar, '/')
            val out = File(dest, rel)
            // Same containment rule as the blob path: `data/memory` names come
            // from inside the package too.
            val parent = out.parentFile?.let { it.mkdirs(); it.canonicalFile }
            if (parent == null || !(parent.path == destRoot.path ||
                    parent.path.startsWith(destRoot.path + File.separator))
            ) {
                report.rejectedPaths += 1
                continue
            }
            file.copyTo(out, overwrite = true)
            report.filesWritten += 1
            report.bytesWritten += file.length()
        }
        return report
    }

    private fun importMcpServers(root: File): CategoryReport {
        val report = CategoryReport(BackupCategory.MCP_SERVERS.key)
        val src = File(root, "data/mcp_servers.json")
        if (!src.isFile) return report
        val dest = File(context.filesDir, "minis-global/mcp-servers/servers.json")
        dest.parentFile?.mkdirs()
        src.copyTo(dest, overwrite = true)
        report.filesWritten = 1
        report.bytesWritten = src.length()
        report.imported = 1
        return report
    }

    private fun applyFileResult(report: CategoryReport, files: BackupRestoreFiles.Result) {
        report.filesWritten += files.written
        report.bytesWritten += files.bytes
        report.missingBlobs += files.missingBlobs
        report.sizeSkippedInPackage += files.sizeSkippedInPackage
        report.notDownloadedInPackage += files.notDownloadedInPackage
        report.rejectedPaths += files.rejectedPaths
    }

    // MARK: - Package plumbing

    /**
     * Decrypt every `.enc` member into a scratch tree, leaving the package
     * untouched.
     *
     * Decrypting in place would destroy the original on a failed run, and the
     * package may be a file the user still wants after a restore goes wrong.
     */
    private fun decryptMembers(root: File, keys: BackupCrypto.Keys): File {
        val work = File(context.cacheDir, "restore-work").apply {
            deleteRecursively(); mkdirs()
        }
        val base = root.canonicalFile
        for (file in base.walkTopDown().filter { it.isFile }) {
            val rel = file.relativeTo(base).path.replace(File.separatorChar, '/')
            val out = File(work, rel.removeSuffix(".enc")).apply { parentFile?.mkdirs() }
            if (rel.endsWith(".enc")) {
                val logical = rel.removeSuffix(".enc")
                val key = if (logical == "secrets.json") keys.secretsKey else keys.dataKey
                // AAD binds to the name the member ships under, `.enc` included.
                BackupCrypto.decryptFile(file, out, key, rel)
            } else {
                file.copyTo(out, overwrite = true)
            }
        }
        return work
    }

    private fun readFileIndex(root: File): List<BackupFileIndexEntry> {
        val file = File(root, "files.index.jsonl")
        if (!file.isFile) return emptyList()
        return file.readLines().mapNotNull { line ->
            if (line.isBlank()) null
            else runCatching {
                BackupFormat.json.decodeFromString(BackupFileIndexEntry.serializer(), line)
            }.getOrNull()
        }
    }

    /**
     * Read one JSONL family, including its rollover shards.
     *
     * §2.2 rule 3: a line that fails to parse is skipped, never fatal — it may
     * come from a newer writer. Shards are read in name order, which is why the
     * writer zero-pads them.
     */
    private fun readJsonl(dataDir: File, baseName: String): List<Envelope> {
        val shards = (dataDir.listFiles() ?: emptyArray())
            .filter { it.isFile && (it.name == "$baseName.jsonl" ||
                (it.name.startsWith("$baseName-") && it.name.endsWith(".jsonl"))) }
            .sortedBy { it.name }
        val out = mutableListOf<Envelope>()
        for (shard in shards) {
            shard.forEachLine { line ->
                if (line.isNotBlank()) {
                    runCatching {
                        val o = BackupFormat.json.parseToJsonElement(line).jsonObject
                        out.add(Envelope(o["d"]?.jsonObject))
                    }
                }
            }
        }
        return out
    }

    private class Envelope(val obj: JsonObject?)

    companion object {
        private const val TAG = "Restore"

        /** Shared with the exporter: the two must never run at once. */
        private val activityLock = Mutex()

        /** Sessions must land before the messages that reference them. */
        private val ORDER = listOf(
            BackupCategory.CHATS,
            BackupCategory.SHARED_FILES,
            BackupCategory.SKILLS,
            BackupCategory.MEMORY,
            BackupCategory.MCP_SERVERS,
        )

        private fun JsonObject.str(key: String): String? =
            this[key]?.takeIf { it.toString() != "null" }?.runCatching { jsonPrimitive.content }
                ?.getOrNull()

        private fun JsonObject.int(key: String): Int? =
            this[key]?.runCatching { jsonPrimitive.content.toInt() }?.getOrNull()

        private fun JsonObject.bool(key: String): Boolean? =
            this[key]?.runCatching { jsonPrimitive.content.toBooleanStrict() }?.getOrNull()

        /**
         * Parse an ISO-8601 instant into epoch millis.
         *
         * iOS writes dates as ISO-8601 strings, but a package written by a
         * future build (or by a tool) could carry a numeric epoch, so both are
         * accepted — §2.2's tolerance rule applied to a value, not just a key.
         */
        fun JsonObject.millis(key: String): Long? {
            val raw = str(key) ?: return null
            raw.toLongOrNull()?.let { return it }
            for (pattern in ISO_PATTERNS) {
                runCatching {
                    val f = SimpleDateFormat(pattern, Locale.US)
                        .apply { timeZone = TimeZone.getTimeZone("UTC") }
                    return f.parse(raw)?.time
                }
            }
            return null
        }

        private val ISO_PATTERNS = listOf(
            "yyyy-MM-dd'T'HH:mm:ss'Z'",
            "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",
            "yyyy-MM-dd'T'HH:mm:ssXXX",
            "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
        )
    }
}
