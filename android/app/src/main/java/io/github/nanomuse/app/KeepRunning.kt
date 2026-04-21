package io.github.nanomuse.app

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.getSystemService
import io.github.nanomuse.app.runtime.WakeAlarms
import org.json.JSONObject

/**
 * What stands between the agent and running in the background on this phone, and the settings
 * pages that fix it. Android itself has three switches — battery optimisation, *display over
 * other apps*, *alarms & reminders* — and the Chinese vendors add their own (auto-start, a
 * background pop-up permission, an aggressive battery manager) that kill or silence a service
 * Android would keep. The web app shows the status and the buttons under *Settings → Keep it
 * running*; the vendor advice lives with it (and in docs/android.md).
 *
 * Nothing here is requested on the app's own initiative: every button is the user's.
 */
object KeepRunning {
    /** The vendor, as far as its background policy goes: xiaomi, huawei, honor, oppo, vivo, samsung, meizu, or "". */
    fun vendor(manufacturer: String = Build.MANUFACTURER, brand: String = Build.BRAND): String {
        val m = manufacturer.lowercase()
        val b = brand.lowercase()
        return when {
            m.contains("xiaomi") || b in setOf("xiaomi", "redmi", "poco") -> "xiaomi"
            m.contains("huawei") -> "huawei"
            m.contains("honor") || b == "honor" -> "honor"
            m.contains("oppo") || m.contains("realme") || m.contains("oneplus") || b in setOf("oppo", "realme", "oneplus") -> "oppo"
            m.contains("vivo") || b in setOf("vivo", "iqoo") -> "vivo"
            m.contains("samsung") -> "samsung"
            m.contains("meizu") -> "meizu"
            else -> ""
        }
    }

    fun batteryUnrestricted(context: Context): Boolean =
        context.getSystemService<PowerManager>()?.isIgnoringBatteryOptimizations(context.packageName) == true

    fun overlayAllowed(context: Context): Boolean = Settings.canDrawOverlays(context)

    /** "granted", "denied", or "n/a" below Android 12 where no permission is needed. */
    fun exactAlarms(context: Context): String = when {
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S -> "n/a"
        WakeAlarms.exactAllowed(context) -> "granted"
        else -> "denied"
    }

    /** The vendor's auto-start / background manager page, when this phone has one we know. */
    fun autostartIntent(context: Context): Intent? {
        val pm = context.packageManager
        for (name in AUTOSTART_ACTIVITIES[vendor()].orEmpty()) {
            val intent = Intent().setComponent(ComponentName.unflattenFromString(name) ?: continue)
            if (pm.resolveActivity(intent, 0) != null) return intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        return null
    }

    /** Everything the settings section shows, as one object for the bridge. */
    fun status(context: Context): JSONObject = JSONObject()
        .put("battery_unrestricted", batteryUnrestricted(context))
        .put("overlay", overlayAllowed(context))
        .put("exact_alarms", exactAlarms(context))
        .put("boot_start", Prefs(context).startOnBoot)
        .put("vendor", vendor())
        .put("autostart_settings", autostartIntent(context) != null)
        .put("android", Build.VERSION.SDK_INT)
        .put("local", BuildConfig.LOCAL_RUNTIME && Prefs(context).isLocal)

    /** Open the settings page for [what]: battery, overlay, alarms, autostart, app. */
    fun open(context: Context, what: String): Boolean {
        val pkg = Uri.parse("package:" + context.packageName)
        val intent = when (what) {
            "battery" -> Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).setData(pkg)
            "overlay" -> Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION).setData(pkg)
            "alarms" -> if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM).setData(pkg)
            } else {
                return false
            }
            "autostart" -> autostartIntent(context) ?: return false
            "app" -> Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).setData(pkg)
            else -> return false
        }
        return try {
            context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (_: Exception) {
            // the battery page is missing on a few builds: the app's own page has it too
            if (what == "battery") open(context, "app") else false
        }
    }

    // The well-known auto-start managers, first the current name, then older ones. The list
    // is the one every background-heavy app carries (see dontkillmyapp.com); a page that is
    // not there is simply skipped.
    private val AUTOSTART_ACTIVITIES = mapOf(
        "xiaomi" to listOf(
            "com.miui.securitycenter/com.miui.permcenter.autostart.AutoStartManagementActivity",
            "com.miui.securitycenter/com.miui.powercenter.PowerSettings",
        ),
        "huawei" to listOf(
            "com.huawei.systemmanager/.startupmgr.ui.StartupNormalAppListActivity",
            "com.huawei.systemmanager/.appcontrol.activity.StartupAppControlActivity",
            "com.huawei.systemmanager/.optimize.process.ProtectActivity",
        ),
        "honor" to listOf(
            "com.hihonor.systemmanager/.startupmgr.ui.StartupNormalAppListActivity",
            "com.huawei.systemmanager/.startupmgr.ui.StartupNormalAppListActivity",
        ),
        "oppo" to listOf(
            "com.coloros.safecenter/.startupapp.StartupAppListActivity",
            "com.coloros.safecenter/.permission.startup.StartupAppListActivity",
            "com.oppo.safe/.permission.startup.StartupAppListActivity",
            "com.coloros.oppoguardelf/com.coloros.powermanager.fuelgaue.PowerUsageModelActivity",
        ),
        "vivo" to listOf(
            "com.vivo.permissionmanager/.activity.BgStartUpManagerActivity",
            "com.iqoo.secure/.ui.phoneoptimize.BgStartUpManager",
            "com.iqoo.secure/.safeguard.PurviewTabActivity",
        ),
        "samsung" to listOf(
            "com.samsung.android.lool/com.samsung.android.sm.battery.ui.BatteryActivity",
            "com.samsung.android.lool/com.samsung.android.sm.ui.battery.BatteryActivity",
        ),
        "meizu" to listOf(
            "com.meizu.safe/.permission.SmartBGActivity",
            "com.meizu.safe/.permission.PermissionMainActivity",
        ),
    )
}
