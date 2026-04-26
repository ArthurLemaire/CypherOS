package io.github.nanomuse.app.runtime

import android.content.Context
import android.net.ConnectivityManager
import android.os.Build
import android.util.Log
import androidx.core.content.getSystemService
import io.github.nanomuse.app.BuildConfig
import org.json.JSONObject
import org.tukaani.xz.XZInputStream
import java.io.File
import java.io.FilterInputStream
import java.io.IOException
import java.io.InputStream
import java.util.Locale
import java.util.TimeZone

/**
 * nanoMuse on the phone itself: an Alpine root file system unpacked from the APK, run under
 * PRoot (a user-mode chroot, no root needed), with `nanomuse serve` on the loopback.
 *
 * What lives where under the app's files directory:
 *
 *   rootfs/    the unpacked Alpine + python + nanomuse; replaced whole on an upgrade
 *   home/      bound over /root inside — the data dir, the workspace, npm's globals; kept across upgrades
 *   etc/       resolv.conf and hosts, written from the phone's network settings before each start
 *   proc/      stand-ins for the /proc files Android hides from apps
 *   tmp/       /tmp inside, and PRoot's own scratch space
 *   logs/      runtime.log: PRoot's and the server's output
 *
 * This class knows how to install and how to start; [RuntimeService] owns the process.
 */
class LocalRuntime(private val context: Context) {
    val files: File = context.filesDir
    val rootfs = File(files, "rootfs")
    val home = File(files, "home")
    val etc = File(files, "etc")
    val fakeProc = File(files, "proc")
    val tmp = File(files, "tmp")
    val logs = File(files, "logs")
    private val marker = File(rootfs, ".nanomuse-installed")

    /** What the APK carries, from assets/rootfs.json; null in the connect-only build. */
    val bundled: RootfsInfo? by lazy {
        if (!BuildConfig.LOCAL_RUNTIME) return@lazy null
        runCatching { RootfsInfo.parse(context.assets.open(ROOTFS_INFO).bufferedReader().readText()) }.getOrNull()
    }

    val available: Boolean get() = bundled != null && File(prootPath()).exists()

    /** Installed, and the same build as the APK's — an app update brings a new root file system. */
    val installed: Boolean
        get() {
            val want = bundled?.version ?: return false
            return marker.exists() && marker.readText().trim() == want && File(rootfs, "usr/local/bin/nanomuse-serve").exists()
        }

    val installedVersion: String? get() = marker.takeIf { it.exists() }?.readText()?.trim()

    // ------------------------------------------------------------------ install

    /**
     * Unpack the root file system from the APK. Slow (a minute on a mid-range phone), so it
     * reports progress: compressed bytes read so far out of the total, and the current entry.
     * Unpacks next to the old one and swaps at the end, so a failure leaves what worked.
     */
    @Throws(IOException::class)
    fun install(progress: (done: Long, total: Long, entry: String) -> Unit) {
        val info = bundled ?: throw IOException("this build has no root file system")
        val fresh = File(files, "rootfs.new")
        fresh.deleteRecursively()
        fresh.mkdirs()
        val total = info.size
        val counting = CountingInputStream(context.assets.open(ROOTFS_ASSET))
        var lastReport = 0L
        val unpacker = TarUnpacker(fresh) { entry ->
            val done = counting.count
            if (done - lastReport > 256 * 1024) {
                lastReport = done
                progress(done, total, entry)
            }
        }
        counting.use { raw -> XZInputStream(raw).use { xz -> unpacker.unpack(xz) } }
        progress(total, total, "")
        // what the tar cannot carry
        File(fresh, "tmp").mkdirs()
        File(fresh, "root").mkdirs()
        File(fresh, ".nanomuse-installed").writeText(info.version)
        val old = File(files, "rootfs.old")
        old.deleteRecursively()
        if (rootfs.exists() && !rootfs.renameTo(old)) throw IOException("cannot move the old root file system aside")
        if (!fresh.renameTo(rootfs)) throw IOException("cannot put the new root file system in place")
        old.deleteRecursively()
        for (d in listOf(home, etc, fakeProc, tmp, logs, File(home, "workspace"), File(home, ".nanomuse"))) d.mkdirs()
        Log.i(TAG, "installed root file system ${info.version}")
    }

    fun uninstall() {
        rootfs.deleteRecursively()
        File(files, "rootfs.new").deleteRecursively()
        File(files, "rootfs.old").deleteRecursively()
    }

    /** Everything, the user's data with it. */
    fun wipe() {
        uninstall()
        for (d in listOf(home, etc, fakeProc, tmp)) d.deleteRecursively()
    }

    // ------------------------------------------------------------------ start

    fun prootPath(): String = File(context.applicationInfo.nativeLibraryDir, "libproot.so").path
    fun loaderPath(): String = File(context.applicationInfo.nativeLibraryDir, "libproot-loader.so").path

    /**
     * The PRoot command line and environment for `nanomuse serve` on [port] with [token].
     * [hostUrl] / [hostToken] are the app's own local API (its device capabilities as an MCP
     * server), when it is running.
     */
    fun command(port: Int, token: String, hostUrl: String? = null, hostToken: String? = null): Command {
        for (d in listOf(home, etc, fakeProc, tmp, logs)) d.mkdirs()
        writeNetworkFiles()
        writeFakeProc()
        val argv = ArrayList<String>()
        argv += prootPath()
        // fake root: apk add and friends want uid 0; there is no real root anywhere here
        argv += "-0"
        // no orphans when the app is killed; hard links as symlinks (Android refuses them)
        argv += "--kill-on-exit"
        argv += "--link2symlink"
        argv += listOf("-r", rootfs.path, "-w", "/root")
        for (b in listOf("/dev", "/proc", "/sys")) argv += listOf("-b", b)
        // the user's data lives outside the root file system, so an upgrade keeps it
        argv += listOf("-b", "${home.path}:/root")
        argv += listOf("-b", "${tmp.path}:/tmp")
        argv += listOf("-b", "${etc.path}/resolv.conf:/etc/resolv.conf")
        argv += listOf("-b", "${etc.path}/hosts:/etc/hosts")
        // /proc files Android keeps from apps: a program that reads them gets these instead
        for (name in FAKE_PROC) {
            val real = File("/proc/$name")
            if (!real.canRead()) argv += listOf("-b", "${fakeProc.path}/$name:/proc/$name")
        }
        argv += listOf("/bin/sh", "/usr/local/bin/nanomuse-serve")

        val env = LinkedHashMap<String, String>()
        env["HOME"] = "/root"
        env["PATH"] = "/opt/nanomuse/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        env["TERM"] = "xterm-256color"
        env["LANG"] = "C.UTF-8"
        env["TMPDIR"] = "/tmp"
        env["TZ"] = TimeZone.getDefault().id
        env["PROOT_LOADER"] = loaderPath()
        env["PROOT_TMP_DIR"] = tmp.path
        env["UV_LINK_MODE"] = "symlink"
        env["NANOMUSE_SERVER_PORT"] = port.toString()
        env["NANOMUSE_SERVER_TOKEN"] = token
        env["NANOMUSE_DEVICE"] = "android"
        env["NANOMUSE_DEVICE_MODEL"] = listOf(Build.MANUFACTURER, Build.MODEL).filter { it.isNotBlank() }.joinToString(" ")
        env["NANOMUSE_DEVICE_SDK"] = Build.VERSION.SDK_INT.toString()
        env["NANOMUSE_REGION"] = Locale.getDefault().country.ifEmpty { context.resources.configuration.locales[0].country }
        if (!hostUrl.isNullOrEmpty()) {
            env["NANOMUSE_HOST_URL"] = hostUrl
            if (!hostToken.isNullOrEmpty()) env["NANOMUSE_HOST_TOKEN"] = hostToken
        }
        proxyEnv()?.let { proxy ->
            for (k in listOf("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")) env[k] = proxy
        }
        return Command(argv, env)
    }

    class Command(val argv: List<String>, val env: Map<String, String>)

    /** musl's resolver reads /etc/resolv.conf; Android has none, so it is written here. */
    private fun writeNetworkFiles() {
        val cm = context.getSystemService<ConnectivityManager>()
        val servers = cm?.activeNetwork?.let { cm.getLinkProperties(it) }?.dnsServers
            ?.mapNotNull { it.hostAddress }?.filter { it.isNotBlank() }.orEmpty()
        val lines = (servers.ifEmpty { DEFAULT_DNS }).map { "nameserver ${it.substringBefore('%')}" } + "options timeout:3 attempts:2"
        File(etc, "resolv.conf").writeText(lines.joinToString("\n") + "\n")
        val hosts = File(etc, "hosts")
        if (!hosts.exists()) hosts.writeText("127.0.0.1\tlocalhost\n::1\tlocalhost\n")
    }

    private fun writeFakeProc() {
        val stat = File(fakeProc, "stat")
        if (stat.exists()) return
        val cpus = Runtime.getRuntime().availableProcessors()
        val sb = StringBuilder("cpu  0 0 0 0 0 0 0 0 0 0\n")
        for (i in 0 until cpus) sb.append("cpu$i 0 0 0 0 0 0 0 0 0 0\n")
        sb.append("intr 0\nctxt 0\nbtime 0\nprocesses 1\nprocs_running 1\nprocs_blocked 0\nsoftirq 0\n")
        stat.writeText(sb.toString())
        File(fakeProc, "version").writeText("Linux version ${System.getProperty("os.version") ?: "5.10"} (nanoMuse) #1 SMP PREEMPT\n")
        File(fakeProc, "loadavg").writeText("0.00 0.00 0.00 1/100 1\n")
        File(fakeProc, "uptime").writeText("1.00 1.00\n")
        File(fakeProc, "vmstat").writeText("nr_free_pages 0\n")
    }

    private fun proxyEnv(): String? {
        val cm = context.getSystemService<ConnectivityManager>() ?: return null
        val p = cm.defaultProxy ?: return null
        if (p.host.isNullOrEmpty() || p.port <= 0) return null
        return "http://${p.host}:${p.port}"
    }

    // ------------------------------------------------------------------ logs

    fun logFile(): File = File(logs, "runtime.log")

    /** Keep the log from growing without end: at start, roll a big one over once. */
    fun rotateLogs() {
        logs.mkdirs()
        val f = logFile()
        if (f.length() > LOG_ROLL_BYTES) {
            File(logs, "runtime.log.1").delete()
            f.renameTo(File(logs, "runtime.log.1"))
        }
    }

    fun logTail(lines: Int = 40): String {
        val f = logFile()
        if (!f.exists()) return ""
        val all = f.readLines()
        return all.takeLast(lines).joinToString("\n")
    }

    private class CountingInputStream(input: InputStream) : FilterInputStream(input) {
        var count = 0L
        override fun read(): Int = super.read().also { if (it >= 0) count++ }
        override fun read(b: ByteArray, off: Int, len: Int): Int = super.read(b, off, len).also { if (it > 0) count += it }
        override fun skip(n: Long): Long = super.skip(n).also { if (it > 0) count += it }
    }

    companion object {
        private const val TAG = "LocalRuntime"
        const val ROOTFS_ASSET = "rootfs.tar.xz"
        const val ROOTFS_INFO = "rootfs.json"
        private const val LOG_ROLL_BYTES = 2L * 1024 * 1024
        private val DEFAULT_DNS = listOf("1.1.1.1", "8.8.8.8", "223.5.5.5")
        private val FAKE_PROC = listOf("stat", "version", "loadavg", "uptime", "vmstat")
    }
}

/** assets/rootfs.json, written by scripts/rootfs/build.sh. */
class RootfsInfo(val version: String, val nanomuse: String, val python: String, val node: String, val size: Long, val unpacked: Long, val sha256: String) {
    companion object {
        fun parse(text: String): RootfsInfo {
            val j = JSONObject(text)
            return RootfsInfo(
                version = j.getString("version"),
                nanomuse = j.optString("nanomuse"),
                python = j.optString("python"),
                node = j.optString("node", "none"),
                size = j.getLong("size"),
                unpacked = j.optLong("unpacked"),
                sha256 = j.optString("sha256"),
            )
        }
    }
}
