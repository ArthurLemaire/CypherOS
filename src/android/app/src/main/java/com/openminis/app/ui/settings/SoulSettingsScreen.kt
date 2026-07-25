package com.openminis.app.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.agent.SoulBodyLimitCheck
import com.openminis.app.agent.SoulFile
import com.openminis.app.agent.SoulMDParser
import com.openminis.app.agent.SoulMetadata
import com.openminis.app.agent.SoulStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.withContext

/**
 * [T-soul-md] Settings page for editing SOUL.md. Mirrors iOS
 * `SoulSettingsView` (commit 6370d5a):
 *   - Header preview card showing `✨ [name]` + `[style]` (emoji is
 *     locked to ✨; the editable emoji field was removed to keep
 *     identity surface consistent across the app)
 *   - Identity fields: name, style, lang (Auto / Chinese / English)
 *   - Personality prompt (multiline) with soft-warning + hard-truncate
 *     length indicators (>2000 chars = yellow, >4000 = red)
 *   - "Restore Default" with confirmation dialog
 *   - "Save" writes to SOUL.md via [SoulStore.save] and refreshes the
 *     in-memory metadata cache so chat bubble headers update without a
 *     restart.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SoulSettingsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var name by remember { mutableStateOf(SoulMetadata.DEFAULT.name) }
    var style by remember { mutableStateOf(SoulMetadata.DEFAULT.style) }
    var lang by remember { mutableStateOf(SoulMetadata.DEFAULT.lang) }
    var body by remember { mutableStateOf("") }
    var loaded by remember { mutableStateOf(false) }
    var showRestoreDialog by remember { mutableStateOf(false) }
    var saveError by remember { mutableStateOf<String?>(null) }
    // Preserve the raw `emoji` field exactly as it appears in SOUL.md so
    // Save round-trips without clobbering a value the user may have set
    // on another device (or an older build). Not surfaced in the UI —
    // the identity emoji shown to the user is locked to ✨ everywhere
    // (see [SoulMetadata.displayEmoji]).
    var preservedEmoji by remember { mutableStateOf(SoulMetadata.DEFAULT.emoji) }

    // Initial load + (defensive) ensureExists. The Application-level call
    // already seeded on first run, but loading from a freshly cleared app
    // shouldn't crash.
    LaunchedEffect(Unit) {
        withContext(Dispatchers.IO) {
            SoulStore.ensureExists(context)
            val parsed = SoulStore.load(context) ?: SoulMDParser.parse(SoulStore.DEFAULT_CONTENT)
            name = parsed.metadata.name
            preservedEmoji = parsed.metadata.emoji
            style = parsed.metadata.style
            lang = parsed.metadata.lang
            body = parsed.body
        }
        loaded = true
    }

    // Language-aware length check used by both the editor counter and the
    // Save button's enabled state. See [SoulStore.isOverLimit] for the rule.
    val bodyLimitCheck by remember(body) { derivedStateOf { SoulStore.isOverLimit(body) } }

    SettingsScaffold(
        title = stringResource(R.string.soul_settings_title),
        onBack = onBack,
    ) {
        SettingsSection(
            header = stringResource(R.string.soul_section_preview),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // Identity emoji is locked to ✨ — the user-customizable
                // emoji field was removed; see [SoulMetadata.displayEmoji].
                Text(
                    text = SoulMetadata.DISPLAY_EMOJI,
                    fontSize = 28.sp,
                    modifier = Modifier.width(48.dp),
                )
                Column(modifier = Modifier.padding(start = 4.dp)) {
                    Text(
                        text = name.ifBlank { "Minis" },
                        fontSize = 17.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    if (style.isNotBlank()) {
                        Text(
                            text = style,
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }

        SettingsSection(
            header = stringResource(R.string.soul_section_identity),
        ) {
            Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text(stringResource(R.string.soul_field_name)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                // Emoji field intentionally removed — identity emoji is
                // locked to ✨; only name / style / lang are editable.
                OutlinedTextField(
                    value = style,
                    onValueChange = { style = it },
                    label = { Text(stringResource(R.string.soul_field_style)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                LangPicker(lang = lang, onLangChange = { lang = it })
            }
        }

        SettingsSection(
            header = stringResource(R.string.soul_section_personality),
            footer = stringResource(R.string.soul_personality_footer),
        ) {
            Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                OutlinedTextField(
                    value = body,
                    onValueChange = { body = it },
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(min = 240.dp),
                    textStyle = MaterialTheme.typography.bodyMedium.copy(
                        fontFamily = FontFamily.Monospace,
                    ),
                    placeholder = { Text(stringResource(R.string.soul_body_placeholder)) },
                )
                Spacer(Modifier.height(6.dp))
                val isOverLimit = bodyLimitCheck.isOverLimit
                val warnColor: Color =
                    if (isOverLimit) Color(0xFFFF3B30)
                    else MaterialTheme.colorScheme.onSurfaceVariant
                val indicatorText: String = when (val c = bodyLimitCheck) {
                    is SoulBodyLimitCheck.Ok -> {
                        // Show the unit that matches whichever rule the
                        // current body is being measured against — mirrors
                        // iOS soulBodyCountText.
                        soulBodyCountTextAndroid(body)
                    }
                    is SoulBodyLimitCheck.OverLimitChinese -> stringResource(
                        R.string.soul_over_limit_chinese, c.chars, c.cap, SoulStore.ENGLISH_WORD_LIMIT,
                    )
                    is SoulBodyLimitCheck.OverLimitEnglish -> stringResource(
                        R.string.soul_over_limit_english, c.words, c.cap, SoulStore.CHINESE_CHAR_LIMIT,
                    )
                }
                Text(
                    text = indicatorText,
                    fontSize = 12.sp,
                    color = warnColor,
                )
            }
        }

        SettingsSection {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                OutlinedButton(
                    onClick = { showRestoreDialog = true },
                    modifier = Modifier.weight(1f),
                ) { Text(stringResource(R.string.soul_restore_default)) }
                Button(
                    onClick = {
                        scope.launch {
                            try {
                                val file = SoulFile(
                                    metadata = SoulMetadata(
                                        name = name.ifBlank { SoulMetadata.DEFAULT.name },
                                        // Round-trip the on-disk emoji
                                        // value unchanged so a user who
                                        // set a custom emoji on another
                                        // device / older build doesn't
                                        // see it silently rewritten when
                                        // they hit Save here.
                                        emoji = preservedEmoji.ifBlank { SoulMetadata.DEFAULT.emoji },
                                        style = style,
                                        lang = lang.ifBlank { SoulMetadata.DEFAULT.lang },
                                    ),
                                    body = body,
                                )
                                withContext(Dispatchers.IO) { SoulStore.save(context, file) }
                                onBack()
                            } catch (t: Throwable) {
                                saveError = t.message ?: "save failed"
                            }
                        }
                    },
                    enabled = loaded && !bodyLimitCheck.isOverLimit,
                    modifier = Modifier.weight(1f),
                ) { Text(stringResource(R.string.soul_save)) }
            }
        }
    }

    if (showRestoreDialog) {
        AlertDialog(
            onDismissRequest = { showRestoreDialog = false },
            title = { Text(stringResource(R.string.soul_restore_confirm_title)) },
            text = { Text(stringResource(R.string.soul_restore_confirm_body)) },
            confirmButton = {
                Button(onClick = {
                    val parsed = SoulMDParser.parse(SoulStore.DEFAULT_CONTENT)
                    name = parsed.metadata.name
                    preservedEmoji = parsed.metadata.emoji
                    style = parsed.metadata.style
                    lang = parsed.metadata.lang
                    body = parsed.body
                    showRestoreDialog = false
                }) { Text(stringResource(R.string.soul_restore_default)) }
            },
            dismissButton = {
                OutlinedButton(onClick = { showRestoreDialog = false }) {
                    Text(stringResource(R.string.soul_cancel))
                }
            },
        )
    }

    saveError?.let { err ->
        AlertDialog(
            onDismissRequest = { saveError = null },
            title = { Text(stringResource(R.string.soul_save_error_title)) },
            text = { Text(err) },
            confirmButton = {
                Button(onClick = { saveError = null }) { Text(stringResource(R.string.soul_ok)) }
            },
        )
    }
}

/// Render the within-budget counter — picks the CJK character unit vs "words" depending on
/// the same CJK ratio rule that decides which cap applies. Standalone
/// helper so it stays out of the Composable hot-path's expression budget.
@Composable
private fun soulBodyCountTextAndroid(body: String): String {
    val trimmed = body.trim()
    if (trimmed.isEmpty()) return stringResource(R.string.soul_count_zero)
    var cjk = 0
    var total = 0
    var i = 0
    while (i < trimmed.length) {
        val cp = trimmed.codePointAt(i)
        total += 1
        val isCJK =
            cp in 0x4E00..0x9FFF ||
                cp in 0x3400..0x4DBF ||
                cp in 0x3040..0x309F ||
                cp in 0x30A0..0x30FF ||
                cp in 0xAC00..0xD7AF
        if (isCJK) cjk += 1
        i += Character.charCount(cp)
    }
    val ratio = if (total > 0) cjk.toDouble() / total else 0.0
    return if (ratio > SoulStore.CJK_RATIO_THRESHOLD) {
        val chars = trimmed.codePointCount(0, trimmed.length)
        stringResource(R.string.soul_count_chars, chars, SoulStore.CHINESE_CHAR_LIMIT)
    } else {
        val words = trimmed.split(Regex("\\s+")).count { it.isNotEmpty() }
        stringResource(R.string.soul_count_words, words, SoulStore.ENGLISH_WORD_LIMIT)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LangPicker(lang: String, onLangChange: (String) -> Unit) {
    val options = listOf(
        "auto" to stringResource(R.string.soul_lang_auto),
        "zh" to stringResource(R.string.soul_lang_zh),
        "en" to stringResource(R.string.soul_lang_en),
    )
    val current = options.firstOrNull { it.first == lang } ?: options.first()
    var expanded by remember { mutableStateOf(false) }
    // Render the picker as a simple labeled row of buttons. Three options
    // (auto / Chinese / English) fit comfortably without a dropdown — avoids
    // depending on material3 ExposedDropdownMenu, which has a fragile
    // alignment story across compose versions.
    Column(modifier = Modifier.fillMaxWidth()) {
        Text(
            text = stringResource(R.string.soul_field_lang),
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 4.dp, bottom = 4.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            options.forEach { (key, label) ->
                if (key == current.first) {
                    Button(
                        onClick = { onLangChange(key) },
                        modifier = Modifier.weight(1f),
                    ) { Text(label) }
                } else {
                    OutlinedButton(
                        onClick = { onLangChange(key) },
                        modifier = Modifier.weight(1f),
                    ) { Text(label) }
                }
            }
        }
    }
    expanded // suppress unused-var warning
}
