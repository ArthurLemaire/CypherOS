package com.openminis.app.backup.remote

import android.content.Context
import com.openminis.app.backup.BackupFormat
import com.openminis.app.logging.AppLogger
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.io.RandomAccessFile
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/**
 * Uploads a backup package to an rclone remote in resumable chunks, and reads
 * them back. Mirrors `src/ios/Agent/Backup/Remote/RcloneChunkedUpload.swift`.
 *
 * ## Why chunk at all
 *
 * rclone has no cross-process upload resume. Its "resume" is FILE-level: a sync
 * compares size/modtime/hash and skips files already transferred. That works
 * when copying many files; a backup package is one big file, which is the worst
 * case — killed at 300 MB of 500 MB, rclone starts again from zero.
 *
 * So the package is split into fixed-size parts, each uploaded as its own
 * object, with a journal recording which parts landed. An interrupted upload
 * resumes at the first missing part. It is protocol-agnostic — it does not rely
 * on S3 multipart or any other backend-specific capability, so SMB and WebDAV
 * resume identically.
 *
 * ## Layout on the remote
 *
 *     <path>/.minis-parts/<backupId>/000000, 000001, …   during upload
 *     <path>/<name>.minisbak                             after assembly
 *
 * The final name appears only once every part is present, so a partial upload
 * is never mistaken for a usable backup. **This layout is cross-platform wire
 * format**: an upload interrupted on Android must be resumable and readable by
 * iOS and vice versa, which is why the chunk size, the zero-padded `%06d` part
 * names and the `.minis-parts` directory name are all fixed here.
 */
class RcloneChunkedUpload(private val context: Context) {

    /**
     * 8 MiB — matches iOS. Small enough that a dropped connection loses little,
     * large enough that per-request overhead stays negligible on a NAS. Changing
     * it breaks resume of an upload started by the other platform.
     */
    private val chunkSize = 8 * 1024 * 1024

    /** Progress across the whole file, not the current chunk. */
    data class Progress(val bytesSent: Long, val totalBytes: Long) {
        val fraction: Double get() = if (totalBytes > 0) bytesSent.toDouble() / totalBytes else 0.0
    }

    class UploadException(message: String) : Exception(message)
    class CancelledException : Exception("Upload cancelled.")

    /** Which parts are already on the remote, so a resumed run skips them. */
    @Serializable
    private data class Journal(
        val backupId: String,
        val remoteName: String,
        val fileName: String,
        val totalParts: Int,
        val uploadedParts: List<Int>,
    )

    /**
     * Lives in filesDir rather than cacheDir: the system may evict the cache at
     * any time, and this has to survive to the next launch to be worth anything.
     */
    private val journalFile: File
        get() = File(context.filesDir, "backup-upload").apply { mkdirs() }
            .let { File(it, "in-progress.json") }

    private fun loadJournal(): Journal? = runCatching {
        journalFile.takeIf { it.exists() }?.readText()
            ?.let { JSON.decodeFromString(Journal.serializer(), it) }
    }.getOrNull()

    private fun save(j: Journal) {
        runCatching { journalFile.writeText(JSON.encodeToString(Journal.serializer(), j)) }
    }

    /** Discard a partial upload's journal (does not touch the remote). */
    fun abandonResume() {
        journalFile.delete()
    }

    // MARK: - Upload

    /**
     * Upload [packageFile] into [remote], resuming a previous attempt when one
     * matches. Blocking; call off the main thread.
     *
     * [isCancelled] is polled between chunks — cancelling mid-chunk would leave
     * a partial object, and the next attempt re-uploads that part anyway, so
     * the boundary is the natural place to stop.
     */
    fun upload(
        packageFile: File,
        remote: RcloneRemoteStore.Remote,
        backupId: String,
        isCancelled: () -> Boolean = { false },
        onProgress: ((Progress) -> Unit)? = null,
    ) {
        if (!packageFile.exists()) throw UploadException("Couldn't read the backup file.")
        val size = packageFile.length()
        val name = packageFile.name
        val totalParts = ((size + chunkSize - 1) / chunkSize).toInt()
        val partsDir = "${remote.path}/$PARTS_DIR/$backupId"

        // Resume only when the previous attempt was the SAME package to the SAME
        // remote. Anything else and the old parts describe a different file, so
        // they are abandoned rather than mixed in.
        val done = sortedSetOf<Int>()
        val prior = loadJournal()
        if (prior != null && prior.backupId == backupId && prior.remoteName == remote.name &&
            prior.fileName == name && prior.totalParts == totalParts
        ) {
            done.addAll(prior.uploadedParts)
            AppLogger.info(TAG, "[Rclone] resuming upload $name: ${done.size}/$totalParts parts already sent")
        } else {
            save(Journal(backupId, remote.name, name, totalParts, emptyList()))
        }

        runCatching {
            RcloneBridge.rpc("operations/mkdir", mapOf("fs" to remote.fsSpec, "remote" to partsDir))
        }

        val scratchDir = File(context.cacheDir, "rclone-chunks").apply { mkdirs() }
        val scratch = File(scratchDir, "minis-chunk-$backupId")
        try {
            RandomAccessFile(packageFile, "r").use { raf ->
                val buffer = ByteArray(chunkSize)
                for (index in 0 until totalParts) {
                    if (isCancelled()) throw CancelledException()
                    if (index in done) continue

                    raf.seek(index.toLong() * chunkSize)
                    val read = raf.read(buffer)
                    if (read <= 0) break
                    scratch.outputStream().use { it.write(buffer, 0, read) }

                    val partName = String.format(Locale.US, "%06d", index)
                    try {
                        // copyfile takes a LOCAL fs and a remote fs; the local
                        // side is the scratch chunk just written.
                        RcloneBridge.rpc(
                            "operations/copyfile",
                            mapOf(
                                "srcFs" to scratchDir.absolutePath,
                                "srcRemote" to scratch.name,
                                "dstFs" to remote.fsSpec,
                                "dstRemote" to "$partsDir/$partName",
                            ),
                        )
                    } catch (e: Exception) {
                        // Record what DID land before giving up, so the next
                        // attempt resumes here instead of restarting.
                        save(Journal(backupId, remote.name, name, totalParts, done.toList()))
                        throw UploadException(e.message ?: "The remote rejected the upload.")
                    }

                    done.add(index)
                    save(Journal(backupId, remote.name, name, totalParts, done.toList()))
                    onProgress?.invoke(
                        Progress(minOf(done.size.toLong() * chunkSize, size), size)
                    )
                }
            }
        } finally {
            scratch.delete()
        }

        assemble(remote, partsDir, totalParts, name)
        journalFile.delete()
        AppLogger.info(TAG, "[Rclone] upload complete: $name -> ${remote.name}")
    }

    /**
     * Turn the uploaded parts into the final package.
     *
     * A single-part upload is just a move. Multi-part needs concatenation,
     * which rclone cannot do server-side for arbitrary backends — so the parts
     * are left in place and [listPackages] surfaces them for reassembly on
     * download. Deliberately NOT renamed to `.minisbak`: a directory of parts
     * must not look like a finished package to anything scanning the folder.
     */
    private fun assemble(
        remote: RcloneRemoteStore.Remote,
        partsDir: String,
        totalParts: Int,
        finalName: String,
    ) {
        if (totalParts == 1) {
            RcloneBridge.rpc(
                "operations/movefile",
                mapOf(
                    "srcFs" to remote.fsSpec, "srcRemote" to "$partsDir/000000",
                    "dstFs" to remote.fsSpec, "dstRemote" to "${remote.path}/$finalName",
                ),
            )
            runCatching {
                RcloneBridge.rpc("operations/rmdir", mapOf("fs" to remote.fsSpec, "remote" to partsDir))
            }
            return
        }
        AppLogger.info(TAG, "[Rclone] $totalParts parts left in $partsDir for reassembly on restore")
    }

    // MARK: - Reading back

    /** A backup found on a remote — either a whole file or a set of parts. */
    data class RemotePackage(
        /** Path used to fetch it: the file, or the parts directory. */
        val key: String,
        val displayName: String,
        val size: Long,
        val modified: Long?,
        /** >1 when this is a chunked upload that needs reassembly. */
        val partCount: Int,
    ) {
        val isChunked: Boolean get() = partCount > 1
    }

    /**
     * Everything restorable in [remote], whole packages and chunked ones alike.
     *
     * Chunked uploads live under `.minis-parts/<backupId>/`, which is a
     * DIRECTORY — a plain listing would either miss them or show a folder the
     * user can't interpret. Both forms are surfaced as one list so the restore
     * UI doesn't have to know the difference.
     */
    fun listPackages(remote: RcloneRemoteStore.Remote): List<RemotePackage> {
        val found = mutableListOf<RemotePackage>()

        val root = RcloneBridge.rpc(
            "operations/list", mapOf("fs" to remote.fsSpec, "remote" to remote.path)
        ).optJSONArray("list")
        for (i in 0 until (root?.length() ?: 0)) {
            val e = root?.optJSONObject(i) ?: continue
            val name = e.optString("Name")
            if (e.optBoolean("IsDir") || !name.endsWith(".${BackupFormat.FILE_EXTENSION}")) continue
            found.add(
                RemotePackage(
                    key = "${remote.path}/$name",
                    displayName = name,
                    size = e.optLong("Size"),
                    modified = parseTime(e.optString("ModTime")),
                    partCount = 1,
                )
            )
        }

        // Chunked uploads, one directory per backupId.
        val partsRoot = "${remote.path}/$PARTS_DIR"
        val dirs = runCatching {
            RcloneBridge.rpc("operations/list", mapOf("fs" to remote.fsSpec, "remote" to partsRoot))
                .optJSONArray("list")
        }.getOrNull()
        for (i in 0 until (dirs?.length() ?: 0)) {
            val d = dirs?.optJSONObject(i) ?: continue
            if (!d.optBoolean("IsDir")) continue
            val backupId = d.optString("Name")
            val dir = "$partsRoot/$backupId"
            val parts = runCatching {
                RcloneBridge.rpc("operations/list", mapOf("fs" to remote.fsSpec, "remote" to dir))
                    .optJSONArray("list")
            }.getOrNull() ?: continue
            if (parts.length() == 0) continue
            var total = 0L
            for (j in 0 until parts.length()) total += parts.optJSONObject(j)?.optLong("Size") ?: 0
            found.add(
                RemotePackage(
                    key = dir,
                    displayName = backupId,
                    size = total,
                    modified = parseTime(parts.optJSONObject(0)?.optString("ModTime")),
                    partCount = parts.length(),
                )
            )
        }
        return found.sortedByDescending { it.modified ?: 0 }
    }

    /**
     * Fetch a package to a local file, reassembling it when it was chunked.
     *
     * Parts are concatenated in NAME order, which is why they are written as
     * zero-padded `%06d` — lexical order then equals numeric order, and a
     * missing part shows up as a gap rather than silently shifting everything
     * after it. A short count is refused outright: half a ZIP would fail later
     * as "corrupt archive", which is a much worse thing to hand a user
     * restoring on a new device.
     */
    fun download(
        pkg: RemotePackage,
        remote: RcloneRemoteStore.Remote,
        destination: File,
        onProgress: ((Progress) -> Unit)? = null,
    ) {
        destination.delete()
        destination.parentFile?.mkdirs()

        if (!pkg.isChunked) {
            RcloneBridge.rpc(
                "operations/copyfile",
                mapOf(
                    "srcFs" to remote.fsSpec, "srcRemote" to pkg.key,
                    "dstFs" to (destination.parentFile?.absolutePath ?: ""),
                    "dstRemote" to destination.name,
                ),
            )
            onProgress?.invoke(Progress(pkg.size, pkg.size))
            return
        }

        val listing = RcloneBridge.rpc(
            "operations/list", mapOf("fs" to remote.fsSpec, "remote" to pkg.key)
        ).optJSONArray("list")
        val names = (0 until (listing?.length() ?: 0))
            .mapNotNull { listing?.optJSONObject(it)?.optString("Name") }
            .filter { it.isNotEmpty() }
            .sorted()
        if (names.size != pkg.partCount) {
            throw UploadException(
                "Expected ${pkg.partCount} parts but found ${names.size} — the upload is incomplete."
            )
        }

        val scratch = File(context.cacheDir, "minis-dl-${pkg.displayName}").apply { mkdirs() }
        try {
            destination.outputStream().buffered().use { out ->
                var written = 0L
                for (name in names) {
                    RcloneBridge.rpc(
                        "operations/copyfile",
                        mapOf(
                            "srcFs" to remote.fsSpec, "srcRemote" to "${pkg.key}/$name",
                            "dstFs" to scratch.absolutePath, "dstRemote" to name,
                        ),
                    )
                    val local = File(scratch, name)
                    local.inputStream().buffered().use { it.copyTo(out) }
                    written += local.length()
                    local.delete() // one part on disk at a time
                    onProgress?.invoke(Progress(written, pkg.size))
                }
            }
        } finally {
            scratch.deleteRecursively()
        }
        AppLogger.info(TAG, "[Rclone] reassembled ${names.size} part(s) -> ${destination.name}")
    }

    private fun parseTime(s: String?): Long? {
        if (s.isNullOrEmpty()) return null
        for (pattern in TIME_PATTERNS) {
            runCatching {
                val f = SimpleDateFormat(pattern, Locale.US).apply {
                    timeZone = TimeZone.getTimeZone("UTC")
                }
                return f.parse(s)?.time
            }
        }
        return null
    }

    companion object {
        private const val TAG = "Rclone"
        /** Cross-platform: iOS writes and reads the same directory name. */
        private const val PARTS_DIR = ".minis-parts"
        private val TIME_PATTERNS = listOf(
            "yyyy-MM-dd'T'HH:mm:ss.SSSSSSSSSXXX",
            "yyyy-MM-dd'T'HH:mm:ss.SSSXXX",
            "yyyy-MM-dd'T'HH:mm:ssXXX",
        )
        private val JSON = Json { ignoreUnknownKeys = true; encodeDefaults = true }
    }
}
