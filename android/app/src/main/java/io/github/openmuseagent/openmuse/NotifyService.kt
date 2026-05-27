package io.github.openmuseagent.openmuse

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
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * One WebSocket to the server, kept open while the app is in the background, turning the
 * events a phone should be told about into notifications: approvals waiting for you,
 * questions the agent asked, the last word of work done in the background. Tapping one
 * opens the app on that chat. A resolved approval takes its notification down again.
 *
 * Web Push does the same job for the web app on the open internet; on a home network
 * there is no push service in between, so the phone connects to the server directly.
 * The same event handling lives in `demo/mobilegym/apps/OpenMuse/bridge.ts` for the
 * simulator.
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
    /** timeline event id → notification id, so a resolved card takes its notification down */
    private val shown = LinkedHashMap<String, Int>()

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
        getSystemService<ConnectivityManager>()?.registerDefaultNetworkCallback(networkCallback)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!prefs.connected || !prefs.notify) {
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
                handler.post { backoffMs = RECONNECT_MIN_MS }
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
        ws?.let { s ->
            ws = null
            runCatching { s.close(1000, null) }
        }
    }

    // ------------------------------------------------------------------ the events

    private fun handle(msg: JSONObject) {
        when (msg.optString("kind")) {
            "hello" -> {
                val state = msg.optJSONObject("state") ?: return
                state.optJSONObject("profile")?.optString("name")?.takeIf { it.isNotEmpty() }?.let { prefs.agentName = it }
                foreground(getString(R.string.link_online, host()))
                val pending = state.optJSONArray("pending_approvals") ?: JSONArray()
                for (i in 0 until pending.length()) pending.optJSONObject(i)?.let { notifyFor(it) }
            }
            "profile" -> msg.optJSONObject("profile")?.optString("name")?.takeIf { it.isNotEmpty() }?.let { prefs.agentName = it }
            "event", "update" -> {
                val ev = msg.optJSONObject("event") ?: return
                when (ev.optString("type")) {
                    "approval", "question" -> if (ev.optString("status") == "pending") notifyFor(ev) else retract(ev.optString("id"))
                    "assistant" -> {
                        // Background work reporting in. Only the run's last word is flagged `final`,
                        // and the agent already decided it was worth surfacing (`quiet` otherwise).
                        if (ev.optString("source") == "background" && ev.optBoolean("final") && !ev.optBoolean("quiet")) {
                            val text = ev.optString("text")
                            val id = ev.optString("id")
                            if (text.isNotEmpty() && id.isNotEmpty() && !shown.containsKey(id)) {
                                post(id, App.CH_UPDATES, backgroundTitle(ev.optString("about")), firstLine(text), ev.optString("thread"), high = false)
                            }
                        }
                    }
                }
            }
        }
    }

    private fun notifyFor(ev: JSONObject) {
        val id = ev.optString("id")
        if (id.isEmpty() || shown.containsKey(id)) return
        val name = agentName()
        val isApproval = ev.optString("type") == "approval"
        val body = if (isApproval) {
            listOfNotNull(
                ev.optString("summary").takeIf { it.isNotEmpty() },
                ev.optString("purpose").takeIf { it.isNotEmpty() }?.let { getString(R.string.notify_for, it) },
            ).joinToString(" — ")
        } else {
            ev.optString("text")
        }
        val title = getString(if (isApproval) R.string.notify_approval_title else R.string.notify_question_title, name)
        post(id, App.CH_ATTENTION, title, firstLine(body, 200), ev.optString("thread"), high = true)
    }

    private fun retract(eventId: String) {
        val nid = shown.remove(eventId) ?: return
        NotificationManagerCompat.from(this).cancel(nid)
    }

    private fun post(eventId: String, channel: String, title: String, body: String, thread: String, high: Boolean) {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            Build.VERSION.SDK_INT >= 33
        ) return
        val nid = eventId.hashCode()
        val open = Intent(this, MainActivity::class.java)
            .setAction(Intent.ACTION_VIEW)
            .setData(Uri.parse("openmuse://thread/${Uri.encode(thread)}"))
            .putExtra(MainActivity.EXTRA_THREAD, thread)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pi = PendingIntent.getActivity(this, nid, open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(this, channel)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(this, R.color.accent))
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setPriority(if (high) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(if (high) NotificationCompat.CATEGORY_REMINDER else NotificationCompat.CATEGORY_MESSAGE)
            .build()
        NotificationManagerCompat.from(this).notify(nid, n)
        shown[eventId] = nid
        while (shown.size > 200) shown.remove(shown.keys.first())
    }

    /** Same titles the server uses for its Web Push notifications. */
    private fun backgroundTitle(about: String): String {
        val name = agentName()
        return when {
            about.startsWith("Check-in: ") -> getString(R.string.notify_checkin, name)
            about.startsWith("Working on your goal: ") -> about.removePrefix("Working on your goal: ").ifEmpty { name }
            about.startsWith("Routine: ") -> about.removePrefix("Routine: ").ifEmpty { name }
            about.contains(": ") -> "$name · ${about.substringBefore(": ").lowercase()}"
            else -> about.ifEmpty { name }
        }
    }

    private fun agentName(): String = prefs.agentName.ifEmpty { getString(R.string.app_name) }

    private fun firstLine(text: String, max: Int = 140): String {
        val line = text.replace(Regex("\\s+"), " ").trim()
        return if (line.length > max) line.substring(0, max - 1) + "…" else line
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
            if (prefs.connected && prefs.notify && allowed) {
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
