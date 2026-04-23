package io.github.nanomuse.app.device

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import io.github.nanomuse.app.Prefs
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * "Share to nanoMuse" from any app: the text and files arrive here, the files are uploaded
 * to the server as attachments, a new conversation is opened with them in the composer and
 * the text as the draft — the user adds what to do and sends. Nothing is sent to the model
 * until they do.
 */
object ShareInbox {
    private val http = OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(60, TimeUnit.SECONDS).writeTimeout(60, TimeUnit.SECONDS).build()

    fun isShare(intent: Intent?): Boolean = intent?.action == Intent.ACTION_SEND || intent?.action == Intent.ACTION_SEND_MULTIPLE

    /** The page to load for this share. Throws [IOException] when the server does not take it. */
    suspend fun accept(context: Context, prefs: Prefs, intent: Intent): String = withContext(Dispatchers.IO) {
        val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)?.trim().orEmpty()
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim().orEmpty()
        val draft = listOf(subject, text).filter { it.isNotEmpty() }.distinct().joinToString("\n")
        val uris = streams(intent)
        val attached = JSONArray()
        for (uri in uris.take(10)) {
            val name = displayName(context, uri) ?: "shared-${attached.length() + 1}"
            val mime = intent.type?.takeIf { it.isNotEmpty() && !it.contains('*') } ?: context.contentResolver.getType(uri) ?: "application/octet-stream"
            val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: continue
            val req = Request.Builder()
                .url("${prefs.serverUrl}/api/files/upload?name=${Uri.encode(name)}")
                .header("Authorization", "Bearer ${prefs.token}")
                .post(bytes.toRequestBody(mime.toMediaType()))
                .build()
            http.newCall(req).execute().use { r ->
                if (!r.isSuccessful) throw IOException("upload of $name failed: HTTP ${r.code}")
                attached.put(JSONObject(r.body?.string() ?: "{}"))
            }
        }
        if (draft.isEmpty() && attached.length() == 0) throw IOException("nothing to share")
        val title = when {
            subject.isNotEmpty() -> subject
            text.isNotEmpty() -> text.lineSequence().first().take(60)
            else -> attached.optJSONObject(0)?.optString("name")?.take(60) ?: "Shared"
        }
        val create = Request.Builder()
            .url("${prefs.serverUrl}/api/threads")
            .header("Authorization", "Bearer ${prefs.token}")
            .post(JSONObject().put("title", title).toString().toRequestBody("application/json".toMediaType()))
            .build()
        val threadId = http.newCall(create).execute().use { r ->
            if (!r.isSuccessful) throw IOException("could not open a conversation: HTTP ${r.code}")
            JSONObject(r.body?.string() ?: "{}").optString("id").ifEmpty { throw IOException("no thread id") }
        }
        val b = Uri.parse(prefs.pageUrl(threadId)).buildUpon()
        if (draft.isNotEmpty()) b.appendQueryParameter("draft", draft.take(4000))
        if (attached.length() > 0) b.appendQueryParameter("attach", attached.toString())
        b.build().toString()
    }

    private fun streams(intent: Intent): List<Uri> {
        @Suppress("DEPRECATION")
        return when (intent.action) {
            Intent.ACTION_SEND -> listOfNotNull(if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java) else intent.getParcelableExtra(Intent.EXTRA_STREAM))
            Intent.ACTION_SEND_MULTIPLE -> (if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java) else intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM)).orEmpty()
            else -> emptyList()
        }
    }

    private fun displayName(context: Context, uri: Uri): String? {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst() && !c.isNull(0)) return c.getString(0)
        }
        return uri.lastPathSegment
    }
}
