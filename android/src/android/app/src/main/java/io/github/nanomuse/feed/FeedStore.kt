package io.github.nanomuse.feed

import android.content.Context
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The feed on disk: `minis-global/nanomuse/feed/<day>/<NN>.md` posts and the one-paragraph
 * `feed-preferences.md` that steers them. Lives for the process; every write refreshes [posts].
 */
object FeedStore {
    private const val TAG = "Feed"
    private const val MAX_POSTS_PER_DAY = 12
    private const val KEEP_DAYS = 30

    private lateinit var root: File
    private lateinit var prefsFile: File
    private lateinit var appContext: Context

    private val _posts = MutableStateFlow<List<FeedPost>>(emptyList())
    /** Newest day first, then by index. */
    val posts: StateFlow<List<FeedPost>> = _posts

    private val _preferences = MutableStateFlow("")
    val preferences: StateFlow<String> = _preferences

    fun init(context: Context) {
        appContext = context.applicationContext
        val base = File(context.filesDir, "minis-global/nanomuse")
        root = File(base, "feed").apply { mkdirs() }
        prefsFile = File(base, "feed-preferences.md")
        reload()
    }

    fun reload() {
        val all = root.listFiles()?.filter(FeedPost::isDayDir)
            ?.sortedByDescending { it.name }
            ?.flatMap { day ->
                day.listFiles()?.mapNotNull(FeedPost::parse)?.sortedBy { it.index }.orEmpty()
            }.orEmpty()
        _posts.value = all
        _preferences.value = runCatching { prefsFile.takeIf { it.exists() }?.readText() }.getOrNull()
            ?.trim().orEmpty().ifEmpty { defaultPreferences() }
    }

    fun defaultPreferences(): String = appContext.getString(R.string.nm_feed_default_preferences)

    fun savePreferences(text: String) {
        runCatching {
            prefsFile.parentFile?.mkdirs()
            prefsFile.writeText(text.trim() + "\n")
        }.onFailure { AppLogger.warning(TAG, "preferences not saved: ${it.message}") }
        _preferences.value = text.trim().ifEmpty { defaultPreferences() }
    }

    fun setLiked(post: FeedPost, liked: Boolean) {
        val updated = post.copy(liked = liked)
        runCatching { post.file.writeText(updated.serialize()) }
            .onFailure { AppLogger.warning(TAG, "like not saved: ${it.message}") }
        _posts.value = _posts.value.map { if (it.file == post.file) updated else it }
    }

    fun delete(post: FeedPost) {
        runCatching { post.file.delete() }
        _posts.value = _posts.value.filterNot { it.file == post.file }
    }

    /** Writes a batch of posts for today, continuing today's numbering. Returns what was written. */
    fun append(drafts: List<Draft>, now: Long = System.currentTimeMillis()): List<FeedPost> {
        if (drafts.isEmpty()) return emptyList()
        val day = DAY.format(Date(now))
        val dir = File(root, day).apply { mkdirs() }
        var next = (dir.listFiles()?.mapNotNull { FeedPost.parse(it)?.index }?.maxOrNull() ?: 0) + 1
        val written = mutableListOf<FeedPost>()
        for (d in drafts) {
            if (next > MAX_POSTS_PER_DAY) break
            val file = File(dir, "%02d.md".format(next))
            val post = FeedPost(
                day = day, index = next, title = d.title.trim().take(80), type = d.type, emoji = d.emoji,
                body = d.body.trim(), source = d.source, createdAt = now, liked = false, file = file,
            )
            runCatching { file.writeText(post.serialize()) }
                .onSuccess { written += post; next++ }
                .onFailure { AppLogger.warning(TAG, "post not written: ${it.message}") }
        }
        prune()
        reload()
        AppLogger.info(TAG, "wrote ${written.size} post(s) for $day")
        return written
    }

    private fun prune() {
        val days = root.listFiles()?.filter(FeedPost::isDayDir)?.sortedByDescending { it.name }.orEmpty()
        days.drop(KEEP_DAYS).forEach { it.deleteRecursively() }
    }

    fun hasAnyPost(): Boolean = _posts.value.isNotEmpty()

    fun latestDay(): String? = _posts.value.firstOrNull()?.day

    data class Draft(
        val title: String,
        val type: String,
        val emoji: String,
        val body: String,
        val source: List<String>,
    )

    private val DAY = SimpleDateFormat("yyyy-MM-dd", Locale.US)
}
