package io.github.nanomuse.avatar

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.ui.avatar.AgentMood
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream

/**
 * The user's own face for the agent: one chosen picture plus, when the image model could make
 * them, one picture per mood. Everything lives under `minis-global/nanomuse/avatar/` as PNGs so
 * it survives updates and can be backed up like the rest of the app's files. Null means the
 * built-in red panda.
 */
data class AvatarSet(
    val base: ImageBitmap,
    val moods: Map<AgentMood, ImageBitmap>,
    val prompt: String,
    val style: String,
    val model: String,
    val createdAt: Long,
) {
    fun forMood(mood: AgentMood): ImageBitmap = moods[mood] ?: base
}

object AvatarStore {
    private const val TAG = "Avatar"
    /** Stored edge in pixels: crisp at the 92 dp header disc on any density, small on disk. */
    const val STORED_PX = 512

    private lateinit var dir: File
    private val _current = MutableStateFlow<AvatarSet?>(null)
    val current: StateFlow<AvatarSet?> = _current

    fun init(context: Context) {
        dir = File(context.filesDir, "minis-global/nanomuse/avatar").apply { mkdirs() }
        reload()
        AvatarMotion.init()
    }

    fun root(): File = dir
    fun candidatesDir(): File = File(dir, "candidates").apply { mkdirs() }
    fun baseFile(): File = File(dir, "base.png")
    fun moodFile(mood: AgentMood): File = File(dir, mood.name.lowercase() + ".png")
    private fun metaFile(): File = File(dir, "avatar.json")

    fun reload() {
        val base = decode(baseFile()) ?: run { _current.value = null; return }
        val moods = AgentMood.entries.mapNotNull { m -> decode(moodFile(m))?.let { m to it } }.toMap()
        val meta = runCatching { JSONObject(metaFile().readText()) }.getOrNull()
        _current.value = AvatarSet(
            base = base,
            moods = moods,
            prompt = meta?.optString("prompt").orEmpty(),
            style = meta?.optString("style").orEmpty(),
            model = meta?.optString("model").orEmpty(),
            createdAt = meta?.optLong("created") ?: baseFile().lastModified(),
        )
    }

    /** Makes [bitmap] the face. Old mood pictures are dropped — they belonged to the old face. */
    fun adopt(bitmap: Bitmap, prompt: String, style: String, model: String) {
        AgentMood.entries.forEach { moodFile(it).delete() }
        AvatarMotion.clear()
        write(baseFile(), bitmap)
        metaFile().writeText(
            JSONObject().put("prompt", prompt).put("style", style).put("model", model)
                .put("created", System.currentTimeMillis()).toString(),
        )
        reload()
    }

    fun putMood(mood: AgentMood, bitmap: Bitmap) {
        if (!baseFile().exists()) return
        write(moodFile(mood), bitmap)
        reload()
    }

    /** Back to the red panda. Candidates are kept so the user can pick again without paying. */
    fun reset() {
        AvatarMotion.clear()
        baseFile().delete()
        AgentMood.entries.forEach { moodFile(it).delete() }
        metaFile().delete()
        reload()
    }

    fun write(file: File, bitmap: Bitmap) {
        val scaled = if (bitmap.width > STORED_PX || bitmap.height > STORED_PX) {
            val s = STORED_PX.toFloat() / maxOf(bitmap.width, bitmap.height)
            Bitmap.createScaledBitmap(bitmap, (bitmap.width * s).toInt(), (bitmap.height * s).toInt(), true)
        } else bitmap
        val tmp = File(file.parentFile, file.name + ".tmp")
        FileOutputStream(tmp).use { scaled.compress(Bitmap.CompressFormat.PNG, 100, it) }
        if (!tmp.renameTo(file)) { file.delete(); tmp.renameTo(file) }
    }

    fun decodeBitmap(file: File): Bitmap? =
        runCatching { file.takeIf { it.exists() }?.let { BitmapFactory.decodeFile(it.path) } }
            .onFailure { AppLogger.warning(TAG, "cannot decode ${file.name}: ${it.message}") }
            .getOrNull()

    private fun decode(file: File): ImageBitmap? = decodeBitmap(file)?.asImageBitmap()
}
