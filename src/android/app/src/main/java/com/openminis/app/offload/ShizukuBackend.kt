package com.openminis.app.offload

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import com.openminis.app.logging.AppLogger
import rikka.shizuku.Shizuku
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * [T-android-privileged-backend] Shizuku-protocol privileged-execution backend.
 *
 * Both the official Shizuku manager (`moe.shizuku.privileged.api`, RikkaApps)
 * and AXManager (`frb.axeron.manager`, Axeron) implement the SAME Shizuku
 * binder protocol and push their binder into the SAME client-side
 * [rikka.shizuku.ShizukuProvider]. The `rikka.shizuku.Shizuku` singleton is
 * therefore a single slot, owned by whichever manager the user authorized —
 * the SDK and this class are unaware of (and indifferent to) which one is
 * running. The earlier two-backend split confused detection because both
 * `ShizukuBackend` and `AxeronBackend` reported state off the same shared
 * singleton; that abstraction has been removed.
 *
 * "Installed" therefore means **any** known Shizuku-protocol manager is on
 * the device. The Settings UI shows both install options.
 */
class ShizukuBackend(private val appContext: Context) {

    @Volatile private var onStateChanged: (() -> Unit)? = null
    private var listenersRegistered = false

    private val binderReceivedListener = Shizuku.OnBinderReceivedListener {
        AppLogger.info(TAG, "binder received")
        onStateChanged?.invoke()
    }
    private val binderDeadListener = Shizuku.OnBinderDeadListener {
        AppLogger.warning(TAG, "binder died")
        onStateChanged?.invoke()
    }
    private val permissionResultListener =
        Shizuku.OnRequestPermissionResultListener { requestCode, grantResult ->
            AppLogger.info(
                TAG,
                "permission result code=$requestCode grant=${grantResult == PackageManager.PERMISSION_GRANTED}",
            )
            onStateChanged?.invoke()
        }

    /** Any known Shizuku-protocol manager installed? */
    fun isInstalled(): Boolean = installedManagerPackage() != null

    /**
     * The first installed Shizuku-protocol manager package (in preference
     * order: official Shizuku, then AXManager), or null if none installed.
     * Used to drive "open the manager app" actions.
     */
    fun installedManagerPackage(): String? = SHIZUKU_COMPATIBLE_PACKAGES.firstOrNull { pkg ->
        runCatching { appContext.packageManager.getPackageInfo(pkg, 0); true }.getOrDefault(false)
    }

    fun isBinderAlive(): Boolean =
        runCatching { Shizuku.pingBinder() }.getOrDefault(false)

    fun isPermissionGranted(): Boolean = runCatching {
        Shizuku.pingBinder() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
    }.getOrDefault(false)

    fun snapshot(): ShizukuManager.Snapshot {
        if (!isInstalled()) return ShizukuManager.Snapshot(ShizukuManager.State.NOT_INSTALLED)
        if (!isBinderAlive()) return ShizukuManager.Snapshot(ShizukuManager.State.NOT_RUNNING)
        return if (isPermissionGranted()) {
            ShizukuManager.Snapshot(ShizukuManager.State.READY, versionOrUnknown(), uidOrUnknown())
        } else {
            ShizukuManager.Snapshot(ShizukuManager.State.NEED_PERMISSION)
        }
    }

    fun registerListeners(onStateChanged: () -> Unit) {
        this.onStateChanged = onStateChanged
        if (listenersRegistered) return
        listenersRegistered = true
        runCatching {
            Shizuku.addBinderReceivedListenerSticky(binderReceivedListener)
            Shizuku.addBinderDeadListener(binderDeadListener)
            Shizuku.addRequestPermissionResultListener(permissionResultListener)
        }.onFailure { AppLogger.warning(TAG, "init listeners failed: ${it.message}") }
    }

    fun refresh() {
        onStateChanged?.invoke()
    }

    /**
     * Launch the installed manager app (Shizuku or AXManager — whichever is
     * present). If none is installed, falls back to the Shizuku install page;
     * the multi-option install UI lives in the Settings screen, not here.
     */
    fun openManagerApp(context: Context) {
        val pkg = installedManagerPackage()
        if (pkg != null) {
            val intent = context.packageManager.getLaunchIntentForPackage(pkg)
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                runCatching { context.startActivity(intent) }
                    .onFailure { AppLogger.warning(TAG, "open $pkg failed: ${it.message}") }
                return
            }
        }
        openInstallPage(context, SHIZUKU_GITHUB_URL)
    }

    fun openInstallPage(context: Context, url: String) {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(intent) }
            .onFailure { AppLogger.warning(TAG, "openInstallPage($url) failed: ${it.message}") }
    }

    fun requestPermission() {
        if (!runCatching { Shizuku.pingBinder() }.getOrDefault(false)) return
        if (Shizuku.shouldShowRequestPermissionRationale()) {
            AppLogger.warning(TAG, "permission permanently denied — user must enable in the manager app")
            return
        }
        runCatching { Shizuku.requestPermission(PERMISSION_REQUEST_CODE) }
            .onFailure { AppLogger.warning(TAG, "requestPermission failed: ${it.message}") }
    }

    private fun versionOrUnknown(): Int = runCatching {
        if (Shizuku.pingBinder()) Shizuku.getVersion() else -1
    }.getOrDefault(-1)

    private fun uidOrUnknown(): Int = runCatching {
        if (Shizuku.pingBinder()) Shizuku.getUid() else -1
    }.getOrDefault(-1)

    /**
     * Shizuku-SDK process path (reflection-based `Shizuku.newProcess`).
     */
    fun runProcess(
        argv: Array<String>,
        env: Array<String>?,
        cwd: String?,
        timeoutMs: Long,
    ): ShizukuManager.ProcessResult {
        if (!isPermissionGranted()) {
            return ShizukuManager.ProcessResult(
                exitCode = 126,
                stdout = "",
                stderr = "shizuku not ready (state=${snapshot().state})",
            )
        }
        // Shizuku.newProcess is hidden API — invoke via reflection so the
        // SDK upgrade doesn't break our build. The returned object is a
        // ShizukuRemoteProcess which extends java.lang.Process, so once we
        // have it, treat it as a normal Process and use the standard
        // waitFor(timeout, unit) API rather than reflecting for a
        // nonexistent `waitForTimeout` method (T343).
        val procAny = runCatching {
            val m = Shizuku::class.java.getDeclaredMethod(
                "newProcess",
                Array<String>::class.java,
                Array<String>::class.java,
                String::class.java,
            )
            m.isAccessible = true
            m.invoke(null, argv, env, cwd)
        }.getOrElse {
            AppLogger.warning(TAG, "newProcess reflection failed: ${it.message}")
            return ShizukuManager.ProcessResult(1, "", "shizuku.newProcess unavailable: ${it.message}")
        } ?: return ShizukuManager.ProcessResult(1, "", "shizuku.newProcess returned null")

        val proc = procAny as? Process ?: return ShizukuManager.ProcessResult(
            1, "",
            "shizuku.newProcess returned ${procAny.javaClass.name}, not java.lang.Process",
        )

        val out = StringBuilder()
        val err = StringBuilder()
        val outThread = Thread {
            runCatching {
                proc.inputStream?.use { s ->
                    s.bufferedReader().forEachLine { l -> synchronized(out) { out.append(l).append('\n') } }
                }
            }
        }
        val errThread = Thread {
            runCatching {
                proc.errorStream?.use { s ->
                    s.bufferedReader().forEachLine { l -> synchronized(err) { err.append(l).append('\n') } }
                }
            }
        }
        outThread.isDaemon = true; errThread.isDaemon = true
        outThread.start(); errThread.start()

        val exited: Boolean = try {
            proc.waitFor(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (t: IllegalArgumentException) {
            // Shizuku v13 RemoteProcess.waitFor(long, TimeUnit) throws IllegalArgumentException
            // ("process hasn't exited") instead of blocking. Fall back to polling exitValue().
            if (polledFallbackLogged.compareAndSet(false, true)) {
                AppLogger.info(TAG, "Using polling fallback for Shizuku RemoteProcess.waitFor(timeout) (SDK bug — throws IllegalArgumentException)")
            }
            val deadline = System.currentTimeMillis() + timeoutMs
            var done = false
            while (System.currentTimeMillis() < deadline) {
                try {
                    proc.exitValue()
                    done = true
                    break
                } catch (e: RuntimeException) {
                    if (e is IllegalThreadStateException || e is IllegalArgumentException) {
                        Thread.sleep(50)
                    } else {
                        throw e
                    }
                }
            }
            done
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "Shizuku waitFor failed: type=${t::class.java.name} msg=${t.message}")
            runCatching { proc.destroy() }
            runCatching { outThread.join(2000) }
            runCatching { errThread.join(2000) }
            return ShizukuManager.ProcessResult(1, out.toString().trimEnd('\n'), (err.toString().trimEnd('\n') + "\nwaitFor failed: ${t.message}").trim())
        }

        if (!exited) {
            runCatching { proc.destroy() }
            runCatching { outThread.join(2000) }
            runCatching { errThread.join(2000) }
            // Linux convention: 124 = command timed out (coreutils `timeout`).
            return ShizukuManager.ProcessResult(124, out.toString().trimEnd('\n'), err.toString().trimEnd('\n'))
        }

        runCatching { outThread.join(2000) }
        runCatching { errThread.join(2000) }
        val rc = runCatching { proc.exitValue() }.getOrDefault(-1)
        return ShizukuManager.ProcessResult(rc, out.toString().trimEnd('\n'), err.toString().trimEnd('\n'))
    }

    companion object {
        private const val TAG = "ShizukuBackend"

        // Known Shizuku-protocol manager packages. Order = UI install-preference.
        const val SHIZUKU_PACKAGE = "moe.shizuku.privileged.api"
        const val AXMANAGER_PACKAGE = "frb.axeron.manager"
        val SHIZUKU_COMPATIBLE_PACKAGES = listOf(SHIZUKU_PACKAGE, AXMANAGER_PACKAGE)

        const val SHIZUKU_GITHUB_URL = "https://github.com/RikkaApps/Shizuku/releases"
        const val AXMANAGER_GITHUB_URL = "https://github.com/fahrez182/AxManager/releases"

        const val PERMISSION_REQUEST_CODE = 0xC1A4D

        private val polledFallbackLogged = AtomicBoolean(false)
    }
}
