package com.openminis.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import com.openminis.app.R
import androidx.compose.ui.unit.dp
import androidx.annotation.StringRes
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import com.openminis.app.data.model.SystemVoiceEntries
import com.openminis.app.data.model.hasAudioInput
import com.openminis.app.data.model.hasAudioOutput
import com.openminis.app.data.model.normalizeModalities

/**
 * [T-android-provider-voice] First-class modality scoping for the shared
 * picker — Android port of iOS ModelPickerConfig.explicitPreferModality.
 * iOS expresses preference as a ModelModality bitset with a superset match;
 * in practice the only prefs used are the two voice directions, so Android
 * models them directly:
 *
 *  - [AUDIO_INPUT]  — ASR scenario: only audio-consuming entries qualify,
 *    and the System Recognition (Online/Offline) virtual entries lead.
 *  - [AUDIO_OUTPUT] — TTS scenario: only audio-producing entries qualify,
 *    and the System Voice (Auto) virtual entry leads.
 *
 * When a filter is active the picker also injects the matching System
 * virtual entries as their own leading "System" section (iOS
 * candidateEntries appends systemASROnline/Offline / systemTTS). Callers in
 * a voice scenario should keep provider sections expanded (iOS d4e3798f
 * seedCollapse: multi-voice vendors would fold all-but-one voice).
 */
enum class PickerModalityFilter {
    AUDIO_INPUT,
    AUDIO_OUTPUT;

    fun matches(model: LLMModel): Boolean = when (this) {
        AUDIO_INPUT -> model.hasAudioInput
        AUDIO_OUTPUT -> model.hasAudioOutput
    }

    /** System virtual entries that serve this direction, in display order. */
    fun systemEntries(): List<ModelEntry> = when (this) {
        AUDIO_INPUT -> listOf(SystemVoiceEntries.asrOnline, SystemVoiceEntries.asrOffline)
        AUDIO_OUTPUT -> listOf(SystemVoiceEntries.tts)
    }
}

/**
 * T185 — shared multi-select picker for model entries.
 *
 * Pre-T185 the agent-loop add sheet (`AgentLoopAddSheets.kt`) and
 * `AddModelsToGroupScreen` rendered the same conceptual list with
 * different visuals: the former a plain ModalBottomSheet with bare
 * tap-and-add rows, the latter a sectioned multi-select with collapsible
 * per-provider cards, search, and a confirm button. User reported the
 * mismatch (T185) — the iOS counterparts use the same sectioned-list
 * style for both. Extract the AddModelsToGroupScreen layout into a
 * reusable [LazyListScope] extension so both call sites share one
 * implementation.
 *
 * [modelEntryPickerItems] is consumed inside a parent `LazyColumn`
 * rather than being a self-contained Composable so the caller controls
 * the surrounding chrome (Scaffold + TopAppBar + confirm button) and
 * retains access to the LazyListState for reorder / scroll-to.
 */
fun LazyListScope.modelEntryPickerItems(
    instances: List<ProviderInstance>,
    availableEntries: List<ModelEntry>,
    selectedIds: Set<String>,
    onToggleSelection: (String) -> Unit,
    searchQuery: MutableState<String>,
    collapsedInstanceIds: MutableState<Set<String>>,
    @StringRes emptyTextRes: Int,
    @StringRes emptySearchTextRes: Int,
    @StringRes searchPlaceholderRes: Int,
    @StringRes clearContentDescriptionRes: Int,
    // [T-android-model-quick-test] Optional per-row Quick Test button. When
    // provided, each model row shows a compact bolt icon that opens the shared
    // QuickTestSheet for that entry (the caller owns the sheet + repository).
    onQuickTest: ((ModelEntry) -> Unit)? = null,
    // [T-android-provider-voice] Modality scoping (see PickerModalityFilter):
    // null = no filtering (all entries, no System injection) — the pre-voice
    // behavior every existing caller keeps by default.
    modalityFilter: PickerModalityFilter? = null,
    // Ids to exclude from the injected System entries (e.g. ids already in the
    // target group). Regular entries are excluded by the caller via
    // [availableEntries]; System entries are built here, hence this knob.
    excludeIds: Set<String> = emptySet(),
    // Localized display label for the injected System provider section.
    // Resolved by the Composable caller via stringResource (this extension is
    // not @Composable); mirrors iOS String(localized: "System").
    systemProviderLabel: String = "System",
) {
    val q = searchQuery.value.lowercase()
    val isSearching = searchQuery.value.isNotBlank()

    fun matchesSearch(entry: ModelEntry): Boolean =
        !isSearching ||
            entry.model.displayName.lowercase().contains(q) ||
            entry.model.id.lowercase().contains(q)

    // System section leads when a modality filter is active (iOS: the System
    // synthetic instance is first in entriesByInstance).
    val systemPair: Pair<ProviderInstance, List<ModelEntry>>? = modalityFilter
        ?.systemEntries()
        ?.filter { it.id !in excludeIds && matchesSearch(it) }
        ?.takeIf { it.isNotEmpty() }
        ?.let { SystemVoiceEntries.syntheticInstance(systemProviderLabel) to it }

    val instanceWithEntries = listOfNotNull(systemPair) + instances
        .filter { it.isEnabled && !SystemVoiceEntries.isSystemEntryId(it.id) }
        .mapNotNull { instance ->
            val entries = availableEntries.filter { entry ->
                entry.providerInstanceId == instance.id &&
                    (modalityFilter == null || modalityFilter.matches(entry.model))
            }
            val filtered = entries.filter { matchesSearch(it) }
            if (filtered.isEmpty()) null else instance to filtered
        }

    // Force expand everything while searching so the user actually
    // sees results — collapsed sections during search would hide hits.
    val effectiveCollapsed = if (isSearching) emptySet() else collapsedInstanceIds.value

    item("__search__") {
        OutlinedTextField(
            value = searchQuery.value,
            onValueChange = { searchQuery.value = it },
            placeholder = { Text(stringResource(searchPlaceholderRes)) },
            singleLine = true,
            shape = RoundedCornerShape(50),
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 8.dp),
            leadingIcon = {
                Icon(
                    Icons.Default.Search,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            },
            trailingIcon = {
                if (searchQuery.value.isNotEmpty()) {
                    IconButton(onClick = { searchQuery.value = "" }) {
                        Icon(
                            Icons.Default.Close,
                            contentDescription = stringResource(clearContentDescriptionRes),
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            },
        )
    }

    instanceWithEntries.forEach { (instance, entries) ->
        val isCollapsed = instance.id in effectiveCollapsed
        val dotColor = providerDotColor(instance.providerType)

        item(key = "header_${instance.id}") {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 20.dp, end = 16.dp, top = 16.dp, bottom = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    instance.label.ifEmpty { instance.providerType.displayName },
                    style = MaterialTheme.typography.titleSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                Box(
                    modifier = Modifier
                        .size(28.dp)
                        .background(MaterialTheme.colorScheme.surfaceContainerHigh, CircleShape)
                        .clip(CircleShape)
                        .clickable {
                            collapsedInstanceIds.value = if (isCollapsed) {
                                collapsedInstanceIds.value - instance.id
                            } else {
                                collapsedInstanceIds.value + instance.id
                            }
                        },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        if (isCollapsed) Icons.Default.KeyboardArrowDown else Icons.Default.KeyboardArrowUp,
                        contentDescription = null,
                        modifier = Modifier.size(16.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (isCollapsed) {
            // Collapsed preview: first row + "N models" hint to remind the
            // user how many are inside the section without expanding.
            item(key = "collapsed_${instance.id}") {
                val firstEntry = entries.firstOrNull() ?: return@item
                val isSelected = firstEntry.id in selectedIds
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp)
                        .background(
                            MaterialTheme.colorScheme.surfaceContainer,
                            RoundedCornerShape(12.dp),
                        )
                        .clip(RoundedCornerShape(12.dp))
                        .clickable { onToggleSelection(firstEntry.id) }
                        .padding(horizontal = 16.dp, vertical = 13.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    SelectionDot(isSelected)
                    Spacer(Modifier.width(10.dp))
                    Box(modifier = Modifier.size(6.dp).background(dotColor, CircleShape))
                    Spacer(Modifier.width(10.dp))
                    Text(
                        firstEntry.model.displayName,
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f),
                    )
                    Text(
                        "${entries.size} models",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                    )
                }
            }
        } else {
            item(key = "entries_${instance.id}") {
                Column(
                    modifier = Modifier
                        .padding(horizontal = 16.dp)
                        .background(
                            MaterialTheme.colorScheme.surfaceContainer,
                            RoundedCornerShape(12.dp),
                        ),
                ) {
                    entries.forEachIndexed { index, entry ->
                        val isSelected = entry.id in selectedIds
                        val rowShape = when {
                            entries.size == 1 -> RoundedCornerShape(12.dp)
                            index == 0 -> RoundedCornerShape(topStart = 12.dp, topEnd = 12.dp)
                            index == entries.size - 1 -> RoundedCornerShape(bottomStart = 12.dp, bottomEnd = 12.dp)
                            else -> RoundedCornerShape(0.dp)
                        }
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(rowShape)
                                .clickable { onToggleSelection(entry.id) }
                                .padding(horizontal = 16.dp, vertical = 13.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            SelectionDot(isSelected)
                            Spacer(Modifier.width(10.dp))
                            Box(modifier = Modifier.size(6.dp).background(dotColor, CircleShape))
                            Spacer(Modifier.width(10.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    entry.model.displayName,
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        entry.model.id,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                    )
                                    // [T-android-provider-voice] Modality chips
                                    // (iOS entryRow modalityBadges: img / audio /
                                    // video / pdf and the -out variants).
                                    modalityBadges(entry.model).forEach { badge ->
                                        Spacer(Modifier.width(4.dp))
                                        Text(
                                            badge,
                                            style = MaterialTheme.typography.labelSmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                            modifier = Modifier
                                                .background(
                                                    MaterialTheme.colorScheme.surfaceContainerHigh,
                                                    RoundedCornerShape(3.dp),
                                                )
                                                .padding(horizontal = 4.dp, vertical = 1.dp),
                                        )
                                    }
                                }
                            }
                            // System virtual entries have no cloud endpoint to
                            // smoke-test — no bolt on those rows.
                            if (onQuickTest != null && !SystemVoiceEntries.isSystemEntryId(entry.id)) {
                                IconButton(
                                    onClick = { onQuickTest(entry) },
                                    modifier = Modifier.size(32.dp),
                                ) {
                                    Icon(
                                        Icons.Outlined.Bolt,
                                        contentDescription = stringResource(R.string.quicktest_button),
                                        tint = MaterialTheme.colorScheme.primary,
                                        modifier = Modifier.size(18.dp),
                                    )
                                }
                            }
                        }
                        if (index < entries.size - 1) {
                            HorizontalDivider(
                                modifier = Modifier.padding(start = 52.dp, end = 16.dp),
                                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
                            )
                        }
                    }
                }
            }
        }
    }

    if (instanceWithEntries.isEmpty()) {
        item("__empty__") {
            Text(
                stringResource(if (isSearching) emptySearchTextRes else emptyTextRes),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(16.dp),
            )
        }
    }
}

@Composable
private fun SelectionDot(isSelected: Boolean) {
    Icon(
        if (isSelected) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
        contentDescription = null,
        tint = if (isSelected) Color(0xFF007AFF)
        else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
        modifier = Modifier.size(20.dp),
    )
}

/**
 * [T-android-provider-voice] Non-text modality chips for a model row —
 * mirrors iOS UnifiedModelPicker.modalityBadges (same labels, same order:
 * inputs first, then outputs; text never badged).
 */
fun modalityBadges(model: LLMModel): List<String> {
    val ins = model.inputModalities.normalizeModalities() ?: emptyList()
    val outs = model.outputModalities.normalizeModalities() ?: emptyList()
    val badges = mutableListOf<String>()
    if ("image" in ins) badges.add("img")
    if ("audio" in ins) badges.add("audio")
    if ("video" in ins) badges.add("video")
    if ("pdf" in ins) badges.add("pdf")
    if ("image" in outs) badges.add("img-out")
    if ("audio" in outs) badges.add("audio-out")
    if ("video" in outs) badges.add("video-out")
    return badges
}

/** Provider color dot — same RGB across ChatScreen, AddModelsToGroup, and
 *  the agent-loop sheets so the visual cue stays consistent everywhere. */
fun providerDotColor(providerType: ProviderType?): Color = when (providerType) {
    ProviderType.anthropic -> Color(0xFFAB47BC)
    ProviderType.gemini -> Color(0xFF42A5F5)
    ProviderType.openAI -> Color(0xFF4CAF50)
    ProviderType.openRouter -> Color(0xFF00BCD4)
    ProviderType.xAI -> Color(0xFFFF7043)
    ProviderType.kimiCode -> Color(0xFF5C6BC0) // indigo — Kimi accent
    null -> Color(0xFF8E8E93)
}
