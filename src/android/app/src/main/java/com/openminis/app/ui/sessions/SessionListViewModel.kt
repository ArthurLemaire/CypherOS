package com.openminis.app.ui.sessions

import android.content.Context
import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.ThinkingLevel
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.data.repository.ProviderRepository
import com.openminis.app.provider.ProviderFactory
import com.openminis.app.ui.chat.ChatViewModelStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

@OptIn(FlowPreview::class)
class SessionListViewModel(
    private val chatRepository: ChatRepository,
    private val providerRepository: ProviderRepository,
    private val context: Context,
) : ViewModel() {

    companion object {
        private const val TAG = "SessionListVM"

        /**
         * Factory for use with `androidx.lifecycle.viewmodel.compose.viewModel`.
         * Hosting the VM on the NavBackStackEntry's ViewModelStore (instead of
         * `remember {}` inside the composable) is what lets [searchQuery] and
         * [isSearchActive] survive navigation push/pop — the user can tap a
         * session in the search results, view it, and pop back to find the
         * filter still applied. Mirrors iOS where ContentView's `@State
         * searchText` survives because the parent view does not unmount during
         * a NavigationLink push.
         */
        fun factory(
            chatRepository: ChatRepository,
            providerRepository: ProviderRepository,
            appContext: Context,
        ): ViewModelProvider.Factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                return SessionListViewModel(
                    chatRepository = chatRepository,
                    providerRepository = providerRepository,
                    context = appContext,
                ) as T
            }
        }
    }

    private val _allSessions = MutableStateFlow<List<ChatSessionEntity>>(emptyList())

    /**
     * Tracks whether the first DB emission has landed. Before this flips true
     * the session list is "unknown" — not "empty". Callers (e.g. onboarding
     * gate) must wait for this before deciding the user has no history,
     * otherwise the onboarding UI flashes on launch for users with existing
     * sessions. Mirrors iOS `didInitialLoad` on ContentView.
     */
    private val _isInitialLoadComplete = MutableStateFlow(false)
    val isInitialLoadComplete: StateFlow<Boolean> = _isInitialLoadComplete.asStateFlow()

    // Search
    val searchQuery = MutableStateFlow("")
    val isSearchActive = MutableStateFlow(false)
    val searchResults = MutableStateFlow<List<ChatSessionEntity>>(emptyList())

    /**
     * True while the user has typed something but the debounced search query
     * has not yet finalised + run. Drives the trailing CircularProgressIndicator
     * in the search field so a slow query (or fast typing) shows visible
     * progress instead of a stale-results-then-snap transition. Cleared the
     * moment a query resolves to results (or to empty when query is blank).
     */
    val isSearching = MutableStateFlow(false)

    /**
     * Per-session content snippet centred on the search-query match. Only
     * populated for sessions whose match is in message content (not just the
     * title). Cleared whenever the search query goes blank. Keyed by
     * session id; absent entries mean "title-only match — no snippet needed".
     */
    val searchSnippets = MutableStateFlow<Map<String, String>>(emptyMap())

    // The list to actually show: search results when searching, otherwise all sessions
    val displayedSessions: StateFlow<List<ChatSessionEntity>> = combine(
        _allSessions, searchResults, searchQuery, isSearchActive
    ) { all, results, q, active ->
        if (active && q.isNotBlank()) results else all
    }.stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    // Multi-select
    val isSelecting = MutableStateFlow(false)
    val selectedIds = MutableStateFlow<Set<String>>(emptySet())

    // Session IDs currently regenerating their titles (UI overlay)
    val regeneratingIds = MutableStateFlow<Set<String>>(emptySet())

    // [T-android-newchat-list-autoscroll] One-shot signal: a session id that
    // we have never seen before has appeared at the TOP of the list (the list
    // is ORDER BY updated_at DESC, so a brand-new chat lands at index 0). The
    // UI collects this and scrolls the list to the top so the new chat is
    // visible — needed because the LazyColumn keeps its old scroll offset
    // across navigation (open chat → back). Lives in the VM (retained across
    // navigation) so the baseline isn't reset when the list composable is
    // disposed during the chat-detail push, which a composable-scoped tracker
    // would lose. extraBufferCapacity=1 + DROP_OLDEST so an emission that
    // happens while the UI isn't collecting (mid-navigation) is still
    // delivered on the next collect.
    val newTopSessionEvent = kotlinx.coroutines.flow.MutableSharedFlow<Unit>(
        replay = 0,
        extraBufferCapacity = 1,
        onBufferOverflow = kotlinx.coroutines.channels.BufferOverflow.DROP_OLDEST,
    )

    // Baseline of session ids already observed. Seeded on the FIRST emission
    // (so pre-existing sessions never fire the event); thereafter any id not
    // in this set that lands at index 0 is a genuinely-new session.
    private var knownSessionIds: Set<String> = emptySet()
    private var newTopBaselineSeeded = false

    init {
        // T-android-crash-safe-mode-v2: gate the cold-start session list
        // observer behind the safe-mode flag. The Room observable issues a
        // full SELECT on first collect; if a malformed row was contributing
        // to the crash burst, we don't want to re-deserialize it before the
        // user has acknowledged the share-logs dialog.
        viewModelScope.launch {
            if (com.openminis.app.crash.CrashFrequencyDetector.isSafeMode()) {
                android.util.Log.w(
                    TAG,
                    "SessionListVM init: safe-mode active, deferring observeSessions",
                )
                // Mark initial-load complete so the empty-state UI surfaces
                // immediately (rather than an indefinite progress spinner).
                _isInitialLoadComplete.value = true
                // Subscribe for the safe-mode-cleared signal and then begin
                // observing. registerSafeModeClearedListener fires exactly
                // once on ON → OFF; after that we start the Flow collector
                // for the rest of the VM's life.
                val started = kotlinx.coroutines.CompletableDeferred<Unit>()
                val unsub = com.openminis.app.crash.CrashFrequencyDetector
                    .registerSafeModeClearedListener {
                        if (!started.isCompleted) started.complete(Unit)
                    }
                started.await()
                runCatching { unsub() }
            }
            chatRepository.observeSessions().collect {
                _allSessions.value = it
                if (!_isInitialLoadComplete.value) _isInitialLoadComplete.value = true
                detectNewTopSession(it)
            }
        }
        viewModelScope.launch {
            combine(searchQuery, isSearchActive) { q, active -> q to active }
                .distinctUntilChanged()
                .onEach { (q, active) ->
                    // Flip [isSearching] true the moment a meaningful query
                    // arrives, BEFORE debounce. The trailing CircularProgress
                    // shows up immediately when the user types, hiding the
                    // small gap until the debounced search runs.
                    isSearching.value = active && q.isNotBlank()
                }
                .debounce(300)
                .collect { (q, active) ->
                    if (active && q.isNotBlank()) {
                        val results = chatRepository.searchSessions(q)
                        searchResults.value = results
                        // Compute per-session content snippets off the main
                        // thread. Sessions whose title already matches don't
                        // need a snippet — we only walk messages when the
                        // title doesn't contain the query.
                        val snips = withContext(Dispatchers.IO) {
                            buildContentSnippets(results, q)
                        }
                        searchSnippets.value = snips
                    } else {
                        searchResults.value = emptyList()
                        searchSnippets.value = emptyMap()
                    }
                    isSearching.value = false
                }
        }
    }

    fun toggleSelect(id: String) {
        selectedIds.value = selectedIds.value.toMutableSet().also {
            if (id in it) it.remove(id) else it.add(id)
        }
    }

    /**
     * [T-android-sessionlist-longpress-select] Long-press → Select: enter
     * selection mode WITH this row selected. ADD semantics, not toggle — if
     * the id is somehow already in the set, tapping Select must still select
     * it. The context-menu item previously only toggled the id into
     * [selectedIds] without ever setting [isSelecting], so the list never
     * showed checkboxes and the id sat invisibly pre-selected.
     */
    fun enterSelection(id: String) {
        selectedIds.value = selectedIds.value + id
        isSelecting.value = true
    }

    fun selectAll() {
        selectedIds.value = _allSessions.value.map { it.id }.toSet()
    }

    fun clearSelection() {
        selectedIds.value = emptySet()
        isSelecting.value = false
    }

    fun deleteSelected() {
        val ids = selectedIds.value.toList()
        viewModelScope.launch {
            ids.forEach {
                chatRepository.deleteSession(it)
                ChatViewModelStore.release(it)
                // [T-android-session-paused-badge] Drop badges for the
                // deleted session so persisted PAUSED entries don't leak
                // forever in SharedPreferences.
                com.openminis.app.service.SessionBadgeStore.clear(it)
            }
        }
        clearSelection()
    }

    fun deleteSession(id: String) {
        viewModelScope.launch {
            chatRepository.deleteSession(id)
            ChatViewModelStore.release(id)
            com.openminis.app.service.SessionBadgeStore.clear(id)
        }
    }

    fun togglePin(id: String) {
        viewModelScope.launch {
            val session = chatRepository.getSession(id) ?: return@launch
            val newPinnedAt = if (session.pinnedAt != null) null else System.currentTimeMillis()
            chatRepository.dao.updatePinnedAt(id, newPinnedAt)
        }
    }

    fun updateTitleAndCategory(id: String, title: String, category: String?) {
        viewModelScope.launch {
            chatRepository.updateSessionTitleAndCategory(id, title, category)
        }
    }

    fun regenerateTitle(id: String) {
        viewModelScope.launch(Dispatchers.IO) {
            withContext(Dispatchers.Main) {
                regeneratingIds.value = regeneratingIds.value + id
            }
            try {
                val session = chatRepository.getSession(id) ?: return@launch
                val messages = chatRepository.loadMessages(id)
                if (messages.isEmpty()) return@launch

                // [T-titlegen-context-first-last-pair] Summary = first user +
                // first assistant, plus (when the session has more than one user
                // turn) the last user + last assistant, each truncated to 200
                // chars — so a regenerated title reflects a mid/late topic shift
                // rather than only the opener.
                val userMessages = messages.filter { it.role == "user" }
                val userText = userMessages.firstOrNull()?.let { extractText(it.partsJson) }?.take(200) ?: return@launch
                // First/last assistant *text* message — skip tool-only messages
                // whose extracted text is blank so the summary carries real prose.
                val assistantTexts = messages.filter { it.role == "assistant" }
                    .map { extractText(it.partsJson) }
                    .filter { it.isNotBlank() }
                val firstAssistantText = assistantTexts.firstOrNull()?.take(200) ?: ""
                val hasMultipleUserTurns = userMessages.size > 1
                val lastUserText = if (hasMultipleUserTurns) userMessages.lastOrNull()?.let { extractText(it.partsJson) }?.take(200) ?: "" else ""
                val lastAssistantText = if (hasMultipleUserTurns) assistantTexts.lastOrNull()?.take(200) ?: "" else ""

                val prompt = buildString {
                    append("Based on the following conversation, generate a short title (max 6 words) that captures the topic. ")
                    append("Also pick a task category from: code, writing, research, analysis, creative, chat, math, translation, health, finance, travel, education, design, productivity, support, other.\n\n")
                    append("You MUST respond with valid JSON only. Example:\n")
                    append("{\"title\": \"Debug Login Page Issue\", \"category\": \"code\"}\n\n")
                    append("User: $userText\n")
                    if (firstAssistantText.isNotEmpty()) append("Assistant: $firstAssistantText\n")
                    if (lastUserText.isNotEmpty()) append("User: $lastUserText\n")
                    if (lastAssistantText.isNotEmpty()) append("Assistant: $lastAssistantText\n")
                    append(com.openminis.app.ui.chat.titleLanguageDirective())
                }

                // Build candidate list: session's model first, then all others.
                // T334: filter out non-text-output models (tts/voiceclone/voicedesign/image/video/audio-only)
                // and models whose id obviously names a non-chat capability — they either reject the
                // chat/completions schema with HTTP 400 or stream nothing useful, masking the real result
                // with a misleading "Param Incorrect" tail error.
                val allEntries = providerRepository.allVisibleEntries()
                val titleEligible = allEntries.filter { entry ->
                    val outs = entry.model.outputModalities
                    val outputsText = outs == null || outs.isEmpty() || outs.contains("text")
                    val idLower = entry.model.id.lowercase()
                    val nonChatId = listOf("tts", "voiceclone", "voicedesign", "embedding", "embed-", "whisper", "image", "video")
                        .any { idLower.contains(it) }
                    outputsText && !nonChatId
                }
                // [T-android-regenerate-title-submodel] Priority: dedicated
                // title sub-model (defaultSubGroupId's first enabled member) >
                // session's bound primary model > every other eligible model.
                // Aligns the manual Regenerate path with the auto-title path
                // (ChatViewModel.resolveTitleProvider) and iOS resolveSubEntry —
                // previously the sub-model was ignored here, so users who
                // configured a cheap/fast title model still paid for the primary.
                // The sub-entry must pass the same T334 modality filter; when no
                // sub-group is configured / all members disabled it's null and we
                // fall through to the existing primary-first ordering.
                val subEntry = providerRepository.resolveTitleSubEntry()
                    ?.takeIf { sub -> titleEligible.any { it == sub } }
                val primary = titleEligible.firstOrNull { it.model.id == session.modelId }
                    ?.takeIf { it != subEntry }
                val candidates = (listOfNotNull(subEntry, primary) +
                    titleEligible.filter { it != subEntry && it != primary })

                var lastError: Exception? = null
                for (entry in candidates) {
                    val instance = providerRepository.instance(entry.providerInstanceId) ?: continue
                    var apiKey = providerRepository.loadApiKey(instance.id) ?: continue

                    // Refresh OAuth token if needed
                    if (instance.credentialType == com.openminis.app.data.model.ProviderCredential.oauth) {
                        try {
                            val manager = com.openminis.app.auth.OAuthManager.forInstance(context, instance)
                            val freshToken = manager?.validAccessToken()
                            if (freshToken != null && freshToken != apiKey) {
                                providerRepository.saveApiKey(instance.id, freshToken)
                                apiKey = freshToken
                            }
                        } catch (e: Exception) {
                            Log.w(TAG, "OAuth refresh failed: ${e.message}")
                        }
                    }

                    val provider = try {
                        ProviderFactory.create(instance, apiKey, entry.model, context)
                    } catch (e: Exception) {
                        Log.w(TAG, "Provider creation failed for ${entry.model.displayName}: ${e.message}")
                        continue
                    }

                    Log.i(TAG, "regenerateTitle: trying ${instance.label.ifEmpty { entry.model.provider }} / ${entry.model.displayName}")

                    try {
                        // T334: reasoning models burn the entire token budget on hidden thinking
                        // before emitting any content. With maxTokens=100 every reasoning candidate
                        // returned `finish_reason=length` with empty text, then the loop silently
                        // moved on. Give reasoning models a real budget (1024) so they can finish
                        // thinking and still emit the JSON title.
                        val titleMaxTokens = if (entry.model.supportsReasoning == true) 2048 else 100
                        // [T-android-titlegen-reasoning] Explicitly disable
                        // thinking (thinkingLevel = OFF), matching iOS
                        // callSubModelForTitle and the auto-title path. The
                        // provider's injectThinkingParams honors OFF (e.g.
                        // DeepSeek V4 → {"thinking":{"type":"disabled"}}), so a
                        // reasoning model doesn't spend the budget on hidden
                        // thinking; the T334 maxTokens bump above stays as a
                        // safety net for models where OFF is a no-op (Qwen3).
                        val response = provider.sendMessage(
                            messages = listOf(LLMMessage(role = LLMMessage.Role.USER, content = prompt)),
                            // [T-android-titlegen-systemprompt-unify] Shared with
                            // the auto path via TITLE_GEN_SYSTEM_PROMPT (iOS-aligned
                            // wording). Passed bare — AnthropicProvider handles the
                            // OAuth Claude Code prefix at the provider layer.
                            systemPrompt = com.openminis.app.ui.chat.TITLE_GEN_SYSTEM_PROMPT,
                            maxTokens = titleMaxTokens,
                            // [T-android-titlegen-temperature] null (not 0.3) so
                            // buildRequestBody omits the field — the gpt-5.x
                            // family only accepts temperature=1 and 400s on any
                            // other value, which would silently skip that
                            // candidate. Aligns with the auto-title path and iOS
                            // AIChatViewModel.swift:11244.
                            temperature = null,
                            thinkingLevel = ThinkingLevel.OFF,
                        )
                        val (title, category) = parseTitleResponse(response.text)
                        if (title.isNotEmpty()) {
                            chatRepository.updateSessionTitleAndCategory(id, title, category)
                            Log.i(TAG, "Regenerated title='$title' category='$category' via ${entry.model.displayName}")
                            return@launch
                        }
                        // T334: previously this empty-result path was silent — only the *last*
                        // failing candidate's exception got reported, masking budget exhaustion
                        // on reasoning models. Surface it explicitly so logs show the real cause.
                        Log.w(
                            TAG,
                            "Title regen empty from ${entry.model.displayName}: " +
                                "stopReason=${response.stopReason} textLen=${response.text.length} " +
                                "maxTokens=$titleMaxTokens supportsReasoning=${entry.model.supportsReasoning}",
                        )
                    } catch (e: Exception) {
                        lastError = e
                        Log.w(TAG, "Title regen via ${entry.model.displayName} failed: ${e.message}")
                        // Continue to next candidate on rate-limit / provider error
                        continue
                    }
                }
                Log.w(TAG, "Title regeneration exhausted all providers. Last error: ${lastError?.message}")
            } catch (e: Exception) {
                Log.w(TAG, "Title regeneration failed: ${e.message}", e)
            } finally {
                withContext(Dispatchers.Main) {
                    regeneratingIds.value = regeneratingIds.value - id
                }
            }
        }
    }

    private fun extractText(partsJson: String): String {
        return try {
            val arr = org.json.JSONArray(partsJson)
            (0 until arr.length()).mapNotNull { i ->
                val obj = arr.getJSONObject(i)
                if (obj.optString("type") != "text") return@mapNotNull null
                val value = obj.optString("value")
                // [T-android-retry-attachment-loss] The user-message
                // <user-attached-files> XML is now persisted as a text part so
                // the model keeps file paths across retry/reload. Drop it from
                // session-list previews + search snippets so the inventory XML
                // never surfaces as visible session content (iOS strips it the
                // same way in ChatStore.toChatMessage).
                if (value.contains("<user-attached-files>")) {
                    val start = value.indexOf("<user-attached-files>")
                    val endTag = "</user-attached-files>"
                    val end = value.indexOf(endTag, start)
                    val cleaned = if (end >= 0) {
                        value.substring(0, start) + value.substring(end + endTag.length)
                    } else {
                        value.substring(0, start)
                    }.trim()
                    cleaned.ifEmpty { null }
                } else {
                    value
                }
            }.joinToString("\n")
        } catch (_: Exception) {
            partsJson
        }
    }

    private fun parseTitleResponse(text: String): Pair<String, String?> {
        val cleaned = text.trim()
            .removePrefix("```json").removePrefix("```")
            .removeSuffix("```").trim()
        try {
            val json = JSONObject(cleaned)
            val title = json.optString("title", "").trim()
            val category = json.optString("category", "").trim().ifEmpty { null }
            if (title.isNotEmpty()) return title to category
        } catch (_: Exception) {}
        val titleMatch = Regex("\"title\"\\s*:\\s*\"([^\"]+)\"").find(cleaned)
        val catMatch = Regex("\"category\"\\s*:\\s*\"([^\"]+)\"").find(cleaned)
        if (titleMatch != null) {
            return titleMatch.groupValues[1].trim() to catMatch?.groupValues?.getOrNull(1)?.trim()
        }
        val firstLine = cleaned.lines().firstOrNull()?.trim() ?: ""
        return firstLine.take(50) to null
    }

    fun duplicateSession(id: String) {
        viewModelScope.launch {
            val session = chatRepository.getSession(id) ?: return@launch
            val messages = chatRepository.loadMessages(id)
            val newSession = chatRepository.createSession(
                modelId = session.modelId,
                title = "${session.title ?: "Chat"} (Copy)",
            )
            for (msg in messages) {
                chatRepository.appendMessage(
                    sessionId = newSession.id,
                    role = msg.role,
                    partsJson = msg.partsJson,
                    tokenUsage = msg.tokenUsage,
                    reasoningContent = msg.reasoningContent,
                )
            }
        }
    }

    /**
     * Create a draft session ID for navigation. The actual DB record is created
     * only when the user sends the first message (deferred creation, matching iOS).
     */
    fun createNewSession(groupId: String? = null): String? {
        if (providerRepository.allVisibleEntries().isEmpty()) return null
        val base = "__new__${java.util.UUID.randomUUID()}"
        return if (groupId != null) "${base}__grp__${groupId}" else base
    }

    /**
     * [T-android-newchat-list-autoscroll] Emit [newTopSessionEvent] when a
     * never-before-seen session id appears at index 0 (the newest session,
     * since the list is updated_at DESC). The first emission only seeds the
     * baseline so existing sessions don't trigger a scroll on launch. Reorders
     * of existing sessions keep their ids (already in [knownSessionIds]) so
     * they never fire. Runs on the collector coroutine; no thread switch.
     */
    private fun detectNewTopSession(sessions: List<ChatSessionEntity>) {
        val topId = sessions.firstOrNull()?.id
        if (!newTopBaselineSeeded) {
            knownSessionIds = sessions.mapTo(HashSet()) { it.id }
            newTopBaselineSeeded = true
            return
        }
        val isNewTop = topId != null && topId !in knownSessionIds
        knownSessionIds = knownSessionIds + sessions.map { it.id }
        if (isNewTop) newTopSessionEvent.tryEmit(Unit)
    }

    fun hasProviders(): Boolean = providerRepository.instances.isNotEmpty()

    /**
     * For every session whose title does NOT contain [query] (case-insensitive),
     * scan its messages to find the first hit in extracted text content and
     * build a ~100-char snippet around it. Sessions with no content hit are
     * omitted from the result map — the row will fall back to its existing
     * lastMessage preview without highlighting.
     *
     * Runs on Dispatchers.IO; caller is responsible for thread switching.
     */
    private suspend fun buildContentSnippets(
        sessions: List<ChatSessionEntity>,
        query: String,
    ): Map<String, String> {
        if (query.isBlank() || sessions.isEmpty()) return emptyMap()
        val q = query.lowercase()
        val out = HashMap<String, String>()
        for (session in sessions) {
            val title = session.title.orEmpty()
            if (title.lowercase().contains(q)) continue
            val msgs = chatRepository.loadMessages(session.id)
            var foundSnippet: String? = null
            for (m in msgs) {
                val text = extractText(m.partsJson)
                val pos = text.lowercase().indexOf(q)
                if (pos < 0) continue
                val radius = 50
                val start = (pos - radius).coerceAtLeast(0)
                val end = (pos + query.length + radius).coerceAtMost(text.length)
                val core = text.substring(start, end).replace('\n', ' ').replace('\r', ' ')
                val prefix = if (start > 0) "…" else ""
                val suffix = if (end < text.length) "…" else ""
                foundSnippet = prefix + core + suffix
                break
            }
            if (foundSnippet != null) out[session.id] = foundSnippet
        }
        return out
    }
}
