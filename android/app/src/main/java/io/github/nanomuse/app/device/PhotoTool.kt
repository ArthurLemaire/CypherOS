package io.github.nanomuse.app.device

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import io.github.nanomuse.app.runtime.LocalRuntime
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.LocalDate

/**
 * Photos and videos the user picks in the system Photo Picker, copied into the workspace
 * (`attachments/<date>/`, the same place the chat's own attachments go) so the agent reads
 * them like any other file. The picker gives access to the chosen items only.
 */
class PhotoTool(private val context: Context) {
    suspend fun pick(max: Int, why: String): JSONObject {
        val uris = Ask.photos(context, max.coerceIn(1, DeviceAskActivity.MAX_PHOTOS), why)
        if (uris.isEmpty()) throw ToolError("The user did not pick a photo (or did not come to the picker in time).")
        return withContext(Dispatchers.IO) {
            val workspace = File(LocalRuntime(context).home, "workspace")
            val folder = File(workspace, "attachments/${LocalDate.now()}").apply { mkdirs() }
            val files = JSONArray()
            for ((i, uri) in uris.withIndex()) {
                val (name, size) = describe(uri)
                val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
                val safe = (name ?: "photo-${i + 1}.${ext(mime)}").replace(Regex("[^\\w.\\- ()\\u4e00-\\u9fff]+"), "_").trim(' ', '.', '_').ifEmpty { "photo" }.take(120)
                var target = File(folder, safe)
                var n = 2
                while (target.exists()) { target = File(folder, safe.substringBeforeLast('.') + "-$n" + safe.substringAfterLast('.', "").let { if (it.isEmpty()) "" else ".$it" }); n++ }
                context.contentResolver.openInputStream(uri)?.use { input -> target.outputStream().use { input.copyTo(it) } }
                    ?: throw ToolError("could not read the picked item")
                files.put(
                    JSONObject()
                        .put("path", "attachments/${folder.name}/${target.name}")
                        .put("name", target.name)
                        .put("mime", mime)
                        .put("size", if (target.length() > 0) target.length() else size),
                )
            }
            JSONObject().put("count", files.length()).put("files", files).put("note", "paths are relative to the workspace")
        }
    }

    private fun describe(uri: Uri): Pair<String?, Long> {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val name = c.getString(0)
                val size = if (c.isNull(1)) 0L else c.getLong(1)
                return name to size
            }
        }
        return null to 0L
    }

    private fun ext(mime: String) = when {
        mime.contains("png") -> "png"
        mime.contains("webp") -> "webp"
        mime.contains("gif") -> "gif"
        mime.contains("heic") || mime.contains("heif") -> "heic"
        mime.startsWith("video/") -> mime.substringAfter('/').take(4)
        else -> "jpg"
    }
}
