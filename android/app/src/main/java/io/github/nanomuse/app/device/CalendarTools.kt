package io.github.nanomuse.app.device

import android.Manifest
import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.provider.CalendarContract
import io.github.nanomuse.app.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/** The phone's calendars through `CalendarContract`: read, add, change, delete. */
class CalendarTools(private val context: Context) {
    private val zone: ZoneId get() = ZoneId.systemDefault()

    suspend fun calendars(): JSONArray {
        need(Manifest.permission.READ_CALENDAR)
        return withContext(Dispatchers.IO) {
            val out = JSONArray()
            val cols = arrayOf(
                CalendarContract.Calendars._ID, CalendarContract.Calendars.CALENDAR_DISPLAY_NAME, CalendarContract.Calendars.ACCOUNT_NAME,
                CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL, CalendarContract.Calendars.IS_PRIMARY, CalendarContract.Calendars.VISIBLE,
            )
            context.contentResolver.query(CalendarContract.Calendars.CONTENT_URI, cols, null, null, "${CalendarContract.Calendars.IS_PRIMARY} DESC")?.use { c ->
                while (c.moveToNext()) {
                    out.put(
                        JSONObject()
                            .put("id", c.getLong(0))
                            .put("name", c.getString(1) ?: "")
                            .put("account", c.getString(2) ?: "")
                            .put("writable", c.getInt(3) >= CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR)
                            .put("primary", c.getInt(4) == 1)
                            .put("visible", c.getInt(5) == 1),
                    )
                }
            }
            out
        }
    }

    suspend fun list(args: JSONObject): JSONObject {
        need(Manifest.permission.READ_CALENDAR)
        val from = args.optString("from").takeIf { it.isNotEmpty() }?.let { parse(it, false).first } ?: LocalDate.now(zone).atStartOfDay(zone).toInstant().toEpochMilli()
        val to = args.optString("to").takeIf { it.isNotEmpty() }?.let { parse(it, false).let { (ms, dateOnly) -> if (dateOnly) ms + DAY_MS else ms } }
            ?: (from + 7 * DAY_MS)
        if (to <= from) throw ToolError("`to` must be after `from`")
        val query = args.optString("query").trim()
        val calendarId = if (args.has("calendar_id")) args.getLong("calendar_id") else null
        val limit = args.optInt("limit", 50).coerceIn(1, 500)
        return withContext(Dispatchers.IO) {
            val uri = CalendarContract.Instances.CONTENT_URI.buildUpon().appendPath(from.toString()).appendPath(to.toString()).build()
            val cols = arrayOf(
                CalendarContract.Instances.EVENT_ID, CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN, CalendarContract.Instances.END,
                CalendarContract.Instances.ALL_DAY, CalendarContract.Instances.EVENT_LOCATION, CalendarContract.Instances.CALENDAR_DISPLAY_NAME,
                CalendarContract.Instances.DESCRIPTION, CalendarContract.Instances.CALENDAR_ID,
            )
            val where = ArrayList<String>()
            val whereArgs = ArrayList<String>()
            if (calendarId != null) { where += "${CalendarContract.Instances.CALENDAR_ID} = ?"; whereArgs += calendarId.toString() }
            if (query.isNotEmpty()) {
                where += "(${CalendarContract.Instances.TITLE} LIKE ? OR ${CalendarContract.Instances.EVENT_LOCATION} LIKE ? OR ${CalendarContract.Instances.DESCRIPTION} LIKE ?)"
                repeat(3) { whereArgs += "%$query%" }
            }
            val events = JSONArray()
            var total = 0
            context.contentResolver.query(uri, cols, where.joinToString(" AND ").ifEmpty { null }, whereArgs.toTypedArray().takeIf { it.isNotEmpty() }, "${CalendarContract.Instances.BEGIN} ASC")?.use { c ->
                while (c.moveToNext()) {
                    total++
                    if (events.length() >= limit) continue
                    val allDay = c.getInt(4) == 1
                    events.put(
                        JSONObject()
                            .put("id", c.getLong(0))
                            .put("title", c.getString(1) ?: "(no title)")
                            .put("start", format(c.getLong(2), allDay))
                            .put("end", format(if (allDay) c.getLong(3) - DAY_MS else c.getLong(3), allDay))
                            .put("all_day", allDay)
                            .put("location", c.getString(5) ?: "")
                            .put("calendar", c.getString(6) ?: "")
                            .put("calendar_id", c.getLong(8))
                            .put("notes", (c.getString(7) ?: "").take(300)),
                    )
                }
            }
            JSONObject()
                .put("from", format(from, false)).put("to", format(to, false))
                .put("count", total).put("events", events)
        }
    }

    suspend fun create(args: JSONObject): JSONObject {
        need(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR)
        val title = args.getString("title").trim().ifEmpty { throw ToolError("the event needs a title") }
        val (start, startDateOnly) = parse(args.getString("start"), true)
        val allDay = args.optBoolean("all_day", startDateOnly)
        val end = args.optString("end").takeIf { it.isNotEmpty() }?.let { parse(it, allDay).let { (ms, dateOnly) -> if (allDay && dateOnly) ms + DAY_MS else ms } }
            ?: (start + if (allDay) DAY_MS else HOUR_MS)
        if (end <= start) throw ToolError("`end` must be after `start`")
        return withContext(Dispatchers.IO) {
            val calendarId = if (args.has("calendar_id")) args.getLong("calendar_id") else defaultCalendar()
            val values = ContentValues().apply {
                put(CalendarContract.Events.CALENDAR_ID, calendarId)
                put(CalendarContract.Events.TITLE, title)
                put(CalendarContract.Events.DTSTART, start)
                put(CalendarContract.Events.DTEND, end)
                put(CalendarContract.Events.ALL_DAY, if (allDay) 1 else 0)
                put(CalendarContract.Events.EVENT_TIMEZONE, if (allDay) "UTC" else zone.id)
                args.optString("location").takeIf { it.isNotEmpty() }?.let { put(CalendarContract.Events.EVENT_LOCATION, it) }
                args.optString("description").takeIf { it.isNotEmpty() }?.let { put(CalendarContract.Events.DESCRIPTION, it) }
                if (args.has("reminder_minutes")) put(CalendarContract.Events.HAS_ALARM, 1)
            }
            val uri = context.contentResolver.insert(CalendarContract.Events.CONTENT_URI, values) ?: throw ToolError("the calendar refused the event")
            val id = ContentUris.parseId(uri)
            if (args.has("reminder_minutes")) {
                val reminder = ContentValues().apply {
                    put(CalendarContract.Reminders.EVENT_ID, id)
                    put(CalendarContract.Reminders.MINUTES, args.getInt("reminder_minutes").coerceAtLeast(0))
                    put(CalendarContract.Reminders.METHOD, CalendarContract.Reminders.METHOD_ALERT)
                }
                context.contentResolver.insert(CalendarContract.Reminders.CONTENT_URI, reminder)
            }
            JSONObject().put("id", id).put("title", title).put("start", format(start, allDay)).put("end", format(if (allDay) end - DAY_MS else end, allDay))
                .put("all_day", allDay).put("calendar_id", calendarId).put("calendar", calendarName(calendarId))
        }
    }

    suspend fun update(args: JSONObject): String {
        need(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR)
        val id = args.getLong("id")
        return withContext(Dispatchers.IO) {
            val current = event(id) ?: throw ToolError("no event with id $id")
            val allDay = if (args.has("all_day")) args.getBoolean("all_day") else current.optBoolean("all_day")
            val values = ContentValues()
            args.optString("title").takeIf { it.isNotEmpty() }?.let { values.put(CalendarContract.Events.TITLE, it) }
            if (args.has("location")) values.put(CalendarContract.Events.EVENT_LOCATION, args.getString("location"))
            if (args.has("description")) values.put(CalendarContract.Events.DESCRIPTION, args.getString("description"))
            var start = current.getLong("start_ms")
            var end = current.getLong("end_ms")
            args.optString("start").takeIf { it.isNotEmpty() }?.let { start = parse(it, allDay).first }
            args.optString("end").takeIf { it.isNotEmpty() }?.let { end = parse(it, allDay).let { (ms, dateOnly) -> if (allDay && dateOnly) ms + DAY_MS else ms } }
            if (args.has("start") && !args.has("end")) end = start + (current.getLong("end_ms") - current.getLong("start_ms")).coerceAtLeast(if (allDay) DAY_MS else 0)
            if (end <= start) throw ToolError("`end` must be after `start`")
            values.put(CalendarContract.Events.DTSTART, start)
            values.put(CalendarContract.Events.DTEND, end)
            values.put(CalendarContract.Events.ALL_DAY, if (allDay) 1 else 0)
            values.put(CalendarContract.Events.EVENT_TIMEZONE, if (allDay) "UTC" else zone.id)
            val n = context.contentResolver.update(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, id), values, null, null)
            if (n == 0) throw ToolError("the calendar did not change event $id")
            "Updated event $id: ${values.getAsString(CalendarContract.Events.TITLE) ?: current.optString("title")} · ${format(start, allDay)} → ${format(if (allDay) end - DAY_MS else end, allDay)}"
        }
    }

    suspend fun delete(id: Long): String {
        need(Manifest.permission.READ_CALENDAR, Manifest.permission.WRITE_CALENDAR)
        return withContext(Dispatchers.IO) {
            val current = event(id) ?: throw ToolError("no event with id $id")
            val n = context.contentResolver.delete(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, id), null, null)
            if (n == 0) throw ToolError("the calendar did not delete event $id")
            "Deleted event $id (${current.optString("title")})."
        }
    }

    // ------------------------------------------------------------------ helpers

    private suspend fun need(vararg permissions: String) {
        Ask.require(context, arrayOf(*permissions), context.getString(R.string.ask_why_calendar), "use the calendar")
    }

    private fun event(id: Long): JSONObject? {
        val cols = arrayOf(CalendarContract.Events.TITLE, CalendarContract.Events.DTSTART, CalendarContract.Events.DTEND, CalendarContract.Events.ALL_DAY, CalendarContract.Events.DURATION)
        context.contentResolver.query(ContentUris.withAppendedId(CalendarContract.Events.CONTENT_URI, id), cols, null, null, null)?.use { c ->
            if (!c.moveToFirst()) return null
            val start = c.getLong(1)
            val end = if (c.isNull(2)) start + HOUR_MS else c.getLong(2)
            return JSONObject().put("title", c.getString(0) ?: "").put("start_ms", start).put("end_ms", end).put("all_day", c.getInt(3) == 1)
        }
        return null
    }

    private fun defaultCalendar(): Long {
        val cols = arrayOf(CalendarContract.Calendars._ID, CalendarContract.Calendars.IS_PRIMARY, CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL, CalendarContract.Calendars.VISIBLE)
        var first: Long? = null
        context.contentResolver.query(CalendarContract.Calendars.CONTENT_URI, cols, "${CalendarContract.Calendars.CALENDAR_ACCESS_LEVEL} >= ?", arrayOf(CalendarContract.Calendars.CAL_ACCESS_CONTRIBUTOR.toString()), null)?.use { c ->
            while (c.moveToNext()) {
                val id = c.getLong(0)
                if (c.getInt(1) == 1 && c.getInt(3) == 1) return id
                if (first == null && c.getInt(3) == 1) first = id
                if (first == null) first = id
            }
        }
        return first ?: throw ToolError("there is no writable calendar on this phone (no account with a calendar)")
    }

    private fun calendarName(id: Long): String {
        context.contentResolver.query(ContentUris.withAppendedId(CalendarContract.Calendars.CONTENT_URI, id), arrayOf(CalendarContract.Calendars.CALENDAR_DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) return c.getString(0) ?: ""
        }
        return ""
    }

    /** Milliseconds for a date or date-time in phone time; second: whether it was a date only. */
    private fun parse(text: String, allDay: Boolean): Pair<Long, Boolean> {
        val t = text.trim().replace('T', ' ')
        try {
            if (t.length == 10) {
                val d = LocalDate.parse(t)
                val ms = if (allDay) d.atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli() else d.atStartOfDay(zone).toInstant().toEpochMilli()
                return ms to true
            }
            val dt = try { LocalDateTime.parse(t, DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")) } catch (_: DateTimeParseException) {
                LocalDateTime.parse(t, DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"))
            }
            return dt.atZone(zone).toInstant().toEpochMilli() to false
        } catch (_: DateTimeParseException) {
            throw ToolError("cannot read the time '$text'; use YYYY-MM-DD HH:MM or YYYY-MM-DD")
        }
    }

    private fun format(ms: Long, allDay: Boolean): String {
        val instant = Instant.ofEpochMilli(ms)
        return if (allDay) instant.atZone(ZoneOffset.UTC).toLocalDate().toString()
        else instant.atZone(zone).toLocalDateTime().truncatedTo(java.time.temporal.ChronoUnit.MINUTES).toString().replace('T', ' ')
    }

    companion object {
        private const val HOUR_MS = 3_600_000L
        private const val DAY_MS = 86_400_000L
    }
}
