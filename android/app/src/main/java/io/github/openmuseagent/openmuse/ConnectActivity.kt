package io.github.openmuseagent.openmuse

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.openmuseagent.openmuse.databinding.ActivityConnectBinding
import okhttp3.Call
import okhttp3.Callback
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * First screen: point the phone at the QR code `openmuse serve` prints, or paste the link.
 * The link is checked against the server (`GET /api/state`) before it is kept, so a typo or
 * a stale token is caught here and not as a blank page later.
 */
class ConnectActivity : AppCompatActivity() {
    private lateinit var ui: ActivityConnectBinding
    private lateinit var prefs: Prefs
    private val http = OkHttpClient.Builder().connectTimeout(6, TimeUnit.SECONDS).readTimeout(6, TimeUnit.SECONDS).build()

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        val text = result.contents ?: return@registerForActivityResult
        ui.url.setText(text)
        connect(text)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = Prefs(this)
        if (prefs.connected) {
            openMain()
            return
        }
        ui = ActivityConnectBinding.inflate(layoutInflater)
        setContentView(ui.root)
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
        intent?.dataString?.let { ui.url.setText(it) }
    }

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
