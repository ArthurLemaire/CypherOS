package io.github.nanomuse.app

import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.core.content.FileProvider
import io.github.nanomuse.app.runtime.RuntimeService
import java.io.File
import java.io.FileOutputStream
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

/**
 * What the app keeps about its own failures, and how it leaves the phone: a crash is written to
 * a file under the app's private storage and nowhere else — there is no crash reporting, no
 * analytics, no network call — and *Settings → Export logs* bundles the crash files, the local
 * server's log and the app's own lines from logcat into one zip for the share sheet, so a
 * problem can be sent to a person the user chooses.
 */
object Diagnostics {
    private const val TAG = "Diagnostics"
    private const val KEEP_CRASHES = 5
    private const val LOG_TAIL_BYTES = 2L * 1024 * 1024
    private val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US)

    fun crashDir(context: Context): File = File(context.filesDir, "crashes")

    /** Write every uncaught exception to a file, then let Android do what it always does. */
    fun install(context: Context) {
        val before = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            try {
                writeCrash(context, thread, error)
            } catch (_: Throwable) {
            }
            before?.uncaughtException(thread, error)
        }
    }

    private fun writeCrash(context: Context, thread: Thread, error: Throwable) {
        val dir = crashDir(context).apply { mkdirs() }
        val trace = StringWriter().also { error.printStackTrace(PrintWriter(it)) }.toString()
        File(dir, "crash-${stamp.format(Date())}.txt").writeText(about(context) + "\nthread: ${thread.name}\n\n" + trace)
        // the last few are enough to see a pattern; older ones go
        dir.listFiles { f -> f.name.startsWith("crash-") }
            ?.sortedByDescending { it.name }
            ?.drop(KEEP_CRASHES)
            ?.forEach { it.delete() }
    }

    /** The build and the phone, never the server address or a token. */
    fun about(context: Context): String {
        val prefs = Prefs(context)
        return buildString {
            appendLine("nanoMuse for Android ${BuildConfig.VERSION_NAME} (${BuildConfig.FLAVOR}, ${if (BuildConfig.DEBUG) "debug" else "release"})")
            appendLine("Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) · ${Build.MANUFACTURER} ${Build.MODEL} · ${Build.SUPPORTED_ABIS.joinToString(",")}")
            appendLine("mode: ${prefs.mode.ifEmpty { "-" }} · runtime: ${RuntimeService.state} · vendor: ${KeepRunning.vendor().ifEmpty { "-" }}")
            appendLine(
                "battery unrestricted: ${KeepRunning.batteryUnrestricted(context)} · overlay: ${KeepRunning.overlayAllowed(context)} · " +
                    "exact alarms: ${KeepRunning.exactAlarms(context)} · start on boot: ${prefs.startOnBoot}",
            )
        }
    }

    /** Bundle everything into a zip under the cache dir and hand it to the share sheet. */
    fun export(context: Context): Boolean {
        val out = File(context.cacheDir, "logs").apply { mkdirs() }
        out.listFiles()?.forEach { it.delete() }
        val zip = File(out, "nanomuse-logs-${stamp.format(Date())}.zip")
        try {
            ZipOutputStream(FileOutputStream(zip)).use { z ->
                z.put("about.txt", about(context).toByteArray())
                crashDir(context).listFiles()?.sortedBy { it.name }?.forEach { z.put("crashes/${it.name}", it.readBytes()) }
                if (BuildConfig.LOCAL_RUNTIME) {
                    val log = RuntimeService.logFile(context)
                    if (log.isFile) z.put("runtime.log", tail(log))
                }
                z.put("logcat.txt", logcat().toByteArray())
            }
        } catch (e: Exception) {
            Log.w(TAG, "log export failed", e)
            return false
        }
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", zip)
        val send = Intent(Intent.ACTION_SEND)
            .setType("application/zip")
            .putExtra(Intent.EXTRA_STREAM, uri)
            .putExtra(Intent.EXTRA_SUBJECT, zip.name)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return try {
            context.startActivity(Intent.createChooser(send, null).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (e: Exception) {
            Log.w(TAG, "no app to share the logs with", e)
            false
        }
    }

    /** The app's own lines from logcat — an app may read its own without any permission. */
    private fun logcat(): String = try {
        val p = ProcessBuilder("logcat", "-d", "-v", "threadtime", "--pid=${android.os.Process.myPid()}", "-t", "3000")
            .redirectErrorStream(true)
            .start()
        val text = p.inputStream.bufferedReader().readText()
        p.waitFor()
        text
    } catch (e: Exception) {
        "logcat unavailable: ${e.message}"
    }

    private fun tail(file: File): ByteArray {
        val size = file.length()
        if (size <= LOG_TAIL_BYTES) return file.readBytes()
        file.inputStream().use { s ->
            s.skip(size - LOG_TAIL_BYTES)
            return s.readBytes()
        }
    }

    private fun ZipOutputStream.put(name: String, bytes: ByteArray) {
        putNextEntry(ZipEntry(name))
        write(bytes)
        closeEntry()
    }
}
