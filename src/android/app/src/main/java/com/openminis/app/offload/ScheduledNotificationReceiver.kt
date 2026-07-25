package com.openminis.app.offload

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.openminis.app.R
import com.openminis.app.logging.AppLogger

/**
 * Fires when an `android-notification schedule` AlarmManager alarm
 * triggers. Posts the notification immediately and removes the entry
 * from the pending-notifications prefs so a follow-up `pending` call
 * no longer lists it.
 *
 * Mirrors the AlarmReceiver pattern but for the user-scheduled
 * notification path (apple-notification schedule), which on iOS goes
 * through UNUserNotificationCenter directly. Android has no equivalent
 * "scheduled local notification" API, so we use AlarmManager + a
 * receiver as the moral equivalent.
 */
class ScheduledNotificationReceiver : BroadcastReceiver() {

    companion object {
        const val EXTRA_ID = "scheduled_notification_id"
        const val EXTRA_TITLE = "scheduled_notification_title"
        const val EXTRA_BODY = "scheduled_notification_body"
        const val CHANNEL_ID = "minis_agent_notifications"
        private const val TAG = "ScheduledNotifReceiver"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra(EXTRA_ID) ?: "unknown"
        val title = intent.getStringExtra(EXTRA_TITLE) ?: "Minis"
        val body = intent.getStringExtra(EXTRA_BODY) ?: ""
        AppLogger.debug(TAG, "scheduled notification fired: id=$id title='$title'")

        // Drop the prefs entry so `pending` no longer surfaces it.
        try {
            ScheduledNotificationStore(context).remove(id)
        } catch (e: Throwable) {
            AppLogger.warning(TAG, "remove($id) failed: ${e.message}")
        }

        val notifId = id.hashCode() and 0x7FFFFFFF
        val launchIntent = context.packageManager.getLaunchIntentForPackage(context.packageName)
        val contentPi = if (launchIntent != null) {
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            } else {
                PendingIntent.FLAG_UPDATE_CURRENT
            }
            PendingIntent.getActivity(context, notifId, launchIntent, flags)
        } else null

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .apply { if (contentPi != null) setContentIntent(contentPi) }
            .build()
        try {
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE)
                as android.app.NotificationManager
            nm.notify(notifId, notification)
        } catch (e: SecurityException) {
            AppLogger.error(TAG, "post denied — POST_NOTIFICATIONS missing: ${e.message}")
        }
    }
}
