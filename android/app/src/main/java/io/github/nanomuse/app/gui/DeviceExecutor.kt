package io.github.nanomuse.app.gui

import org.json.JSONArray
import org.json.JSONObject

/**
 * What a phone must do for the GUI operator — the `screen` and `act` operations of the device
 * protocol (docs/gui.md, "The device protocol"), plus the apps it can open and a channel for the
 * server to say a task begins, ends or needs the user.
 *
 * One implementation ships: [A11yExecutor], on Android's accessibility service. Others (Shizuku
 * / wireless adb, a bundled input method) would plug in here; the protocol above does not change.
 */
interface DeviceExecutor {
    /** Whether the operator can work right now (the service is on, the Android version allows it). */
    val available: Boolean

    /** `[{"id": "com.tencent.mm", "name": "微信"}, …]`: what `open_app` may name. */
    fun apps(): JSONArray

    /** The current screen: screenshot, app, size, keyboard, nodes. */
    suspend fun screen(): JSONObject

    /** One action, then the screen as it looks afterwards: `{"note": …, "screen": {…}}`. */
    suspend fun act(params: JSONObject): JSONObject

    /** `begin` / `end` of a task (with its goal), or a `notice` the user should see on the operated screen. */
    fun task(event: String, text: String)
}
