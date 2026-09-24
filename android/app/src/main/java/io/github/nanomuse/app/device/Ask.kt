package io.github.nanomuse.app.device

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import io.github.nanomuse.app.App
import io.github.nanomuse.app.Prefs
import io.github.nanomuse.app.R
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap

/**
 * The moments a phone tool needs the user's hand: a runtime permission, the clipboard (which
 * Android 10+ only shows to the app on screen), the Photo Picker. Each goes through
 * [DeviceAskActivity], a see-through activity that does the one thing and reports back here.
 *
 * When the app is in the foreground the activity opens at once. When it is not — the agent
 * working in the background — Android does not let an app open activities, so a notification
 * is posted and the tool waits for the tap; if none comes in time it fails with a sentence
 * the model can pass on. Nothing is granted by the agent itself: every dialog is Android's.
 */
object Ask {
    private val pending = ConcurrentHashMap<String, CompletableDeferred<Bundle?>>()

    const val EXTRA_REQUEST = "request"
    const val EXTRA_MODE = "mode"
    const val EXTRA_PERMISSIONS = "permissions"
    const val EXTRA_MAX = "max"
    const val MODE_PERMISSIONS = "permissions"
    const val MODE_CLIPBOARD = "clipboard"
    const val MODE_PHOTOS = "photos"
    const val RESULT_GRANTED = "granted"
    const val RESULT_TEXT = "text"
    const val RESULT_URIS = "uris"

    fun granted(context: Context, vararg permissions: String): Boolean =
        permissions.all { ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED }

    /** How a permission request ended. */
    enum class Outcome { GRANTED, DECLINED, NO_ANSWER }

    /** Have these permissions, asking the user if need be. */
    suspend fun permissions(context: Context, permissions: Array<String>, what: String): Outcome {
        if (granted(context, *permissions)) return Outcome.GRANTED
        val intent = Intent(context, DeviceAskActivity::class.java)
            .putExtra(EXTRA_MODE, MODE_PERMISSIONS)
            .putExtra(EXTRA_PERMISSIONS, permissions)
        val result = run(context, intent, context.getString(R.string.ask_permission_title, agentName(context)), what, PERMISSION_WAIT_MS)
        return when {
            result?.getBoolean(RESULT_GRANTED) == true || granted(context, *permissions) -> Outcome.GRANTED
            result == null -> Outcome.NO_ANSWER
            else -> Outcome.DECLINED
        }
    }

    /**
     * Have these permissions or throw a [ToolError] that tells the model what actually happened:
     * the user said no (do not ask again), or nobody answered while the app was in the background.
     */
    suspend fun require(context: Context, permissions: Array<String>, what: String, use: String) {
        when (permissions(context, permissions, what)) {
            Outcome.GRANTED -> return
            Outcome.DECLINED -> throw ToolError("The user did not allow nanoMuse to $use. Do not try again now; they can allow it later in Android's settings for the app.")
            Outcome.NO_ANSWER -> throw ToolError("Android asked the user to let nanoMuse $use, but nobody answered within ${PERMISSION_WAIT_MS / 60_000} minutes (the app is in the background). Ask the user to open nanoMuse and try again.")
        }
    }

    /** The clipboard's text, read by an activity of ours that has the focus. Null: the user did not come. */
    suspend fun clipboard(context: Context): String? {
        val intent = Intent(context, DeviceAskActivity::class.java).putExtra(EXTRA_MODE, MODE_CLIPBOARD)
        val result = run(context, intent, context.getString(R.string.ask_clipboard_title, agentName(context)), context.getString(R.string.ask_clipboard_body), CLIPBOARD_WAIT_MS)
        return result?.getString(RESULT_TEXT)
    }

    /** Photos the user picks in the system picker. Empty: nothing picked, or nobody came. */
    suspend fun photos(context: Context, max: Int, why: String): List<Uri> {
        val intent = Intent(context, DeviceAskActivity::class.java).putExtra(EXTRA_MODE, MODE_PHOTOS).putExtra(EXTRA_MAX, max)
        val body = why.ifBlank { context.getString(R.string.ask_photos_body) }
        val result = run(context, intent, context.getString(R.string.ask_photos_title, agentName(context)), body, PHOTOS_WAIT_MS) ?: return emptyList()
        @Suppress("DEPRECATION")
        val uris = if (Build.VERSION.SDK_INT >= 33) result.getParcelableArrayList(RESULT_URIS, Uri::class.java) else result.getParcelableArrayList(RESULT_URIS)
        return uris.orEmpty()
    }

    /** Called by [DeviceAskActivity] with what it got; null means cancelled. */
    fun complete(request: String, result: Bundle?) {
        pending.remove(request)?.complete(result)
        NotificationManagerCompat.from(App.instance).cancel(request.hashCode())
    }

    private suspend fun run(context: Context, intent: Intent, title: String, body: String, waitMs: Long): Bundle? {
        val id = UUID.randomUUID().toString()
        val waiter = CompletableDeferred<Bundle?>()
        pending[id] = waiter
        intent.putExtra(EXTRA_REQUEST, id)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_NO_ANIMATION or Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS)
        if (App.foreground) {
            context.startActivity(intent)
        } else {
            notify(context, id, intent, title, body)
        }
        val result = withTimeoutOrNull(waitMs) { waiter.await() }
        if (result == null) {
            pending.remove(id)
            NotificationManagerCompat.from(context).cancel(id.hashCode())
        }
        return result
    }

    private fun notify(context: Context, id: String, intent: Intent, title: String, body: String) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED &&
            Build.VERSION.SDK_INT >= 33
        ) return // spelled out inline: lint's MissingPermission check follows this form
        val pi = PendingIntent.getActivity(context, id.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(context, App.CH_ATTENTION)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(ContextCompat.getColor(context, R.color.accent))
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pi)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .build()
        NotificationManagerCompat.from(context).notify(id.hashCode(), n)
    }

    private fun agentName(context: Context) = Prefs(context).agentName.ifEmpty { context.getString(R.string.app_name) }

    private const val PERMISSION_WAIT_MS = 120_000L
    private const val CLIPBOARD_WAIT_MS = 90_000L
    private const val PHOTOS_WAIT_MS = 240_000L
}
