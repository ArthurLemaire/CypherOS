package io.github.nanomuse.app.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermission

/**
 * The unpacker against archives written here, byte by byte: ustar entries, PAX long names,
 * GNU long names, symlinks, hard links, modes — and the two ways an archive may try to escape.
 */
class TarUnpackerTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun unpacksFilesDirsLinksAndModes() {
        val tar = TarWriter()
        tar.dir("bin/", 0b111_101_101)
        tar.file("bin/sh", "#!/bin/sh\necho hi\n".toByteArray(), 0b111_101_101)
        tar.file("etc/motd", "welcome\n".toByteArray(), 0b110_100_100)
        tar.symlink("bin/ash", "sh")
        tar.hardlink("bin/busybox", "bin/sh")
        tar.file("empty", ByteArray(0), 0b110_100_100)
        val root = tmp.newFolder("root")
        val seen = ArrayList<String>()
        val n = TarUnpacker(root) { seen += it }.unpack(ByteArrayInputStream(tar.finish()))

        assertEquals(6, n)
        assertEquals(listOf("bin", "bin/sh", "etc/motd", "bin/ash", "bin/busybox", "empty"), seen)
        assertEquals("#!/bin/sh\necho hi\n", File(root, "bin/sh").readText())
        assertEquals("welcome\n", File(root, "etc/motd").readText())
        assertEquals(0L, File(root, "empty").length())
        val link = File(root, "bin/ash").toPath()
        assertTrue(Files.isSymbolicLink(link))
        assertEquals("sh", Files.readSymbolicLink(link).toString())
        assertEquals("#!/bin/sh\necho hi\n", File(root, "bin/busybox").readText())
        val perms = Files.getPosixFilePermissions(File(root, "bin/sh").toPath())
        assertTrue(perms.contains(PosixFilePermission.OWNER_EXECUTE))
        assertTrue(perms.contains(PosixFilePermission.OTHERS_EXECUTE))
        assertFalse(Files.getPosixFilePermissions(File(root, "etc/motd").toPath()).contains(PosixFilePermission.OWNER_EXECUTE))
    }

    @Test
    fun longNamesThroughPaxAndGnuHeaders() {
        val tar = TarWriter()
        val deep = "opt/nanomuse/lib/python3.12/site-packages/" + "a".repeat(80) + "/" + "b".repeat(60) + ".py"
        tar.paxFile(deep, "x = 1\n".toByteArray())
        val gnu = "usr/lib/node_modules/npm/node_modules/" + "c".repeat(120) + "/index.js"
        tar.gnuLongFile(gnu, "module.exports = 1\n".toByteArray())
        tar.paxSymlink("very/" + "d".repeat(150) + "/link", "../" + "e".repeat(120) + "/target")
        val root = tmp.newFolder("root")
        TarUnpacker(root).unpack(ByteArrayInputStream(tar.finish()))

        assertEquals("x = 1\n", File(root, deep).readText())
        assertEquals("module.exports = 1\n", File(root, gnu).readText())
        val link = File(root, "very/" + "d".repeat(150) + "/link").toPath()
        assertTrue(Files.isSymbolicLink(link))
        assertEquals("../" + "e".repeat(120) + "/target", Files.readSymbolicLink(link).toString())
    }

    @Test
    fun ustarPrefixFieldIsHonoured() {
        val tar = TarWriter()
        val prefix = "share/" + "p".repeat(90)
        tar.fileWithPrefix(prefix, "leaf.txt", "leaf\n".toByteArray())
        val root = tmp.newFolder("root")
        TarUnpacker(root).unpack(ByteArrayInputStream(tar.finish()))
        assertEquals("leaf\n", File(root, "$prefix/leaf.txt").readText())
    }

    @Test
    fun skipsDevicesAndFifos() {
        val tar = TarWriter()
        tar.entry("dev/null", '3', ByteArray(0), 0b110_110_110)
        tar.entry("run/fifo", '6', ByteArray(0), 0b110_000_000)
        tar.file("ok", "ok".toByteArray(), 0b110_100_100)
        val root = tmp.newFolder("root")
        val n = TarUnpacker(root).unpack(ByteArrayInputStream(tar.finish()))
        assertEquals(3, n)
        assertFalse(File(root, "dev/null").exists())
        assertFalse(File(root, "run/fifo").exists())
        assertTrue(File(root, "ok").exists())
    }

    @Test
    fun refusesEntriesThatEscapeTheRoot() {
        val root = tmp.newFolder("root")
        for (name in listOf("../outside", "a/../../outside", "/../outside")) {
            val tar = TarWriter()
            tar.file(name, "x".toByteArray(), 0b110_100_100)
            try {
                TarUnpacker(root).unpack(ByteArrayInputStream(tar.finish()))
                fail("$name should have been refused")
            } catch (e: IOException) {
                assertTrue(e.message!!.contains("escapes"))
            }
        }
        assertFalse(File(tmp.root, "outside").exists())
    }

    @Test
    fun refusesHardLinksToOutsideTheRoot() {
        val root = tmp.newFolder("root")
        val victim = tmp.newFile("secret.txt").apply { writeText("s") }
        val tar = TarWriter()
        tar.hardlink("stolen", "../${victim.name}")
        try {
            TarUnpacker(root).unpack(ByteArrayInputStream(tar.finish()))
            fail("should have been refused")
        } catch (e: IOException) {
            assertTrue(e.message!!.contains("escapes"))
        }
    }

    @Test
    fun truncatedArchiveIsAnError() {
        val tar = TarWriter()
        tar.file("a", ByteArray(2000) { 1 }, 0b110_100_100)
        val bytes = tar.finish().copyOf(512 + 1000)
        try {
            TarUnpacker(tmp.newFolder("root")).unpack(ByteArrayInputStream(bytes))
            fail("should have been refused")
        } catch (e: IOException) {
            assertTrue(e.message!!.contains("ended"))
        }
    }

    @Test
    fun emptyArchiveHasNoEntries() {
        assertEquals(0, TarUnpacker(tmp.newFolder("root")).unpack(ByteArrayInputStream(ByteArray(1024))))
        assertEquals(0, TarUnpacker(tmp.newFolder("root2")).unpack(ByteArrayInputStream(ByteArray(0))))
    }

    /** Just enough of a tar writer for the tests: ustar headers, PAX and GNU long-name records. */
    private class TarWriter {
        private val out = ByteArrayOutputStream()

        fun file(name: String, data: ByteArray, mode: Int) = entry(name, '0', data, mode)
        fun dir(name: String, mode: Int) = entry(name, '5', ByteArray(0), mode)
        fun symlink(name: String, target: String) = entry(name, '2', ByteArray(0), 0b111_111_111, link = target)
        fun hardlink(name: String, target: String) = entry(name, '1', ByteArray(0), 0b110_100_100, link = target)

        fun paxFile(name: String, data: ByteArray) {
            pax(mapOf("path" to name))
            entry(name.take(100), '0', data, 0b110_100_100)
        }

        fun paxSymlink(name: String, target: String) {
            pax(mapOf("path" to name, "linkpath" to target))
            entry(name.take(100), '2', ByteArray(0), 0b111_111_111, link = target.take(100))
        }

        fun gnuLongFile(name: String, data: ByteArray) {
            val bytes = (name + "\u0000").toByteArray()
            entry("././@LongLink", 'L', bytes, 0)
            entry(name.take(100), '0', data, 0b110_100_100)
        }

        fun fileWithPrefix(prefix: String, name: String, data: ByteArray) = entry(name, '0', data, 0b110_100_100, prefix = prefix)

        fun entry(name: String, type: Char, data: ByteArray, mode: Int, link: String = "", prefix: String = "") {
            val h = ByteArray(512)
            put(h, 0, name.toByteArray())
            put(h, 100, "%07o\u0000".format(mode).toByteArray())
            put(h, 108, "0000000\u0000".toByteArray())
            put(h, 116, "0000000\u0000".toByteArray())
            put(h, 124, "%011o\u0000".format(data.size).toByteArray())
            put(h, 136, "%011o\u0000".format(0).toByteArray())
            h[156] = type.code.toByte()
            put(h, 157, link.toByteArray())
            put(h, 257, "ustar\u0000".toByteArray())
            put(h, 265, "00".toByteArray())
            put(h, 345, prefix.toByteArray())
            put(h, 148, "        ".toByteArray())
            var sum = 0
            for (b in h) sum += b.toInt() and 0xff
            put(h, 148, "%06o\u0000 ".format(sum).toByteArray())
            out.write(h)
            out.write(data)
            val pad = (512 - data.size % 512) % 512
            out.write(ByteArray(pad))
        }

        private fun pax(records: Map<String, String>) {
            val sb = StringBuilder()
            for ((k, v) in records) {
                val body = " $k=$v\n"
                var len = body.toByteArray().size
                len += len.toString().length
                if ((len.toString() + body).toByteArray().size != len) len++
                sb.append(len).append(body)
            }
            entry("PaxHeader", 'x', sb.toString().toByteArray(), 0b110_100_100)
        }

        fun finish(): ByteArray {
            out.write(ByteArray(1024))
            return out.toByteArray()
        }

        private fun put(h: ByteArray, off: Int, bytes: ByteArray) {
            System.arraycopy(bytes, 0, h, off, bytes.size)
        }
    }
}
