package io.github.nanomuse.app

import android.Manifest
import android.app.Activity
import android.app.DownloadManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.view.View
import android.webkit.CookieManager
import android.webkit.PermissionRequest
import android.webkit.URLUtil
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.util.Log
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.lifecycleScope
import io.github.nanomuse.app.browser.TakeOverSheet
import io.github.nanomuse.app.databinding.ActivityMainBinding
import io.github.nanomuse.app.device.ShareInbox
import io.github.nanomuse.app.runtime.LocalRuntime
import io.github.nanomuse.app.runtime.RuntimeService
import kotlinx.coroutines.launch

/**
 * The app proper: the nanoMuse web app in a WebView, plus the parts a browser tab cannot do —
 * notifications while the screen is off (see [NotifyService]), the camera for QR codes,
 * a file picker for attachments, downloads, and a way back to the Connect screen.
 *
 * In local mode the server is the phone's own [RuntimeService]; the page is loaded once it
 * answers, and its failures are shown here with the runtime log.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var ui: ActivityMainBinding
    private lateinit var prefs: Prefs
    private var pendingThread: String? = null
    private var pendingShare: Intent? = null
    private var waitingForRuntime = false
    private var takeOver: TakeOverSheet? = null
    private val runtimeListener: (RuntimeService.State, String?) -> Unit = { state, detail ->
        runOnUiThread { runtimeChanged(state, detail) }
    }
    private var pendingFiles: ValueCallback<Array<Uri>>? = null
    private var pendingPermission: PermissionRequest? = null

    private val pickFiles = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        val cb = pendingFiles ?: return@registerForActivityResult
        pendingFiles = null
        val data = result.data
        val uris = when {
            result.resultCode != Activity.RESULT_OK || data == null -> null
            data.clipData != null -> Array(data.clipData!!.itemCount) { data.clipData!!.getItemAt(it).uri }
            data.data != null -> arrayOf(data.data!!)
            else -> null
        }
        cb.onReceiveValue(uris)
    }

    private val askNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        NotifyService.sync(this)
    }

    private val askCamera = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val req = pendingPermission ?: return@registerForActivityResult
        pendingPermission = null
        if (granted) req.grant(req.resources) else req.deny()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        if (!prefs.connected || (prefs.isLocal && !LocalRuntime(this).installed)) {
            goConnect()
            return
        }
        ui = ActivityMainBinding.inflate(layoutInflater)
        setContentView(ui.root)
        ViewCompat.setOnApplyWindowInsetsListener(ui.root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        setupWebView()
        ui.retry.setOnClickListener { retry() }
        ui.changeServer.setOnClickListener { forget() }
        if (prefs.isLocal) {
            ui.changeServer.text = getString(R.string.start_over)
            RuntimeService.listeners.add(runtimeListener)
        }

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (ui.web.canGoBack()) ui.web.goBack() else moveTaskToBack(true)
            }
        })

        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            NotifyService.sync(this)
        }
        if (ShareInbox.isShare(intent)) pendingShare = intent
        load(intent?.getStringExtra(EXTRA_THREAD))
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (ShareInbox.isShare(intent)) {
            pendingShare = intent
            load(null)
            return
        }
        intent.getStringExtra(EXTRA_THREAD)?.let { load(it) }
    }

    private fun setupWebView() {
        val web = ui.web
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            mediaPlaybackRequiresUserGesture = false
            allowFileAccess = false
            allowContentAccess = true
            cacheMode = WebSettings.LOAD_DEFAULT
            userAgentString = userAgentString + App.USER_AGENT_SUFFIX
            setSupportMultipleWindows(false)
        }
        CookieManager.getInstance().setAcceptCookie(true)
        web.addJavascriptInterface(Bridge(this), Bridge.NAME)
        web.setBackgroundColor(ContextCompat.getColor(this, R.color.bg))

        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url
                if (sameServer(url)) return false
                // anything else (links the agent found, OAuth pages…) belongs in the real browser
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, url)) }
                return true
            }

            override fun onPageFinished(view: WebView, url: String) {
                ui.offline.visibility = View.GONE
            }

            override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                if (!request.isForMainFrame) return
                if (prefs.isLocal) {
                    showRuntimeFailure(getString(R.string.offline_body, prefs.serverUrl))
                    return
                }
                ui.offlineTitle.text = getString(R.string.offline_title)
                ui.offlineBody.text = getString(R.string.offline_body, prefs.serverUrl)
                ui.offlineProgress.visibility = View.GONE
                ui.offlineLog.visibility = View.GONE
                ui.retry.visibility = View.VISIBLE
                ui.changeServer.visibility = View.VISIBLE
                ui.offline.visibility = View.VISIBLE
            }
        }

        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                webView: WebView,
                filePathCallback: ValueCallback<Array<Uri>>,
                params: FileChooserParams,
            ): Boolean {
                pendingFiles?.onReceiveValue(null)
                pendingFiles = filePathCallback
                val intent = params.createIntent().apply {
                    if (params.mode == FileChooserParams.MODE_OPEN_MULTIPLE) putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                    if (params.acceptTypes.none { it.isNotBlank() }) type = "*/*"
                }
                return runCatching { pickFiles.launch(intent); true }.getOrElse {
                    pendingFiles = null
                    false
                }
            }

            override fun onPermissionRequest(request: PermissionRequest) {
                // the page asks for the camera (attachments); microphone is not used by the web app
                if (request.resources.contains(PermissionRequest.RESOURCE_VIDEO_CAPTURE)) {
                    if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                        request.grant(request.resources)
                    } else {
                        pendingPermission = request
                        askCamera.launch(Manifest.permission.CAMERA)
                    }
                } else {
                    request.deny()
                }
            }
        }

        web.setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
            val uri = Uri.parse(url)
            if (!sameServer(uri)) {
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
                return@setDownloadListener
            }
            // workspace files carry the token in the query, so the DownloadManager can fetch them as is
            val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
            val req = DownloadManager.Request(uri)
                .setMimeType(mimeType)
                .addRequestHeader("User-Agent", userAgent)
                .setTitle(name)
                .setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                .setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name)
            runCatching { getSystemService<DownloadManager>()?.enqueue(req) }
        }
    }

    private fun sameServer(url: Uri): Boolean {
        val server = Uri.parse(prefs.serverUrl)
        return url.scheme == server.scheme && url.host == server.host && url.port == server.port
    }

    private fun load(thread: String?) {
        if (prefs.isLocal && RuntimeService.state != RuntimeService.State.RUNNING) {
            // the phone's own server: start it (idempotent) and load once it answers
            pendingThread = thread
            waitingForRuntime = true
            if (RuntimeService.state == RuntimeService.State.FAILED) {
                showRuntimeFailure(RuntimeService.lastError ?: getString(R.string.runtime_no_answer))
            } else {
                showStarting()
            }
            RuntimeService.start(this)
            return
        }
        ui.offline.visibility = View.GONE
        val share = pendingShare
        if (share != null) {
            // something shared from another app: a new conversation with it in the composer
            pendingShare = null
            lifecycleScope.launch {
                val url = try {
                    ShareInbox.accept(this@MainActivity, prefs, share)
                } catch (e: Exception) {
                    Log.w("MainActivity", "share into nanoMuse failed", e)
                    Toast.makeText(this@MainActivity, getString(R.string.share_failed, e.message ?: ""), Toast.LENGTH_LONG).show()
                    prefs.pageUrl(thread)
                }
                ui.web.loadUrl(url)
            }
            return
        }
        ui.web.loadUrl(prefs.pageUrl(thread))
    }

    private fun retry() {
        if (prefs.isLocal && RuntimeService.state != RuntimeService.State.RUNNING) {
            showStarting()
            waitingForRuntime = true
            RuntimeService.start(this)
        } else {
            load(pendingThread)
        }
    }

    private fun runtimeChanged(state: RuntimeService.State, detail: String?) {
        if (!::ui.isInitialized) return
        when (state) {
            RuntimeService.State.RUNNING -> if (waitingForRuntime) {
                waitingForRuntime = false
                val t = pendingThread
                pendingThread = null
                load(t)
            }
            RuntimeService.State.FAILED -> showRuntimeFailure(detail ?: RuntimeService.lastError ?: getString(R.string.runtime_no_answer))
            else -> Unit
        }
    }

    private fun showStarting() {
        ui.offlineTitle.text = getString(R.string.local_starting_title)
        ui.offlineBody.text = getString(R.string.local_starting_body)
        ui.offlineProgress.visibility = View.VISIBLE
        ui.offlineLog.visibility = View.GONE
        ui.retry.visibility = View.GONE
        ui.changeServer.visibility = View.GONE
        ui.offline.visibility = View.VISIBLE
    }

    private fun showRuntimeFailure(message: String) {
        ui.offlineTitle.text = getString(R.string.offline_title)
        ui.offlineBody.text = message
        ui.offlineProgress.visibility = View.GONE
        val tail = LocalRuntime(this).logTail(30)
        ui.offlineLog.text = tail
        ui.offlineLog.visibility = if (tail.isBlank()) View.GONE else View.VISIBLE
        ui.retry.visibility = View.VISIBLE
        ui.changeServer.visibility = View.VISIBLE
        ui.offline.visibility = View.VISIBLE
    }

    /** From the JS bridge: the agent's browser (this app's own WebView) into the user's hands. */
    fun takeOverBrowser(thread: String) {
        val sheet = takeOver ?: TakeOverSheet(this) {
            val js = "window.dispatchEvent(new CustomEvent('nanomuse:browser-handed-back', {detail: {thread: " +
                org.json.JSONObject.quote(thread) + "}}))"
            if (::ui.isInitialized) ui.web.evaluateJavascript(js, null)
        }.also { takeOver = it }
        if (!sheet.show()) Toast.makeText(this, R.string.takeover_nothing, Toast.LENGTH_SHORT).show()
    }

    /** From the JS bridge and the offline screen: drop the server and start over. */
    fun forget() {
        NotifyService.stop(this)
        if (prefs.isLocal) RuntimeService.stop(this) // the phone's data stays on disk
        prefs.forget()
        ui.web.clearHistory()
        goConnect()
    }

    private fun goConnect() {
        startActivity(Intent(this, ConnectActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        finish()
    }

    override fun onResume() {
        super.onResume()
        if (::ui.isInitialized) ui.web.onResume()
    }

    override fun onPause() {
        if (::ui.isInitialized) ui.web.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        RuntimeService.listeners.remove(runtimeListener)
        takeOver?.dismiss()
        if (::ui.isInitialized) ui.web.destroy()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_THREAD = "thread"
    }
}
