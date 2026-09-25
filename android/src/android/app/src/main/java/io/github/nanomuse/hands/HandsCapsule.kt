package io.github.nanomuse.hands

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Outline
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewOutlineProvider
import android.view.WindowManager
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import androidx.compose.ui.graphics.asAndroidBitmap
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.avatar.AvatarStore
import io.github.nanomuse.ui.avatar.AgentMood
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * The capsule that sits over the operated app while the hands work: the face, what is being
 * done, and **Stop**. When the hands need the user it grows into a card — *Your turn* with
 * **Continue** for a login or a code, *Waiting for your approval* with **Open** for a tap that
 * needs the card in the chat. Plain views on a `TYPE_APPLICATION_OVERLAY` window, so it lives
 * outside any Activity; every call is safe from any thread.
 *
 * The capsule hides itself for the instant a screenshot is taken ([hideForCapture]), so the
 * screen model never sees it and cannot tap its own Stop button.
 */
class HandsCapsule(private val context: Context) {
    private val main = Handler(Looper.getMainLooper())
    private val wm = context.getSystemService(Context.WINDOW_SERVICE) as WindowManager
    private var root: LinearLayout? = null
    private var titleView: TextView? = null
    private var detailView: TextView? = null
    private var continueBtn: TextView? = null
    private var openBtn: TextView? = null

    var onStop: (() -> Unit)? = null
    var onContinue: (() -> Unit)? = null
    var onOpenApp: (() -> Unit)? = null

    private fun dp(v: Int): Int = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), context.resources.displayMetrics).toInt()

    /** Shows (or updates) the working state. */
    fun working(step: Int, detail: String) = onMain {
        ensure()
        titleView?.text = context.getString(R.string.nm_hands_step, step)
        detailView?.text = detail
        continueBtn?.visibility = View.GONE
        openBtn?.visibility = View.GONE
    }

    /** The hands wait for the user to do something on the phone. */
    fun takeOver(reason: String) = onMain {
        ensure()
        titleView?.text = context.getString(R.string.nm_hands_your_turn)
        detailView?.text = reason.ifBlank { context.getString(R.string.nm_hands_your_turn_detail) }
        continueBtn?.visibility = View.VISIBLE
        openBtn?.visibility = View.GONE
    }

    /** A tap waits for the approval card in the chat. */
    fun approval(what: String) = onMain {
        ensure()
        titleView?.text = context.getString(R.string.nm_hands_approval_title)
        detailView?.text = what
        continueBtn?.visibility = View.GONE
        openBtn?.visibility = View.VISIBLE
    }

    fun hide() = onMain {
        root?.let { v -> runCatching { wm.removeView(v) } }
        root = null; titleView = null; detailView = null; continueBtn = null; openBtn = null
    }

    /** Hides the capsule for a screenshot and waits until the frame is gone; [restore] brings it back. */
    fun hideForCapture() {
        val latch = CountDownLatch(1)
        main.post { root?.visibility = View.INVISIBLE; latch.countDown() }
        latch.await(300, TimeUnit.MILLISECONDS)
        // One more frame so the compositor has dropped it.
        Thread.sleep(80)
    }

    fun restore() = onMain { root?.visibility = View.VISIBLE }

    // ── building ───────────────────────────────────────────────────────────

    private fun onMain(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) runCatching(block).onFailure { AppLogger.warning(TAG, "capsule: ${it.message}") }
        else main.post { runCatching(block).onFailure { AppLogger.warning(TAG, "capsule: ${it.message}") } }
    }

    private fun ensure() {
        if (root != null) return
        val pill = LinearLayout(context).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(8), dp(10), dp(8))
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(22).toFloat()
                setColor(0xF2202124.toInt())
            }
            elevation = dp(6).toFloat()
            clipToOutline = true
            outlineProvider = object : ViewOutlineProvider() {
                override fun getOutline(v: View, outline: Outline) {
                    outline.setRoundRect(0, 0, v.width, v.height, dp(22).toFloat())
                }
            }
        }
        val face = ImageView(context).apply {
            val s = dp(30)
            layoutParams = LinearLayout.LayoutParams(s, s)
            scaleType = ImageView.ScaleType.CENTER_CROP
            clipToOutline = true
            outlineProvider = object : ViewOutlineProvider() {
                override fun getOutline(v: View, outline: Outline) { outline.setOval(0, 0, v.width, v.height) }
            }
            faceBitmap()?.let { setImageBitmap(it) } ?: setImageResource(R.drawable.nm_avatar_working)
        }
        val texts = LinearLayout(context).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(10); marginEnd = dp(10) }
        }
        val title = TextView(context).apply {
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            maxLines = 1
        }
        val detail = TextView(context).apply {
            setTextColor(0xFFC8CCD2.toInt())
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f)
            maxLines = 2
        }
        texts.addView(title); texts.addView(detail)
        val cont = button(context.getString(R.string.nm_hands_continue), 0xFF0078FD.toInt()) { onContinue?.invoke() }.apply { visibility = View.GONE }
        val open = button(context.getString(R.string.nm_hands_open), 0xFF0078FD.toInt()) { onOpenApp?.invoke() }.apply { visibility = View.GONE }
        val stop = button(context.getString(R.string.nm_hands_stop), 0xFFE5484D.toInt()) { onStop?.invoke() }
        pill.addView(face); pill.addView(texts); pill.addView(cont); pill.addView(open); pill.addView(stop)

        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE
        val dm = context.resources.displayMetrics
        val params = WindowManager.LayoutParams(
            minOf((dm.widthPixels * 0.94f).toInt(), dp(420)),
            WindowManager.LayoutParams.WRAP_CONTENT,
            type,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
            y = statusBarHeight() + dp(6)
        }
        try {
            wm.addView(pill, params)
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "addView failed: ${t.message}")
            return
        }
        root = pill; titleView = title; detailView = detail; continueBtn = cont; openBtn = open
    }

    private fun button(text: String, color: Int, onClick: () -> Unit): TextView = TextView(context).apply {
        this.text = text
        setTextColor(Color.WHITE)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f)
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setPadding(dp(12), dp(6), dp(12), dp(6))
        background = GradientDrawable().apply { cornerRadius = dp(14).toFloat(); setColor(color) }
        layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { marginStart = dp(6) }
        setOnClickListener { onClick() }
    }

    private fun faceBitmap(): Bitmap? = runCatching { AvatarStore.current.value?.forMood(AgentMood.WORKING)?.asAndroidBitmap() }.getOrNull()

    private fun statusBarHeight(): Int {
        val id = context.resources.getIdentifier("status_bar_height", "dimen", "android")
        return if (id > 0) context.resources.getDimensionPixelSize(id) else dp(24)
    }

    /** Brings nanoMuse's chat back to the front. */
    fun bringAppToFront(sessionId: String?) {
        try {
            val intent = Intent(context, Class.forName("com.openminis.app.MainActivity")).apply {
                if (!sessionId.isNullOrBlank()) data = android.net.Uri.parse("minis://session/$sessionId")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            context.startActivity(intent)
        } catch (t: Throwable) {
            AppLogger.warning(TAG, "bring to front failed: ${t.message}")
        }
    }

    companion object {
        private const val TAG = "HandsCapsule"
    }
}
