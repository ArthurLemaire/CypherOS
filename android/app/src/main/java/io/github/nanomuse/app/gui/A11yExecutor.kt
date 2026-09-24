package io.github.nanomuse.app.gui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.os.Build
import android.os.SystemClock
import android.os.Bundle
import android.util.Base64
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import io.github.nanomuse.app.gui.MuseAccessibilityService.Companion.recycleQuietly
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.Locale

/**
 * The GUI operator's executor on a real phone, through [MuseAccessibilityService].
 *
 * The picture the model sees is the screen scaled to at most [MAX_WIDTH] pixels wide (a
 * 1080×2400 phone becomes 720×1600) and the size it is told is that picture's; taps come back in
 * the same space and are scaled to real pixels here, so the model never converts anything. The
 * accessibility tree of the same moment goes along as `nodes`, in the same space.
 *
 * Rules that live here because only the executor can see them: it does not type into a password
 * field (the node says so; the operator's own prompt says the same, this is the backstop), and it
 * refuses everything the moment the user has pressed **Stop** on the [GuiOverlay].
 */
class A11yExecutor(private val context: Context) : DeviceExecutor {
    /** The service's overlay — its window token is the only one an accessibility overlay accepts. */
    private val overlay: GuiOverlay? get() = MuseAccessibilityService.instance?.overlay
    private var scale = 1f // real pixels per reported pixel
    private var reportedW = 0
    private var reportedH = 0
    private val labels = HashMap<String, String>()

    override val available: Boolean get() = MuseAccessibilityService.available

    private fun service(): MuseAccessibilityService = MuseAccessibilityService.instance ?: throw IllegalStateException(
        "the accessibility service is off on this phone: turn it on under Android Settings → Accessibility → nanoMuse (the Phone card in the app opens it)",
    )

    private fun checkStopped() {
        if (overlay?.isStopped == true) throw stopError()
    }

    private fun stopError() = IllegalStateException("the user pressed Stop on the phone (nanomuse:stop)")

    /** Sleeps [ms], but wakes at once when the user presses Stop. */
    private suspend fun sleepUnlessStopped(ms: Long, since: Long) {
        var left = ms
        while (left > 0) {
            val slice = minOf(left, 200L)
            delay(slice)
            left -= slice
            if (overlay?.stoppedSince(since) == true) throw stopError()
        }
    }

    // ------------------------------------------------------------------ apps

    override fun apps(): JSONArray {
        val pm = context.packageManager
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        val out = JSONArray()
        val seen = HashSet<String>()
        val list = try {
            pm.queryIntentActivities(intent, 0)
        } catch (e: Exception) {
            Log.w(TAG, "queryIntentActivities failed: ${e.message}")
            return out
        }
        val rows = list.mapNotNull { ri ->
            val pkg = ri.activityInfo?.packageName ?: return@mapNotNull null
            if (pkg == context.packageName || !seen.add(pkg)) return@mapNotNull null
            val name = ri.loadLabel(pm)?.toString()?.trim().orEmpty().ifEmpty { pkg }
            labels[pkg] = name
            pkg to name
        }.sortedBy { it.second.lowercase(Locale.ROOT) }.take(200)
        for ((pkg, name) in rows) out.put(JSONObject().put("id", pkg).put("name", name))
        return out
    }

    private fun appLabel(pkg: String): String {
        if (pkg.isEmpty()) return ""
        labels[pkg]?.let { return it }
        return try {
            val label = context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(pkg, 0)).toString()
            labels[pkg] = label
            label
        } catch (_: PackageManager.NameNotFoundException) {
            pkg
        }
    }

    // ------------------------------------------------------------------ screen

    override suspend fun screen(): JSONObject {
        checkStopped()
        val svc = service()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) throw IllegalStateException("operating the phone needs Android 11 or newer")
        val shot = svc.overlay.hiddenForCapture { svc.screenshot() }
        val dm = context.resources.displayMetrics
        val realW = shot?.width ?: dm.widthPixels
        val realH = shot?.height ?: dm.heightPixels
        scale = if (realW > MAX_WIDTH) realW.toFloat() / MAX_WIDTH else 1f
        reportedW = Math.round(realW / scale)
        reportedH = Math.round(realH / scale)
        val pkg = svc.foregroundPackage()
        val out = JSONObject()
            .put("app", pkg)
            .put("app_name", appLabel(pkg))
            .put("route", svc.activeWindowTitle())
            .put("width", reportedW)
            .put("height", reportedH)
            .put("keyboard", svc.keyboardShown())
        if (shot != null) {
            out.put("screenshot", withContext(Dispatchers.Default) { encode(shot) })
        } else {
            out.put("note", "Android gave no screenshot: the screen may be off, locked, or showing a protected (FLAG_SECURE) app")
        }
        // right after a window change the active window may have no root yet: give it a moment
        var root = svc.rootInActiveWindow
        if (root == null) {
            delay(300)
            root = svc.rootInActiveWindow
        }
        try {
            val nodes = NodeTree.dump(root, realW, realH)
            if (scale != 1f) rescale(nodes)
            out.put("nodes", nodes)
        } finally {
            root?.recycleQuietly()
        }
        return out
    }

    private fun rescale(nodes: JSONArray) {
        for (i in 0 until nodes.length()) {
            val n = nodes.getJSONObject(i)
            n.put("cx", Math.round(n.getInt("cx") / scale)).put("cy", Math.round(n.getInt("cy") / scale))
            val box = n.getJSONArray("box")
            val scaled = JSONArray()
            for (j in 0 until 4) scaled.put(Math.round(box.getInt(j) / scale))
            n.put("box", scaled)
        }
    }

    private fun encode(shot: Bitmap): String {
        val bmp = if (scale != 1f) Bitmap.createScaledBitmap(shot, reportedW, reportedH, true) else shot
        val buf = ByteArrayOutputStream(256 * 1024)
        bmp.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, buf)
        if (bmp !== shot) bmp.recycle()
        shot.recycle()
        return Base64.encodeToString(buf.toByteArray(), Base64.NO_WRAP)
    }

    // ------------------------------------------------------------------ act

    override suspend fun act(params: JSONObject): JSONObject {
        val since = SystemClock.uptimeMillis()
        checkStopped()
        val svc = service()
        val action = params.optString("action")
        val label = params.optString("label")
        if (label.isNotEmpty()) overlay?.step(label)
        val note = when (action) {
            "tap" -> {
                val (x, y) = point(params, "x", "y")
                overlay?.tapMark(x, y, 60, label)
                if (!svc.tap(x, y)) throw IllegalStateException("the tap was not delivered (another gesture in progress?)")
                ""
            }
            "double_tap" -> {
                val (x, y) = point(params, "x", "y")
                overlay?.tapMark(x, y, 60, label)
                svc.tap(x, y)
                delay(80)
                svc.tap(x, y)
                ""
            }
            "long_press" -> {
                val (x, y) = point(params, "x", "y")
                val ms = (params.optDouble("seconds", 0.8).coerceIn(0.2, 5.0) * 1000).toLong()
                overlay?.tapMark(x, y, ms, label)
                if (!svc.tap(x, y, ms)) throw IllegalStateException("the long press was not delivered")
                ""
            }
            "swipe" -> swipe(svc, params, label)
            "type" -> type(svc, params)
            "enter" -> {
                overlay?.caption(label.ifEmpty { "Enter" })
                if (!imeEnter(svc)) throw IllegalStateException("no text field has the focus, so there is nothing to press Enter in — tap the field or the button on screen")
                ""
            }
            "back", "home", "recents" -> {
                overlay?.caption(label.ifEmpty { action })
                if (!svc.systemButton(action)) throw IllegalStateException("Android did not take the $action button")
                ""
            }
            "open_app" -> openApp(svc, params.optString("app"))
            "wait" -> {
                sleepUnlessStopped((params.optDouble("seconds", 1.0).coerceIn(0.2, 10.0) * 1000).toLong(), since)
                ""
            }
            else -> throw IllegalArgumentException("this phone cannot do '$action'")
        }
        svc.awaitIdle(quietMs = 450, maxMs = 3000)
        delay(150)
        // Stop pressed while this step ran: the step fails, whatever it did
        if (overlay?.stoppedSince(since) == true) throw stopError()
        return JSONObject().put("note", note).put("screen", screen())
    }

    private fun point(p: JSONObject, kx: String, ky: String): Pair<Float, Float> {
        if (!p.has(kx) || !p.has(ky)) throw IllegalArgumentException("`${p.optString("action")}` needs `$kx` and `$ky`")
        val x = (p.getDouble(kx) * scale).toFloat()
        val y = (p.getDouble(ky) * scale).toFloat()
        val dm = context.resources.displayMetrics
        return x.coerceIn(0f, dm.widthPixels - 1f) to y.coerceIn(0f, dm.heightPixels - 1f)
    }

    private suspend fun swipe(svc: MuseAccessibilityService, p: JSONObject, label: String): String {
        val dm = context.resources.displayMetrics
        val w = dm.widthPixels.toFloat()
        val h = dm.heightPixels.toFloat()
        val x: Float
        val y: Float
        val x2: Float
        val y2: Float
        if (p.has("direction")) {
            val d = (p.optDouble("distance", 0.5)).coerceIn(0.1, 0.9).toFloat()
            val start = if (p.has("x") && p.has("y")) point(p, "x", "y") else (w / 2 to h / 2)
            x = start.first
            y = start.second
            when (p.getString("direction")) {
                "up" -> { x2 = x; y2 = (y - h * d).coerceAtLeast(h * 0.05f) }
                "down" -> { x2 = x; y2 = (y + h * d).coerceAtMost(h * 0.95f) }
                "left" -> { x2 = (x - w * d).coerceAtLeast(w * 0.05f); y2 = y }
                "right" -> { x2 = (x + w * d).coerceAtMost(w * 0.95f); y2 = y }
                else -> throw IllegalArgumentException("direction must be up, down, left or right")
            }
        } else {
            val a = point(p, "x", "y")
            val b = point(p, "x2", "y2")
            x = a.first; y = a.second; x2 = b.first; y2 = b.second
        }
        overlay?.swipeMark(x, y, x2, y2, 320, label.ifEmpty { "swipe" })
        if (!svc.swipe(x, y, x2, y2)) throw IllegalStateException("the swipe was not delivered")
        return ""
    }

    private suspend fun type(svc: MuseAccessibilityService, p: JSONObject): String {
        val text = p.optString("text")
        if (p.has("x") && p.has("y")) {
            val (x, y) = point(p, "x", "y")
            svc.tap(x, y)
            svc.awaitIdle(300, 1200)
        }
        val node = svc.focusedInput() ?: throw IllegalStateException("no text field has the focus: tap the field first, then type")
        try {
            if (node.isPassword) {
                throw IllegalStateException("that is a password field; nanoMuse does not type passwords, PINs or codes — ask the user to enter it")
            }
            // an empty field reports its hint as its text; that is not text to keep
            val existing = if (node.isShowingHintText) "" else node.text?.toString().orEmpty()
            val wanted = if (p.optBoolean("clear")) text else existing + text
            overlay?.typeMark(text)
            var ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, Bundle().apply {
                putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, wanted)
            })
            var how = "set"
            if (!ok) {
                // a field that takes no SET_TEXT (some web views, custom editors): paste instead
                val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("nanoMuse", text))
                ok = node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
                how = "pasted"
            }
            if (!ok) throw IllegalStateException("the field did not take the text (neither set nor paste worked)")
            var note = "typed ${text.length} characters ($how)"
            if (p.optBoolean("submit")) {
                delay(120)
                note += if (imeEnter(svc)) ", pressed Enter" else ", but Enter could not be pressed here — tap the button on screen"
            }
            return note
        } finally {
            node.recycleQuietly()
        }
    }

    private fun imeEnter(svc: MuseAccessibilityService): Boolean {
        val node = svc.focusedInput() ?: return false
        try {
            return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
            } else {
                false
            }
        } finally {
            node.recycleQuietly()
        }
    }

    private suspend fun openApp(svc: MuseAccessibilityService, wanted: String): String {
        if (wanted.isBlank()) throw IllegalArgumentException("`open_app` needs `app`")
        val pm = context.packageManager
        val low = wanted.trim().lowercase(Locale.ROOT)
        if (labels.isEmpty()) apps()
        val pkg = labels.entries.firstOrNull { it.key.lowercase(Locale.ROOT) == low || it.value.lowercase(Locale.ROOT) == low }?.key
            ?: labels.entries.firstOrNull { it.value.lowercase(Locale.ROOT).contains(low) || low.contains(it.value.lowercase(Locale.ROOT)) }?.key
            ?: (if (wanted.contains('.')) wanted.trim() else null)
            ?: throw IllegalArgumentException("no app called '$wanted' on this phone")
        val intent = pm.getLaunchIntentForPackage(pkg) ?: throw IllegalArgumentException("'$wanted' ($pkg) has nothing to open")
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        overlay?.caption("open ${appLabel(pkg)}")
        try {
            context.startActivity(intent)
        } catch (e: Exception) {
            throw IllegalStateException("could not open ${appLabel(pkg)}: ${e.message}")
        }
        // Android may silently refuse an activity start from the background; check what is on top
        for (i in 0 until 12) {
            delay(250)
            if (svc.foregroundPackage() == pkg) return "opened ${appLabel(pkg)}"
        }
        return "asked Android to open ${appLabel(pkg)}, but it is not in front yet — if the screen shows another app, press Home and tap its icon"
    }

    // ------------------------------------------------------------------ task events

    override fun task(event: String, text: String) {
        val o = overlay ?: return
        when (event) {
            "begin" -> o.show(text)
            "end" -> o.hide()
            "notice" -> o.notice(text)
        }
    }

    companion object {
        private const val TAG = "A11yExecutor"
        private const val MAX_WIDTH = 720
        private const val JPEG_QUALITY = 72
    }
}
