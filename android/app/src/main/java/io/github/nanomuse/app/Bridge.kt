package io.github.nanomuse.app

import android.webkit.JavascriptInterface

/**
 * `window.NanoMuseAndroid` inside the page. The web app uses it to know it runs in the phone
 * app (so it hides the Web Push setup, which the app replaces) and to offer the phone-side
 * settings from its own Settings screen.
 */
class Bridge(private val activity: MainActivity) {
    private val prefs = Prefs(activity)

    @JavascriptInterface
    fun version(): String = BuildConfig.VERSION_NAME

    @JavascriptInterface
    fun serverUrl(): String = prefs.serverUrl

    /** "local" when the server runs on this phone, "remote" when it is the user's computer. */
    @JavascriptInterface
    fun mode(): String = prefs.mode.ifEmpty { Prefs.MODE_REMOTE }

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

    /**
     * The agent's browser runs in this app: pull it into the take-over sheet. When the user
     * taps Done the page dispatches `nanomuse:browser-handed-back` with the thread, and the
     * web app tells the server.
     */
    @JavascriptInterface
    fun takeOverBrowser(thread: String?) {
        activity.runOnUiThread { activity.takeOverBrowser(thread ?: "") }
    }

    /** Whether this app has a browser of its own to take over (always, on Android). */
    @JavascriptInterface
    fun hasBrowser(): Boolean = true

    companion object {
        const val NAME = "NanoMuseAndroid"
    }
}
