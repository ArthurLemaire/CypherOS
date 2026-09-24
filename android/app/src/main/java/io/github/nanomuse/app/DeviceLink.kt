package io.github.nanomuse.app

import android.content.Context
import android.os.Build
import android.util.Log
import io.github.nanomuse.app.browser.DeviceBrowser
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * The phone as a device the server may ask things of, over the same WebSocket the
 * notifications use. On connect it announces what it can do (`kind: device`); each
 * `device_request` gets exactly one `device_result`. See `nanomuse/phone/link.py`.
 *
 * Today the one capability is the browser ([DeviceBrowser]); the screen and the phone's
 * own tools join here later.
 */
class DeviceLink(private val context: Context, private val send: (JSONObject) -> Unit) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val browser = DeviceBrowser.get(context)

    /** What to say when the socket opens. */
    fun hello(): JSONObject {
        val dm = context.resources.displayMetrics
        return JSONObject()
            .put("kind", "device")
            .put("name", listOf(Build.MANUFACTURER, Build.MODEL).filter { it.isNotBlank() }.joinToString(" ").ifEmpty { "phone" })
            .put("platform", "android")
            .put("gui", false)
            .put("browser", true)
            .put("screen", JSONObject().put("width", dm.widthPixels).put("height", dm.heightPixels))
            .put("app", BuildConfig.VERSION_NAME)
    }

    /** Handle a message if it is for us. Returns true when it was. */
    fun handle(msg: JSONObject): Boolean {
        if (msg.optString("kind") != "device_request") return false
        val id = msg.optString("id")
        val op = msg.optString("op")
        val params = msg.optJSONObject("params") ?: JSONObject()
        scope.launch {
            val reply = JSONObject().put("kind", "device_result").put("id", id)
            try {
                val result = when (op) {
                    "browser" -> browser.handle(params.optString("op"), params)
                    else -> throw IllegalArgumentException("this phone cannot do '$op'")
                }
                reply.put("ok", true).put("result", result)
            } catch (e: Exception) {
                Log.w(TAG, "device request $op failed: ${e.message}")
                reply.put("ok", false).put("error", e.message ?: e.javaClass.simpleName)
            }
            send(reply)
        }
        return true
    }

    fun close() {
        scope.cancel()
    }

    companion object {
        private const val TAG = "DeviceLink"
    }
}
