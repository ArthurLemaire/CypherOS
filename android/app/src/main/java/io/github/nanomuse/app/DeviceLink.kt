package io.github.nanomuse.app

import android.content.Context
import android.os.Build
import android.util.Log
import android.view.WindowManager
import io.github.nanomuse.app.browser.DeviceBrowser
import io.github.nanomuse.app.gui.A11yExecutor
import io.github.nanomuse.app.gui.DeviceExecutor
import io.github.nanomuse.app.gui.MuseAccessibilityService
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
 * Two capabilities: the browser ([DeviceBrowser], always) and the screen — `screen` / `act` /
 * `task` through the [DeviceExecutor], which is there when the user has turned the
 * accessibility service on. When the service comes or goes the phone announces itself again,
 * so the server's *Phone* card and the agent's prompt follow.
 */
class DeviceLink(private val context: Context, private val send: (JSONObject) -> Unit) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val browser = DeviceBrowser.get(context)
    private val executor: DeviceExecutor = A11yExecutor(context)
    private val onServiceChange: () -> Unit = { announce() }

    init {
        MuseAccessibilityService.listeners.add(onServiceChange)
    }

    /** What to say when the socket opens. */
    fun hello(): JSONObject {
        val dm = context.resources.displayMetrics
        val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        val bounds = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) wm.maximumWindowMetrics.bounds else null
        val screenW = bounds?.width() ?: dm.widthPixels
        val screenH = bounds?.height() ?: dm.heightPixels
        val gui = executor.available
        val o = JSONObject()
            .put("kind", "device")
            .put("name", listOf(Build.MANUFACTURER, Build.MODEL).filter { it.isNotBlank() }.joinToString(" ").ifEmpty { "phone" })
            .put("platform", "android")
            .put("gui", gui)
            .put("browser", true)
            .put("capsule", true) // it shows the step and a Stop button while operated (`task` requests)
            .put("screen", JSONObject().put("width", screenW).put("height", screenH))
            .put("app", BuildConfig.VERSION_NAME)
        if (gui) o.put("apps", executor.apps())
        return o
    }

    /** Say hello again (the accessibility service was turned on or off). */
    fun announce() {
        try {
            send(hello())
        } catch (e: Exception) {
            Log.w(TAG, "announce failed: ${e.message}")
        }
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
                    "screen" -> executor.screen()
                    "act" -> executor.act(params)
                    "task" -> {
                        executor.task(params.optString("event"), params.optString("text"))
                        JSONObject().put("ok", true)
                    }
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
        MuseAccessibilityService.listeners.remove(onServiceChange)
        scope.cancel()
    }

    companion object {
        private const val TAG = "DeviceLink"
    }
}
