package com.openminis.app.ui.chat

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.util.LruCache
import android.webkit.JavascriptInterface
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.ui.unit.IntSize
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull

/**
 * T155: single offscreen WebView that renders LaTeX (and mhchem chemistry)
 * via KaTeX, returning a Bitmap for inline-bubble display in markdown.
 *
 * Mirrors iOS KaTeXRenderer: one WebView is loaded from assets once,
 * each render call evaluates `renderMath(...)` JS, the bridge fires
 * `AndroidBridge.onRendered(w, h, err)` once KaTeX finishes laying out
 * the formula, then we snapshot the WebView with `view.draw(Canvas)`
 * after resizing it to the measured CSS size. Results are cached by
 * (latex, displayMode, fontSize, isDark) so re-renders during recompose
 * are free.
 *
 * Concurrency: a single Mutex serializes render requests because the
 * JS bridge has only one pending callback slot. A queue of requests
 * sharing the same WebView is enough — math formulas are small and
 * complete in tens of ms each once KaTeX is warm.
 */
internal class KatexRenderResult(val bitmap: Bitmap, val size: IntSize)

internal object KatexWebViewPool {

    private const val TAG = "KatexWebViewPool"
    private const val ASSET_HTML = "file:///android_asset/katex/katex-render.html"
    private const val DEFAULT_FONT_SIZE_PX = 17
    private const val RENDER_TIMEOUT_MS = 4_000L
    // Layout viewport for the offscreen WebView, in PHYSICAL pixels. KaTeX
    // needs this many px of width to lay out a formula before reporting its
    // measured width via getBoundingClientRect(). On a density-2.625 device
    // 8192 px ≈ 3120 CSS px ≈ enough for any sane single-line display
    // formula or wide matrix. Smaller values caused wide formulas like
    // `I_c = W_c^{\text{non-private}} \cdot \alpha_c + ...` (≈ 1000 CSS
    // px wide) to be clipped at layout time, and the resulting bitmap
    // showed only the leftmost portion.
    private const val LAYOUT_PIXELS = 8192

    private val mainHandler = Handler(Looper.getMainLooper())
    private val mutex = Mutex()
    private val cache = LruCache<String, KatexRenderResult>(150)

    @Volatile
    private var webView: WebView? = null
    @Volatile
    private var isReady = false
    @Volatile
    private var pending: CompletableDeferred<Triple<Int, Int, String>>? = null

    /**
     * Render [latex] via KaTeX. Returns null on error / timeout. Callers
     * are expected to fall back to displaying the raw LaTeX text.
     */
    suspend fun render(
        context: Context,
        latex: String,
        displayMode: Boolean,
        isDark: Boolean,
        fontSizePx: Int = DEFAULT_FONT_SIZE_PX,
    ): KatexRenderResult? {
        val key = cacheKey(latex, displayMode, isDark, fontSizePx)
        cache.get(key)?.let { return it }
        return mutex.withLock {
            cache.get(key)?.let { return@withLock it }
            val result = renderInternal(context.applicationContext, latex, displayMode, isDark, fontSizePx)
            if (result != null) cache.put(key, result)
            result
        }
    }

    private suspend fun renderInternal(
        appContext: Context,
        latex: String,
        displayMode: Boolean,
        isDark: Boolean,
        fontSizePx: Int,
    ): KatexRenderResult? {
        val wv = ensureWebView(appContext) ?: return null
        if (!awaitReady()) return null

        val deferred = CompletableDeferred<Triple<Int, Int, String>>()
        pending = deferred

        val js = "renderMath(" +
            "'${latex.escapeForJs()}', " +
            "$displayMode, " +
            "$fontSizePx, " +
            "$isDark" +
            ")"
        runOnMain { wv.evaluateJavascript(js, null) }

        val (w, h, err) = withTimeoutOrNull(RENDER_TIMEOUT_MS) { deferred.await() }
            ?: Triple(0, 0, "timeout")
        pending = null
        if (err.isNotEmpty() || w <= 0 || h <= 0) {
            android.util.Log.w(TAG, "render failed latex='${latex.take(40)}' err=$err w=$w h=$h")
            return null
        }
        return runOnMainSync { snapshot(wv, w, h) }
    }

    private suspend fun ensureWebView(appContext: Context): WebView? {
        webView?.let { return it }
        return runOnMainSync { createWebView(appContext) }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createWebView(appContext: Context): WebView? {
        webView?.let { return it }
        val wv = WebView(appContext).apply {
            // Offscreen layout — a real frame is required so KaTeX can measure
            // the formula. We resize to the measured size before snapshotting.
            measure(
                android.view.View.MeasureSpec.makeMeasureSpec(LAYOUT_PIXELS, android.view.View.MeasureSpec.EXACTLY),
                android.view.View.MeasureSpec.makeMeasureSpec(LAYOUT_PIXELS, android.view.View.MeasureSpec.EXACTLY),
            )
            layout(0, 0, LAYOUT_PIXELS, LAYOUT_PIXELS)
            // T208-6: force software layer — hardware-accelerated WebView
            // drawn onto a software Canvas via wv.draw() returns stale or
            // empty pixels because the GPU layer's framebuffer is opaque
            // to software readback. With LAYER_TYPE_SOFTWARE, draw() walks
            // the actual display list and paints into the destination
            // bitmap. (Symptom this fixes: each captured bitmap had the
            // right dimensions but the pixels were the *previous* render's
            // formula — Σ in the integral cell, P=[…] in the matrix cell
            // missing its leading mathbf, etc.)
            setLayerType(android.view.View.LAYER_TYPE_SOFTWARE, null)
            setBackgroundColor(Color.TRANSPARENT)
            settings.javaScriptEnabled = true
            settings.allowFileAccess = true
            settings.cacheMode = WebSettings.LOAD_NO_CACHE
            addJavascriptInterface(JsBridge { w, h, err ->
                pending?.complete(Triple(w, h, err))
            }, "AndroidBridge")
            webViewClient = object : WebViewClient() {
                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    isReady = true
                    readyDeferred?.complete(Unit)
                }
            }
            loadUrl(ASSET_HTML)
        }
        webView = wv
        return wv
    }

    private fun snapshot(wv: WebView, w: Int, h: Int): KatexRenderResult? {
        return try {
            val density = wv.context.resources.displayMetrics.density
            // KaTeX reports `w`/`h` in CSS pixels (initial-scale=1.0 → 1 CSS px = 1 dp).
            // The bitmap holds physical pixels (= CSS px × density). T208-5.
            //
            // Important (T208-6): do NOT resize the WebView before drawing.
            // Resizing the body changes its CSS width, which causes the
            // already-laid-out KaTeX HTML to reflow — and reflow shifts the
            // span's left edge / triggers wrap. The previous code resized to
            // pxW × pxH then drew, which captured the post-reflow layout
            // (sometimes with the leading glyph clipped, e.g. the `Σ` cut
            // from `\sum_{i=1}^{n} i^2`). Instead we keep the WebView at its
            // full LAYOUT_PIXELS canvas and let canvas clipping crop to the
            // formula's rectangle at (0,0)–(pxW,pxH). Equivalent to a CSS
            // overflow-hidden viewport of exactly (pxW, pxH) physical px.
            val pxW = (w * density).toInt().coerceAtLeast(1)
            val pxH = (h * density).toInt().coerceAtLeast(1)
            val bitmap = Bitmap.createBitmap(pxW, pxH, Bitmap.Config.ARGB_8888)
            val canvas = Canvas(bitmap)
            wv.draw(canvas)
            KatexRenderResult(bitmap, IntSize(w, h))
        } catch (e: Throwable) {
            android.util.Log.w(TAG, "snapshot failed: ${e.message}")
            null
        }
    }

    @Volatile
    private var readyDeferred: CompletableDeferred<Unit>? = null

    private suspend fun awaitReady(): Boolean {
        if (isReady) return true
        val d = readyDeferred ?: CompletableDeferred<Unit>().also { readyDeferred = it }
        val ok = withTimeoutOrNull(RENDER_TIMEOUT_MS) { d.await() } != null
        if (!ok) android.util.Log.w(TAG, "WebView never reached ready state")
        return ok
    }

    private inline fun runOnMain(crossinline block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) block()
        else mainHandler.post { block() }
    }

    private suspend fun <T> runOnMainSync(block: () -> T): T {
        if (Looper.myLooper() == Looper.getMainLooper()) return block()
        val out = CompletableDeferred<T>()
        mainHandler.post {
            try {
                out.complete(block())
            } catch (t: Throwable) {
                out.completeExceptionally(t)
            }
        }
        return out.await()
    }

    private fun cacheKey(latex: String, displayMode: Boolean, isDark: Boolean, fontSizePx: Int): String {
        val d = if (displayMode) 'D' else 'I'
        val k = if (isDark) 'k' else 'l'
        return "$d:$k:$fontSizePx:$latex"
    }

    private fun String.escapeForJs(): String =
        this.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "\\n")
            .replace("\r", "")

    private class JsBridge(private val onResult: (Int, Int, String) -> Unit) {
        @JavascriptInterface
        fun onRendered(width: Int, height: Int, error: String) {
            onResult(width, height, error)
        }
    }
}
