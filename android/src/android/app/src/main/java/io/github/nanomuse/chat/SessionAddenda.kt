package io.github.nanomuse.chat

/**
 * Short-lived system-prompt addenda, per session. A feature (the Goals tab, an idea card) can
 * steer the next few turns of a conversation without touching the cacheable prefix of the prompt:
 * ChatViewModel.buildSystemPrompt appends [forPrompt] last, and [onTurnFinished] counts the
 * turns down. Process-lifetime, main-thread + agent-loop access, so it is synchronized.
 */
object SessionAddenda {
    data class Addendum(val tag: String, val text: String, var turnsLeft: Int)

    private val bySession = HashMap<String, MutableList<Addendum>>()

    @Synchronized
    fun add(sessionId: String, tag: String, text: String, turns: Int) {
        val list = bySession.getOrPut(sessionId) { mutableListOf() }
        list.removeAll { it.tag == tag }
        list += Addendum(tag, text, turns)
    }

    @Synchronized
    fun remove(sessionId: String, tag: String) {
        bySession[sessionId]?.removeAll { it.tag == tag }
    }

    @Synchronized
    fun has(sessionId: String, tag: String): Boolean =
        bySession[sessionId]?.any { it.tag == tag } == true

    @Synchronized
    fun forPrompt(sessionId: String): String? {
        val list = bySession[sessionId]?.filter { it.turnsLeft > 0 } ?: return null
        if (list.isEmpty()) return null
        return list.joinToString("\n\n") { it.text }
    }

    @Synchronized
    fun onTurnFinished(sessionId: String) {
        val list = bySession[sessionId] ?: return
        list.forEach { it.turnsLeft-- }
        list.removeAll { it.turnsLeft <= 0 }
        if (list.isEmpty()) bySession.remove(sessionId)
    }

    /** A draft became a real session: carry its addenda over. */
    @Synchronized
    fun rebind(fromSessionId: String, toSessionId: String) {
        val list = bySession.remove(fromSessionId) ?: return
        bySession.getOrPut(toSessionId) { mutableListOf() }.addAll(list)
    }
}
