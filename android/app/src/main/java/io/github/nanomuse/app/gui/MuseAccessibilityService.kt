package io.github.nanomuse.app.gui

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import androidx.annotation.RequiresApi
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import java.util.concurrent.CopyOnWriteArraySet
import kotlin.coroutines.resume

/**
 * The hands and eyes of the GUI operator on a real phone: Android's accessibility service.
 *
 * It does four things and nothing else — a picture of the screen (`takeScreenshot`, Android 11+),
 * gestures (`dispatchGesture`), the system buttons (`performGlobalAction`) and a look at the
 * window tree for the keyboard, the focused field and the [NodeTree]. It never acts on its own:
 * every gesture is a request from the server, made through [A11yExecutor] after the Sentinel.
 *
 * The user turns it on in Android's accessibility settings (the *Phone* card in the app opens
 * them); Android may switch it off again after an update or when the app is force-stopped, and
 * the app announces the change to the server either way ([listeners]).
 */
class MuseAccessibilityService : AccessibilityService() {
    @Volatile private var lastEventAt = 0L
    @Volatile private var lastEventPackage: CharSequence? = null

    /**
     * The marks and the capsule. Owned here because a `TYPE_ACCESSIBILITY_OVERLAY` window is only
     * valid with the service's own window token — created on the application context it fails
     * with "token null is not valid".
     */
    val overlay: GuiOverlay by lazy { GuiOverlay(this) { Log.i(TAG, "the user pressed Stop") } }

    override fun onServiceConnected() {
        super.onServiceConnected()
        instance = this
        Log.i(TAG, "accessibility service connected")
        notifyChange()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        lastEventAt = SystemClock.uptimeMillis()
        event?.packageName?.let { lastEventPackage = it }
    }

    override fun onInterrupt() = Unit

    override fun onUnbind(intent: android.content.Intent?): Boolean {
        if (instance === this) instance = null
        Log.i(TAG, "accessibility service unbound")
        try {
            overlay.hide()
        } catch (_: Exception) {
        }
        notifyChange()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        notifyChange()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ looking

    /** The package on top, from the active window (or the last event when there is none). */
    fun foregroundPackage(): String {
        val root = rootInActiveWindow
        val pkg = root?.packageName ?: lastEventPackage
        root?.recycleQuietly()
        return pkg?.toString() ?: ""
    }

    /** Whether an input method window is showing. */
    fun keyboardShown(): Boolean = try {
        windows.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }
    } catch (_: Exception) {
        false
    }

    /** The active window's title, when the app set one (an activity's label, a dialog's title). */
    fun activeWindowTitle(): String = try {
        windows.firstOrNull { it.isActive }?.title?.toString() ?: ""
    } catch (_: Exception) {
        ""
    }

    /**
     * A picture of the whole screen. Null when Android refuses (a protected screen, or the display
     * is off). Android allows one screenshot per ~330 ms; two steps back to back hit that limit,
     * so the interval error is waited out and tried again.
     */
    @RequiresApi(Build.VERSION_CODES.R)
    suspend fun screenshot(): Bitmap? {
        repeat(3) { attempt ->
            val (bitmap, code) = screenshotOnce()
            if (bitmap != null) return bitmap
            if (code != ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT || attempt == 2) {
                Log.w(TAG, "takeScreenshot failed: $code")
                return null
            }
            delay(400)
        }
        return null
    }

    @RequiresApi(Build.VERSION_CODES.R)
    private suspend fun screenshotOnce(): Pair<Bitmap?, Int> = suspendCancellableCoroutine { cont ->
        try {
            takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
                override fun onSuccess(result: ScreenshotResult) {
                    val hw = result.hardwareBuffer
                    val bmp = try {
                        Bitmap.wrapHardwareBuffer(hw, result.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                    } finally {
                        hw.close()
                    }
                    if (cont.isActive) cont.resume(bmp to 0)
                }

                override fun onFailure(errorCode: Int) {
                    if (cont.isActive) cont.resume(null to errorCode)
                }
            })
        } catch (e: Exception) {
            Log.w(TAG, "takeScreenshot threw", e)
            if (cont.isActive) cont.resume(null to ERROR_TAKE_SCREENSHOT_INTERNAL_ERROR)
        }
    }

    /** The field with input focus, if any (recycle it). */
    fun focusedInput(): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        val focus = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
        if (focus == null || focus.isEditable) {
            if (focus !== root) root.recycleQuietly()
            return focus
        }
        focus.recycleQuietly()
        root.recycleQuietly()
        return null
    }

    // ------------------------------------------------------------------ acting

    /** A finger down at (x, y) for [holdMs], then up. */
    suspend fun tap(x: Float, y: Float, holdMs: Long = 60): Boolean {
        val path = Path().apply { moveTo(x, y) }
        return gesture(GestureDescription.StrokeDescription(path, 0, holdMs))
    }

    /** A finger from (x, y) to (x2, y2) over [durationMs]. */
    suspend fun swipe(x: Float, y: Float, x2: Float, y2: Float, durationMs: Long = 320): Boolean {
        val path = Path().apply { moveTo(x, y); lineTo(x2, y2) }
        return gesture(GestureDescription.StrokeDescription(path, 0, durationMs))
    }

    private suspend fun gesture(stroke: GestureDescription.StrokeDescription): Boolean = suspendCancellableCoroutine { cont ->
        val ok = dispatchGesture(
            GestureDescription.Builder().addStroke(stroke).build(),
            object : GestureResultCallback() {
                override fun onCompleted(gestureDescription: GestureDescription?) {
                    if (cont.isActive) cont.resume(true)
                }

                override fun onCancelled(gestureDescription: GestureDescription?) {
                    if (cont.isActive) cont.resume(false)
                }
            },
            null,
        )
        if (!ok && cont.isActive) cont.resume(false)
    }

    /** Back, Home or Recents. */
    fun systemButton(which: String): Boolean = when (which) {
        "back" -> performGlobalAction(GLOBAL_ACTION_BACK)
        "home" -> performGlobalAction(GLOBAL_ACTION_HOME)
        "recents" -> performGlobalAction(GLOBAL_ACTION_RECENTS)
        else -> false
    }

    /**
     * Wait until the screen has been quiet for [quietMs] (no accessibility events), or [maxMs]
     * at most: what "the UI has settled" means here. A screen that never stops animating (a
     * video, a spinner) ends the wait at [maxMs].
     */
    suspend fun awaitIdle(quietMs: Long = 400, maxMs: Long = 2500) {
        val start = SystemClock.uptimeMillis()
        while (true) {
            val now = SystemClock.uptimeMillis()
            val sinceEvent = now - lastEventAt
            if (sinceEvent >= quietMs || now - start >= maxMs) return
            delay(minOf(quietMs - sinceEvent, maxMs - (now - start)).coerceAtLeast(30))
        }
    }

    private fun notifyChange() {
        for (l in listeners) {
            try {
                l()
            } catch (e: Exception) {
                Log.w(TAG, "listener failed", e)
            }
        }
    }

    companion object {
        private const val TAG = "MuseA11y"

        /** The running service, or null when the user has not turned it on (or Android stopped it). */
        @Volatile var instance: MuseAccessibilityService? = null
            private set

        /** Called (on the main thread) whenever the service comes or goes. */
        val listeners = CopyOnWriteArraySet<() -> Unit>()

        /** Whether the operator can work on this phone right now. */
        val available: Boolean get() = instance != null && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R

        fun AccessibilityNodeInfo.recycleQuietly() {
            // recycle() is a no-op from API 34 on and deprecated; harmless before
            @Suppress("DEPRECATION")
            try {
                if (Build.VERSION.SDK_INT < 34) recycle()
            } catch (_: Exception) {
            }
        }
    }
}
