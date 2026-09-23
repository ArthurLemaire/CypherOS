package io.github.openmuseagent.openmuse

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import androidx.core.content.getSystemService

class App : Application() {
    override fun onCreate() {
        super.onCreate()
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
        const val CH_ATTENTION = "attention"
        const val CH_UPDATES = "updates"
        const val CH_LINK = "link"
        const val USER_AGENT_SUFFIX = " OpenMuseAndroid/" + BuildConfig.VERSION_NAME
    }
}
