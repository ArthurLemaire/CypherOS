package io.github.nanomuse.ui.hands

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Accessibility
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsChoiceRow
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import com.openminis.app.ui.settings.SettingsSwitchRow
import io.github.nanomuse.hands.Hands
import io.github.nanomuse.ui.home.MuseTones

const val ROUTE_HANDS = "nanomuse/hands"

/**
 * Settings → Hands. The switch (off by default), the three things the hands need — the
 * accessibility service, drawing over other apps, a model that sees pictures — each with
 * the button that fixes it, the screen model, and the plain words on what the hands will and
 * will not do.
 */
@Composable
fun HandsScreen(onBack: () -> Unit, onOpenProviders: () -> Unit) {
    val context = LocalContext.current
    val repo = (context.applicationContext as? MinisApp)?.providerRepositoryOrNull
    val config = repo?.config?.collectAsState()?.value
    var enabled by remember { mutableStateOf(Hands.enabled(context)) }
    var chosen by remember { mutableStateOf(Hands.modelEntryId(context)) }
    var tick by remember { mutableIntStateOf(0) }
    val active by Hands.active.collectAsState()

    // Permissions are granted in other apps; re-read when the user comes back.
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) tick++ }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    val readiness = remember(tick, config, chosen) { Hands.readiness(context) }
    val visionEntries = remember(config) { Hands.visionEntries(context) }

    SettingsScaffold(title = stringResource(R.string.nm_hands_title), onBack = onBack) {
        Text(
            text = stringResource(R.string.nm_hands_intro),
            fontSize = 14.sp,
            lineHeight = 20.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp).padding(top = 12.dp),
        )

        SettingsSection(footer = stringResource(R.string.nm_hands_switch_footer)) {
            SettingsSwitchRow(
                title = stringResource(R.string.nm_hands_switch),
                subtitle = when {
                    active -> stringResource(R.string.nm_hands_status_working)
                    enabled && readiness.ready -> stringResource(R.string.nm_hands_status_ready)
                    enabled -> stringResource(R.string.nm_hands_status_missing)
                    else -> stringResource(R.string.nm_hands_status_off)
                },
                checked = enabled,
                onCheckedChange = { enabled = it; Hands.setEnabled(context, it) },
                icon = Icons.Outlined.PhoneAndroid,
                iconColor = if (enabled) MuseTones.action else MaterialTheme.colorScheme.onSurfaceVariant,
                showDivider = active,
            )
            if (active) {
                SettingsRow(
                    title = stringResource(R.string.nm_hands_stop_run),
                    onClick = { Hands.stopCurrent() },
                    showChevron = false,
                    showDivider = false,
                    titleColor = MaterialTheme.colorScheme.error,
                )
            }
        }

        // ── what it needs ──
        SettingsSection(header = stringResource(R.string.nm_hands_section_needs), footer = stringResource(R.string.nm_hands_needs_footer)) {
            NeedRow(
                icon = Icons.Outlined.Accessibility,
                title = stringResource(R.string.nm_hands_need_a11y),
                ok = readiness.serviceOn,
                okText = stringResource(R.string.nm_hands_need_on),
                fixText = stringResource(R.string.nm_hands_need_a11y_fix),
                onFix = { openAccessibilitySettings(context) },
            )
            NeedRow(
                icon = Icons.Outlined.Layers,
                title = stringResource(R.string.nm_hands_need_overlay),
                ok = readiness.overlayOk,
                okText = stringResource(R.string.nm_hands_need_granted),
                fixText = stringResource(R.string.nm_hands_need_overlay_fix),
                onFix = { openOverlaySettings(context) },
            )
            NeedRow(
                icon = Icons.Outlined.Visibility,
                title = stringResource(R.string.nm_hands_need_model),
                ok = readiness.model != null,
                okText = readiness.model?.label ?: "",
                fixText = stringResource(R.string.nm_hands_need_model_fix),
                onFix = onOpenProviders,
                showDivider = !readiness.androidOk,
            )
            if (!readiness.androidOk) {
                SettingsRow(
                    title = stringResource(R.string.nm_hands_need_android),
                    subtitle = stringResource(R.string.nm_hands_need_android_sub),
                    showDivider = false,
                )
            }
        }

        // ── the screen model ──
        if (visionEntries.isNotEmpty()) {
            SettingsSection(header = stringResource(R.string.nm_hands_section_model), footer = stringResource(R.string.nm_hands_model_footer)) {
                SettingsChoiceRow(
                    title = stringResource(R.string.nm_hands_model_auto),
                    selected = chosen == null,
                    onSelect = { chosen = null; Hands.setModelEntryId(context, null) },
                )
                visionEntries.forEachIndexed { i, (inst, entry) ->
                    SettingsChoiceRow(
                        title = entry.model.displayName.ifBlank { entry.model.id } + " · " + inst.label,
                        selected = chosen == entry.id,
                        onSelect = { chosen = entry.id; Hands.setModelEntryId(context, entry.id) },
                        showDivider = i < visionEntries.lastIndex,
                    )
                }
            }
        }

        // ── the rules ──
        SettingsSection(header = stringResource(R.string.nm_hands_section_rules)) {
            RuleRow(stringResource(R.string.nm_hands_rule_ladder))
            RuleRow(stringResource(R.string.nm_hands_rule_secrets))
            RuleRow(stringResource(R.string.nm_hands_rule_approvals))
            RuleRow(stringResource(R.string.nm_hands_rule_stop))
            RuleRow(stringResource(R.string.nm_hands_rule_screenshots), last = true)
        }
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun NeedRow(
    icon: ImageVector,
    title: String,
    ok: Boolean,
    okText: String,
    fixText: String,
    onFix: () -> Unit,
    showDivider: Boolean = true,
) {
    SettingsRow(
        title = title,
        subtitle = if (ok) okText else fixText,
        icon = icon,
        iconColor = if (ok) MuseTones.action else MaterialTheme.colorScheme.onSurfaceVariant,
        onClick = if (ok) null else onFix,
        showChevron = false,
        showDivider = showDivider,
        minHeight = 64.dp,
        trailing = {
            Text(
                text = stringResource(if (ok) R.string.nm_hands_need_ok else R.string.nm_hands_need_set_up),
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                color = if (ok) MaterialTheme.colorScheme.onSurfaceVariant else MuseTones.action,
            )
        },
    )
}

@Composable
private fun RuleRow(text: String, last: Boolean = false) {
    SettingsRow(title = text, showDivider = !last, minHeight = 48.dp)
}

private fun openAccessibilitySettings(context: Context) {
    try {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Throwable) {
        runCatching { context.startActivity(Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}

private fun openOverlaySettings(context: Context) {
    try {
        context.startActivity(
            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    } catch (_: Throwable) {
        runCatching { context.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}
