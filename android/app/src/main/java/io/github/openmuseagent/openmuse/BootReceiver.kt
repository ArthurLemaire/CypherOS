package io.github.openmuseagent.openmuse

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Reconnect after a reboot, so approvals keep arriving without opening the app first. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) NotifyService.sync(context)
    }
}
