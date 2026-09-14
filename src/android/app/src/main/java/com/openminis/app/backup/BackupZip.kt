package com.openminis.app.backup

import com.openminis.app.logging.AppLogger
import java.io.File
import java.io.InputStream
import java.io.OutputStream
import java.util.zip.CRC32
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream

/**
 * ZIP packaging for `.minisbak`, on both sides of the wire.
 *
 * ## Why STORED and not DEFLATE
 *
 * iOS reads packages with a hand-rolled parser
 * (`BackupZipExtractor.swift` / `BackupPackageReader.swift`) that streams
 * STORED entries in 4MB chunks but must inflate a DEFLATE entry **as a unit**,
 * into memory. A backup's largest members are already-compressed blobs
 * (media, zips) that deflate would barely shrink, so compressing them buys
 * almost nothing and hands the iOS importer a multi-hundred-MB allocation on a
 * device with a documented jetsam history. Everything is therefore written
 * STORED, which is also what `NSFileCoordinator(.forUploading)` produces on
 * the iOS side — one archive shape for both writers.
 *
 * STORED via [ZipOutputStream] requires size and CRC up front, which means one
 * hashing pass over each member before it is written. That pass is streaming,
 * so peak memory stays at the copy buffer regardless of member size.
 *
 * ZIP64 must NEVER be emitted, and that constraint is sharper than it looks.
 * iOS's reader takes the entry count from the classic EOCD's 16-bit field and
 * loops exactly that many times. In a ZIP64 archive that field is saturated to
 * 0xFFFF, so iOS does not fail — it extracts 65 535 members, skips the rest,
 * and reports success. Silent data loss on restore, which is the one outcome a
 * backup must never produce. `ZipOutputStream` switches to ZIP64 on its own
 * once any of three limits is crossed, so all three are checked up front:
 * per-member size, total archive size, and entry count.
 */
object BackupZip {

    private const val TAG = "Backup"

    /** Classic-ZIP ceiling for a member's size and for the archive's total. */
    private const val MAX_MEMBER_BYTES = 0xFFFFFFFFL - 1

    /**
     * Classic EOCD stores the entry count in 16 bits. One more than this and
     * ZipOutputStream emits a ZIP64 record that iOS silently under-reads.
     */
    private const val MAX_ENTRIES = 65_535

    class ZipException(message: String) : Exception(message)

    // MARK: - Writing

    /**
     * Archive every file under [staging] into [destination], STORED, with
     * package-relative entry names.
     *
     * Entry order follows a directory walk; the manifest is written last by
     * the exporter, so it lands near the end of the archive exactly as it does
     * on iOS (which is why a duplicate copy exists for rescue).
     */
    fun archive(staging: File, destination: File) {
        val base = staging.canonicalFile
        val members = base.walkTopDown()
            .filter { it.isFile }
            .sortedBy { it.relativeTo(base).invariantPath() }
            .toList()

        // Refuse before writing anything, rather than discovering it at the
        // end: ZipOutputStream would quietly promote the archive to ZIP64, and
        // the resulting package looks perfectly valid right up until iOS reads
        // 65 535 of its members and calls the restore a success.
        if (members.size > MAX_ENTRIES) {
            throw ZipException(
                "Package would hold ${members.size} files, beyond the ${MAX_ENTRIES}-entry " +
                    "limit of the cross-platform ZIP format."
            )
        }
        val totalBytes = members.sumOf { it.length() }
        if (totalBytes > MAX_MEMBER_BYTES) {
            throw ZipException(
                "Package would be $totalBytes bytes, beyond the 4GB limit of the " +
                    "cross-platform ZIP format."
            )
        }

        ZipOutputStream(destination.outputStream().buffered()).use { zos ->
            zos.setMethod(ZipOutputStream.STORED)
            members.forEach { file ->
                writeStoredEntry(zos, file.relativeTo(base).invariantPath(), file)
            }
        }
    }

    private fun writeStoredEntry(zos: ZipOutputStream, name: String, file: File) {
        val size = file.length()
        if (size > MAX_MEMBER_BYTES) {
            throw ZipException(
                "Package member '$name' is ${size} bytes, beyond the 4GB classic-ZIP limit."
            )
        }
        val crc = CRC32()
        file.inputStream().buffered().use { input ->
            val buf = ByteArray(4 * 1024 * 1024)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                crc.update(buf, 0, n)
            }
        }
        val entry = ZipEntry(name).apply {
            method = ZipEntry.STORED
            this.size = size
            compressedSize = size
            this.crc = crc.value
            time = file.lastModified()
        }
        zos.putNextEntry(entry)
        file.inputStream().buffered().use { it.copyTo(zos, 4 * 1024 * 1024) }
        zos.closeEntry()
    }

    // MARK: - Reading

    /**
     * Extract every entry of [zipFile] under [destination].
     *
     * Uses a forward [ZipInputStream] scan rather than random access, so a
     * package whose central directory is damaged still yields whatever
     * precedes the damage — the same tolerance iOS's forward-scan rescue path
     * provides.
     */
    fun extract(zipFile: File, destination: File, onProgress: ((String) -> Unit)? = null) {
        destination.mkdirs()
        val root = destination.canonicalFile
        ZipInputStream(zipFile.inputStream().buffered()).use { zis ->
            while (true) {
                val entry = zis.nextEntry ?: break
                val out = safeResolve(root, entry.name)
                if (entry.isDirectory) {
                    out.mkdirs()
                } else {
                    out.parentFile?.mkdirs()
                    out.outputStream().buffered().use { sink ->
                        zis.copyTo(sink, 4 * 1024 * 1024)
                    }
                    onProgress?.invoke(entry.name)
                }
                zis.closeEntry()
            }
        }
    }

    /**
     * Read one small entry by name, without extracting the archive.
     *
     * Names are matched on suffix as well as equality: iOS packages the
     * staging tree through `NSFileCoordinator(.forUploading)`, which wraps
     * everything in an outer folder, so entries arrive as
     * `minisbak-<uuid>/manifest.json` rather than bare `manifest.json`.
     */
    fun readEntry(zipFile: File, name: String, maxBytes: Int = 32 * 1024 * 1024): ByteArray? {
        ZipInputStream(zipFile.inputStream().buffered()).use { zis ->
            while (true) {
                val entry = zis.nextEntry ?: break
                if (entry.name == name || entry.name.endsWith("/$name")) {
                    return zis.readAtMost(maxBytes)
                }
                zis.closeEntry()
            }
        }
        return null
    }

    /** Entry names in the archive, in stream order. */
    fun listEntries(zipFile: File): List<String> {
        val out = mutableListOf<String>()
        ZipInputStream(zipFile.inputStream().buffered()).use { zis ->
            while (true) {
                val entry = zis.nextEntry ?: break
                out.add(entry.name)
                zis.closeEntry()
            }
        }
        return out
    }

    /**
     * Strip the outer wrapper directory iOS's zipper adds, if there is one.
     *
     * After extraction the real package root may be `<dest>/minisbak-<uuid>/`
     * rather than `<dest>/`. Detected by looking for `manifest.json`, which
     * every package has at its root by definition.
     */
    fun packageRoot(extracted: File): File {
        if (File(extracted, "manifest.json").exists()) return extracted
        val dirs = extracted.listFiles()?.filter { it.isDirectory } ?: emptyList()
        val wrapped = dirs.firstOrNull { File(it, "manifest.json").exists() }
        if (wrapped != null) {
            AppLogger.info(TAG, "[Backup] package root is wrapped in '${wrapped.name}'")
            return wrapped
        }
        return extracted
    }

    /**
     * §5.5's path-traversal rule: a malicious package must not write outside
     * the destination. Absolute paths and any `..` component are refused
     * rather than normalised away.
     */
    private fun safeResolve(root: File, entryName: String): File {
        if (entryName.startsWith("/") || entryName.startsWith("\\")) {
            throw ZipException("Refusing unsafe entry path: $entryName")
        }
        val parts = entryName.split('/', '\\').filter { it.isNotEmpty() }
        if (parts.any { it == ".." }) {
            throw ZipException("Refusing unsafe entry path: $entryName")
        }
        val resolved = parts.fold(root) { acc, part -> File(acc, part) }
        // Belt and braces: a symlink or exotic name must not escape either.
        if (!resolved.canonicalPath.startsWith(root.canonicalPath + File.separator) &&
            resolved.canonicalPath != root.canonicalPath
        ) {
            throw ZipException("Refusing unsafe entry path: $entryName")
        }
        return resolved
    }

    private fun File.invariantPath(): String = path.replace(File.separatorChar, '/')

    private fun InputStream.readAtMost(max: Int): ByteArray {
        val buf = ByteArray(minOf(max, 64 * 1024))
        val out = java.io.ByteArrayOutputStream()
        var total = 0
        while (total < max) {
            val n = read(buf, 0, minOf(buf.size, max - total))
            if (n < 0) break
            out.write(buf, 0, n)
            total += n
        }
        return out.toByteArray()
    }
}

/** Copy helper with an explicit buffer size, so large members never chunk at 8KB. */
private fun InputStream.copyTo(out: OutputStream, bufferSize: Int): Long {
    val buffer = ByteArray(bufferSize)
    var bytes = 0L
    while (true) {
        val n = read(buffer)
        if (n < 0) break
        out.write(buffer, 0, n)
        bytes += n
    }
    return bytes
}
