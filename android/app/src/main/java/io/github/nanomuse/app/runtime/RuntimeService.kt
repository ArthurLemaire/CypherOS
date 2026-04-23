package io.github.nanomuse.app.runtime

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import io.github.nanomuse.app.App
import io.github.nanomuse.app.DeviceLink
import io.github.nanomuse.app.MainActivity
import io.github.nanomuse.app.Notifier
import io.github.nanomuse.app.Prefs
import io.github.nanomuse.app.R
import io.github.nanomuse.app.device.DeviceHost
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Keeps `nanomuse serve` running on the phone: starts PRoot, watches the process, restarts it
 * when it dies, and shows one quiet notification with what the agent is doing. A foreground
 * service so Android keeps the process alive; a partial wake lock only while a task runs, so
 * the phone may sleep between them.
 *
 * It learns what the agent is doing from the server's own event stream (`/ws`), the same one
 * the notification service and the status capsule read.
 */
class RuntimeService : Service() {
    private lateinit var prefs: Prefs
    private lateinit var runtime: LocalRuntime
    private lateinit var notifier: Notifier
    private val handler = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder().connectTimeout(3, TimeUnit.SECONDS).readTimeout(5, TimeUnit.SECONDS).build()

    private var process: Process? = null
    private var watcher: Thread? = null
    private var stopping = false
    private var restarts = 0
    private var startedAt = 0L
    private var ws: WebSocket? = null
    private var wsRetry: Runnable? = null
    private var link: DeviceLink? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var releaseLock: Runnable? = null
    private val busy = HashMap<String, String>() // thread → what it is doing

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        runtime = LocalRuntime(this)
        notifier = Notifier(this, prefs)
        state = State.STARTING
        foreground(getString(R.string.runtime_starting))
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (process == null) {
            restarts = 0 // an explicit start (the user, the app opening) gets a fresh run of retries
            start()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        stopping = true
        closeSocket()
        releaseWake(now = true)
        process?.let { p ->
            p.destroy()
            if (!p.waitFor(3, TimeUnit.SECONDS)) p.destroyForcibly()
        }
        process = null
        state = State.STOPPED
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ------------------------------------------------------------------ the process

    private fun start() {
        if (!runtime.installed) {
            Log.w(TAG, "root file system not installed; nothing to run")
            fail(getString(R.string.runtime_not_installed))
            return
        }
        val port = prefs.localPort.takeIf { it > 0 } ?: pickPort().also { prefs.localPort = it }
        val token = prefs.localToken.ifEmpty { Prefs.newToken().also { prefs.localToken = it } }
        prefs.serverUrl = "http://127.0.0.1:$port"
        prefs.token = token
        prefs.mode = Prefs.MODE_LOCAL
        // the phone's own capabilities, an MCP server on the loopback the Python side connects to
        val host = DeviceHost.start(this)
        val cmd = runtime.command(port, token, host.url, host.token)
        runtime.rotateLogs()
        val log = runtime.logFile()
        val builder = ProcessBuilder(cmd.argv)
            .directory(runtime.files)
            .redirectErrorStream(true)
            .redirectOutput(ProcessBuilder.Redirect.appendTo(log))
        builder.environment().clear()
        builder.environment().putAll(cmd.env)
        try {
            log.appendText("\n--- nanoMuse ${io.github.nanomuse.app.BuildConfig.VERSION_NAME} starting on port $port (${java.util.Date()}) ---\n")
            process = builder.start()
        } catch (e: Exception) {
            Log.e(TAG, "cannot start proot", e)
            fail(getString(R.string.runtime_failed, e.message ?: e.javaClass.simpleName))
            return
        }
        startedAt = System.currentTimeMillis()
        state = State.STARTING
        foreground(getString(R.string.runtime_starting))
        val p = process!!
        watcher = thread(name = "runtime-watch", isDaemon = true) {
            val code = try { p.waitFor() } catch (_: InterruptedException) { -1 }
            handler.post { exited(p, code) }
        }
        thread(name = "runtime-health", isDaemon = true) { waitHealthy(p, port, token) }
    }

    private fun waitHealthy(p: Process, port: Int, token: String) {
        val deadline = System.currentTimeMillis() + HEALTH_TIMEOUT_MS
        while (System.currentTimeMillis() < deadline && p.isAlive && !stopping) {
            try {
                http.newCall(Request.Builder().url("http://127.0.0.1:$port/api/health").build()).execute().use { r ->
                    if (r.isSuccessful) {
                        handler.post { healthy(port, token) }
                        return
                    }
                }
            } catch (_: Exception) {
                // not up yet
            }
            Thread.sleep(500)
        }
        if (p.isAlive && !stopping) handler.post { fail(getString(R.string.runtime_no_answer)) }
    }

    private fun healthy(port: Int, token: String) {
        restarts = 0
        state = State.RUNNING
        lastError = null
        foreground(getString(R.string.runtime_idle))
        openSocket(port, token)
        listeners.forEach { it(State.RUNNING, null) }
    }

    private fun exited(p: Process, code: Int) {
        if (process !== p) return
        process = null
        closeSocket()
        releaseWake(now = true)
        if (stopping) return
        val lived = System.currentTimeMillis() - startedAt
        Log.w(TAG, "server exited with $code after ${lived / 1000}s")
        if (lived > 60_000) restarts = 0
        restarts++
        if (restarts > MAX_RESTARTS) {
            fail(getString(R.string.runtime_crashed, code))
            return
        }
        val delay = minOf(2_000L shl (restarts - 1), 60_000L)
        state = State.STARTING
        foreground(getString(R.string.runtime_restarting, delay / 1000))
        handler.postDelayed({ if (!stopping && process == null) start() }, delay)
    }

    private fun fail(message: String) {
        state = State.FAILED
        lastError = message
        foreground(message)
        listeners.forEach { it(State.FAILED, message) }
    }

    private fun pickPort(): Int {
        java.net.ServerSocket(0).use { return it.localPort }
    }

    // ------------------------------------------------------------------ the event stream

    private fun openSocket(port: Int, token: String) {
        closeSocket()
        val request = Request.Builder().url("ws://127.0.0.1:$port/ws?token=$token").build()
        ws = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                handler.post {
                    if (ws !== webSocket) return@post
                    // the phone is the server's device: its browser is the agent's browser
                    link?.close()
                    link = DeviceLink(this@RuntimeService) { reply -> webSocket.send(reply.toString()) }
                    webSocket.send(link!!.hello().toString())
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = runCatching { JSONObject(text) }.getOrNull() ?: return
                handler.post { if (ws === webSocket) handle(msg) }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                handler.post { if (ws === webSocket) retrySocket(port, token) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                handler.post { if (ws === webSocket) retrySocket(port, token) }
            }
        })
    }

    private fun retrySocket(port: Int, token: String) {
        ws = null
        if (stopping || process == null) return
        val r = Runnable { wsRetry = null; if (ws == null && process != null) openSocket(port, token) }
        wsRetry = r
        handler.postDelayed(r, 3_000)
    }

    private fun closeSocket() {
        wsRetry?.let { handler.removeCallbacks(it) }
        wsRetry = null
        link?.close()
        link = null
        ws?.let { s -> ws = null; runCatching { s.close(1000, null) } }
    }

    private fun handle(msg: JSONObject) {
        if (link?.handle(msg) == true) return
        // approvals, questions, finished background work: the same notifications as remote mode
        notifier.handle(msg)
        when (msg.optString("kind")) {
            "hello" -> {
                busy.clear()
                msg.optJSONObject("state")?.optJSONObject("status")?.let { status(it) }
            }
            "status" -> msg.optJSONObject("status")?.let { status(it) }
        }
    }

    private fun status(s: JSONObject) {
        val thread = s.optString("thread", "main")
        val st = s.optString("state")
        if (st == "idle") busy.remove(thread) else busy[thread] = s.optString("detail").ifEmpty { st }
        val working = busy.values.firstOrNull()
        currentDetail = working
        if (working != null) {
            holdWake()
            foreground(working)
        } else {
            releaseWake(now = false)
            foreground(getString(R.string.runtime_idle))
        }
        listeners.forEach { it(state, working) }
    }

    // ------------------------------------------------------------------ wake lock

    private fun holdWake() {
        releaseLock?.let { handler.removeCallbacks(it) }
        releaseLock = null
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService<PowerManager>() ?: return
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "nanomuse:task").apply {
            setReferenceCounted(false)
            acquire(WAKE_MAX_MS)
        }
    }

    private fun releaseWake(now: Boolean) {
        releaseLock?.let { handler.removeCallbacks(it) }
        releaseLock = null
        val lock = wakeLock ?: return
        if (now) {
            if (lock.isHeld) lock.release()
            return
        }
        // a short grace: tasks often follow one another (a check-in, then its notification)
        val r = Runnable { releaseLock = null; if (lock.isHeld) lock.release() }
        releaseLock = r
        handler.postDelayed(r, WAKE_GRACE_MS)
    }

    // ------------------------------------------------------------------ the notification

    private fun foreground(text: String) {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val n: Notification = NotificationCompat.Builder(this, App.CH_LINK)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(prefs.agentName.ifEmpty { getString(R.string.app_name) })
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .addAction(0, getString(R.string.runtime_stop), PendingIntent.getService(
                this, 1, Intent(this, RuntimeService::class.java).setAction(ACTION_STOP),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            ))
            .build()
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, NOTIFICATION_ID, n, type)
    }

    enum class State { STOPPED, STARTING, RUNNING, FAILED }

    companion object {
        private const val TAG = "RuntimeService"
        private const val NOTIFICATION_ID = 2
        private const val ACTION_STOP = "io.github.nanomuse.app.runtime.STOP"
        private const val HEALTH_TIMEOUT_MS = 120_000L
        private const val MAX_RESTARTS = 5
        private const val WAKE_MAX_MS = 30 * 60_000L
        private const val WAKE_GRACE_MS = 15_000L

        /** What the rest of the app sees; written on the main thread. */
        @Volatile var state: State = State.STOPPED
            private set
        @Volatile var lastError: String? = null
            private set
        @Volatile var currentDetail: String? = null
            private set
        val listeners = java.util.concurrent.CopyOnWriteArraySet<(State, String?) -> Unit>()

        fun start(context: Context) {
            runCatching { ContextCompat.startForegroundService(context, Intent(context, RuntimeService::class.java)) }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, RuntimeService::class.java))
        }

        /** The local server's log, for the app's diagnostics screen. */
        fun logFile(context: Context): File = LocalRuntime(context).logFile()
    }
}
