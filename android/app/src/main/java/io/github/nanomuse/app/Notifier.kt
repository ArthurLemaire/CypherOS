package io.github.nanomuse.app

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject

/**
 * Turns the server's event stream into notifications: approvals waiting for you, questions the
 * agent asked, the last word of work done in the background. Tapping one opens the app on that
 * chat; a resolved approval takes its notification down again.
 *
 * Fed by whichever service holds the WebSocket — [NotifyService] when the server is on the
 * user's computer, `RuntimeService` when it runs on the phone. The same event handling lives
 * in `demo/mobilegym/apps/nanoMuse/bridge.ts` for the simulator.
 */
class Notifier(private val context: Context, private val prefs: Prefs) {
    /** timeline event id → notification id, so a resolved card takes its notification down */
    private val shown = LinkedHashMap<String, Int>()

    /** Handle one message from `/ws`. Returns true when the message was one of ours. */
    fun handle(msg: JSONObject): Boolean {
        when (msg.optString("kind")) {
            "hello" -> {
                val state = msg.optJSONObject("state") ?: return true
                state.optJSONObject("profile")?.optString("name")?.takeIf { it.isNotEmpty() }?.let { prefs.agentName = it }
                val pending = state.optJSONArray("pending_approvals") ?: JSONArray()
                for (i in 0 until pending.length()) pending.optJSONObject(i)?.let { notifyFor(it) }
            }
            "profile" -> msg.optJSONObject("profile")?.optString("name")?.takeIf { it.isNotEmpty() }?.let { prefs.agentName = it }
            "event", "update" -> {
                val ev = msg.optJSONObject("event") ?: return true
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
            else -> return false
        }
        return true
    }

    private fun notifyFor(ev: JSONObject) {
        val id = ev.optString("id")
        if (id.isEmpty() || shown.containsKey(id)) return
        val name = agentName()
        val isApproval = ev.optString("type") == "approval"
        val body = if (isApproval) {
            listOfNotNull(
                ev.optString("summary").takeIf { it.isNotEmpty() },
                ev.optString("purpose").takeIf { it.isNotEmpty() }?.let { context.getString(R.string.notify_for, it) },
            ).joinToString(" — ")
        } else {
            ev.optString("text")
        }
        val title = context.getString(if (isApproval) R.string.notify_approval_title else R.string.notify_question_title, name)
        post(id, App.CH_ATTENTION, title, firstLine(body, 200), ev.optString("thread"), high = true)
    }

    private fun retract(eventId: String) {
        val nid = shown.remove(eventId) ?: return
        NotificationManagerCompat.from(context).cancel(nid)
    }

    private fun post(eventId: String, channel: String, title: String, body: String, thread: String, high: Boolean) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            Build.VERSION.SDK_INT >= 33
        ) return
        val nid = eventId.hashCode()
        val open = Intent(context, MainActivity::class.java)
            .setAction(Intent.ACTION_VIEW)
            .setData(Uri.parse("nanomuse://thread/${Uri.encode(thread)}"))
            .putExtra(MainActivity.EXTRA_THREAD, thread)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val pi = PendingIntent.getActivity(context, nid, open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(context, R.color.accent))
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setPriority(if (high) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setCategory(if (high) NotificationCompat.CATEGORY_REMINDER else NotificationCompat.CATEGORY_MESSAGE)
            .build()
        NotificationManagerCompat.from(context).notify(nid, n)
        shown[eventId] = nid
        while (shown.size > 200) shown.remove(shown.keys.first())
    }

    /** Same titles the server uses for its Web Push notifications. */
    private fun backgroundTitle(about: String): String {
        val name = agentName()
        return when {
            about.startsWith("Check-in: ") -> context.getString(R.string.notify_checkin, name)
            about.startsWith("Working on your goal: ") -> about.removePrefix("Working on your goal: ").ifEmpty { name }
            about.startsWith("Routine: ") -> about.removePrefix("Routine: ").ifEmpty { name }
            about.contains(": ") -> "$name · ${about.substringBefore(": ").lowercase()}"
            else -> about.ifEmpty { name }
        }
    }

    private fun agentName(): String = prefs.agentName.ifEmpty { context.getString(R.string.app_name) }

    private fun firstLine(text: String, max: Int = 140): String {
        val line = text.replace(Regex("\\s+"), " ").trim()
        return if (line.length > max) line.substring(0, max - 1) + "…" else line
    }
}
