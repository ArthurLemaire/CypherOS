package io.github.nanomuse.app.device

import android.Manifest
import android.app.PendingIntent
import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.AlarmClock
import android.provider.Settings
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import io.github.nanomuse.app.App
import io.github.nanomuse.app.MainActivity
import io.github.nanomuse.app.Prefs
import io.github.nanomuse.app.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar

/** A tool refusing or failing in a way the model should read as text. */
class ToolError(message: String) : Exception(message)

/** What an MCP endpoint serves: a list of tools and a way to call one. */
interface ToolSource {
    fun describe(): JSONArray
    suspend fun call(name: String, args: JSONObject): String
}

/** One capability of the phone, as the MCP `tools/list` describes it. */
class Tool(val name: String, val description: String, val schema: JSONObject, val run: suspend (JSONObject) -> Any)

/** Builds a JSON Schema object for a tool's arguments. */
internal class Schema {
    private val props = JSONObject()
    private val required = JSONArray()

    fun str(name: String, description: String, required: Boolean = false, enum: List<String>? = null) {
        val p = JSONObject().put("type", "string").put("description", description)
        if (enum != null) p.put("enum", JSONArray(enum))
        add(name, p, required)
    }

    fun int(name: String, description: String, required: Boolean = false) = add(name, JSONObject().put("type", "integer").put("description", description), required)
    fun num(name: String, description: String) = add(name, JSONObject().put("type", "number").put("description", description), false)
    fun bool(name: String, description: String) = add(name, JSONObject().put("type", "boolean").put("description", description), false)
    fun ints(name: String, description: String) =
        add(name, JSONObject().put("type", "array").put("items", JSONObject().put("type", "integer")).put("description", description), false)

    private fun add(name: String, p: JSONObject, req: Boolean) {
        props.put(name, p)
        if (req) required.put(name)
    }

    fun build(): JSONObject {
        val o = JSONObject().put("type", "object").put("properties", props)
        if (required.length() > 0) o.put("required", required)
        return o
    }
}

internal fun schema(block: Schema.() -> Unit): JSONObject = Schema().apply(block).build()

/**
 * What the phone can do for the agent: the seven capabilities of the launch checklist, as
 * MCP tools served on the loopback by [DeviceHost]. The names are what `nanomuse-device`
 * takes and what the server prefixes with `device__`; their Sentinel defaults live in
 * `nanomuse/runtime.py` (`DEVICE_TOOLS`) and must be kept in step.
 *
 * Every permission is asked of the user by Android through [Ask]; nothing here grants
 * anything on its own. Reading notifications is deliberately absent (P2, its own switch).
 */
class DeviceTools(private val context: Context) : ToolSource {
    private val calendar = CalendarTools(context)
    private val contacts = ContactsTools(context)
    private val location = LocationTool(context)
    private val photos = PhotoTool(context)

    val all: List<Tool> = listOf(
        Tool(
            "clipboard_read",
            "What is on the phone's clipboard right now (text). Android only shows the clipboard to the app on screen: when nanoMuse is not, the user is asked with a notification.",
            schema { },
        ) { clipboardRead() },
        Tool(
            "clipboard_write",
            "Put text on the phone's clipboard, ready to paste anywhere.",
            schema { str("text", "The text to copy", required = true) },
        ) { clipboardWrite(it.getString("text")) },
        Tool(
            "notify",
            "Post a notification on the phone from the agent — for something worth a glance while the app is closed. Tapping it opens the chat.",
            schema {
                str("title", "Short title", required = true)
                str("body", "One or two sentences", required = true)
                str("thread", "Chat to open on tap (default: the main chat)")
            },
        ) { notify(it.getString("title"), it.getString("body"), it.optString("thread")) },
        Tool("calendars", "The calendars on this phone (id, name, account, whether events can be added).", schema { }) { calendar.calendars() },
        Tool(
            "calendar_list",
            "Events on the phone's calendars in a time range (default: today and the next 7 days), optionally filtered by a word.",
            schema {
                str("from", "Start of the range: YYYY-MM-DD or YYYY-MM-DD HH:MM (phone time)")
                str("to", "End of the range, same forms")
                str("query", "Only events whose title, location or notes contain this")
                int("calendar_id", "Only this calendar (see `calendars`)")
                int("limit", "At most this many events (default 50)")
            },
        ) { calendar.list(it) },
        Tool(
            "calendar_create",
            "Add an event to a calendar on the phone. Times are phone time; an all-day event takes dates.",
            schema {
                str("title", "Event title", required = true)
                str("start", "YYYY-MM-DD HH:MM, or YYYY-MM-DD for all-day", required = true)
                str("end", "Same form; default one hour after start (all-day: the same day)")
                bool("all_day", "All-day event")
                str("location", "Where")
                str("description", "Notes")
                int("calendar_id", "Which calendar (default: the primary writable one)")
                int("reminder_minutes", "A reminder this many minutes before")
            },
        ) { calendar.create(it) },
        Tool(
            "calendar_update",
            "Change an event on the phone's calendar. Only the fields given change.",
            schema {
                int("id", "The event id from `calendar_list`", required = true)
                str("title", "New title")
                str("start", "New start, YYYY-MM-DD HH:MM")
                str("end", "New end")
                bool("all_day", "All-day")
                str("location", "New place")
                str("description", "New notes")
            },
        ) { calendar.update(it) },
        Tool(
            "calendar_delete",
            "Delete an event from the phone's calendar.",
            schema { int("id", "The event id from `calendar_list`", required = true) },
        ) { calendar.delete(it.getInt("id").toLong()) },
        Tool(
            "contacts_search",
            "Find people in the phone's contacts by name (also matches phone numbers and e-mail addresses). Read-only.",
            schema {
                str("query", "Name or part of one", required = true)
                int("limit", "At most this many (default 10)")
            },
        ) { contacts.search(it.getString("query"), it.optInt("limit", 10)) },
        Tool(
            "location",
            "Where the phone is now: coordinates, accuracy, and the address when it can be looked up.",
            schema {
                str("accuracy", "`fine` (GPS, default) or `coarse` (about a city block)", enum = listOf("fine", "coarse"))
                int("max_age_seconds", "A fix this old is good enough (default 120)")
            },
        ) { location.locate(it.optString("accuracy", "fine"), it.optInt("max_age_seconds", 120)) },
        Tool(
            "alarm_set",
            "Set an alarm in the phone's clock app.",
            schema {
                int("hour", "0–23", required = true)
                int("minute", "0–59", required = true)
                str("message", "Label shown with the alarm")
                ints("days", "Repeat on these weekdays: 1 = Monday … 7 = Sunday; omit for once")
                bool("vibrate", "Vibrate too")
            },
        ) { alarm(it) },
        Tool(
            "timer_set",
            "Start a countdown timer in the phone's clock app.",
            schema {
                int("seconds", "Length in seconds (or give minutes)")
                int("minutes", "Length in minutes, if you would rather")
                str("message", "Label")
            },
        ) { timer(it) },
        Tool(
            "photo_pick",
            "Ask the user to choose photos or videos in the system picker; they are copied into the workspace and the paths returned. Nothing else in the library is readable.",
            schema {
                int("max", "How many at most (default 1, up to 10)")
                str("why", "One line shown to the user about what the photos are for")
            },
        ) { photos.pick(it.optInt("max", 1), it.optString("why")) },
    )

    /** `tools/list`. */
    override fun describe(): JSONArray {
        val arr = JSONArray()
        for (t in all) arr.put(JSONObject().put("name", t.name).put("description", t.description).put("inputSchema", t.schema))
        return arr
    }

    /** `tools/call`: the tool's answer as text. Throws [ToolError] with a sentence for the model. */
    override suspend fun call(name: String, args: JSONObject): String {
        val tool = all.firstOrNull { it.name == name } ?: throw ToolError("this phone has no tool '$name'")
        return when (val out = tool.run(args)) {
            is String -> out
            is JSONObject -> out.toString(2)
            is JSONArray -> out.toString(2)
            else -> out.toString()
        }
    }

    // ------------------------------------------------------------------ clipboard

    private suspend fun clipboardRead(): Any {
        val cm = context.getSystemService<ClipboardManager>() ?: throw ToolError("no clipboard service")
        // the app on screen may read it directly; otherwise only through a focused window of ours
        val direct = withContext(Dispatchers.Main) {
            if (App.foreground && cm.hasPrimaryClip()) cm.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(context)?.toString() else null
        }
        val text = direct ?: Ask.clipboard(context)
            ?: throw ToolError("The clipboard can only be read while nanoMuse is on screen, and the user did not open it. Ask them to open the app or to paste the text.")
        return if (text.isEmpty()) "The clipboard is empty." else text
    }

    private suspend fun clipboardWrite(text: String): String {
        val cm = context.getSystemService<ClipboardManager>() ?: throw ToolError("no clipboard service")
        withContext(Dispatchers.Main) { cm.setPrimaryClip(ClipData.newPlainText("nanoMuse", text)) }
        return "Copied ${text.length} characters to the clipboard."
    }

    // ------------------------------------------------------------------ notifications

    private suspend fun notify(title: String, body: String, thread: String): String {
        if (Build.VERSION.SDK_INT >= 33 && Ask.permissions(context, arrayOf(Manifest.permission.POST_NOTIFICATIONS), context.getString(R.string.ask_why_notify)) != Ask.Outcome.GRANTED) {
            throw ToolError("Notifications are not allowed for nanoMuse on this phone; the user can allow them in the app or in Android's settings.")
        }
        val prefs = Prefs(context)
        val open = Intent(context, MainActivity::class.java)
            .setAction(Intent.ACTION_VIEW)
            .setData(Uri.parse("nanomuse://thread/${Uri.encode(thread.ifEmpty { "main" })}"))
            .putExtra(MainActivity.EXTRA_THREAD, thread.ifEmpty { "main" })
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val id = ("agent:" + title + body).hashCode()
        val pi = PendingIntent.getActivity(context, id, open, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(context, App.CH_UPDATES)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(context, R.color.accent))
            .setContentTitle(title)
            .setContentText(body)
            .setSubText(prefs.agentName.ifEmpty { null })
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .build()
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            Build.VERSION.SDK_INT >= 33
        ) throw ToolError("Notifications are not allowed for nanoMuse on this phone.")
        NotificationManagerCompat.from(context).notify(id, n)
        return "Notification posted."
    }

    // ------------------------------------------------------------------ alarms and timers

    private suspend fun alarm(args: JSONObject): String {
        val hour = args.getInt("hour")
        val minute = args.getInt("minute")
        if (hour !in 0..23 || minute !in 0..59) throw ToolError("hour must be 0–23 and minute 0–59")
        val intent = Intent(AlarmClock.ACTION_SET_ALARM)
            .putExtra(AlarmClock.EXTRA_HOUR, hour)
            .putExtra(AlarmClock.EXTRA_MINUTES, minute)
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        args.optString("message").takeIf { it.isNotEmpty() }?.let { intent.putExtra(AlarmClock.EXTRA_MESSAGE, it) }
        if (args.has("vibrate")) intent.putExtra(AlarmClock.EXTRA_VIBRATE, args.getBoolean("vibrate"))
        args.optJSONArray("days")?.let { days ->
            val list = ArrayList<Int>()
            for (i in 0 until days.length()) {
                when (days.optInt(i)) { // 1 = Monday … 7 = Sunday → java.util.Calendar constants
                    1 -> Calendar.MONDAY; 2 -> Calendar.TUESDAY; 3 -> Calendar.WEDNESDAY; 4 -> Calendar.THURSDAY
                    5 -> Calendar.FRIDAY; 6 -> Calendar.SATURDAY; 7 -> Calendar.SUNDAY; else -> null
                }?.let(list::add)
            }
            if (list.isNotEmpty()) intent.putExtra(AlarmClock.EXTRA_DAYS, list)
        }
        val label = "%02d:%02d".format(hour, minute)
        return launch(intent, context.getString(R.string.device_alarm_tap, label), "Alarm set for $label" + (args.optString("message").takeIf { it.isNotEmpty() }?.let { " ($it)" } ?: "") + ".")
    }

    private suspend fun timer(args: JSONObject): String {
        val seconds = if (args.has("seconds")) args.getInt("seconds") else args.optInt("minutes") * 60
        if (seconds <= 0 || seconds > 24 * 3600) throw ToolError("give seconds (1–86400) or minutes (1–1440)")
        val intent = Intent(AlarmClock.ACTION_SET_TIMER)
            .putExtra(AlarmClock.EXTRA_LENGTH, seconds)
            .putExtra(AlarmClock.EXTRA_SKIP_UI, true)
        args.optString("message").takeIf { it.isNotEmpty() }?.let { intent.putExtra(AlarmClock.EXTRA_MESSAGE, it) }
        val label = if (seconds >= 60) "${seconds / 60} min" + (if (seconds % 60 != 0) " ${seconds % 60} s" else "") else "$seconds s"
        return launch(intent, context.getString(R.string.device_timer_tap, label), "Timer started: $label.")
    }

    /**
     * Hand an intent to another app. From the foreground (or with the overlay permission,
     * which Android takes as consent) it opens at once; from the background it is offered as
     * a notification the user taps — that is the rule for every app on Android 10+.
     */
    private suspend fun launch(intent: Intent, tapTitle: String, done: String): String {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (context.packageManager.resolveActivity(intent, 0) == null) throw ToolError("No clock app on this phone takes alarms or timers.")
        if (App.foreground || Settings.canDrawOverlays(context)) {
            try {
                withContext(Dispatchers.Main) { context.startActivity(intent) }
            } catch (e: ActivityNotFoundException) {
                throw ToolError("No clock app on this phone takes alarms or timers.")
            }
            return done
        }
        if (Build.VERSION.SDK_INT >= 33 && !Ask.granted(context, Manifest.permission.POST_NOTIFICATIONS)) {
            throw ToolError("nanoMuse is in the background and may not open the clock app from there; ask the user to open nanoMuse and try again.")
        }
        val id = tapTitle.hashCode()
        val pi = PendingIntent.getActivity(context, id, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(context, App.CH_ATTENTION)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(context, R.color.accent))
            .setContentTitle(tapTitle)
            .setContentText(context.getString(R.string.device_tap_body, Prefs(context).agentName.ifEmpty { context.getString(R.string.app_name) }))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .build()
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            Build.VERSION.SDK_INT >= 33
        ) throw ToolError("nanoMuse is in the background and may not post notifications, so it cannot hand the alarm to the clock app now. Ask the user to open nanoMuse (or allow notifications) and try again.")
        NotificationManagerCompat.from(context).notify(id, n)
        return "nanoMuse is in the background, so the phone will not let it open the clock app directly: a notification is waiting — the alarm or timer is set when the user taps it. Tell the user."
    }
}
