package com.openminis.app.ui.settings

import com.openminis.app.R

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.stringResource
import com.openminis.app.data.db.ChatDao
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ProviderConfig
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private data class ModelStats(
    val modelId: String,
    val displayName: String,
    val provider: String,
    var inputTokens: Long = 0,
    var outputTokens: Long = 0,
    var cacheCreationTokens: Long = 0,
    var cacheReadTokens: Long = 0,
    val distinctDays: MutableSet<String> = mutableSetOf(),
    val distinctSessions: MutableSet<String> = mutableSetOf(),
) {
    val totalInput: Long get() = inputTokens + cacheReadTokens + cacheCreationTokens
}

private data class ProviderGroup(val name: String, val models: List<ModelStats>)

private data class GrandTotal(
    val totalInput: Long = 0,
    val outputTokens: Long = 0,
    val cacheReadTokens: Long = 0,
    val cacheCreationTokens: Long = 0,
) {
    val cacheHitRate: Double?
        get() = if (totalInput <= 0 || cacheReadTokens <= 0) null
        else (cacheReadTokens.toDouble() / totalInput) * 100
}

@Composable
fun UsageStatsScreen(
    chatDao: ChatDao,
    providerConfig: ProviderConfig? = null,
    onBack: () -> Unit,
) {
    var grandTotal by remember { mutableStateOf(GrandTotal()) }
    var providerGroups by remember { mutableStateOf<List<ProviderGroup>>(emptyList()) }
    var isLoaded by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        val records = chatDao.allUsageRecords()

        val modelLookup = mutableMapOf<String, Pair<String, String>>()
        for (m in LLMModel.allModels) modelLookup[m.id] = m.displayName to m.provider
        providerConfig?.let { config ->
            for (entry in config.modelEntries) {
                if (entry.model.id !in modelLookup) {
                    val instance = config.instances.find { it.id == entry.providerInstanceId }
                    val providerName = instance?.providerType?.displayName ?: entry.model.provider
                    modelLookup[entry.model.id] = entry.model.displayName to providerName
                }
            }
        }

        val statsMap = mutableMapOf<String, ModelStats>()
        val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.US)

        for (record in records) {
            val usage = try { JSONObject(record.tokenUsage) } catch (_: Exception) { continue }
            val input = usage.optLong("inputTokens", 0)
            val output = usage.optLong("outputTokens", 0)
            val cacheCr = usage.optLong("cacheCreationTokens", usage.optLong("cacheCreationInputTokens", 0))
            val cacheRd = usage.optLong("cacheReadTokens", usage.optLong("cacheReadInputTokens", 0))

            val (displayName, provider) = modelLookup[record.modelId]
                ?: (record.modelId to "Unknown")

            val stats = statsMap.getOrPut(record.modelId) {
                ModelStats(record.modelId, displayName, provider)
            }
            stats.inputTokens += input
            stats.outputTokens += output
            stats.cacheCreationTokens += cacheCr
            stats.cacheReadTokens += cacheRd
            stats.distinctDays.add(dateFormat.format(Date(record.createdAt)))
            stats.distinctSessions.add(record.sessionId)
        }

        val providerOrder = listOf("OpenAI", "Anthropic", "Google Gemini", "Google", "Antigravity", "Unknown")
        val grouped = statsMap.values.groupBy { it.provider }
        val sortedGroups = grouped.entries.sortedBy { (name, _) ->
            val idx = providerOrder.indexOf(name)
            if (idx >= 0) idx else providerOrder.size
        }.map { (name, models) ->
            ProviderGroup(name, models.sortedByDescending { it.totalInput })
        }

        val allStats = statsMap.values
        grandTotal = GrandTotal(
            totalInput = allStats.sumOf { it.totalInput },
            outputTokens = allStats.sumOf { it.outputTokens },
            cacheReadTokens = allStats.sumOf { it.cacheReadTokens },
            cacheCreationTokens = allStats.sumOf { it.cacheCreationTokens },
        )

        providerGroups = sortedGroups
        isLoaded = true
    }

    SettingsScaffold(title = stringResource(R.string.usage_title), onBack = onBack) {
        if (!isLoaded) return@SettingsScaffold

        SettingsSection(header = stringResource(R.string.usage_section_total)) {
            val stats = listOfNotNull(
                stringResource(R.string.usage_label_total_input) to formatCount(grandTotal.totalInput),
                stringResource(R.string.usage_label_output) to formatCount(grandTotal.outputTokens),
                if (grandTotal.cacheReadTokens > 0) stringResource(R.string.usage_label_cache_read) to formatCount(grandTotal.cacheReadTokens) else null,
                if (grandTotal.cacheCreationTokens > 0) stringResource(R.string.usage_label_cache_creation) to formatCount(grandTotal.cacheCreationTokens) else null,
                grandTotal.cacheHitRate?.let { rate -> stringResource(R.string.usage_label_cache_hit_rate) to String.format("%.1f%%", rate) },
            )
            stats.forEachIndexed { idx, (label, value) ->
                SettingsValueRow(
                    title = label,
                    value = value,
                    valueColor = MaterialTheme.colorScheme.onSurface,
                    showDivider = idx < stats.size - 1,
                )
            }
        }

        for (group in providerGroups) {
            SettingsSection(header = group.name) {
                group.models.forEachIndexed { idx, model ->
                    ExpandableModelRow(
                        model = model,
                        showDivider = idx < group.models.size - 1,
                    )
                }
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun ExpandableModelRow(model: ModelStats, showDivider: Boolean) {
    var expanded by remember { mutableStateOf(false) }
    val summary = "${formatCount(model.totalInput)} / ${formatCount(model.outputTokens)}"

    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { expanded = !expanded }
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                model.displayName,
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.weight(1f),
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    summary,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Icon(
                    if (expanded) Icons.Default.ExpandMore else Icons.AutoMirrored.Filled.KeyboardArrowRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                )
            }
        }

        AnimatedVisibility(visible = expanded) {
            Column(modifier = Modifier.padding(start = 32.dp, end = 16.dp, bottom = 8.dp)) {
                DetailRow(stringResource(R.string.usage_detail_input), formatCount(model.inputTokens))
                DetailRow(stringResource(R.string.usage_detail_output), formatCount(model.outputTokens))
                if (model.cacheReadTokens > 0) DetailRow(stringResource(R.string.usage_label_cache_read), formatCount(model.cacheReadTokens))
                if (model.cacheCreationTokens > 0) DetailRow(stringResource(R.string.usage_label_cache_creation), formatCount(model.cacheCreationTokens))
                val modelTotalInput = model.totalInput
                if (modelTotalInput > 0 && model.cacheReadTokens > 0) {
                    val rate = (model.cacheReadTokens.toDouble() / modelTotalInput) * 100
                    DetailRow(stringResource(R.string.usage_label_cache_hit_rate), String.format("%.1f%%", rate))
                }
                val days = model.distinctDays.size
                val sessions = model.distinctSessions.size
                if (days > 0) {
                    DetailRow(stringResource(R.string.usage_detail_daily_avg), formatCount((model.inputTokens + model.outputTokens) / days))
                }
                if (sessions > 0) {
                    DetailRow(stringResource(R.string.usage_detail_session_avg), formatCount((model.inputTokens + model.outputTokens) / sessions))
                }
                DetailRow(stringResource(R.string.usage_detail_sessions), sessions.toString())
                DetailRow(stringResource(R.string.usage_detail_active_days), days.toString())
            }
        }

        if (showDivider) {
            val divider = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 16.dp, end = 14.dp)
                    .height(0.5.dp)
                    .background(divider),
            )
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Default)
    }
}

private fun formatCount(n: Long): String = when {
    n >= 1_000_000 -> String.format("%.1fM", n / 1_000_000.0)
    n >= 1_000 -> {
        val k = n / 1000.0
        if (k == k.toLong().toDouble()) "${k.toLong()}k"
        else String.format("%.1fk", k)
    }
    else -> n.toString()
}
