package io.github.nanomuse.app

import android.Manifest
import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * One WebSocket to the server on the user's computer, kept open while the app is in the
 * background, so the events a phone should be told about become notifications (see
 * [Notifier]). Web Push does the same job for the web app on the open internet; on a home
 * network there is no push service in between, so the phone connects to the server directly.
 *
 * When the server runs on the phone itself, `RuntimeService` holds the socket instead and
 * this service stays stopped.
 */
class NotifyService : Service() {
    private lateinit var prefs: Prefs
    private val handler = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private var ws: WebSocket? = null
    private var wsUrl = ""
    private var backoffMs = RECONNECT_MIN_MS
    private var reconnect: Runnable? = null
    private var unauthorized = false
    private lateinit var notifier: Notifier
    private var link: DeviceLink? = null

    private val networkCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            handler.post {
                if (ws == null && !unauthorized) {
                    backoffMs = RECONNECT_MIN_MS
                    open()
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        notifier = Notifier(this, prefs)
        getSystemService<ConnectivityManager>()?.registerDefaultNetworkCallback(networkCallback)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!prefs.connected || !prefs.notify || prefs.isLocal) {
            // in local mode RuntimeService holds the socket and feeds the same Notifier
            stopSelf()
            return START_NOT_STICKY
        }
        foreground(getString(R.string.link_connecting, host()))
        val url = prefs.wsUrl()
        if (url != wsUrl || (ws == null && reconnect == null)) {
            wsUrl = url
            unauthorized = false
            backoffMs = RECONNECT_MIN_MS
            close()
            open()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        close()
        getSystemService<ConnectivityManager>()?.unregisterNetworkCallback(networkCallback)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ------------------------------------------------------------------ the connection

    private fun open() {
        if (wsUrl.isEmpty()) return
        val request = Request.Builder().url(wsUrl).build()
        val socket = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                handler.post {
                    backoffMs = RECONNECT_MIN_MS
                    // the phone is a device too: its browser is the agent's when asked
                    link?.close()
                    link = DeviceLink(this@NotifyService) { reply -> webSocket.send(reply.toString()) }
                    webSocket.send(link!!.hello().toString())
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val msg = runCatching { JSONObject(text) }.getOrNull() ?: return
                handler.post { if (ws === webSocket) handle(msg) }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                handler.post { lost(webSocket, code) }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                handler.post { lost(webSocket, response?.code ?: 0) }
            }
        })
        ws = socket
    }

    private fun lost(socket: WebSocket, code: Int) {
        if (ws !== socket) return
        ws = null
        if (code == 4401) {
            // the server rejected the token: no point retrying until the settings change
            unauthorized = true
            foreground(getString(R.string.link_unauthorized))
            return
        }
        foreground(getString(R.string.link_offline))
        val r = Runnable {
            reconnect = null
            if (ws == null && !unauthorized) open()
        }
        reconnect = r
        handler.postDelayed(r, backoffMs)
        backoffMs = (backoffMs * 2).coerceAtMost(RECONNECT_MAX_MS)
    }

    private fun close() {
        reconnect?.let { handler.removeCallbacks(it) }
        reconnect = null
        link?.close()
        link = null
        ws?.let { s ->
            ws = null
            runCatching { s.close(1000, null) }
        }
    }

    // ------------------------------------------------------------------ the events

    private fun handle(msg: JSONObject) {
        if (link?.handle(msg) == true) return
        notifier.handle(msg)
        if (msg.optString("kind") == "hello") foreground(getString(R.string.link_online, host()))
    }

    private fun host(): String = Uri.parse(prefs.serverUrl).let { u -> (u.host ?: prefs.serverUrl) + if (u.port > 0) ":${u.port}" else "" }

    // ------------------------------------------------------------------ the foreground notification

    private fun foreground(text: String) {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val n: Notification = NotificationCompat.Builder(this, App.CH_LINK)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, LINK_NOTIFICATION_ID, n, type)
    }

    companion object {
        private const val LINK_NOTIFICATION_ID = 1
        private const val RECONNECT_MIN_MS = 1_000L
        private const val RECONNECT_MAX_MS = 60_000L

        /** Start or stop the service to match the settings. Idempotent; safe to call often. */
        fun sync(context: Context) {
            val prefs = Prefs(context)
            val allowed = Build.VERSION.SDK_INT < 33 ||
                ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            if (prefs.connected && prefs.notify && allowed && !prefs.isLocal) {
                runCatching { ContextCompat.startForegroundService(context, Intent(context, NotifyService::class.java)) }
            } else {
                stop(context)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, NotifyService::class.java))
        }
    }
}
