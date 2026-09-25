package io.github.nanomuse.hands

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import com.openminis.app.logging.AppLogger
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.sin

/**
 * What the user sees while the hands work, drawn on one full-screen window that never takes a
 * touch (`FLAG_NOT_TOUCHABLE`, so neither a finger nor an injected gesture can land on it): a
 * glow breathing along the screen's edges for as long as the run is on — blue while the hands
 * work, amber while they wait for the user — and, at the point the model chose, a dashed ring
 * turning once a second with a dot at its centre and the action's name beside it, a moment
 * before the finger lands so the eye gets there first, then a ripple as it lands. A long press
 * fills a second ring for as long as it is held; a swipe sends the ring along its path with a
 * trail and an arrow. Actions without a place — typing, Enter, Back — write their name where
 * the last ring was.
 *
 * The look follows UI-TARS-desktop's ScreenMarker (bytedance/UI-TARS-desktop,
 * `apps/ui-tars/src/main/window/ScreenMarker.ts` and `main/shared/setOfMarks.ts`, Apache-2.0):
 * its blue "water flow" breathing around the screen (a 5 s cycle, scale 1 → 1.05 → 1) and its
 * red circle — radius 16, stroke 3, dashes 80/20, one turn a second — with the action written
 * to its right. That code is Electron, CSS and SVG; this is the same picture on an Android
 * Canvas.
 *
 * Hidden, like the capsule, for the instant a screenshot is taken, so the model never sees any
 * of it. Every call is safe from any thread.
 */
class HandsStage(private val context: Context) {
    enum class Mood { WORKING, WAITING }

    private val main = Handler(Looper.getMainLooper())
    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var view: StageView? = null

    /** Adds the window (below anything added after it) and returns once it is there. */
    fun show() {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            runCatching { ensure() }.onFailure { AppLogger.warning(TAG, "stage: ${it.message}") }
            return
        }
        val latch = CountDownLatch(1)
        main.post {
            try {
                ensure()
            } catch (t: Throwable) {
                AppLogger.warning(TAG, "stage: ${t.message}")
            } finally {
                latch.countDown()
            }
        }
        latch.await(500, TimeUnit.MILLISECONDS)
    }

    fun hide() = onMain {
        view?.let { v -> runCatching { wm.removeView(v) } }
        view = null
    }

    /** Invisible for a screenshot (the marker is dropped too — it belonged to the step just done). */
    fun setVisible(visible: Boolean) = onMain {
        val v = view ?: return@onMain
        if (!visible) v.clearMarks()
        v.visibility = if (visible) View.VISIBLE else View.INVISIBLE
    }

    fun mood(m: Mood) = onMain { view?.mood = m }

    /** The ring locks on to ([x], [y]) with [label] beside it. */
    fun aim(x: Int, y: Int, label: String) = onMain { view?.aim(x.toFloat(), y.toFloat(), label) }

    /** A second ring fills over [holdMs] — the finger is being held down. */
    fun hold(holdMs: Long) = onMain { view?.hold(holdMs) }

    /** The finger landed at ([x], [y]). */
    fun ripple(x: Int, y: Int) = onMain { view?.ripple(x.toFloat(), y.toFloat()) }

    /** After [delayMs], the ring travels from ([x1], [y1]) to ([x2], [y2]) over [durationMs]. */
    fun sweep(x1: Int, y1: Int, x2: Int, y2: Int, delayMs: Long, durationMs: Long, label: String) = onMain {
        view?.sweep(x1.toFloat(), y1.toFloat(), x2.toFloat(), y2.toFloat(), delayMs, durationMs, label)
    }

    /** An action with no place on the screen: its name, where the last ring was. */
    fun say(label: String) = onMain { view?.say(label) }

    fun clear() = onMain { view?.clearMarks() }

    // ── window ─────────────────────────────────────────────────────────────

    private fun onMain(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) runCatching(block).onFailure { AppLogger.warning(TAG, "stage: ${it.message}") }
        else main.post { runCatching(block).onFailure { AppLogger.warning(TAG, "stage: ${it.message}") } }
    }

    private fun ensure() {
        if (view != null) return
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = 0
            y = 0
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                fitInsetsTypes = 0
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        val v = StageView(context)
        try {
            wm.addView(v, params)
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "addView failed: ${t.message}")
            return
        }
        view = v
    }

    // ── drawing ────────────────────────────────────────────────────────────

    private class StageView(context: Context) : View(context) {
        var mood: Mood = Mood.WORKING
            set(value) { field = value; postInvalidateOnAnimation() }

        private fun dp(v: Float): Float = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics)
        private fun sp(v: Float): Float = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, v, resources.displayMetrics)

        private val born = SystemClock.uptimeMillis()
        private val loc = IntArray(2)

        // The glow: four bands, one per edge, drawn with the colour at the edge fading out at
        // half the band (UI-TARS: `linear-gradient(..., transparent 50%)` over a 10% band).
        private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG)
        private var glowW = 0
        private var glowH = 0
        private var glowColor = 0
        private var glowShaders: Array<Shader>? = null

        // The ring and what goes with it.
        private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
            strokeWidth = dp(2.5f)
        }
        private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
        private val trailPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
            strokeWidth = dp(3f)
        }
        private val chipPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = CHIP_BG }
        private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            color = Color.WHITE
            textSize = sp(12.5f)
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        }
        private val arc = RectF()
        private val chipRect = RectF()
        private val arrow = Path()

        private class Mark(val x: Float, val y: Float, val label: String, val at: Long) {
            var holdMs: Long = 0L
            var holdFrom: Long = 0L
        }
        private class Ripple(val x: Float, val y: Float, val at: Long)
        private class Sweep(val x1: Float, val y1: Float, val x2: Float, val y2: Float, val at: Long, val delay: Long, val duration: Long, val label: String)
        private class Chip(val text: String, val x: Float, val y: Float, val at: Long)

        private var mark: Mark? = null
        private val ripples = ArrayList<Ripple>(4)
        private var sweep: Sweep? = null
        private var chip: Chip? = null
        private var lastX = -1f
        private var lastY = -1f

        fun aim(x: Float, y: Float, label: String) {
            mark = Mark(x, y, label, SystemClock.uptimeMillis())
            sweep = null; chip = null
            lastX = x; lastY = y
            postInvalidateOnAnimation()
        }

        fun hold(holdMs: Long) {
            mark?.let { it.holdMs = holdMs; it.holdFrom = SystemClock.uptimeMillis() }
            postInvalidateOnAnimation()
        }

        fun ripple(x: Float, y: Float) {
            ripples += Ripple(x, y, SystemClock.uptimeMillis())
            postInvalidateOnAnimation()
        }

        fun sweep(x1: Float, y1: Float, x2: Float, y2: Float, delay: Long, duration: Long, label: String) {
            sweep = Sweep(x1, y1, x2, y2, SystemClock.uptimeMillis(), delay, duration, label)
            mark = null; chip = null
            lastX = x2; lastY = y2
            postInvalidateOnAnimation()
        }

        fun say(label: String) {
            val x = if (lastX >= 0) lastX else width / 2f
            val y = if (lastY >= 0) lastY else height * 0.42f
            chip = Chip(label, x, y, SystemClock.uptimeMillis())
            mark = null; sweep = null
            postInvalidateOnAnimation()
        }

        fun clearMarks() {
            mark = null; sweep = null; chip = null; ripples.clear()
            postInvalidateOnAnimation()
        }

        override fun onDraw(canvas: Canvas) {
            val now = SystemClock.uptimeMillis()
            drawGlow(canvas, now)
            // Screen pixels (the model's coordinates) → this window's pixels.
            getLocationOnScreen(loc)
            canvas.save()
            canvas.translate(-loc[0].toFloat(), -loc[1].toFloat())
            sweep?.let { drawSweep(canvas, it, now) }
            mark?.let { drawMark(canvas, it, now) }
            drawRipples(canvas, now)
            chip?.let { drawChip(canvas, it, now) }
            canvas.restore()
            if (visibility == VISIBLE) postInvalidateOnAnimation() // the glow breathes for as long as we are shown
        }

        // ── the glow ──

        private fun drawGlow(canvas: Canvas, now: Long) {
            val w = width; val h = height
            if (w == 0 || h == 0) return
            val color = if (mood == Mood.WORKING) GLOW_WORKING else GLOW_WAITING
            if (glowShaders == null || glowW != w || glowH != h || glowColor != color) {
                val band = min(w, h) * GLOW_BAND
                val clear = color and 0x00FFFFFF
                val mid = band * 0.5f
                glowShaders = arrayOf(
                    LinearGradient(0f, 0f, mid, 0f, color, clear, Shader.TileMode.CLAMP),                   // left
                    LinearGradient(w.toFloat(), 0f, w - mid, 0f, color, clear, Shader.TileMode.CLAMP),      // right
                    LinearGradient(0f, 0f, 0f, mid, color, clear, Shader.TileMode.CLAMP),                   // top
                    LinearGradient(0f, h.toFloat(), 0f, h - mid, color, clear, Shader.TileMode.CLAMP),      // bottom
                )
                glowW = w; glowH = h; glowColor = color
            }
            // UI-TARS: a 5 s cycle, scale 1 → 1.03 → 1.05 → 1.03 → 1 with the alpha easing down
            // a little at the peak. Scaling about the centre pushes the bands outward, so the
            // glow thins as it "exhales".
            val t = ((now - born) % GLOW_CYCLE_MS) / GLOW_CYCLE_MS.toFloat()
            val breathe = (1f - cos(2.0 * Math.PI * t).toFloat()) / 2f
            val scale = 1f + 0.05f * breathe
            glowPaint.alpha = (255 * (1f - 0.08f * breathe)).toInt()
            val shaders = glowShaders ?: return
            val band = min(w, h) * GLOW_BAND
            canvas.save()
            canvas.scale(scale, scale, w / 2f, h / 2f)
            glowPaint.shader = shaders[0]; canvas.drawRect(0f, 0f, band, h.toFloat(), glowPaint)
            glowPaint.shader = shaders[1]; canvas.drawRect(w - band, 0f, w.toFloat(), h.toFloat(), glowPaint)
            glowPaint.shader = shaders[2]; canvas.drawRect(0f, 0f, w.toFloat(), band, glowPaint)
            glowPaint.shader = shaders[3]; canvas.drawRect(0f, h - band, w.toFloat(), h.toFloat(), glowPaint)
            canvas.restore()
            glowPaint.shader = null
        }

        // ── the ring ──

        private fun drawMark(canvas: Canvas, m: Mark, now: Long): Boolean {
            val age = now - m.at
            // Lock-on: from 1.8× and clear to 1× and solid in 220 ms.
            val p = (age / LOCK_ON_MS.toFloat()).coerceIn(0f, 1f)
            val eased = 1f - (1f - p) * (1f - p)
            val scale = 1.8f - 0.8f * eased
            val alpha = (255 * eased).toInt()
            val r = dp(RING_DP) * scale
            // One turn a second, 80 % arc + 20 % gap, like UI-TARS's dasharray 80/20.
            val rotation = (age % 1000L) / 1000f * 360f
            ringPaint.color = RING
            ringPaint.alpha = alpha
            arc.set(m.x - r, m.y - r, m.x + r, m.y + r)
            canvas.drawArc(arc, rotation, 288f, false, ringPaint)
            fillPaint.color = RING
            fillPaint.alpha = alpha
            canvas.drawCircle(m.x, m.y, dp(3f), fillPaint)
            // A held finger: a thin ring filling clockwise for the length of the hold.
            if (m.holdMs > 0) {
                val hp = ((now - m.holdFrom) / m.holdMs.toFloat()).coerceIn(0f, 1f)
                val hr = r + dp(7f)
                ringPaint.strokeWidth = dp(1.5f)
                ringPaint.alpha = (alpha * 0.9f).toInt()
                arc.set(m.x - hr, m.y - hr, m.x + hr, m.y + hr)
                canvas.drawArc(arc, -90f, 360f * hp, false, ringPaint)
                ringPaint.strokeWidth = dp(2.5f)
            }
            if (m.label.isNotBlank()) drawLabel(canvas, m.label, m.x, m.y, r + dp(10f), alpha)
            return true
        }

        private fun drawRipples(canvas: Canvas, now: Long): Boolean {
            if (ripples.isEmpty()) return false
            val it = ripples.iterator()
            while (it.hasNext()) {
                val rp = it.next()
                val p = (now - rp.at) / RIPPLE_MS.toFloat()
                if (p >= 1f) { it.remove(); continue }
                val r = dp(RING_DP) * (1f + 1.6f * p)
                ringPaint.color = RING
                ringPaint.alpha = (230 * (1f - p)).toInt()
                ringPaint.strokeWidth = dp(1f) + dp(2f) * (1f - p)
                canvas.drawCircle(rp.x, rp.y, r, ringPaint)
                ringPaint.strokeWidth = dp(2.5f)
            }
            return ripples.isNotEmpty()
        }

        private fun drawSweep(canvas: Canvas, s: Sweep, now: Long): Boolean {
            val age = now - s.at
            val fadeIn = (age / LOCK_ON_MS.toFloat()).coerceIn(0f, 1f)
            val travel = ((age - s.delay) / s.duration.toFloat()).coerceIn(0f, 1f)
            // Ease in and out along the path, like a thumb.
            val e = if (travel < 0.5f) 2f * travel * travel else 1f - (-2f * travel + 2f) * (-2f * travel + 2f) / 2f
            val cx = s.x1 + (s.x2 - s.x1) * e
            val cy = s.y1 + (s.y2 - s.y1) * e
            val done = travel >= 1f
            val fadeOut = if (done) (1f - ((age - s.delay - s.duration) / SWEEP_FADE_MS.toFloat())).coerceIn(0f, 1f) else 1f
            if (fadeOut <= 0f) { sweep = null; return false }
            val alpha = (255 * fadeIn * fadeOut).toInt()
            // The whole path, faint, with an arrowhead at the end; the trail behind the ring, brighter.
            trailPaint.color = RING
            trailPaint.alpha = (alpha * 0.28f).toInt()
            canvas.drawLine(s.x1, s.y1, s.x2, s.y2, trailPaint)
            drawArrow(canvas, s.x1, s.y1, s.x2, s.y2, trailPaint)
            if (e > 0f) {
                trailPaint.alpha = (alpha * 0.7f).toInt()
                canvas.drawLine(s.x1, s.y1, cx, cy, trailPaint)
            }
            val r = dp(RING_DP)
            ringPaint.color = RING
            ringPaint.alpha = alpha
            canvas.drawCircle(cx, cy, r, ringPaint)
            fillPaint.color = RING
            fillPaint.alpha = alpha
            canvas.drawCircle(cx, cy, dp(3f), fillPaint)
            if (s.label.isNotBlank()) drawLabel(canvas, s.label, s.x1, s.y1, r + dp(10f), alpha)
            if (done && ripples.isEmpty() && fadeOut > 0.98f) ripples += Ripple(s.x2, s.y2, now)
            return true
        }

        private fun drawArrow(canvas: Canvas, x1: Float, y1: Float, x2: Float, y2: Float, paint: Paint) {
            val len = hypot(x2 - x1, y2 - y1)
            if (len < dp(12f)) return
            val ang = atan2(y2 - y1, x2 - x1)
            val head = dp(9f)
            val spread = 0.5f
            arrow.reset()
            arrow.moveTo(x2 - head * cos(ang - spread), y2 - head * sin(ang - spread))
            arrow.lineTo(x2, y2)
            arrow.lineTo(x2 - head * cos(ang + spread), y2 - head * sin(ang + spread))
            canvas.drawPath(arrow, paint)
        }

        private fun drawChip(canvas: Canvas, c: Chip, now: Long): Boolean {
            val age = now - c.at
            if (age > CHIP_TTL_MS) { chip = null; return false }
            val fadeIn = (age / 150f).coerceIn(0f, 1f)
            val fadeOut = ((CHIP_TTL_MS - age) / 250f).coerceIn(0f, 1f)
            drawLabel(canvas, c.text, c.x, c.y, dp(RING_DP) + dp(10f), (255 * min(fadeIn, fadeOut)).toInt())
            return true
        }

        /** The action's name in a dark pill to the right of ([x], [y]) — to the left when the screen ends. */
        private fun drawLabel(canvas: Canvas, text: String, x: Float, y: Float, gap: Float, alpha: Int) {
            val label = if (text.length > 30) text.take(29) + "…" else text
            val padX = dp(9f); val padY = dp(5f)
            val tw = textPaint.measureText(label)
            val th = textPaint.descent() - textPaint.ascent()
            val cw = tw + 2 * padX
            val ch = th + 2 * padY
            val screenRight = loc[0] + width
            var left = x + gap
            if (left + cw > screenRight - dp(8f)) left = x - gap - cw
            if (left < loc[0] + dp(8f)) left = loc[0] + dp(8f)
            val top = (y - ch / 2f).coerceIn(loc[1] + dp(8f), loc[1] + height - ch - dp(8f))
            chipRect.set(left, top, left + cw, top + ch)
            chipPaint.alpha = (alpha * 0.86f).toInt()
            canvas.drawRoundRect(chipRect, ch / 2f, ch / 2f, chipPaint)
            textPaint.alpha = alpha
            canvas.drawText(label, left + padX, top + padY - textPaint.ascent(), textPaint)
        }

        companion object {
            /** UI-TARS's dodger blue, rgba(30, 144, 255, 0.4), a little stronger for a phone's small bands. */
            private const val GLOW_WORKING = 0x8A1E90FF.toInt()
            /** Amber while the hands wait for the user. */
            private const val GLOW_WAITING = 0x8AFFB000.toInt()
            /** Band width as a share of the shorter side; the colour is gone at half of it. */
            private const val GLOW_BAND = 0.14f
            private const val GLOW_CYCLE_MS = 5000L
            /** UI-TARS's red circle. */
            private const val RING = 0xFFFF3B30.toInt()
            private const val RING_DP = 16f
            private const val CHIP_BG = 0xFF202124.toInt()
            private const val LOCK_ON_MS = 220L
            private const val RIPPLE_MS = 450L
            private const val SWEEP_FADE_MS = 320L
            private const val CHIP_TTL_MS = 2200L
        }
    }

    companion object {
        private const val TAG = "HandsStage"
    }
}
