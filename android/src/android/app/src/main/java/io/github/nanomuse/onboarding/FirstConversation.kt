package io.github.nanomuse.onboarding

import android.content.Context
import com.openminis.app.R
import com.openminis.app.agent.SoulMetadata
import com.openminis.app.agent.SoulStore
import com.openminis.app.data.repository.MemoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject

/**
 * The first conversation, the way Muse does it: no form. After the three setup cards the user
 * lands in the chat, the app speaks first (a scripted opening, zero tokens), asks what to call
 * them, and then — with the model doing the talking — asks what they would like to call it. A
 * name chooser card appears under that question; the pick is written to SOUL.md on the spot,
 * so the header changes before the model has even replied.
 *
 * The model, not a regex, decides what the user meant. Its reply carries a small
 * `nanomuse-naming` block when something happened — the form of address was given (with two
 * name suggestions for the agent, in the user's language), or the agent was named — and the
 * app moves the [Phase] on that. A reply without the block means the user talked about
 * something else: the model helps with it and steers back, and the phase stays where it is.
 *
 * Everything the app shows on its own behalf here is virtual: the opening and the card live in
 * the view model's message list only, never in the database and never in the model's history.
 * The model learns what happened through a short system-prompt addendum for the current phase.
 */
enum class Phase {
    /** Never started; eligible on the next fresh draft if the name is still the default. */
    NONE,

    /** The opening is on screen; the user is answering "what should I call you?". */
    ASK_USER_NAME,

    /** The model asked for its name; the chooser card is showing. */
    ASK_AGENT_NAME,

    /** The name was just picked from the chooser; the model's next reply is its first as itself. */
    NAMED,

    /** Over — either completed or the user talked past it. */
    DONE,
}

data class NamingCardState(val suggestions: List<String>, val chosen: String? = null)

/** What the model told the app in a `nanomuse-naming` block. */
data class NamingBlock(
    /** The block had a `user_address` key (null value = the user wants no form of address). */
    val addressGiven: Boolean,
    val userAddress: String?,
    /** Names the model suggests for itself, already cleaned. */
    val suggestions: List<String>,
    /** The name the user gave the agent, if this block says so. */
    val agentName: String?,
)

class FirstConversation(
    private val context: Context,
    private val memoryRepository: MemoryRepository?,
) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    var phase: Phase
        get() = prefs.getString(KEY_PHASE, null)?.let { runCatching { Phase.valueOf(it) }.getOrNull() } ?: Phase.NONE
        private set(value) {
            prefs.edit().putString(KEY_PHASE, value.name).apply()
        }

    /** The session (draft or real id) the conversation is bound to. */
    var sessionId: String?
        get() = prefs.getString(KEY_SESSION, null)
        private set(value) {
            prefs.edit().putString(KEY_SESSION, value).apply()
        }

    private val _namingCard = MutableStateFlow<NamingCardState?>(null)
    val namingCard: StateFlow<NamingCardState?> = _namingCard.asStateFlow()

    /** Whether the intro belongs in [sessionId]'s transcript — either it starts here or it already did. */
    fun shouldShowIntro(currentSessionId: String, hasOtherSessions: Boolean): Boolean {
        val bound = sessionId
        if (bound != null && phase != Phase.NONE) {
            // A dead draft (left before the first message) re-seeds in the next draft.
            return bound == currentSessionId ||
                (phase == Phase.ASK_USER_NAME && bound.startsWith("__new__") && currentSessionId.startsWith("__new__"))
        }
        return phase == Phase.NONE && !hasOtherSessions && SoulStore.load(context)?.metadata?.name == SoulMetadata.DEFAULT.name
    }

    /** Bind to [currentSessionId] and step into [Phase.ASK_USER_NAME] if this is the start. */
    fun start(currentSessionId: String) {
        sessionId = currentSessionId
        if (phase == Phase.NONE) phase = Phase.ASK_USER_NAME
        if (phase == Phase.ASK_AGENT_NAME) _namingCard.value = NamingCardState(currentSuggestions())
    }

    /** The draft became a real session: keep following it. */
    fun rebind(fromDraft: String, toReal: String) {
        if (sessionId == fromDraft) sessionId = toReal
    }

    fun isBoundTo(currentSessionId: String): Boolean = sessionId == currentSessionId && phase != Phase.NONE

    /** The three opening paragraphs, in the device language. */
    fun intro(): List<String> = listOf(
        context.getString(R.string.nm_intro_hello),
        context.getString(R.string.nm_intro_how_i_work),
        context.getString(R.string.nm_intro_ask_name),
    )

    /**
     * The model's reply just finished. Reads its `nanomuse-naming` block, if any, and moves the
     * phase; a reply without one leaves the phase alone (the user talked about something else,
     * and the model steered back). Returns true when the chooser should be (re)shown under this
     * reply.
     */
    fun afterTurn(assistantText: String?): Boolean {
        val block = parseBlock(assistantText)
        when (phase) {
            Phase.ASK_USER_NAME -> {
                if (block == null || !block.addressGiven) return false
                block.userAddress?.let { saveAddress(it) }
                if (block.suggestions.isNotEmpty()) saveSuggestions(block.suggestions)
                phase = Phase.ASK_AGENT_NAME
                _namingCard.value = NamingCardState(currentSuggestions())
                return true
            }
            Phase.ASK_AGENT_NAME -> {
                val name = block?.agentName
                if (name != null) {
                    // The model already replied as itself in this turn, so the ritual is over.
                    applyName(name)
                    phase = Phase.DONE
                    return false
                }
                return true
            }
            Phase.NAMED -> { phase = Phase.DONE; return false }
            else -> return false
        }
    }

    /** A chip was tapped: the name is saved at once; the model's next reply is its first as itself. */
    fun pick(name: String) {
        if (phase != Phase.ASK_AGENT_NAME) return
        applyName(name)
        phase = Phase.NAMED
    }

    /** The user moved on to something the app handles itself (an avatar change): drop the chooser. */
    fun dismissChooser() {
        if (phase == Phase.ASK_AGENT_NAME) {
            phase = Phase.DONE
            _namingCard.value = null
        }
    }

    private fun applyName(name: String) {
        val cur = SoulStore.load(context) ?: com.openminis.app.agent.SoulMDParser.parse(SoulStore.DEFAULT_CONTENT)
        SoulStore.save(context, cur.copy(metadata = cur.metadata.copy(name = name)))
        _namingCard.value = (_namingCard.value ?: NamingCardState(currentSuggestions())).copy(chosen = name)
    }

    /** The system-prompt addendum for the current phase; null once it is over. */
    fun promptAddendum(): String? {
        val address = prefs.getString(KEY_ADDRESS, null)
        val addressLine = if (address != null) " The user goes by \"$address\" — address them that way." else ""
        return when (phase) {
            Phase.ASK_USER_NAME -> buildString {
                append("First conversation. The app already showed the user this opening on your behalf:\n")
                intro().forEach { append("  > ").append(it.replace("\n", "\n  > ")).append('\n') }
                append("They are now replying to the last line (what should I call you?). Decide from their message what they meant:\n")
                append("(a) If it says how to address them — a name, a nickname, \"just call me boss\" — confirm it in one short sentence, ")
                append("ask in one sentence what they would like to call you, and end the reply with exactly this fenced block:\n")
                append("```$BLOCK\n{\"user_address\": \"<how to address them>\", \"suggest\": [\"<name 1>\", \"<name 2>\"]}\n```\n")
                append("`suggest` holds two names for yourself the user could pick, in the language they write: two-character Chinese names ")
                append("in the spirit of 豆丁 or 小满 (warm, a little playful, easy to say) when they write Chinese; short English names like Pip or Wren otherwise. ")
                append("Never suggest the name of an existing assistant or product ($TAKEN_NAMES), nor the user's own name. ")
                append("The app renders the block as a chooser under your reply, so do not list the names in your text.\n")
                append("(b) If they say they would rather not be called anything in particular, do the same with \"user_address\": null.\n")
                append("(c) If the message is about something else — a question, a task, small talk — help with it first, in full, ")
                append("and end with one light sentence bringing the question back (what should I call you?). No block in that case; the app keeps waiting.\n")
                append("Reply in the user's language; keep it short.")
            }
            Phase.ASK_AGENT_NAME -> buildString {
                val chips = currentSuggestions()
                append("First conversation. You asked what the user would like to call you; the app is showing a chooser under that question with ")
                append(chips.joinToString(", ") { "\"$it\"" }).append(" and \"something else\". Decide from their message:\n")
                append("(a) If it gives you a name — typed on its own, \"call you 豆丁\", \"the first one\" (meaning \"").append(chips.firstOrNull().orEmpty()).append("\") — ")
                append("that is your name from now on. Reply as yourself: one short line about the name, then three bullets with the most useful things you can do ")
                append("for them right now on this phone (choose from: running commands in your Linux sandbox, browsing websites and filling forms, ")
                append("reading and organising files and photos they mount, setting reminders and scheduled tasks, searching the web), one concrete line each, no emoji; ")
                append("end by asking what they want to try first. Then end the reply with exactly this fenced block:\n")
                append("```$BLOCK\n{\"agent_name\": \"<the name>\"}\n```\n")
                append("The app saves the name to SOUL.md from the block — do not call minis-config for it.\n")
                append("(b) If the message is about something else, help with it first, in full, and end with one light sentence bringing the naming back; ")
                append("no block, the chooser stays.\n")
                append("Reply in the user's language.").append(addressLine)
            }
            Phase.NAMED -> {
                val name = SoulStore.load(context)?.metadata?.name ?: SoulMetadata.DEFAULT.name
                "First conversation. The user just named you \"$name\" — the app already saved it to SOUL.md, so it is your name now; do not call minis-config for it. " +
                    "Reply in the user's language: one short line about the name, then three bullets with the most useful things you can do for them right now on this phone " +
                    "(choose from: running commands in your Linux sandbox, browsing websites and filling forms, reading and organising files and photos they mount, " +
                    "setting reminders and scheduled tasks, searching the web). One concrete line each, no emoji. End by asking what they want to try first." + addressLine
            }
            Phase.NONE, Phase.DONE -> null
        }
    }

    private fun saveAddress(address: String) {
        prefs.edit().putString(KEY_ADDRESS, address).apply()
        val repo = memoryRepository ?: return
        runCatching {
            val current = repo.loadGlobalMd()
            val line = "- Call them: $address"
            val updated = when {
                current.lines().any { it.trim().startsWith("- Call them:") } ->
                    current.lines().joinToString("\n") { if (it.trim().startsWith("- Call them:")) line else it }
                current.isBlank() -> "## About the user\n$line\n"
                else -> current.trimEnd() + "\n\n## About the user\n$line\n"
            }
            repo.saveGlobalMd(updated)
        }
    }

    private fun saveSuggestions(names: List<String>) {
        prefs.edit().putString(KEY_SUGGESTIONS, names.joinToString("\n")).apply()
    }

    /** The model's suggestions when it gave some; otherwise two from the bundled pool, in the device language. */
    private fun currentSuggestions(): List<String> {
        prefs.getString(KEY_SUGGESTIONS, null)?.split('\n')?.filter { it.isNotBlank() }?.takeIf { it.isNotEmpty() }?.let { return it }
        val pool = context.resources.getStringArray(R.array.nm_name_suggestions).toList()
        val seed = (sessionId ?: "").hashCode()
        return pool.shuffled(java.util.Random(seed.toLong())).take(2)
    }

    companion object {
        const val BLOCK = "nanomuse-naming"
        private const val PREFS = "nanomuse"
        private const val KEY_PHASE = "first_conversation.phase"
        private const val KEY_SESSION = "first_conversation.session"
        private const val KEY_ADDRESS = "first_conversation.address"
        private const val KEY_SUGGESTIONS = "first_conversation.suggestions"
        private const val TAKEN_NAMES = "Siri, Alexa, Cortana, Jarvis, Muse, Gemini, Copilot, 小爱, 小度, 小艺, 天猫精灵, 豆包, 文心, 通义, 阿福"
        private const val MAX_NAME = 16

        private val blockRegex = Regex("```$BLOCK[ \\t]*\\r?\\n([\\s\\S]*?)```")
        private val QUOTES = Regex("^[\\s\"'“”‘’「」『』]+|[\\s\"'“”‘’「」『』。，、！!？?.]+$")

        /** The last `nanomuse-naming` block in [text], or null when there is none or it is not JSON. */
        fun parseBlock(text: String?): NamingBlock? {
            if (text.isNullOrEmpty() || !text.contains("```$BLOCK")) return null
            val json = blockRegex.findAll(text).lastOrNull()?.groupValues?.get(1) ?: return null
            val o = runCatching { JSONObject(json.trim()) }.getOrNull() ?: return null
            val suggestions = o.optJSONArray("suggest")?.let { arr ->
                (0 until arr.length()).mapNotNull { cleanName(arr.optString(it)) }.distinct().take(3)
            }.orEmpty()
            return NamingBlock(
                addressGiven = o.has("user_address"),
                userAddress = if (o.isNull("user_address")) null else cleanName(o.optString("user_address")),
                suggestions = suggestions,
                agentName = if (o.isNull("agent_name")) null else cleanName(o.optString("agent_name")),
            )
        }

        /** A usable name: one line, quotes and trailing punctuation gone, not absurdly long. */
        fun cleanName(raw: String?): String? {
            val t = raw?.replace(QUOTES, "")?.trim() ?: return null
            if (t.isEmpty() || t.contains('\n') || t.length > MAX_NAME) return null
            return t
        }
    }
}
