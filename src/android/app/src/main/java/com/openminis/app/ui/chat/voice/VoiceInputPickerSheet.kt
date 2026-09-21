package com.openminis.app.ui.chat.voice

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.GraphicEq
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.SystemVoiceEntries
import com.openminis.app.data.model.SystemVoiceIds
import com.openminis.app.data.model.hasAudioInput
import com.openminis.app.data.repository.ProviderRepository
import com.openminis.app.ui.components.MinisTextButton
import com.openminis.app.ui.components.QuickTestSheet
import com.openminis.app.ui.components.modalityBadges
import com.openminis.app.ui.components.providerDotColor

/**
 * [T-android-voice-panel] Single-select voice INPUT engine picker — Android
 * port of iOS UnifiedModelPicker(config: .voiceInput()) as a bottom sheet:
 *
 *  • Model Groups: the bound Voice Input group row (selected when no explicit
 *    override) with member count + FB badge.
 *  • System: Recognition (Online) / (Offline) virtual rows.
 *  • One section per enabled provider with audio-input models (chat-based ASR
 *    multimodals included), each row with modality chips + Quick Test bolt.
 *
 * Selection writes ProviderRepository.voiceInputOverrideEntryId (System
 * composite id / entry id / null = follow the group).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VoiceInputPickerSheet(
    providerRepository: ProviderRepository,
    onDismiss: () -> Unit,
) {
    val config by providerRepository.config.collectAsState()
    var quickTestEntry by remember { mutableStateOf<ModelEntry?>(null) }
    val override = providerRepository.voiceInputOverrideEntryId
    val groupName = providerRepository.voiceInputGroupName()
    val group = config.voiceInputGroupId?.let { gid -> config.modelGroups.find { it.id == gid } }

    fun select(id: String?) {
        providerRepository.voiceInputOverrideEntryId = id
        onDismiss()
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(modifier = Modifier.padding(bottom = 24.dp)) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    stringResource(R.string.voice_input_picker_title),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                MinisTextButton(onClick = onDismiss) {
                    Text(stringResource(R.string.voice_input_picker_done))
                }
            }

            LazyColumn {
                // ── Model Groups ──
                if (group != null) {
                    item("group_header") {
                        SectionLabel(stringResource(R.string.voice_input_picker_groups))
                    }
                    item("group_row") {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(horizontal = 16.dp)
                                .clip(RoundedCornerShape(12.dp))
                                .background(MaterialTheme.colorScheme.surfaceContainer)
                                .clickable { select(null) }
                                .padding(horizontal = 16.dp, vertical = 13.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            SelectionMark(selected = override == null)
                            Spacer(Modifier.width(10.dp))
                            Icon(
                                Icons.Outlined.GraphicEq,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.primary,
                                modifier = Modifier.size(18.dp),
                            )
                            Spacer(Modifier.width(10.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Text(
                                        groupName ?: "",
                                        style = MaterialTheme.typography.bodyMedium,
                                        fontWeight = FontWeight.Medium,
                                    )
                                    Spacer(Modifier.width(6.dp))
                                    Text(
                                        "FB",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = ChatColorsCompat.secondary,
                                        modifier = Modifier
                                            .background(
                                                MaterialTheme.colorScheme.surfaceContainerHigh,
                                                RoundedCornerShape(4.dp),
                                            )
                                            .padding(horizontal = 4.dp, vertical = 1.dp),
                                    )
                                }
                                Text(
                                    stringResource(
                                        R.string.voice_input_picker_group_models,
                                        group.memberEntryIds.size,
                                    ),
                                    style = MaterialTheme.typography.labelSmall,
                                    color = ChatColorsCompat.secondary,
                                )
                            }
                        }
                    }
                    item("group_footer") {
                        Text(
                            stringResource(R.string.voice_input_picker_group_footer),
                            style = MaterialTheme.typography.labelSmall,
                            color = ChatColorsCompat.secondary,
                            modifier = Modifier.padding(horizontal = 24.dp, vertical = 6.dp),
                        )
                    }
                }

                // ── System ──
                item("system_header") { SectionLabel(stringResource(R.string.voice_input_picker_system)) }
                item("system_rows") {
                    Column(
                        modifier = Modifier
                            .padding(horizontal = 16.dp)
                            .background(
                                MaterialTheme.colorScheme.surfaceContainer,
                                RoundedCornerShape(12.dp),
                            ),
                    ) {
                        val systemRows = listOf(
                            Triple(
                                SystemVoiceEntries.asrOnline.id,
                                stringResource(R.string.voice_system_recognition_online),
                                stringResource(R.string.voice_system_online_subtitle),
                            ),
                            Triple(
                                SystemVoiceEntries.asrOffline.id,
                                stringResource(R.string.voice_system_recognition_offline),
                                stringResource(R.string.voice_system_offline_subtitle),
                            ),
                        )
                        systemRows.forEachIndexed { i, (id, title, subtitle) ->
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(if (i == 0) 12.dp else 0.dp))
                                    .clickable { select(id) }
                                    .padding(horizontal = 16.dp, vertical = 13.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                SelectionMark(selected = override == id)
                                Spacer(Modifier.width(10.dp))
                                Icon(
                                    Icons.Default.Mic,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(16.dp),
                                )
                                Spacer(Modifier.width(10.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(title, style = MaterialTheme.typography.bodyMedium)
                                    Text(
                                        subtitle,
                                        style = MaterialTheme.typography.labelSmall,
                                        color = ChatColorsCompat.secondary,
                                    )
                                }
                            }
                            if (i == 0) {
                                HorizontalDivider(
                                    modifier = Modifier.padding(start = 52.dp, end = 16.dp),
                                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
                                )
                            }
                        }
                    }
                }

                // ── Providers with audio-input models ──
                val audioEntriesByInstance = config.instances
                    .filter { it.isEnabled }
                    .mapNotNull { inst ->
                        val entries = config.modelEntries.filter {
                            it.providerInstanceId == inst.id && !it.isHidden && it.model.hasAudioInput
                        }
                        if (entries.isEmpty()) null else inst to entries
                    }
                audioEntriesByInstance.forEach { (inst, entries) ->
                    item("h_${inst.id}") {
                        SectionLabel(inst.label.ifEmpty { inst.providerType.displayName })
                    }
                    item("e_${inst.id}") {
                        Column(
                            modifier = Modifier
                                .padding(horizontal = 16.dp)
                                .background(
                                    MaterialTheme.colorScheme.surfaceContainer,
                                    RoundedCornerShape(12.dp),
                                ),
                        ) {
                            entries.forEachIndexed { i, entry ->
                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable { select(entry.id) }
                                        .padding(horizontal = 16.dp, vertical = 13.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    SelectionMark(selected = override == entry.id)
                                    Spacer(Modifier.width(10.dp))
                                    Box(
                                        modifier = Modifier
                                            .size(6.dp)
                                            .background(
                                                providerDotColor(inst.providerType),
                                                CircleShape,
                                            ),
                                    )
                                    Spacer(Modifier.width(10.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(
                                            entry.model.displayName,
                                            style = MaterialTheme.typography.bodyMedium,
                                        )
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text(
                                                entry.baseModel.id,
                                                style = MaterialTheme.typography.labelSmall,
                                                color = ChatColorsCompat.secondary,
                                            )
                                            modalityBadges(entry.model).forEach { badge ->
                                                Spacer(Modifier.width(4.dp))
                                                Text(
                                                    badge,
                                                    style = MaterialTheme.typography.labelSmall,
                                                    color = ChatColorsCompat.secondary,
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
                                    IconButton(
                                        onClick = { quickTestEntry = entry },
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
                                if (i < entries.size - 1) {
                                    HorizontalDivider(
                                        modifier = Modifier.padding(start = 52.dp, end = 16.dp),
                                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.3f),
                                    )
                                }
                            }
                        }
                    }
                }
                item("bottom_pad") { Spacer(Modifier.padding(12.dp)) }
            }
        }
    }

    quickTestEntry?.let { entry ->
        QuickTestSheet(
            entry = entry,
            providerRepository = providerRepository,
            onDismiss = { quickTestEntry = null },
        )
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = ChatColorsCompat.secondary,
        modifier = Modifier.padding(start = 20.dp, end = 16.dp, top = 14.dp, bottom = 4.dp),
    )
}

@Composable
private fun SelectionMark(selected: Boolean) {
    Icon(
        if (selected) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
        contentDescription = null,
        tint = if (selected) Color(0xFF007AFF)
        else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
        modifier = Modifier.size(20.dp),
    )
}

/** Neutral secondary color without importing chat-internal ChatColors here. */
private object ChatColorsCompat {
    val secondary: Color
        @Composable get() = MaterialTheme.colorScheme.onSurfaceVariant
}
