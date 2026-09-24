package io.github.nanomuse.app.runtime

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import androidx.core.content.getSystemService

/**
 * The phone's alarm for the local server's schedule. Under Doze the process's own timers run
 * late — a `sleep(30)` can take an hour — so a reminder for 07:30 needs Android to wake the
 * phone at 07:30: an exact alarm for the server's `next_wake_at` (`GET /api/upcoming`), which
 * on firing has [RuntimeService] hold its wake lock for a moment and `POST /api/tick`.
 *
 * Exact alarms are a permission on Android 12+ (*Alarms & reminders*; Android 14 denies it by
 * default). Without it the alarm is set with [AlarmManager.setAndAllowWhileIdle], which Doze may
 * delay by up to about fifteen minutes — reminders still fire, a little late; the *Keep it
 * running* section in Settings says so and opens the permission page.
 */
object WakeAlarms {
    const val ACTION_WAKE = "io.github.nanomuse.app.WAKE"
    private const val TAG = "WakeAlarms"
    private const val MIN_AHEAD_MS = 1_000L

    /** Whether the alarm may be exact here: always below Android 12, a permission from then on. */
    fun exactAllowed(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        return context.getSystemService<AlarmManager>()?.canScheduleExactAlarms() == true
    }

    /** Set the (one) alarm for [atMs] (epoch); returns whether it is exact. */
    fun arm(context: Context, atMs: Long): Boolean {
        val am = context.getSystemService<AlarmManager>() ?: return false
        val at = maxOf(atMs, System.currentTimeMillis() + MIN_AHEAD_MS)
        val pi = pending(context)
        val exact = exactAllowed(context)
        try {
            if (exact) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
        } catch (e: SecurityException) {
            // the permission went away between the check and the call
            Log.w(TAG, "exact alarm refused, falling back", e)
            am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            return false
        }
        Log.i(TAG, "next wake in ${(at - System.currentTimeMillis()) / 1000}s (${if (exact) "exact" else "inexact"})")
        return exact
    }

    fun cancel(context: Context) {
        context.getSystemService<AlarmManager>()?.cancel(pending(context))
    }

    private fun pending(context: Context): PendingIntent = PendingIntent.getBroadcast(
        context,
        0,
        Intent(context, WakeReceiver::class.java).setAction(ACTION_WAKE),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
}

/** The alarm went off (or the exact-alarm permission changed): poke the runtime. */
class WakeReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            WakeAlarms.ACTION_WAKE -> RuntimeService.poke(context)
            AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED -> RuntimeService.poke(context)
        }
    }
}
