package io.github.nanomuse.onboarding

import android.content.Context
import com.openminis.app.R
import com.openminis.app.agent.SoulMetadata
import com.openminis.app.agent.SoulStore
import com.openminis.app.data.repository.MemoryRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The first conversation, the way Muse does it: no form. After the three setup cards the user
 * lands in the chat, the app speaks first (a scripted opening, zero tokens), asks what to call
 * them, and then — with the model doing the talking — asks what they would like to call it. A
 * name chooser card appears under that question; the pick is written to SOUL.md on the spot,
 * so the header changes before the model has even replied.
 *
 * Everything the app shows on its own behalf here is virtual: the opening and the card live in
 * the view model's message list only, never in the database and never in the model's history.
 * The model learns what happened through a short system-prompt addendum for the current
 * [Phase], which keeps every provider happy (some reject a history that opens with the
 * assistant) and costs a few dozen tokens for two turns.
 */
enum class Phase {
    /** Never started; eligible on the next fresh draft if the name is still the default. */
    NONE,

    /** The opening is on screen; the user is answering "what should I call you?". */
    ASK_USER_NAME,

    /** The model asked for its name; the chooser card is showing. */
    ASK_AGENT_NAME,

    /** The name was just written; the model's next reply is its first as itself. */
    NAMED,

    /** Over — either completed or the user talked past it. */
    DONE,
}

data class NamingCardState(val suggestions: List<String>, val chosen: String? = null)

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
        if (phase == Phase.ASK_AGENT_NAME) _namingCard.value = NamingCardState(suggestions())
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
     * The user answered "what should I call you?". Saves a short answer as their form of address
     * (GLOBAL.md, which the model reads every session) and moves on; a long answer is left for
     * the model to interpret.
     */
    fun onUserNameReply(text: String) {
        if (phase != Phase.ASK_USER_NAME) return
        extractAddress(text)?.let { saveAddress(it) }
    }

    /** The model's turn after the address question ended: show the chooser. */
    fun onTurnFinished() {
        when (phase) {
            Phase.ASK_USER_NAME -> {
                phase = Phase.ASK_AGENT_NAME
                _namingCard.value = NamingCardState(suggestions())
            }
            Phase.NAMED -> phase = Phase.DONE
            else -> Unit
        }
    }

    /**
     * What to do with a message typed while the chooser is showing. A name-shaped message names
     * the agent; anything else dismisses the chooser and goes through as a normal message.
     */
    fun interceptWhileChoosing(text: String): String? {
        if (phase != Phase.ASK_AGENT_NAME) return null
        val name = extractAgentName(text) ?: run {
            phase = Phase.DONE
            _namingCard.value = null
            return null
        }
        applyName(name)
        return name
    }

    /** A chip was tapped. */
    fun pick(name: String) {
        if (phase != Phase.ASK_AGENT_NAME) return
        applyName(name)
    }

    private fun applyName(name: String) {
        val cur = SoulStore.load(context) ?: com.openminis.app.agent.SoulMDParser.parse(SoulStore.DEFAULT_CONTENT)
        SoulStore.save(context, cur.copy(metadata = cur.metadata.copy(name = name)))
        _namingCard.value = (_namingCard.value ?: NamingCardState(suggestions())).copy(chosen = name)
        phase = Phase.NAMED
    }

    /** The system-prompt addendum for the current phase; null once it is over. */
    fun promptAddendum(): String? {
        val address = prefs.getString(KEY_ADDRESS, null)
        val addressLine = if (address != null) " The user goes by \"$address\" — address them that way." else ""
        return when (phase) {
            Phase.ASK_USER_NAME -> buildString {
                append("First conversation. The app already showed the user this opening on your behalf:\n")
                intro().forEach { append("  > ").append(it.replace("\n", "\n  > ")).append('\n') }
                append("They are now replying to the last line.")
                if (address != null) {
                    append(" The app saved their form of address (\"").append(address).append("\").")
                } else {
                    append(" If their message says how they want to be addressed, remember it with memory_write.")
                }
                append(" Confirm in one short sentence, then ask in one sentence what they would like to call you.")
                append(" The app shows name suggestions right under your reply, so do not list any names yourself.")
                append(" If the message is about something else, just help with it and skip the ritual.")
                append(" Reply in the user's language. Two short sentences at most.")
            }
            Phase.ASK_AGENT_NAME ->
                "First conversation. You asked what the user would like to call you; the app is showing a name chooser under that message. " +
                    "If they talk about something else, answer normally and do not push the naming." + addressLine
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

    private fun suggestions(): List<String> {
        val pool = context.resources.getStringArray(R.array.nm_name_suggestions).toList()
        val seed = (sessionId ?: "").hashCode()
        return pool.shuffled(java.util.Random(seed.toLong())).take(2)
    }

    companion object {
        private const val PREFS = "nanomuse"
        private const val KEY_PHASE = "first_conversation.phase"
        private const val KEY_SESSION = "first_conversation.session"
        private const val KEY_ADDRESS = "first_conversation.address"

        private val TRAILING_PUNCTUATION = Regex("[\\s。，、！!？?.~～…\"'“”‘’「」『』]+$")
        private val LEADING_QUOTES = Regex("^[\\s\"'“”‘’「」『』]+")
        private val ADDRESS_PREFIX = Regex(
            "^(?:你(?:可以|就)?)?(?:叫我|喊我|称呼我|称我|管我叫|叫)\\s*|^(?:我叫|我是|我的名字是|我名字叫|我姓)\\s*|" +
                "^(?:(?:you can |just |please )?call me|i am|i'm|im|my name is|my name's|it's|this is|name's)\\s+",
            RegexOption.IGNORE_CASE,
        )
        private val ADDRESS_SUFFIX = Regex("(?:吧|就行|就好|好了|即可|就可以|哦|呀|啦|呗|就成|please|will do|is fine)$", RegexOption.IGNORE_CASE)
        private val AGENT_NAME_PREFIX = Regex(
            "^(?:那|就|那就|你|你就|我)?(?:叫你|叫|喊你|称呼你|管你叫|名字叫|你的名字是|你就叫|就叫)\\s*|" +
                "^(?:(?:let's |i'll |i will |i'd like to |we'll )?(?:call|name) you|you are|you're|your name is|how about|what about|maybe)\\s+",
            RegexOption.IGNORE_CASE,
        )
        private val AGENT_NAME_SUFFIX = Regex(
            "(?:吧|好了|怎么样|怎样|如何|好不好|行不行|可以吗|行吗|好吗|呗|就行|就好|then|ok|okay|maybe|sounds good|\\?)$",
            RegexOption.IGNORE_CASE,
        )
        private val CJK = Regex("[\\p{IsHan}\\p{IsHiragana}\\p{IsKatakana}\\p{IsHangul}]")

        /** "叫我老板" → "老板", "call me Kevin" → "Kevin", a long sentence → null. */
        fun extractAddress(raw: String): String? {
            var t = raw.trim().replace(LEADING_QUOTES, "").replace(TRAILING_PUNCTUATION, "")
            if (t.isEmpty() || t.contains('\n')) return null
            val matched = ADDRESS_PREFIX.containsMatchIn(t)
            t = t.replace(ADDRESS_PREFIX, "").trim().replace(ADDRESS_SUFFIX, "").trim().replace(TRAILING_PUNCTUATION, "")
            return t.takeIf { it.isNotEmpty() && looksLikeName(it, matched, maxCjk = 8, maxLatin = 24) }
        }

        /** "就叫你阿福吧" → "阿福", "Hana" → "Hana", "帮我查天气" → null. */
        fun extractAgentName(raw: String): String? {
            var t = raw.trim().replace(LEADING_QUOTES, "").replace(TRAILING_PUNCTUATION, "")
            if (t.isEmpty() || t.contains('\n') || t.contains('?') || t.contains('？')) return null
            val matched = AGENT_NAME_PREFIX.containsMatchIn(t)
            t = t.replace(AGENT_NAME_PREFIX, "").trim().replace(AGENT_NAME_SUFFIX, "").trim().replace(TRAILING_PUNCTUATION, "")
            return t.takeIf { it.isNotEmpty() && it.length <= 20 && looksLikeName(it, matched, maxCjk = 6, maxLatin = 20) }
        }

        /**
         * A name is short and has no sentence structure. After an explicit prefix ("call me …")
         * we accept a little more; a bare message must be very short to count.
         */
        private fun looksLikeName(t: String, afterPrefix: Boolean, maxCjk: Int, maxLatin: Int): Boolean {
            if (t.any { it == '，' || it == '。' || it == ',' || it == '；' || it == ';' || it == ':' || it == '：' }) return false
            val cjk = CJK.containsMatchIn(t)
            val words = t.split(Regex("\\s+")).size
            return if (cjk) {
                t.length <= (if (afterPrefix) maxCjk else maxCjk - 2).coerceAtLeast(2) && words <= 2
            } else {
                t.length <= maxLatin && words <= (if (afterPrefix) 3 else 2)
            }
        }
    }
}
