package io.github.nanomuse.guard

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.identity.NanoMuseIdentity

/**
 * When the agent needs a yes while the app is in the background — a goal check at 3 a.m.
 * that wants to delete something — the card cannot be seen, so the request becomes a
 * notification with Allow and Deny buttons. Tapping the body opens the conversation the
 * request came from, where the card is waiting. "Allow" here is allow-once; standing
 * grants are only given from the card, where the object is spelled out.
 */
class RiskApprovalNotifier(
    private val context: Context,
    private val isAppForeground: () -> Boolean,
) {
    init { ensureChannel() }

    fun notifyIfBackgrounded(request: RiskRequest): Boolean {
        if (isAppForeground()) return false
        val nm = NotificationManagerCompat.from(context)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !nm.areNotificationsEnabled()) return false

        val name = NanoMuseIdentity.name(context)
        val title = RiskText.title(context, request, name)
        val body = RiskText.description(context, request, name) + "\n" + request.preview.lines().first().take(120)

        val open = PendingIntent.getActivity(
            context, request.id.hashCode(),
            Intent(Intent.ACTION_VIEW, Uri.parse("minis://session/${request.sessionId}")).apply {
                setPackage(context.packageName)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        fun action(decision: RiskDecision, code: Int): PendingIntent = PendingIntent.getBroadcast(
            context, request.id.hashCode() * 7 + code,
            Intent(context, RiskApprovalReceiver::class.java).apply {
                action = RiskApprovalReceiver.ACTION_DECIDE
                putExtra(RiskApprovalReceiver.EXTRA_ID, request.id)
                putExtra(RiskApprovalReceiver.EXTRA_DECISION, decision.name)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_nanomuse)
            .setLargeIcon(NanoMuseIdentity.face(context))
            .setContentTitle(title)
            .setContentText(body.lines().first())
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open)
            .addAction(0, context.getString(R.string.nm_risk_allow_once), action(RiskDecision.ALLOW_ONCE, 1))
            .addAction(0, context.getString(R.string.nm_risk_deny), action(RiskDecision.DENY, 2))
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_RECOMMENDATION)
            .setTimeoutAfter(RiskGate.TIMEOUT_MS)
            .build()
        return try {
            nm.notify(TAG_NOTIF, request.id.hashCode(), notification)
            true
        } catch (_: SecurityException) {
            AppLogger.info(TAG, "notify denied (POST_NOTIFICATIONS not granted)")
            false
        }
    }

    fun cancel(requestId: String) {
        NotificationManagerCompat.from(context).cancel(TAG_NOTIF, requestId.hashCode())
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = ContextCompat.getSystemService(context, NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, context.getString(R.string.nm_risk_channel_name), NotificationManager.IMPORTANCE_HIGH).apply {
                description = context.getString(R.string.nm_risk_channel_description)
                setShowBadge(true)
            },
        )
    }

    companion object {
        private const val TAG = "RiskNotifier"
        const val CHANNEL_ID = "nanomuse_approval"
        private const val TAG_NOTIF = "nanomuse-approval"
    }
}

/** The Allow / Deny buttons on the notification land here. */
class RiskApprovalReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_DECIDE) return
        val id = intent.getStringExtra(EXTRA_ID) ?: return
        val decision = runCatching { RiskDecision.valueOf(intent.getStringExtra(EXTRA_DECISION) ?: "") }.getOrNull() ?: return
        // Only allow-once and deny come from a notification; anything else is ignored.
        if (decision != RiskDecision.ALLOW_ONCE && decision != RiskDecision.DENY) return
        RiskGate.decide(id, decision)
    }

    companion object {
        const val ACTION_DECIDE = "io.github.nanomuse.RISK_DECIDE"
        const val EXTRA_ID = "id"
        const val EXTRA_DECISION = "decision"
    }
}
