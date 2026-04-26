package io.github.nanomuse.app.runtime

import java.io.File
import java.io.IOException
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermission
import java.nio.file.attribute.PosixFilePermission.GROUP_EXECUTE
import java.nio.file.attribute.PosixFilePermission.GROUP_READ
import java.nio.file.attribute.PosixFilePermission.GROUP_WRITE
import java.nio.file.attribute.PosixFilePermission.OTHERS_EXECUTE
import java.nio.file.attribute.PosixFilePermission.OTHERS_READ
import java.nio.file.attribute.PosixFilePermission.OTHERS_WRITE
import java.nio.file.attribute.PosixFilePermission.OWNER_EXECUTE
import java.nio.file.attribute.PosixFilePermission.OWNER_READ
import java.nio.file.attribute.PosixFilePermission.OWNER_WRITE

/**
 * Unpacks a tar stream (already decompressed) into a directory: regular files, directories,
 * symbolic links, hard links and the file modes; long names through PAX and GNU headers.
 * Device nodes and FIFOs are skipped — PRoot binds the phone's /dev over the root file system's.
 *
 * Only what a root file system needs, in a few hundred lines, so the app does not carry a
 * compression library for it. Everything is checked to stay under [root]: an entry that
 * would escape (`../x`, an absolute link target used as a hard link) fails the unpack.
 */
class TarUnpacker(private val root: File, private val onEntry: ((String) -> Unit)? = null) {
    private val rootPath = root.canonicalFile.toPath()

    /** Unpack everything; returns the number of entries written. */
    @Throws(IOException::class)
    fun unpack(input: InputStream): Int {
        var count = 0
        var paxNext: Map<String, String> = emptyMap()
        var gnuName: String? = null
        var gnuLink: String? = null
        val header = ByteArray(512)
        while (true) {
            if (!readFully(input, header)) break
            if (header.all { it == 0.toByte() }) {
                // two zero blocks end the archive; one is enough for us
                break
            }
            val h = Header.parse(header)
            when (h.type) {
                'x' -> { paxNext = parsePax(readContent(input, h.size)); continue }
                'g' -> { skip(input, h.size); continue } // global PAX header: nothing we use
                'L' -> { gnuName = readContent(input, h.size).toString(Charsets.UTF_8).trimEnd('\u0000'); continue }
                'K' -> { gnuLink = readContent(input, h.size).toString(Charsets.UTF_8).trimEnd('\u0000'); continue }
            }
            val name = paxNext["path"] ?: gnuName ?: h.name
            val linkName = paxNext["linkpath"] ?: gnuLink ?: h.linkName
            val size = paxNext["size"]?.toLongOrNull() ?: h.size
            paxNext = emptyMap(); gnuName = null; gnuLink = null

            val rel = name.trimStart('/').removePrefix("./").trimEnd('/')
            if (rel.isEmpty() || rel == ".") { skip(input, size); continue }
            val target = resolve(rel)
            onEntry?.invoke(rel)
            when (h.type) {
                '0', '\u0000', '7' -> {
                    target.parentFile?.mkdirs()
                    writeFile(input, target, size)
                    setMode(target, h.mode)
                }
                '5' -> {
                    if (!target.isDirectory && !target.mkdirs() && !target.isDirectory) throw IOException("cannot create $rel")
                    setMode(target, h.mode or 0b111_000_000) // the owner keeps rwx on its own dirs
                    skip(input, size)
                }
                '2' -> {
                    target.parentFile?.mkdirs()
                    if (target.exists() || Files.isSymbolicLink(target.toPath())) target.delete()
                    Files.createSymbolicLink(target.toPath(), File(linkName).toPath())
                    skip(input, size)
                }
                '1' -> {
                    val source = resolve(linkName.trimStart('/').removePrefix("./"))
                    target.parentFile?.mkdirs()
                    if (target.exists()) target.delete()
                    try {
                        Files.createLink(target.toPath(), source.toPath())
                    } catch (_: Exception) {
                        // some file systems refuse hard links to an app's files: a copy is as good
                        source.copyTo(target, overwrite = true)
                        setMode(target, h.mode)
                    }
                    skip(input, size)
                }
                else -> skip(input, size) // '3','4' devices, '6' FIFO: not ours to make
            }
            count++
        }
        return count
    }

    private fun resolve(rel: String): File {
        val f = File(root, rel)
        val norm = f.toPath().normalize()
        if (!norm.startsWith(rootPath) && !norm.startsWith(root.toPath().normalize())) {
            throw IOException("entry escapes the root: $rel")
        }
        return f
    }

    private fun writeFile(input: InputStream, target: File, size: Long) {
        if (Files.isSymbolicLink(target.toPath())) target.delete()
        target.outputStream().use { out ->
            var left = size
            val buf = ByteArray(64 * 1024)
            while (left > 0) {
                val n = input.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
                if (n < 0) throw IOException("archive ended inside ${target.name}")
                out.write(buf, 0, n)
                left -= n
            }
        }
        skipPadding(input, size)
    }

    private fun readContent(input: InputStream, size: Long): ByteArray {
        if (size > 1 shl 20) throw IOException("header too large")
        val data = ByteArray(size.toInt())
        if (!readFully(input, data)) throw IOException("archive ended inside a header")
        skipPadding(input, size)
        return data
    }

    /** Skip an entry's content and the padding to the next 512-byte block. */
    private fun skip(input: InputStream, size: Long) = skipBytes(input, size + padding(size))

    private fun skipPadding(input: InputStream, size: Long) = skipBytes(input, padding(size))

    private fun skipBytes(input: InputStream, count: Long) {
        var left = count
        while (left > 0) {
            val n = input.skip(left)
            if (n <= 0) {
                if (input.read() < 0) throw IOException("archive ended early")
                left -= 1
            } else left -= n
        }
    }

    private fun padding(size: Long): Long = (512 - size % 512) % 512

    /** Fill [buf]; false at a clean end of stream, an error if it ends inside a block. */
    private fun readFully(input: InputStream, buf: ByteArray): Boolean {
        var off = 0
        while (off < buf.size) {
            val n = input.read(buf, off, buf.size - off)
            if (n < 0) {
                if (off == 0) return false
                throw IOException("archive ended inside a block")
            }
            off += n
        }
        return true
    }

    private fun setMode(file: File, mode: Int) {
        try {
            Files.setPosixFilePermissions(file.toPath(), permissions(mode))
        } catch (_: Exception) {
            // not a POSIX file system (a test on Windows): best effort
            file.setExecutable(mode and 0b001_000_000 != 0, false)
        }
    }

    private class Header(val name: String, val mode: Int, val size: Long, val type: Char, val linkName: String) {
        companion object {
            fun parse(b: ByteArray): Header {
                val magic = str(b, 257, 6)
                val name0 = str(b, 0, 100)
                val prefix = if (magic.startsWith("ustar")) str(b, 345, 155) else ""
                val name = if (prefix.isNotEmpty() && !magic.startsWith("ustar ")) "$prefix/$name0" else name0
                return Header(
                    name = name,
                    mode = octal(b, 100, 8).toInt(),
                    size = size(b),
                    type = b[156].toInt().toChar(),
                    linkName = str(b, 157, 100),
                )
            }

            private fun str(b: ByteArray, off: Int, len: Int): String {
                var end = off
                while (end < off + len && b[end] != 0.toByte()) end++
                return String(b, off, end - off, Charsets.UTF_8)
            }

            private fun octal(b: ByteArray, off: Int, len: Int): Long {
                var v = 0L
                for (i in off until off + len) {
                    val c = b[i].toInt().toChar()
                    if (c == ' ' || c == '\u0000') { if (v != 0L) break else continue }
                    if (c !in '0'..'7') break
                    v = v * 8 + (c - '0')
                }
                return v
            }

            /** The size field: octal, or base-256 for files over 8 GB (GNU / star). */
            private fun size(b: ByteArray): Long {
                if (b[124].toInt() and 0x80 != 0) {
                    var v = 0L
                    for (i in 125 until 136) v = (v shl 8) or (b[i].toLong() and 0xff)
                    return v
                }
                return octal(b, 124, 12)
            }
        }
    }

    companion object {
        private fun parsePax(data: ByteArray): Map<String, String> {
            val out = HashMap<String, String>()
            var pos = 0
            while (pos < data.size) {
                var sp = pos
                while (sp < data.size && data[sp] != ' '.code.toByte()) sp++
                val len = String(data, pos, sp - pos, Charsets.US_ASCII).trim().toIntOrNull() ?: break
                if (len <= 0 || pos + len > data.size) break
                val record = String(data, sp + 1, pos + len - sp - 2, Charsets.UTF_8) // minus the trailing \n
                val eq = record.indexOf('=')
                if (eq > 0) out[record.substring(0, eq)] = record.substring(eq + 1)
                pos += len
            }
            return out
        }

        fun permissions(mode: Int): Set<PosixFilePermission> {
            val set = HashSet<PosixFilePermission>()
            if (mode and 0b100_000_000 != 0) set += OWNER_READ
            if (mode and 0b010_000_000 != 0) set += OWNER_WRITE
            if (mode and 0b001_000_000 != 0) set += OWNER_EXECUTE
            if (mode and 0b000_100_000 != 0) set += GROUP_READ
            if (mode and 0b000_010_000 != 0) set += GROUP_WRITE
            if (mode and 0b000_001_000 != 0) set += GROUP_EXECUTE
            if (mode and 0b000_000_100 != 0) set += OTHERS_READ
            if (mode and 0b000_000_010 != 0) set += OTHERS_WRITE
            if (mode and 0b000_000_001 != 0) set += OTHERS_EXECUTE
            // the app must always be able to read and traverse what it unpacked
            set += OWNER_READ
            return set
        }
    }
}
