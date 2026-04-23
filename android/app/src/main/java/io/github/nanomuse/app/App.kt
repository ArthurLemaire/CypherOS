package io.github.nanomuse.app

import android.app.Activity
import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Bundle
import androidx.core.content.getSystemService
import io.github.nanomuse.app.device.DeviceHost

class App : Application() {
    private var started = 0

    override fun onCreate() {
        super.onCreate()
        instance = this
        // whether any of our activities is on screen: what the phone tools may do directly
        // (read the clipboard, open the clock app) depends on it
        registerActivityLifecycleCallbacks(object : ActivityLifecycleCallbacks {
            override fun onActivityStarted(activity: Activity) { started++; foreground = true }
            override fun onActivityStopped(activity: Activity) { started = (started - 1).coerceAtLeast(0); foreground = started > 0 }
            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
            override fun onActivityResumed(activity: Activity) = Unit
            override fun onActivityPaused(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        })
        if (BuildConfig.DEBUG && !BuildConfig.LOCAL_RUNTIME) {
            // debug builds of the connect flavour serve the phone's tools too, so the MCP server
            // can be exercised from a computer over `adb forward` (docs/device.md)
            val host = DeviceHost.start(this)
            android.util.Log.i("App", "device MCP (debug): ${host.url}/mcp token=${host.token}")
        }
        val nm = getSystemService<NotificationManager>() ?: return
        nm.createNotificationChannels(
            listOf(
                NotificationChannel(CH_ATTENTION, getString(R.string.channel_attention), NotificationManager.IMPORTANCE_HIGH).apply {
                    description = getString(R.string.channel_attention_desc)
                },
                NotificationChannel(CH_UPDATES, getString(R.string.channel_updates), NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = getString(R.string.channel_updates_desc)
                },
                NotificationChannel(CH_LINK, getString(R.string.channel_link), NotificationManager.IMPORTANCE_MIN).apply {
                    description = getString(R.string.channel_link_desc)
                    setShowBadge(false)
                },
            )
        )
    }

    companion object {
        lateinit var instance: App
            private set

        /** True while one of the app's activities is started (visible). */
        @Volatile
        var foreground: Boolean = false
            private set

        const val CH_ATTENTION = "attention"
        const val CH_UPDATES = "updates"
        const val CH_LINK = "link"
        const val USER_AGENT_SUFFIX = " NanoMuseAndroid/" + BuildConfig.VERSION_NAME
    }
}
