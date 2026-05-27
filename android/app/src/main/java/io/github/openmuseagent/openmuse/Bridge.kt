package io.github.openmuseagent.openmuse

import android.webkit.JavascriptInterface

/**
 * `window.OpenMuseAndroid` inside the page. The web app uses it to know it runs in the phone
 * app (so it hides the Web Push setup, which the app replaces) and to offer the phone-side
 * settings from its own Settings screen.
 */
class Bridge(private val activity: MainActivity) {
    private val prefs = Prefs(activity)

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    @JavascriptInterface
    fun serverUrl(): String = prefs.serverUrl

    /** Whether the background connection (and with it, notifications) is on. */
    @JavascriptInterface
    fun notificationsEnabled(): Boolean = prefs.notify

    @JavascriptInterface
    fun setNotificationsEnabled(on: Boolean) {
        prefs.notify = on
        activity.runOnUiThread { NotifyService.sync(activity) }
    }

    /** Forget this server and return to the Connect screen. */
    @JavascriptInterface
    fun disconnect() {
        activity.runOnUiThread { activity.forget() }
    }

    companion object {
        const val NAME = "OpenMuseAndroid"
    }
}
