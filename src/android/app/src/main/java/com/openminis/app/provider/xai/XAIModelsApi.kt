package com.openminis.app.provider.xai

import com.openminis.app.data.model.LLMModel
import com.openminis.app.logging.AppLogger
import com.openminis.app.provider.ModelsDevApi

/**
 * Static catalog of xAI (Grok) models exposed to OAuth users.
 *
 * Unlike OpenAI/Anthropic, the xAI Console doesn't gate `/v1/models` for
 * OAuth bearer holders, but the spec /tmp/grok-oauth-design.md §6 fixes
 * the user-facing default list to a known-good set so the Add Provider
 * step doesn't depend on a network round-trip. Returned in the exact
 * priority order the UI should display.
 *
 * The same set is the [LLMModel.allXAI] companion list — keep them in
 * sync. Returned through [ModelsDevApi.enrichModels] so context window
 * / modality metadata fills in from the shared catalog.
 */
object XAIModelsApi {
    private const val TAG = "XAIModelsApi"

    /** Static fallback used when /v1/models is unreachable or untrusted. */
    fun fetchModelsOAuth(): List<LLMModel> {
        val models = LLMModel.allXAI
        AppLogger.info(TAG, "xAI OAuth model list (${models.size} models): ${models.joinToString { it.id }}")
        return ModelsDevApi.enrichModels(models)
    }
}
