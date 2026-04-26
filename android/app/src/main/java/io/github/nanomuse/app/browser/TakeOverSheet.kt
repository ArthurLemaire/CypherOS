package io.github.nanomuse.app.browser

import android.content.Intent
import android.net.Uri
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageButton
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialog
import io.github.nanomuse.app.R

/**
 * The user takes over the agent's browser: the very same WebView, moved into a bottom sheet,
 * no reload, same cookies. Sign in, decide, tap **Done** — the view goes back offscreen and
 * the server is told the page was handed back ([onDone]), so the agent's next look says so.
 *
 * Pages a WebView cannot sign in to (Google refuses embedded views) have the arrow: the
 * system browser opens the same URL; a login made there does not reach this view, which is
 * why the docs say to prefer sites' own accounts on the phone.
 */
class TakeOverSheet(private val activity: AppCompatActivity, private val onDone: () -> Unit) {
    private val browser = DeviceBrowser.get(activity)
    private var dialog: BottomSheetDialog? = null

    val showing: Boolean get() = dialog?.isShowing == true

    /** Show the sheet; false when the agent has no page open (nothing to take over). */
    fun show(): Boolean {
        if (showing) return true
        if (!browser.isOpen) return false
        val d = BottomSheetDialog(activity, R.style.Theme_nanoMuse_Sheet)
        d.setContentView(R.layout.sheet_browser)
        val view = d.findViewById<View>(R.id.browser_root)!!
        val container = d.findViewById<FrameLayout>(R.id.browser_container)!!
        val title = d.findViewById<TextView>(R.id.browser_title)!!
        val url = d.findViewById<TextView>(R.id.browser_url)!!
        val height = (activity.resources.displayMetrics.heightPixels * 0.82).toInt()
        container.layoutParams = (container.layoutParams as ViewGroup.LayoutParams).apply { this.height = height - dp(120) }
        d.behavior.state = BottomSheetBehavior.STATE_EXPANDED
        d.behavior.skipCollapsed = true
        d.behavior.isDraggable = false // the page scrolls; the sheet should not follow the finger
        (view.parent as? ViewGroup)?.layoutParams?.height = height

        val listener: (String, String) -> Unit = { u, t ->
            activity.runOnUiThread {
                url.text = u
                title.text = t.ifEmpty { activity.getString(R.string.takeover_title) }
            }
        }
        browser.onPageChanged.add(listener)
        listener(browser.currentUrl, browser.currentTitle)

        d.findViewById<ImageButton>(R.id.browser_external)!!.setOnClickListener {
            val u = browser.currentUrl
            if (u.isNotEmpty()) runCatching { activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(u))) }
        }
        d.findViewById<View>(R.id.browser_done)!!.setOnClickListener { d.dismiss() }
        d.setOnDismissListener {
            browser.onPageChanged.remove(listener)
            browser.detach()
            dialog = null
            onDone()
        }
        browser.attachTo(container)
        dialog = d
        d.show()
        return true
    }

    fun dismiss() {
        dialog?.dismiss()
    }

    private fun dp(v: Int): Int = (v * activity.resources.displayMetrics.density).toInt()
}
