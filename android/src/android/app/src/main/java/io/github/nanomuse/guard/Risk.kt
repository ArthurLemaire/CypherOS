package io.github.nanomuse.guard

/**
 * What a tool call is about to do to the world. Ordered by how much it matters:
 * a command that both installs and pays is a payment.
 */
enum class RiskClass {
    /** Reads, computes, writes inside the sandbox. Runs without a word. */
    SAFE,
    /** Fetches software into the sandbox. Runs, and the user is told. */
    INSTALL,
    /** Removes the user's files or history. Asks. */
    DESTRUCTIVE,
    /** Sends something out: a message, a mail, a push, a form. Asks. */
    OUTBOUND,
    /** Moves money. Asks, every object separately. */
    MONEY,
}

/** Where a request came from; the card words itself differently for each. */
enum class GuardKind {
    SHELL,
    BROWSER,
    /** A tap on the phone's own screen, by the hands (0.1.12). [RiskRequest.pageUrl] carries the app. */
    SCREEN,
}

/**
 * The verdict on one call. [target] is the object a standing grant would be bound to — a
 * folder, a host, a recipient — so "always allow for X" means exactly X and nothing wider.
 * [warnings] are the always-ask flags (`rm -rf /`, `curl | sh`, force push): a call that
 * carries one is never waved through by a grant and offers none.
 */
data class RiskAssessment(
    val riskClass: RiskClass,
    val reason: String,
    val target: String? = null,
    val warnings: List<String> = emptyList(),
) {
    val needsApproval: Boolean
        get() = warnings.isNotEmpty() || riskClass == RiskClass.DESTRUCTIVE ||
            riskClass == RiskClass.OUTBOUND || riskClass == RiskClass.MONEY

    companion object {
        val SAFE = RiskAssessment(RiskClass.SAFE, "")

        /** The stronger of two verdicts, keeping every warning. */
        fun merge(a: RiskAssessment, b: RiskAssessment): RiskAssessment {
            val top = if (b.riskClass.ordinal > a.riskClass.ordinal) b else a
            val reasons = listOf(a, b).map { it.reason }.filter { it.isNotBlank() }.distinct()
            return top.copy(
                reason = reasons.take(3).joinToString("; "),
                warnings = (a.warnings + b.warnings).distinct(),
            )
        }
    }
}
