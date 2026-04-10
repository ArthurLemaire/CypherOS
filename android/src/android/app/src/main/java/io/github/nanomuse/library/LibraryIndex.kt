package io.github.nanomuse.library

import android.content.Context
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.ui.sandbox.FileItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

enum class LibraryKind { ARTIFACT, MEDIA }

/** One file the agent produced, with where it came from. */
data class LibraryEntry(
    val item: FileItem,
    val kind: LibraryKind,
    /** Session the workspace belongs to; null for the shared folder. */
    val sessionId: String?,
    val sessionTitle: String?,
    /** `/var/minis/...` path as the agent sees it, for the detail line. */
    val linuxPath: String,
)

/**
 * The Library tab's content: everything the agent wrote into a session workspace
 * (`minis-sessions/<id>/workspace` = `/var/minis/workspace`) or the shared folder
 * (`minis-global/shared` = `/var/minis/shared`), newest first. Muse splits this into
 * "artifacts" and "media"; so do we, by extension.
 */
object LibraryIndex {
    private const val MAX_DEPTH = 4
    private const val MAX_ENTRIES = 600
    private val skipDirs = setOf("node_modules", ".git", "__pycache__", ".cache", ".venv", "venv", ".npm")
    private val mediaExt = setOf(
        "png", "jpg", "jpeg", "gif", "bmp", "webp", "heic", "svg",
        "mp4", "mov", "avi", "mkv", "webm", "mp3", "wav", "aac", "flac", "ogg", "m4a",
    )

    suspend fun scan(context: Context, chatRepository: ChatRepository): List<LibraryEntry> = withContext(Dispatchers.IO) {
        val titles = runCatching { chatRepository.dao.listSessions().associate { it.id to (it.title ?: "") } }
            .getOrDefault(emptyMap())
        val out = ArrayList<LibraryEntry>()
        val sessionsRoot = File(context.filesDir, "minis-sessions")
        sessionsRoot.listFiles()?.forEach { sessionDir ->
            if (!sessionDir.isDirectory || sessionDir.name.startsWith("__new__")) return@forEach
            val ws = File(sessionDir, "workspace")
            if (ws.isDirectory) {
                walk(ws, 0) { f ->
                    out += entry(f, ws, "/var/minis/workspace", sessionDir.name, titles[sessionDir.name])
                }
            }
        }
        val shared = File(context.filesDir, "minis-global/shared")
        if (shared.isDirectory) {
            walk(shared, 0) { f -> out += entry(f, shared, "/var/minis/shared", null, null) }
        }
        out.sortByDescending { it.item.modifiedMs }
        out.take(MAX_ENTRIES)
    }

    private fun entry(f: File, root: File, linuxRoot: String, sessionId: String?, title: String?): LibraryEntry {
        val item = FileItem.from(f) ?: FileItem(f, f.name, false, false, f.length(), f.lastModified())
        val rel = f.relativeTo(root).path.replace(File.separatorChar, '/')
        val kind = if (f.extension.lowercase() in mediaExt) LibraryKind.MEDIA else LibraryKind.ARTIFACT
        return LibraryEntry(item, kind, sessionId, title?.takeIf { it.isNotBlank() }, "$linuxRoot/$rel")
    }

    private fun walk(dir: File, depth: Int, visit: (File) -> Unit) {
        if (depth > MAX_DEPTH) return
        val children = dir.listFiles() ?: return
        for (c in children) {
            val name = c.name
            if (name.startsWith(".") || name in skipDirs) continue
            if (c.isDirectory) walk(c, depth + 1, visit)
            else if (c.isFile && c.length() > 0) visit(c)
        }
    }
}
