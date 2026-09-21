package com.openminis.app.provider

import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ThinkingLevel

/**
 * [T-android-thinking-level-arch] Declarative catalog of each model's thinking-
 * level ceiling. Adding a model = adding a rule; retiring one = removing a rule.
 * It touches no other code path — a model that matches no rule falls back to
 * [catalogMaxThinkingLevel]'s conservative supportsReasoning default.
 *
 * Kept content-aligned with iOS ThinkingLevelCatalog.swift (same understanding
 * of what each model can do), Kotlin idiom on this side.
 */
object ThinkingLevelCatalog {
    private data class Rule(val match: (String) -> Boolean, val max: ThinkingLevel)

    private val rules: List<Rule> = listOf(
        // GPT-5.6 family: sol / terra / luna all reach MAX. ULTRA is a
        // client-side "Max + orchestration" concept, never a wire effort — the
        // effort layer maps both MAX and ULTRA to "max". Keep in lockstep with
        // iOS ThinkingLevelCatalog.swift.
        Rule({ it.startsWith("gpt-5.6-sol") || it.startsWith("gpt-5.6-terra") }, ThinkingLevel.MAX),
        Rule({ it.startsWith("gpt-5.6-luna") }, ThinkingLevel.MAX),
        Rule({ it.startsWith("gpt-5.5") }, ThinkingLevel.XHIGH),
        // Third-party models known to top out at high.
        // MiMo ships BOTH id spellings in the wild: catalog docs say
        // "MiMo-2.5" but the live API (api.xiaomimimo.com /v1/models) returns
        // "mimo-v2.5" / "mimo-v2.5-pro" — the old "mimo-2.5" substring missed
        // those, so the clamp passed xhigh straight through to a backend that
        // 400s on it. Match the family, not one spelling (mirrors iOS 72968c4f).
        Rule({ it.contains("mimo") || it.contains("agnes") }, ThinkingLevel.HIGH),
        // ByteDance seed (Volcano Ark "seed-1.6…"/"seed-2.0…", OpenRouter
        // "bytedance-seed/…"): rejects xhigh with "Invalid reasoning_effort:
        // xhigh". Ark's ladder tops out at high.
        Rule({ it.contains("seed-") || it.contains("bytedance-seed") }, ThinkingLevel.HIGH),
        // Anthropic Opus 4.x adaptive-thinking family. The old per-version
        // startsWith("claude-opus-4.7"/"claude-opus-4.6") checks never matched:
        // LLMModel.id separates the minor version with a hyphen
        // (claude-opus-4-8 / claude-opus-4-6), not a dot, so every Claude Opus
        // fell through to the XHIGH default instead of MAX — and Opus 4.8 had no
        // rule at all. Normalize dots→hyphens first, then a single prefix match
        // covers 4.6 / 4.7 / 4.8 and future 4.x (mirrors iOS normalizedHasPrefix).
        Rule({ normalizedHasPrefix(it, "claude-opus-4") }, ThinkingLevel.MAX),
    )

    /** Prefix match that treats "." and "-" interchangeably in the version
     *  separator so a rule matches whether the id is dotted or hyphenated. */
    private fun normalizedHasPrefix(id: String, prefix: String): Boolean =
        id.replace('.', '-').startsWith(prefix)

    /** Null means the catalog doesn't cover this model — the caller should fall
     *  through to the supportsReasoning default. */
    fun declaredMaxLevel(modelId: String): ThinkingLevel? {
        val lid = modelId.lowercase()
        return rules.firstOrNull { it.match(lid) }?.max
    }
}

/**
 * [T-android-thinking-level-arch] "How high can this model's thinking go?"
 * resolved through the built-in tiers only (no user override — see
 * [ModelEntry.effectiveMaxThinkingLevel] for that):
 *   1. supportsReasoning == false → OFF (checked BEFORE catalog rules so a
 *      broadened family rule can't lift a non-reasoning member's ceiling).
 *   2. ThinkingLevelCatalog rule.
 *   3. true/null → XHIGH (conservative default so a reasoning model isn't
 *      accidentally capped below the tiers every provider already accepted
 *      pre-GPT-5.6).
 */
val LLMModel.catalogMaxThinkingLevel: ThinkingLevel
    get() {
        // A model that can't reason has max level OFF regardless of any
        // catalog family rule — family rules match by id substring, so a
        // broadened rule (e.g. "mimo" covering mimo-v2.5) must not lift the
        // ceiling of that family's non-reasoning members (mimo-v2.5-tts/-asr).
        // [T-fallback-thinking-preclamp]
        if (supportsReasoning == false) return ThinkingLevel.OFF
        return ThinkingLevelCatalog.declaredMaxLevel(id) ?: ThinkingLevel.XHIGH
    }

/**
 * [T-android-thinking-level-arch] The four-level resolution the rest of the app
 * consults: the user's manual override on the entry (highest priority) wins over
 * the catalog/default. `entry.model` already folds ModelOverrides into the base
 * model, so read the ceiling off the resolved model there.
 */
val ModelEntry.effectiveMaxThinkingLevel: ThinkingLevel
    get() = overrides.maxThinkingLevel ?: model.catalogMaxThinkingLevel
