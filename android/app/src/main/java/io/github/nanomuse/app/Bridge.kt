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

    /**
     * Operating the phone: "on" when the accessibility service runs, "off" when it does not,
     * "unsupported" below Android 11 (no screenshots for accessibility services there).
     */
    @JavascriptInterface
    fun accessibilityState(): String = when {
        android.os.Build.VERSION.SDK_INT < android.os.Build.VERSION_CODES.R -> "unsupported"
        io.github.nanomuse.app.gui.MuseAccessibilityService.available -> "on"
        else -> "off"
    }

    /** Android's accessibility settings, where the service is switched on (and off). */
    @JavascriptInterface
    fun openAccessibilitySettings() {
        activity.runOnUiThread {
            try {
                activity.startActivity(
                    android.content.Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)
                        .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            } catch (_: Exception) {
            }
        }
    }

    /** This app's page in Android's settings — for "Allow restricted settings" on Android 13+. */
    @JavascriptInterface
    fun openAppSettings() {
        activity.runOnUiThread {
            try {
                activity.startActivity(
                    android.content.Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                        .setData(android.net.Uri.parse("package:" + activity.packageName))
                        .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            } catch (_: Exception) {
            }
        }
    }

    /**
     * What stands in the way of running in the background, as JSON: `battery_unrestricted`,
     * `overlay`, `exact_alarms` (granted · denied · n/a), `boot_start`, `vendor`,
     * `autostart_settings` (whether this phone has a page we can open), `android`, `local`.
     */
    @JavascriptInterface
    fun keepRunning(): String = KeepRunning.status(activity).toString()

    /** Open the settings page for one of them: battery, overlay, alarms, autostart, app. */
    @JavascriptInterface
    fun openKeepRunning(what: String?) {
        activity.runOnUiThread { KeepRunning.open(activity, what ?: "") }
    }

    @JavascriptInterface
    fun setStartOnBoot(on: Boolean) {
        prefs.startOnBoot = on
    }

    /** Zip the crash files, the runtime's log and the app's logcat lines; open the share sheet. */
    @JavascriptInterface
    fun exportLogs() {
        activity.runOnUiThread { Thread { Diagnostics.export(activity) }.start() }
    }

    companion object {
        const val NAME = "NanoMuseAndroid"
    }
}
