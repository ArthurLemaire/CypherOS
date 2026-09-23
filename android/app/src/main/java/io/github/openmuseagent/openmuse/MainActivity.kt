package io.github.openmuseagent.openmuse

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
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.getSystemService
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import io.github.openmuseagent.openmuse.databinding.ActivityMainBinding

/**
 * The app proper: the OpenMuse web app in a WebView, plus the parts a browser tab cannot do —
 * notifications while the screen is off (see [NotifyService]), the camera for QR codes,
 * a file picker for attachments, downloads, and a way back to the Connect screen.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var ui: ActivityMainBinding
    private lateinit var prefs: Prefs
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
        if (!prefs.connected) {
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
        ui.retry.setOnClickListener { load(null) }
        ui.changeServer.setOnClickListener { forget() }

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
        load(intent?.getStringExtra(EXTRA_THREAD))
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
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
                ui.offlineBody.text = getString(R.string.offline_body, prefs.serverUrl)
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
        ui.offline.visibility = View.GONE
        ui.web.loadUrl(prefs.pageUrl(thread))
    }

    /** From the JS bridge and the offline screen: drop the server and start over. */
    fun forget() {
        NotifyService.stop(this)
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
        if (::ui.isInitialized) ui.web.destroy()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_THREAD = "thread"
    }
}
