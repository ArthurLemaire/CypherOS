package io.github.nanomuse.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import io.github.nanomuse.app.runtime.RuntimeService

/**
 * After a reboot: reconnect to the computer so approvals keep arriving, or bring the phone's
 * own server back so routines and check-ins run, without the app being opened first.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = Prefs(context)
        if (prefs.isLocal && prefs.connected) RuntimeService.start(context) else NotifyService.sync(context)
    }
}
