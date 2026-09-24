package io.github.nanomuse.ideas

import android.content.Context
import com.openminis.app.logging.AppLogger
import org.json.JSONObject
import java.util.Locale

/** What tapping an idea creates: a message in the main chat, a routine, or a goal conversation. */
enum class IdeaKind { CHAT, ROUTINE, GOAL }

data class Idea(
    val id: String,
    val emoji: String,
    val title: String,
    val body: String,
    val kind: IdeaKind,
    /** What is sent to the agent (chat / goal) or becomes the routine's prompt. */
    val prompt: String,
    /** Routine default: "HH:MM". */
    val time: String? = null,
    /** Goal default category key, see GoalCategory. */
    val category: String? = null,
)

data class IdeaSection(val id: String, val title: String, val ideas: List<Idea>)

/**
 * The Ideas tab content: `assets/nanomuse/ideas.<lang>.json`, picked by the app's locale
 * (zh-TW reads the zh file). Curated, not generated — these are the things a phone-local agent
 * can actually do today.
 */
object Ideas {
    private const val TAG = "nanoMuse.Ideas"

    fun load(context: Context): List<IdeaSection> {
        val lang = context.resources.configuration.locales[0]?.language ?: Locale.getDefault().language
        val name = if (lang == "zh") "nanomuse/ideas.zh.json" else "nanomuse/ideas.en.json"
        return runCatching {
            val text = context.assets.open(name).bufferedReader().use { it.readText() }
            val root = JSONObject(text)
            val sections = root.getJSONArray("sections")
            buildList {
                for (i in 0 until sections.length()) {
                    val s = sections.getJSONObject(i)
                    val ideasArr = s.getJSONArray("ideas")
                    val ideas = buildList {
                        for (j in 0 until ideasArr.length()) {
                            val o = ideasArr.getJSONObject(j)
                            add(
                                Idea(
                                    id = o.getString("id"),
                                    emoji = o.optString("emoji", "✨"),
                                    title = o.getString("title"),
                                    body = o.optString("body", ""),
                                    kind = runCatching { IdeaKind.valueOf(o.optString("kind", "CHAT").uppercase()) }.getOrDefault(IdeaKind.CHAT),
                                    prompt = o.optString("prompt", o.getString("title")),
                                    time = o.optString("time", null).takeIf { !it.isNullOrBlank() },
                                    category = o.optString("category", null).takeIf { !it.isNullOrBlank() },
                                ),
                            )
                        }
                    }
                    add(IdeaSection(s.getString("id"), s.getString("title"), ideas))
                }
            }
        }.onFailure { AppLogger.warning(TAG, "$name unreadable: ${it.message}") }.getOrDefault(emptyList())
    }
}
