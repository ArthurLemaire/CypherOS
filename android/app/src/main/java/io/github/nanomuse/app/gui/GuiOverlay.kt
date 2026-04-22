package io.github.nanomuse.app.gui

import android.animation.ValueAnimator
import android.content.Context
import android.content.Intent
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import io.github.nanomuse.app.MainActivity
import io.github.nanomuse.app.Prefs
import io.github.nanomuse.app.R

/**
 * What the user sees while nanoMuse operates the phone — two accessibility-overlay windows:
 *
 * - **marks**: a full-screen, untouchable layer that shows the finger (a ring where it tapped, a
 *   line where it swiped, the typed text appearing) and a caption `Muse · <label>` at the bottom,
 *   per the spec in docs/gui.md ("Showing the finger");
 * - **capsule**: a pill at the top with the red panda, the current step and a **Stop** button.
 *   The operator is working on the very screen the user is looking at, so the capsule shows no
 *   screenshot — the step and a way out are what matter. When the agent needs the user
 *   ([notice]) the pill grows into a card with the question and an *Open* button.
 *
 * Both are hidden for the instant a screenshot is taken ([hiddenForCapture]) so the model never
 * sees the marks. Neither needs the "display over other apps" permission: an accessibility
 * service may draw its own overlay.
 */
class GuiOverlay(private val context: Context, private val onStop: () -> Unit) {
    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private val marks = MarksView(context)
    private val capsule = LinearLayout(context)
    private val stepText = TextView(context)
    private val noticeText = TextView(context)
    private val openButton = TextView(context)
    private val stopButton = TextView(context)
    private var shown = false
    private var stopped = false
    /** When the user last pressed Stop (uptime); 0 once a new task began. Read from any thread. */
    @Volatile private var stoppedAt = 0L
    private var hideAt = 0L
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    private val autoHide = Runnable { if (SystemClock.uptimeMillis() >= hideAt) hide() }

    init {
        val accent = ContextCompat.getColor(context, R.color.accent)
        val bg = GradientDrawable().apply {
            cornerRadius = dp(22f)
            setColor(Color.argb(235, 24, 24, 28))
        }
        capsule.orientation = LinearLayout.VERTICAL
        capsule.background = bg
        capsule.elevation = dp(6f)
        capsule.setPadding(dp(12f).toInt(), dp(8f).toInt(), dp(8f).toInt(), dp(8f).toInt())

        val row = LinearLayout(context).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val face = ImageView(context).apply {
            setImageResource(R.drawable.ic_launcher_foreground)
            layoutParams = LinearLayout.LayoutParams(dp(30f).toInt(), dp(30f).toInt())
            scaleType = ImageView.ScaleType.CENTER_CROP
            background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Color.argb(255, 42, 106, 86)) }
            clipToOutline = true
        }
        stepText.apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(8f).toInt(); marginEnd = dp(8f).toInt() }
        }
        stopButton.apply {
            text = context.getString(R.string.gui_stop)
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            setPadding(dp(14f).toInt(), dp(7f).toInt(), dp(14f).toInt(), dp(7f).toInt())
            background = GradientDrawable().apply { cornerRadius = dp(16f); setColor(Color.argb(255, 214, 60, 60)) }
            setOnClickListener { stop() }
        }
        row.addView(face)
        row.addView(stepText)
        row.addView(stopButton)
        capsule.addView(row)

        noticeText.apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13.5f)
            setPadding(dp(4f).toInt(), dp(8f).toInt(), dp(4f).toInt(), dp(4f).toInt())
            visibility = View.GONE
        }
        openButton.apply {
            text = context.getString(R.string.gui_open_app, agentName())
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            typeface = android.graphics.Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            setPadding(dp(14f).toInt(), dp(9f).toInt(), dp(14f).toInt(), dp(9f).toInt())
            background = GradientDrawable().apply { cornerRadius = dp(16f); setColor(accent) }
            visibility = View.GONE
            setOnClickListener {
                val i = Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                try {
                    context.startActivity(i)
                } catch (_: Exception) {
                }
                clearNotice()
            }
        }
        capsule.addView(noticeText)
        capsule.addView(openButton)
    }

    // ------------------------------------------------------------------ showing

    /** The capsule with [label] as the current step; shown until [hide] or a while after the last step. */
    fun show(label: String) {
        stoppedAt = 0L
        handler.post {
            stopped = false
            stepText.text = label.ifBlank { context.getString(R.string.gui_working, agentName()) }
            stopButton.text = context.getString(R.string.gui_stop)
            stopButton.setOnClickListener { stop() }
            if (!shown) {
                try {
                    wm.addView(marks, marksParams())
                    wm.addView(capsule, capsuleParams())
                    shown = true
                } catch (e: Exception) {
                    android.util.Log.w(TAG, "overlay could not be shown: ${e.message}")
                    return@post
                }
                stopButton.post {
                    val at = IntArray(2)
                    stopButton.getLocationOnScreen(at)
                    android.util.Log.d(TAG, "capsule shown; Stop at ${at[0]},${at[1]} ${stopButton.width}x${stopButton.height}")
                }
            }
            touch()
        }
    }

    fun step(label: String) {
        handler.post {
            if (!shown) show(label) else {
                stepText.text = label
                touch()
            }
        }
    }

    /** Something the agent wants the user to see (it needs them): the capsule becomes a card. */
    fun notice(text: String) {
        handler.post {
            if (!shown) show(context.getString(R.string.gui_needs_you, agentName()))
            stepText.text = context.getString(R.string.gui_needs_you, agentName())
            noticeText.text = text
            noticeText.visibility = View.VISIBLE
            openButton.visibility = View.VISIBLE
            hideAt = SystemClock.uptimeMillis() + NOTICE_MS
            handler.removeCallbacks(autoHide)
            handler.postDelayed(autoHide, NOTICE_MS)
        }
    }

    private fun clearNotice() {
        noticeText.visibility = View.GONE
        openButton.visibility = View.GONE
        hide()
    }

    fun hide() {
        handler.post {
            if (!shown) return@post
            try {
                wm.removeView(marks)
                wm.removeView(capsule)
            } catch (_: Exception) {
            }
            shown = false
            stopped = false
            noticeText.visibility = View.GONE
            openButton.visibility = View.GONE
        }
    }

    /** The user pressed Stop: the request in flight fails, and so does every new one for a while. */
    private fun stop() {
        stopped = true
        stoppedAt = SystemClock.uptimeMillis()
        stepText.text = context.getString(R.string.gui_stopped)
        stopButton.text = context.getString(R.string.gui_hide)
        stopButton.setOnClickListener { hide() }
        marks.caption(context.getString(R.string.gui_stopped))
        onStop()
        hideAt = SystemClock.uptimeMillis() + STOPPED_MS
        handler.removeCallbacks(autoHide)
        handler.postDelayed(autoHide, STOPPED_MS)
    }

    /**
     * Whether a request arriving now must be refused: Stop was pressed and no task has begun
     * since, within [STOP_STICKY_MS] — long enough to end the run that was going, short enough
     * that the user's next request an hour later is not refused too.
     */
    val isStopped: Boolean
        get() = stoppedAt != 0L && SystemClock.uptimeMillis() - stoppedAt < STOP_STICKY_MS

    /** Whether Stop was pressed after [since] (uptime): the request that began then must fail. */
    fun stoppedSince(since: Long): Boolean = stoppedAt > since

    /** Both windows invisible while [block] runs, so a screenshot shows the app alone. */
    suspend fun <T> hiddenForCapture(block: suspend () -> T): T {
        val wasShown = shown
        if (wasShown) {
            withMain { marks.visibility = View.INVISIBLE; capsule.visibility = View.INVISIBLE }
            kotlinx.coroutines.delay(40) // one frame for the compositor to drop them
        }
        try {
            return block()
        } finally {
            if (wasShown) withMain { marks.visibility = View.VISIBLE; capsule.visibility = View.VISIBLE }
        }
    }

    private suspend fun withMain(f: () -> Unit) = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.Main.immediate) { f() }

    // ------------------------------------------------------------------ the finger

    fun tapMark(x: Float, y: Float, holdMs: Long, label: String) {
        handler.post { marks.ring(x, y, holdMs + 520); marks.caption(captionFor(label)) }
    }

    fun swipeMark(x: Float, y: Float, x2: Float, y2: Float, durationMs: Long, label: String) {
        handler.post { marks.line(x, y, x2, y2, durationMs + 400); marks.caption(captionFor(label)) }
    }

    fun typeMark(text: String) {
        handler.post { marks.typed(text) }
    }

    fun caption(label: String) {
        handler.post { marks.caption(captionFor(label)) }
    }

    private fun captionFor(label: String) = "${agentName()} · $label"

    private fun touch() {
        hideAt = SystemClock.uptimeMillis() + IDLE_MS
        handler.removeCallbacks(autoHide)
        handler.postDelayed(autoHide, IDLE_MS)
    }

    private fun agentName() = Prefs(context).agentName.ifEmpty { context.getString(R.string.app_name) }

    private fun marksParams() = WindowManager.LayoutParams(
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.START
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            // the whole screen, status bar and cutout included: a mark at (x, y) must land on the
            // screen's (x, y), not be pushed down by the bars the window would otherwise avoid
            fitInsetsTypes = 0
            layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        }
    }

    private fun capsuleParams() = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
        y = dp(36f).toInt()
        width = (context.resources.displayMetrics.widthPixels * 0.92f).toInt()
    }

    private fun dp(v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, context.resources.displayMetrics)

    /** Rings, lines, typed text and the caption, each fading on its own clock. */
    private class MarksView(context: Context) : View(context) {
        private data class Ring(val x: Float, val y: Float, val until: Long, val from: Long)
        private data class Line(val x: Float, val y: Float, val x2: Float, val y2: Float, val until: Long, val from: Long)

        private val rings = mutableListOf<Ring>()
        private val lines = mutableListOf<Line>()
        private var captionText = ""
        private var captionUntil = 0L
        private var typedText = ""
        private var typedFrom = 0L
        private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = dp(3f); color = Color.argb(230, 255, 122, 61) }
        private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL; color = Color.argb(90, 255, 122, 61) }
        private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = dp(4f); strokeCap = Paint.Cap.ROUND; color = Color.argb(220, 255, 122, 61) }
        private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; textSize = dp(14f); textAlign = Paint.Align.CENTER }
        private val boxPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(200, 24, 24, 28) }
        private val ticker = ValueAnimator.ofFloat(0f, 1f).apply { duration = 1000; repeatCount = ValueAnimator.INFINITE; addUpdateListener { invalidate() } }

        private fun dp(v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics)

        fun ring(x: Float, y: Float, ms: Long) {
            val now = SystemClock.uptimeMillis()
            rings.add(Ring(x, y, now + ms, now))
            tick()
        }

        fun line(x: Float, y: Float, x2: Float, y2: Float, ms: Long) {
            val now = SystemClock.uptimeMillis()
            lines.add(Line(x, y, x2, y2, now + ms, now))
            tick()
        }

        fun typed(text: String) {
            typedText = text.take(80)
            typedFrom = SystemClock.uptimeMillis()
            captionText = ""
            tick()
        }

        fun caption(text: String) {
            captionText = text.take(90)
            captionUntil = SystemClock.uptimeMillis() + 2600
            typedText = ""
            tick()
        }

        private fun tick() {
            if (!ticker.isStarted) ticker.start()
            invalidate()
        }

        override fun onDraw(canvas: Canvas) {
            val now = SystemClock.uptimeMillis()
            rings.removeAll { it.until <= now }
            lines.removeAll { it.until <= now }
            for (r in rings) {
                val t = ((now - r.from).toFloat() / (r.until - r.from).coerceAtLeast(1)).coerceIn(0f, 1f)
                val radius = dp(14f) + dp(26f) * t
                ringPaint.alpha = (230 * (1 - t)).toInt()
                fillPaint.alpha = (90 * (1 - t)).toInt()
                canvas.drawCircle(r.x, r.y, radius, fillPaint)
                canvas.drawCircle(r.x, r.y, radius, ringPaint)
            }
            for (l in lines) {
                val t = ((now - l.from).toFloat() / (l.until - l.from).coerceAtLeast(1)).coerceIn(0f, 1f)
                linePaint.alpha = (220 * (1 - t * t)).toInt()
                canvas.drawLine(l.x, l.y, l.x2, l.y2, linePaint)
                canvas.drawCircle(l.x2, l.y2, dp(10f), linePaint)
            }
            val bottom = height - dp(96f)
            val shown = when {
                typedText.isNotEmpty() -> {
                    val chars = ((now - typedFrom) / 40).toInt().coerceIn(0, typedText.length)
                    if (now - typedFrom > typedText.length * 40 + 2600) { typedText = ""; "" } else "\u2328 " + typedText.take(chars)
                }
                captionUntil > now -> captionText
                else -> ""
            }
            if (shown.isNotEmpty()) {
                val w = textPaint.measureText(shown) + dp(28f)
                val cx = width / 2f
                canvas.drawRoundRect(cx - w / 2, bottom - dp(20f), cx + w / 2, bottom + dp(16f), dp(18f), dp(18f), boxPaint)
                canvas.drawText(shown, cx, bottom + dp(3f), textPaint)
            }
            if (rings.isEmpty() && lines.isEmpty() && shown.isEmpty() && ticker.isStarted) ticker.cancel()
        }
    }

    companion object {
        private const val TAG = "GuiOverlay"
        private const val IDLE_MS = 20_000L
        private const val STOPPED_MS = 4_000L
        private const val STOP_STICKY_MS = 15_000L
        private const val NOTICE_MS = 60_000L
    }
}
