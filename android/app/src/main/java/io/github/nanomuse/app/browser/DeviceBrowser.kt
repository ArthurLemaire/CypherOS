package io.github.nanomuse.app.browser

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import android.util.Log
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.webkit.CookieManager
import android.webkit.JsResult
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import io.github.nanomuse.app.App
import io.github.nanomuse.app.runtime.LocalRuntime
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import org.json.JSONTokener
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.math.roundToInt

/**
 * The agent's browser on the phone: one WebView the server drives through the device link
 * (`browser` requests — the protocol is documented in `nanomuse/tools/browser_backends.py`,
 * `DeviceBackend`). It renders offscreen, and the user can pull the very same view into a
 * bottom sheet to take over (sign in, decide, then hand it back) — no reload, same cookies.
 *
 * Offscreen rendering: a WebView that is not attached to a window counts as hidden to
 * Chromium — `requestAnimationFrame` stops and timers run once a second — so the view is
 * hosted in a [Presentation] on a private [VirtualDisplay] of its own, where it is a real,
 * visible window nobody sees. When that is refused (a vendor build), the fallback is a
 * detached view with `measure` / `layout` / `draw`, which still loads and scripts pages,
 * only slower to settle.
 *
 * Coordinates in the protocol are CSS pixels of the viewport; the JPEG frames are the same
 * size, so the app's browser card can map a tap straight back.
 *
 * Everything here runs on the main thread except [fetch].
 */
@SuppressLint("SetJavaScriptEnabled")
class DeviceBrowser private constructor(private val app: Context) {
    class Profile(val userAgent: String, val width: Int, val height: Int, val mobile: Boolean)

    private val main = Handler(Looper.getMainLooper())
    private val density = app.resources.displayMetrics.density
    private var web: WebView? = null
    private var host: Host? = null
    private var profile = Profile("", 412, 915, mobile = true)
    private var loading = false
    private var loadWaiters = ArrayList<CompletableDeferred<Unit>>()
    private var lastDialog: String? = null
    private val http = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
        .followRedirects(true).build()

    /** The user has the page in the take-over sheet; the agent's actions wait their turn. */
    var userControl = false
        private set

    /** Listeners for the take-over UI: the URL changed, a page finished. */
    val onPageChanged = java.util.concurrent.CopyOnWriteArraySet<(String, String) -> Unit>()

    val isOpen: Boolean get() = web != null
    val currentUrl: String get() = web?.url ?: ""
    val currentTitle: String get() = web?.title ?: ""
    fun view(): WebView? = web

    // ------------------------------------------------------------------ the protocol

    /** One request from the server. Throws with a message the model can read. */
    suspend fun handle(op: String, p: JSONObject): JSONObject = withContext(Dispatchers.Main.immediate) {
        if (userControl && op !in READ_ONLY_OPS) {
            throw IllegalStateException("the user is using the page in the app right now; ask them, then try again")
        }
        when (op) {
            "open" -> {
                applyProfile(p)
                ensure()
                state()
            }
            "navigate" -> {
                val w = ensure()
                var url = p.getString("url")
                if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://$url"
                w.loadUrl(url)
                awaitLoaded(NAVIGATE_TIMEOUT_MS)
                state()
            }
            "evaluate" -> {
                val w = ensure()
                val js = p.getString("js")
                val arg = if (!p.has("arg") || p.isNull("arg")) "null" else when (val v = p.get("arg")) {
                    is String -> JSONObject.quote(v)
                    is Number, is Boolean -> v.toString()
                    else -> v.toString() // a JSONObject / JSONArray: already a JSON literal
                }
                val value = evaluate(w, "($js)($arg)")
                JSONObject().put("value", value).put("encoded", "json")
            }
            "tap" -> {
                tap(ensure(), p.getDouble("x").toFloat(), p.getDouble("y").toFloat())
                JSONObject()
            }
            "type" -> {
                typeText(ensure(), p.getString("text"))
                JSONObject()
            }
            "key" -> {
                key(ensure(), p.optString("key", "Enter"))
                JSONObject()
            }
            "scroll" -> {
                evaluate(ensure(), "window.scrollBy(0, ${p.optDouble("dy", 600.0)})")
                JSONObject()
            }
            "back" -> {
                val w = ensure()
                if (w.canGoBack()) {
                    w.goBack()
                    awaitLoaded(NAVIGATE_TIMEOUT_MS)
                }
                state()
            }
            "settle" -> {
                awaitLoaded(p.optLong("timeout_ms", 8_000L).coerceAtMost(20_000L))
                JSONObject()
            }
            "screenshot" -> screenshot(ensure(), p.optInt("quality", 55))
            "state" -> state()
            "fetch" -> fetch(p)
            "profile" -> {
                applyProfile(p)
                web?.let { w ->
                    applySettings(w)
                    layoutView(w)
                    if (!w.url.isNullOrEmpty() && w.url != "about:blank") {
                        w.reload()
                        awaitLoaded(NAVIGATE_TIMEOUT_MS)
                    }
                }
                JSONObject()
            }
            "close" -> {
                close()
                JSONObject()
            }
            else -> throw IllegalArgumentException("unknown browser op '$op'")
        }
    }

    // ------------------------------------------------------------------ the view

    private fun ensure(): WebView {
        web?.let { return it }
        val w = WebView(app)
        applySettings(w)
        CookieManager.getInstance().apply {
            setAcceptCookie(true)
            setAcceptThirdPartyCookies(w, true)
        }
        w.webViewClient = object : WebViewClient() {
            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                loading = true
            }

            override fun onPageFinished(view: WebView, url: String?) {
                loading = false
                CookieManager.getInstance().flush()
                val waiters = loadWaiters
                loadWaiters = ArrayList()
                waiters.forEach { it.complete(Unit) }
                onPageChanged.forEach { it(url ?: "", view.title ?: "") }
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val scheme = request.url.scheme ?: ""
                // app links (weixin://, alipays:// …) are not for this view; the page stays put
                return scheme != "http" && scheme != "https"
            }
        }
        w.webChromeClient = object : WebChromeClient() {
            // dialogs: nothing waits on a human here. Alerts are acknowledged, questions
            // declined (nothing irreversible by accident); the text is kept for the state.
            override fun onJsAlert(view: WebView, url: String, message: String, result: JsResult): Boolean {
                lastDialog = "alert: $message"; result.confirm(); return true
            }

            override fun onJsConfirm(view: WebView, url: String, message: String, result: JsResult): Boolean {
                lastDialog = "confirm (declined): $message"; result.cancel(); return true
            }

            override fun onJsBeforeUnload(view: WebView, url: String, message: String, result: JsResult): Boolean {
                result.confirm(); return true
            }

            override fun onReceivedTitle(view: WebView, title: String?) {
                onPageChanged.forEach { it(view.url ?: "", title ?: "") }
            }
        }
        w.setDownloadListener { url, _, contentDisposition, mimeType, _ ->
            Downloads.save(app, http, url, contentDisposition, mimeType)
        }
        web = w
        host = Host.create(app, w, pxW(), pxH(), profile) ?: Host.Detached(w)
        layoutView(w)
        w.onResume()
        w.resumeTimers()
        return w
    }

    private fun applySettings(w: WebView) {
        with(w.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadsImagesAutomatically = true
            mediaPlaybackRequiresUserGesture = true
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false) // one tab: target=_blank lands here
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
            cacheMode = WebSettings.LOAD_DEFAULT
            // the layout viewport is the view itself: 412 CSS px as a phone, 1280 as a desktop.
            // No overview zoom, so a point on the frame is the same point on the page.
            useWideViewPort = false
            loadWithOverviewMode = false
            setSupportZoom(false)
            builtInZoomControls = false
            userAgentString = if (profile.userAgent.isNotEmpty()) profile.userAgent
            else WebSettings.getDefaultUserAgent(app).let { ua ->
                if (profile.mobile) ua else ua.replace("Mobile ", "").replace(Regex("Android [^;)]*; [^;)]*"), "X11; Linux x86_64")
            } + App.USER_AGENT_SUFFIX
        }
    }

    private fun applyProfile(p: JSONObject) {
        profile = Profile(
            userAgent = p.optString("user_agent", profile.userAgent),
            width = p.optInt("width", profile.width).coerceIn(320, 3840),
            height = p.optInt("height", profile.height).coerceIn(320, 4320),
            mobile = if (p.has("mobile")) p.optBoolean("mobile", profile.mobile) else profile.mobile,
        )
    }

    private fun pxW() = (profile.width * density).roundToInt()
    private fun pxH() = (profile.height * density).roundToInt()

    private fun layoutView(w: WebView) {
        val h = host
        if (h is Host.Presentation && !userControl) {
            h.resize(pxW(), pxH())
        } else if (!userControl) {
            w.measure(
                View.MeasureSpec.makeMeasureSpec(pxW(), View.MeasureSpec.EXACTLY),
                View.MeasureSpec.makeMeasureSpec(pxH(), View.MeasureSpec.EXACTLY),
            )
            w.layout(0, 0, pxW(), pxH())
        }
    }

    private suspend fun awaitLoaded(timeoutMs: Long) {
        // give a click a moment to start a navigation before deciding nothing happened
        kotlinx.coroutines.delay(150)
        if (!loading) {
            kotlinx.coroutines.delay(250)
            return
        }
        val d = CompletableDeferred<Unit>()
        loadWaiters.add(d)
        withTimeoutOrNull(timeoutMs) { d.await() }
        loadWaiters.remove(d)
        kotlinx.coroutines.delay(300)
    }

    private suspend fun evaluate(w: WebView, expression: String): Any? {
        val wrapped = "(function(){try{var r=($expression);return JSON.stringify(r===undefined?null:r);}catch(e){return JSON.stringify({__error:String(e)});}})()"
        val raw = suspendCancellableCoroutine<String?> { cont ->
            w.evaluateJavascript(wrapped) { value -> cont.resume(value) }
        } ?: return null
        // evaluateJavascript hands back the result as a JSON literal: a quoted string here
        val text = JSONTokener(raw).nextValue() as? String ?: return null
        if (text.startsWith("{\"__error\"")) throw IllegalStateException("page script error: " + JSONObject(text).optString("__error"))
        return text // the JSON of the result; the Python side decodes it
    }

    private suspend fun tap(w: WebView, cssX: Float, cssY: Float) {
        val x = cssX * density
        val y = cssY * density
        if (x < 0 || y < 0 || x > pxW() || y > pxH()) throw IllegalArgumentException("tap (${cssX.toInt()}, ${cssY.toInt()}) is outside the ${profile.width}×${profile.height} viewport")
        if (w.isAttachedToWindow) {
            val t = SystemClock.uptimeMillis()
            w.dispatchTouchEvent(MotionEvent.obtain(t, t, MotionEvent.ACTION_DOWN, x, y, 0).also { it.source = android.view.InputDevice.SOURCE_TOUCHSCREEN })
            w.dispatchTouchEvent(MotionEvent.obtain(t, t + 60, MotionEvent.ACTION_UP, x, y, 0).also { it.source = android.view.InputDevice.SOURCE_TOUCHSCREEN })
        } else {
            // no window to deliver touches to: the element under the point is clicked from script
            evaluate(w, "(function(){var e=document.elementFromPoint($cssX,$cssY);if(!e)return false;e.focus&&e.focus();e.click&&e.click();return true;})()")
        }
        awaitLoaded(NAVIGATE_TIMEOUT_MS)
    }

    private suspend fun typeText(w: WebView, text: String) {
        val q = JSONObject.quote(text)
        evaluate(
            w,
            """(function(){var e=document.activeElement;if(!e||e===document.body)return false;
               if(e.isContentEditable){document.execCommand('insertText',false,$q);return true;}
               var tag=e.tagName.toLowerCase();if(tag!=='input'&&tag!=='textarea')return false;
               var proto=tag==='input'?HTMLInputElement.prototype:HTMLTextAreaElement.prototype;
               var set=Object.getOwnPropertyDescriptor(proto,'value').set;
               var s=e.selectionStart==null?e.value.length:e.selectionStart, en=e.selectionEnd==null?s:e.selectionEnd;
               set.call(e,e.value.slice(0,s)+$q+e.value.slice(en));
               try{e.setSelectionRange(s+$q.length,s+$q.length);}catch(_){}
               e.dispatchEvent(new Event('input',{bubbles:true}));return true;})()""".trimIndent(),
        )
    }

    private suspend fun key(w: WebView, name: String) {
        val code = KEYS[name] ?: KEYS[name.replaceFirstChar { it.uppercase() }]
        if (code != null && w.isAttachedToWindow) {
            w.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, code))
            w.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, code))
        }
        // from script as well: a form submits on Enter whether or not the key event landed
        val js = when (name) {
            "Enter" -> "(function(){var e=document.activeElement;if(!e)return false;" +
                "var ev=new KeyboardEvent('keydown',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true});" +
                "var ok=e.dispatchEvent(ev);" +
                "if(ok&&e.form&&(e.tagName==='INPUT')){if(e.form.requestSubmit)e.form.requestSubmit();else e.form.submit();}" +
                "e.dispatchEvent(new KeyboardEvent('keyup',{key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true}));return ok;})()"
            "Tab" -> null
            else -> if (code == null) "(function(){var e=document.activeElement||document.body;" +
                "e.dispatchEvent(new KeyboardEvent('keydown',{key:${JSONObject.quote(name)},bubbles:true}));" +
                "e.dispatchEvent(new KeyboardEvent('keyup',{key:${JSONObject.quote(name)},bubbles:true}));return true;})()" else null
        }
        if (js != null && (!w.isAttachedToWindow || name == "Enter")) evaluate(w, js)
        awaitLoaded(NAVIGATE_TIMEOUT_MS)
    }

    private suspend fun screenshot(w: WebView, quality: Int): JSONObject {
        val pw = pxW(); val ph = pxH()
        // the display's own composited frame when there is one (video, canvas and all);
        // otherwise the view drawn by hand
        val shown = host as? Host.Presentation
        shown?.awaitFrame(FRAME_WAIT_MS)
        val bmp = shown?.latestFrame() ?: Bitmap.createBitmap(pw, ph, Bitmap.Config.RGB_565).also { b ->
            val canvas = Canvas(b)
            canvas.drawColor(android.graphics.Color.WHITE)
            // the page's scroll offset is inside the view's own coordinates
            canvas.translate(-w.scrollX.toFloat(), -w.scrollY.toFloat())
            w.draw(canvas)
        }
        // frames are CSS-sized: what the server draws and maps taps on
        val scaled = if (bmp.width != profile.width || bmp.height != profile.height) Bitmap.createScaledBitmap(bmp, profile.width, profile.height, true) else bmp
        val out = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, quality.coerceIn(20, 95), out)
        if (scaled !== bmp) scaled.recycle()
        bmp.recycle()
        return JSONObject()
            .put("jpeg", Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP))
            .put("width", profile.width)
            .put("height", profile.height)
    }

    private fun state(): JSONObject {
        val w = web
        val j = JSONObject()
            .put("url", w?.url ?: "")
            .put("title", w?.title ?: "")
            .put("width", profile.width)
            .put("height", profile.height)
            .put("loading", loading)
            .put("user_control", userControl)
            .put("host", host?.kind ?: "none")
        lastDialog?.let { j.put("dialog", it); lastDialog = null }
        return j
    }

    /** A request with the WebView's cookies and user agent — signed in, no page driven. */
    private suspend fun fetch(p: JSONObject): JSONObject {
        val url = p.getString("url")
        val method = p.optString("method", "GET").uppercase()
        val cm = CookieManager.getInstance()
        // WebView state is read here, on the main thread; only the request itself goes to IO
        val userAgent = web?.settings?.userAgentString ?: (WebSettings.getDefaultUserAgent(app) + App.USER_AGENT_SUFFIX)
        val cookie = cm.getCookie(url)
        val builder = Request.Builder().url(url)
        cookie?.let { builder.header("Cookie", it) }
        builder.header("User-Agent", userAgent)
        p.optJSONObject("headers")?.let { h -> h.keys().forEach { k -> builder.header(k, h.optString(k)) } }
        val body = if (p.has("body") && !p.isNull("body")) p.getString("body") else null
        if (method == "GET" || method == "HEAD") builder.method(method, null)
        else builder.method(method, (body ?: "").toRequestBody((p.optJSONObject("headers")?.optString("Content-Type")?.ifEmpty { null } ?: "application/x-www-form-urlencoded").toMediaTypeOrNull()))
        val request = builder.build()
        val (result, setCookies, finalUrl) = withContext(Dispatchers.IO) {
            http.newCall(request).execute().use { r ->
                val text = r.body?.let { b ->
                    val bytes = b.source().use { s -> s.readByteArray(minOf(b.contentLength().takeIf { it > 0 } ?: FETCH_MAX_BYTES, FETCH_MAX_BYTES)) }
                    String(bytes, (b.contentType()?.charset() ?: Charsets.UTF_8))
                } ?: ""
                val headers = JSONObject()
                r.headers.names().forEach { n -> headers.put(n.lowercase(), r.header(n)) }
                Triple(
                    JSONObject().put("status", r.code).put("headers", headers).put("body", text).put("url", r.request.url.toString()),
                    r.headers("Set-Cookie"),
                    r.request.url.toString(),
                )
            }
        }
        // what the site set on the way back belongs to the WebView too
        setCookies.forEach { cm.setCookie(finalUrl, it) }
        if (setCookies.isNotEmpty()) cm.flush()
        return result
    }

    fun close() {
        val w = web ?: return
        web = null
        host?.release()
        host = null
        userControl = false
        CookieManager.getInstance().flush()
        (w.parent as? ViewGroup)?.removeView(w)
        w.stopLoading()
        w.destroy()
    }

    // ------------------------------------------------------------------ the user takes over

    /** Move the page into [container] (the take-over sheet). The agent's actions wait. */
    fun attachTo(container: ViewGroup) {
        val w = ensure()
        userControl = true
        host?.detachView()
        (w.parent as? ViewGroup)?.removeView(w)
        container.addView(w, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        w.requestFocus()
    }

    /** Back offscreen, as the user left it. */
    fun detach() {
        val w = web ?: run { userControl = false; return }
        (w.parent as? ViewGroup)?.removeView(w)
        userControl = false
        host?.attachView() ?: run { host = Host.Detached(w) }
        layoutView(w)
        CookieManager.getInstance().flush()
    }

    // ------------------------------------------------------------------ where it renders

    private sealed class Host(val kind: String) {
        abstract fun attachView()
        abstract fun detachView()
        abstract fun release()

        /** A window on a private virtual display: visible to Chromium, seen by nobody. */
        class Presentation(
            private val app: Context,
            private val web: WebView,
            private var reader: ImageReader,
            private var display: VirtualDisplay,
            private var dialog: android.app.Presentation,
            private val container: FrameLayout,
        ) : Host("presentation") {
            private var latest: android.media.Image? = null
            private var frameWaiter: CompletableDeferred<Unit>? = null
            private val handler = Handler(Looper.getMainLooper())

            init {
                listen(reader)
            }

            /** Keep the newest composited frame (and only that one), so the producer never stalls. */
            private fun listen(r: ImageReader) {
                r.setOnImageAvailableListener({ rd ->
                    val img = runCatching { rd.acquireLatestImage() }.getOrNull() ?: return@setOnImageAvailableListener
                    latest?.close()
                    latest = img
                    frameWaiter?.complete(Unit)
                }, handler)
            }

            /**
             * Ask for a redraw and wait for the frame it produces, so a screenshot taken right
             * after a load shows the page and not the frame before it. Bounded: a page that
             * does not repaint gives back the last frame.
             */
            suspend fun awaitFrame(timeoutMs: Long) {
                val d = CompletableDeferred<Unit>()
                frameWaiter = d
                web.invalidate()
                withTimeoutOrNull(timeoutMs) { d.await() }
                if (frameWaiter === d) frameWaiter = null
            }

            /** The last frame as a bitmap, or null before the first one. */
            fun latestFrame(): Bitmap? {
                val img = latest ?: return null
                return try {
                    val plane = img.planes[0]
                    val pixelStride = plane.pixelStride
                    val rowStride = plane.rowStride
                    val padded = Bitmap.createBitmap(rowStride / pixelStride, img.height, Bitmap.Config.ARGB_8888)
                    padded.copyPixelsFromBuffer(plane.buffer.also { it.rewind() })
                    if (padded.width == img.width) padded else Bitmap.createBitmap(padded, 0, 0, img.width, img.height).also { padded.recycle() }
                } catch (e: Exception) {
                    Log.w(TAG, "frame copy failed: ${e.message}")
                    null
                }
            }

            fun resize(w: Int, h: Int) {
                if (reader.width == w && reader.height == h) return
                val dpi = app.resources.displayMetrics.densityDpi
                val newReader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3)
                listen(newReader)
                display.resize(w, h, dpi)
                display.surface = newReader.surface
                latest?.close()
                latest = null
                reader.close()
                reader = newReader
                dialog.window?.setLayout(w, h)
            }

            override fun attachView() {
                if (web.parent !== container) {
                    (web.parent as? ViewGroup)?.removeView(web)
                    container.addView(web, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
                }
            }

            override fun detachView() {
                if (web.parent === container) container.removeView(web)
            }

            override fun release() {
                latest?.close()
                latest = null
                runCatching { dialog.dismiss() }
                runCatching { display.release() }
                runCatching { reader.close() }
            }
        }

        /** No window: measured and laid out by hand, drawn on demand. */
        class Detached(private val web: WebView) : Host("detached") {
            override fun attachView() = Unit
            override fun detachView() = Unit
            override fun release() = Unit
        }

        companion object {
            fun create(app: Context, web: WebView, w: Int, h: Int, profile: Profile): Host? {
                return try {
                    val dm = app.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
                    val dpi = app.resources.displayMetrics.densityDpi
                    val reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 3)
                    val flags = DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY or DisplayManager.VIRTUAL_DISPLAY_FLAG_PRESENTATION
                    val display = dm.createVirtualDisplay("nanomuse-browser", w, h, dpi, reader.surface, flags)
                        ?: return null
                    val container = FrameLayout(app)
                    val dialog = android.app.Presentation(app, display.display)
                    dialog.setContentView(container)
                    dialog.window?.setLayout(w, h)
                    dialog.show()
                    val host = Presentation(app, web, reader, display, dialog, container)
                    host.attachView()
                    Log.i(TAG, "browser hosted on a virtual display ${w}x$h")
                    host
                } catch (e: Exception) {
                    Log.w(TAG, "no virtual display for the browser (${e.javaClass.simpleName}: ${e.message}); rendering detached")
                    null
                }
            }
        }
    }

    companion object {
        private const val TAG = "DeviceBrowser"
        /** How long a screenshot waits for the page to paint once more. */
        private const val FRAME_WAIT_MS = 700L
        private const val NAVIGATE_TIMEOUT_MS = 20_000L
        private const val FETCH_MAX_BYTES = 4L * 1024 * 1024
        private val READ_ONLY_OPS = setOf("state", "screenshot", "evaluate", "settle")
        private val KEYS = mapOf(
            "Enter" to KeyEvent.KEYCODE_ENTER, "Tab" to KeyEvent.KEYCODE_TAB, "Backspace" to KeyEvent.KEYCODE_DEL,
            "Delete" to KeyEvent.KEYCODE_FORWARD_DEL, "Escape" to KeyEvent.KEYCODE_ESCAPE, "Space" to KeyEvent.KEYCODE_SPACE,
            "ArrowUp" to KeyEvent.KEYCODE_DPAD_UP, "ArrowDown" to KeyEvent.KEYCODE_DPAD_DOWN,
            "ArrowLeft" to KeyEvent.KEYCODE_DPAD_LEFT, "ArrowRight" to KeyEvent.KEYCODE_DPAD_RIGHT,
            "PageDown" to KeyEvent.KEYCODE_PAGE_DOWN, "PageUp" to KeyEvent.KEYCODE_PAGE_UP,
            "Home" to KeyEvent.KEYCODE_MOVE_HOME, "End" to KeyEvent.KEYCODE_MOVE_END,
        )

        // the application context only, never an activity: nothing to leak
        @SuppressLint("StaticFieldLeak")
        @Volatile private var instance: DeviceBrowser? = null

        /** One browser per app process, created lazily on the main thread. */
        fun get(context: Context): DeviceBrowser =
            instance ?: synchronized(this) { instance ?: DeviceBrowser(context.applicationContext).also { instance = it } }
    }
}

/** Downloads the agent's browser starts: into the phone's own workspace in local mode, else Downloads. */
private object Downloads {
    fun save(app: Context, http: OkHttpClient, url: String, contentDisposition: String?, mimeType: String?) {
        val name = android.webkit.URLUtil.guessFileName(url, contentDisposition, mimeType)
        val prefs = io.github.nanomuse.app.Prefs(app)
        if (prefs.isLocal) {
            Thread {
                try {
                    val dir = File(LocalRuntime(app).home, "workspace/downloads").apply { mkdirs() }
                    val req = Request.Builder().url(url).apply {
                        CookieManager.getInstance().getCookie(url)?.let { header("Cookie", it) }
                    }.build()
                    http.newCall(req).execute().use { r ->
                        r.body?.byteStream()?.use { input -> File(dir, name).outputStream().use { input.copyTo(it) } }
                    }
                    Log.i("DeviceBrowser", "downloaded $name into the workspace")
                } catch (e: Exception) {
                    Log.w("DeviceBrowser", "download failed: ${e.message}")
                }
            }.start()
        } else {
            val req = android.app.DownloadManager.Request(android.net.Uri.parse(url))
                .setMimeType(mimeType)
                .setTitle(name)
                .setNotificationVisibility(android.app.DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(android.os.Environment.DIRECTORY_DOWNLOADS, name)
            CookieManager.getInstance().getCookie(url)?.let { req.addRequestHeader("Cookie", it) }
            runCatching { (app.getSystemService(Context.DOWNLOAD_SERVICE) as android.app.DownloadManager).enqueue(req) }
        }
    }
}
