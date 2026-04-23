package io.github.nanomuse.app.device

import android.content.ClipboardManager
import android.net.Uri
import android.os.Bundle
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.getSystemService

/**
 * A see-through activity that does one thing for [Ask] and closes: asks Android for
 * permissions, reads the clipboard while it has the focus, or opens the Photo Picker.
 * It has no UI of its own; what the user sees is the system's dialog.
 */
class DeviceAskActivity : AppCompatActivity() {
    private var request: String = ""
    private var answered = false

    private val askPermissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { grants ->
        finishWith(Bundle().apply { putBoolean(Ask.RESULT_GRANTED, grants.values.all { it }) })
    }

    private val pickOne = registerForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        finishWith(uris(listOfNotNull(uri)))
    }

    private var pickMany = registerForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(MAX_PHOTOS)) { list ->
        finishWith(uris(list))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        request = intent.getStringExtra(Ask.EXTRA_REQUEST) ?: run { finish(); return }
        when (intent.getStringExtra(Ask.EXTRA_MODE)) {
            Ask.MODE_PERMISSIONS -> {
                val perms = intent.getStringArrayExtra(Ask.EXTRA_PERMISSIONS)
                if (perms.isNullOrEmpty()) finishWith(Bundle().apply { putBoolean(Ask.RESULT_GRANTED, true) })
                else askPermissions.launch(perms)
            }
            Ask.MODE_PHOTOS -> {
                val max = intent.getIntExtra(Ask.EXTRA_MAX, 1).coerceIn(1, MAX_PHOTOS)
                val req = PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo)
                if (max == 1) pickOne.launch(req) else pickMany.launch(req)
            }
            Ask.MODE_CLIPBOARD -> Unit // needs the window focus first: see onWindowFocusChanged
            else -> finishWith(null)
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus && intent.getStringExtra(Ask.EXTRA_MODE) == Ask.MODE_CLIPBOARD && !answered) {
            val cm = getSystemService<ClipboardManager>()
            val text = cm?.primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(this)?.toString()
            finishWith(Bundle().apply { putString(Ask.RESULT_TEXT, text ?: "") })
        }
    }

    private fun uris(list: List<Uri>) = Bundle().apply { putParcelableArrayList(Ask.RESULT_URIS, ArrayList(list)) }

    private fun finishWith(result: Bundle?) {
        if (answered) return
        answered = true
        Ask.complete(request, result)
        finish()
        overridePendingTransitionCompat()
    }

    override fun onDestroy() {
        if (!answered) Ask.complete(request, null) // swiped away or killed: the tool learns it
        super.onDestroy()
    }

    @Suppress("DEPRECATION")
    private fun overridePendingTransitionCompat() {
        if (android.os.Build.VERSION.SDK_INT >= 34) overrideActivityTransition(OVERRIDE_TRANSITION_CLOSE, 0, 0) else overridePendingTransition(0, 0)
    }

    companion object {
        const val MAX_PHOTOS = 10
    }
}
