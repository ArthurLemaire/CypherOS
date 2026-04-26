package io.github.nanomuse.app

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.nanomuse.app.databinding.ActivityConnectBinding
import io.github.nanomuse.app.runtime.LocalRuntime
import io.github.nanomuse.app.runtime.RuntimeService
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * First screen. The build that carries a root file system asks where nanoMuse should live:
 * on this phone (unpack, then start the runtime) or on the user's computer. The connect-only
 * build goes straight to the second: point the phone at the QR code `nanomuse serve` prints,
 * or paste the link. The link is checked against the server (`GET /api/state`) before it is
 * kept, so a typo or a stale token is caught here and not as a blank page later.
 */
class ConnectActivity : AppCompatActivity() {
    private lateinit var ui: ActivityConnectBinding
    private lateinit var prefs: Prefs
    private lateinit var runtime: LocalRuntime
    private var runtimeListener: ((RuntimeService.State, String?) -> Unit)? = null
    private val http = OkHttpClient.Builder().connectTimeout(6, TimeUnit.SECONDS).readTimeout(6, TimeUnit.SECONDS).build()

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        val text = result.contents ?: return@registerForActivityResult
        ui.url.setText(text)
        connect(text)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        runtime = LocalRuntime(this)
        if (prefs.connected && (!prefs.isLocal || runtime.installed)) {
            openMain()
            return
        }
        ui = ActivityConnectBinding.inflate(layoutInflater)
        setContentView(ui.root)
        if (runtime.available) setupModes()
        ViewCompat.setOnApplyWindowInsetsListener(ui.root) { v, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        ui.scan.setOnClickListener {
            scanner.launch(
                ScanOptions()
                    .setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                    .setPrompt(getString(R.string.connect_scan_prompt))
                    .setBeepEnabled(false)
                    .setOrientationLocked(true)
            )
        }
        ui.connect.setOnClickListener { connect(ui.url.text?.toString() ?: "") }
        ui.url.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_GO) {
                connect(ui.url.text?.toString() ?: "")
                true
            } else false
        }
        // a link shared from another app (or a deep link) lands here too
        intent?.dataString?.let {
            ui.url.setText(it)
            showRemote()
        }
    }

    override fun onDestroy() {
        runtimeListener?.let { RuntimeService.listeners.remove(it) }
        super.onDestroy()
    }

    // ------------------------------------------------------------------ on this phone

    private fun setupModes() {
        ui.title.text = getString(R.string.mode_title)
        ui.body.text = getString(R.string.mode_body)
        ui.modes.visibility = View.VISIBLE
        ui.remote.visibility = View.GONE
        val mb = ((runtime.bundled?.unpacked ?: 0L) / (1024 * 1024)).toInt().coerceAtLeast(1)
        ui.localHint.text = getString(R.string.mode_local_hint, mb)
        ui.runLocal.setOnClickListener { runLocal() }
        ui.useRemote.setOnClickListener { showRemote() }
    }

    private fun showRemote() {
        if (!runtime.available) return
        ui.title.text = getString(R.string.connect_title)
        ui.body.text = getText(R.string.connect_body)
        ui.modes.visibility = View.GONE
        ui.install.visibility = View.GONE
        ui.remote.visibility = View.VISIBLE
    }

    /** Unpack (once), start the service, wait for the first health check, open the app. */
    private fun runLocal() {
        ui.modes.visibility = View.GONE
        ui.error.visibility = View.GONE
        ui.install.visibility = View.VISIBLE
        ui.installProgress.isIndeterminate = false
        ui.installProgress.progress = 0
        ui.installText.text = getString(R.string.install_unpacking, 0)
        thread(name = "rootfs-install") {
            try {
                if (!runtime.installed) {
                    var lastPercent = -1
                    runtime.install { done, total, _ ->
                        val percent = if (total > 0) (done * 100 / total).toInt().coerceIn(0, 100) else 0
                        if (percent != lastPercent) {
                            lastPercent = percent
                            runOnUiThread {
                                ui.installProgress.progress = percent * 10
                                ui.installText.text = getString(R.string.install_unpacking, percent)
                            }
                        }
                    }
                }
                runOnUiThread { startLocal() }
            } catch (e: Exception) {
                runOnUiThread {
                    ui.install.visibility = View.GONE
                    ui.modes.visibility = View.VISIBLE
                    fail(getString(R.string.install_failed, e.message ?: e.javaClass.simpleName))
                }
            }
        }
    }

    private fun startLocal() {
        ui.installProgress.isIndeterminate = true
        ui.installText.text = getString(R.string.install_starting)
        prefs.mode = Prefs.MODE_LOCAL
        val listener: (RuntimeService.State, String?) -> Unit = { state, detail ->
            runOnUiThread {
                when (state) {
                    RuntimeService.State.RUNNING -> {
                        runtimeListener?.let { RuntimeService.listeners.remove(it) }
                        runtimeListener = null
                        openMain()
                    }
                    RuntimeService.State.FAILED -> {
                        runtimeListener?.let { RuntimeService.listeners.remove(it) }
                        runtimeListener = null
                        ui.install.visibility = View.GONE
                        ui.modes.visibility = View.VISIBLE
                        fail(detail ?: RuntimeService.lastError ?: getString(R.string.runtime_no_answer))
                    }
                    else -> Unit
                }
            }
        }
        runtimeListener = listener
        RuntimeService.listeners.add(listener)
        RuntimeService.start(this)
    }

    // ------------------------------------------------------------------ on the computer

    private fun connect(text: String) {
        val parsed = Prefs.parseLink(text)
        if (parsed == null) return fail(getString(R.string.connect_bad_url))
        val (origin, token) = parsed
        if (token.isEmpty()) return fail(getString(R.string.connect_no_token))
        busy(true)
        val req = Request.Builder().url("$origin/api/state").header("Authorization", "Bearer $token").build()
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread { fail(getString(R.string.connect_unreachable, origin)) }
            }

            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                response.close()
                runOnUiThread {
                    when {
                        response.code == 401 || response.code == 403 -> fail(getString(R.string.connect_unauthorized))
                        !response.isSuccessful -> fail(getString(R.string.connect_unreachable, origin))
                        else -> {
                            prefs.mode = Prefs.MODE_REMOTE
                            prefs.serverUrl = origin
                            prefs.token = token
                            prefs.agentName = runCatching { JSONObject(body).getJSONObject("profile").optString("name") }.getOrDefault("")
                            NotifyService.sync(this@ConnectActivity)
                            openMain()
                        }
                    }
                }
            }
        })
    }

    private fun busy(on: Boolean) {
        ui.progress.visibility = if (on) View.VISIBLE else View.GONE
        ui.error.visibility = View.GONE
        ui.connect.isEnabled = !on
        ui.scan.isEnabled = !on
        ui.connect.text = getString(if (on) R.string.connect_checking else R.string.connect_button)
    }

    private fun fail(message: String) {
        busy(false)
        ui.error.text = message
        ui.error.visibility = View.VISIBLE
    }

    private fun openMain() {
        startActivity(Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK))
        finish()
    }
}
