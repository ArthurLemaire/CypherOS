package com.openminis.app.ui.settings

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.offload.ShizukuBackend
import com.openminis.app.offload.ShizukuManager

/**
 * T322 / [T-android-privileged-backend]: state-driven Shizuku-protocol
 * permission walkthrough.
 *
 * Renders a single section whose body changes based on
 * [ShizukuManager.snapshot]:
 *
 *   NOT_INSTALLED     → TWO install CTAs (Shizuku · GitHub / AXManager · GitHub).
 *                        Both managers speak the same protocol — the user picks
 *                        whichever they prefer.
 *   NOT_RUNNING       → "Open Manager App and press Start" — launches the
 *                        installed manager.
 *   NEED_PERMISSION   → "Authorize Minis" CTA → triggers system dialog.
 *   READY             → green status row with version + uid.
 */
@Composable
fun ShizukuPermissionScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val snap by ShizukuManager.snapshot.collectAsState()

    LaunchedEffect(Unit) { ShizukuManager.refresh() }

    SettingsScaffold(
        title = stringResource(R.string.shizuku_title),
        onBack = onBack,
    ) {
        SettingsSection(
            header = stringResource(R.string.shizuku_status_header),
            footer = stringResource(R.string.shizuku_status_footer),
        ) {
            SettingsRow(
                title = stringResource(stateTitle(snap.state)),
                subtitle = if (snap.state == ShizukuManager.State.READY) {
                    stringResource(R.string.shizuku_ready_subtitle, snap.version, snap.uid)
                } else {
                    stringResource(stateSubtitle(snap.state))
                },
                trailing = {
                    Text(
                        text = stringResource(stateBadge(snap.state)),
                        style = MaterialTheme.typography.labelMedium,
                        color = stateColor(snap.state),
                    )
                },
                showDivider = false,
            )
        }

        when (snap.state) {
            // Two parallel install entries — Shizuku and AXManager are
            // functionally equivalent; the user picks whichever they like.
            // Both go to the project's GitHub Releases page (no Play Store —
            // AXManager isn't published there, and a single source per manager
            // keeps the option set symmetrical).
            ShizukuManager.State.NOT_INSTALLED -> SettingsSection(
                header = stringResource(R.string.shizuku_actions_header),
                footer = stringResource(R.string.shizuku_install_footer),
            ) {
                SettingsRow(
                    title = stringResource(R.string.shizuku_install_btn),
                    subtitle = stringResource(R.string.shizuku_install_btn_subtitle),
                    onClick = { ShizukuManager.openInstallPage(context, ShizukuBackend.SHIZUKU_GITHUB_URL) },
                )
                SettingsRow(
                    title = stringResource(R.string.shizuku_install_btn_axmanager),
                    subtitle = stringResource(R.string.shizuku_install_btn_axmanager_subtitle),
                    onClick = { ShizukuManager.openInstallPage(context, ShizukuBackend.AXMANAGER_GITHUB_URL) },
                    showDivider = false,
                )
            }

            ShizukuManager.State.NOT_RUNNING -> SettingsSection(
                header = stringResource(R.string.shizuku_actions_header),
                footer = stringResource(R.string.shizuku_start_footer),
            ) {
                SettingsRow(
                    title = stringResource(R.string.shizuku_open_btn),
                    subtitle = stringResource(R.string.shizuku_open_btn_subtitle),
                    onClick = { ShizukuManager.openShizukuApp(context) },
                )
                SettingsRow(
                    title = stringResource(R.string.shizuku_recheck_btn),
                    subtitle = stringResource(R.string.shizuku_recheck_subtitle),
                    onClick = { ShizukuManager.refresh() },
                    showDivider = false,
                )
            }

            ShizukuManager.State.NEED_PERMISSION -> SettingsSection(
                header = stringResource(R.string.shizuku_actions_header),
                footer = stringResource(R.string.shizuku_grant_footer),
            ) {
                SettingsRow(
                    title = stringResource(R.string.shizuku_grant_btn),
                    subtitle = stringResource(R.string.shizuku_grant_subtitle),
                    onClick = { ShizukuManager.requestPermission() },
                )
                SettingsRow(
                    title = stringResource(R.string.shizuku_open_btn),
                    subtitle = stringResource(R.string.shizuku_open_btn_subtitle),
                    onClick = { ShizukuManager.openShizukuApp(context) },
                    showDivider = false,
                )
            }

            ShizukuManager.State.READY -> SettingsSection(
                header = stringResource(R.string.shizuku_capabilities_header),
                footer = stringResource(R.string.shizuku_capabilities_footer),
            ) {
                SettingsRow(
                    title = stringResource(R.string.shizuku_open_btn),
                    subtitle = stringResource(R.string.shizuku_open_btn_subtitle),
                    onClick = { ShizukuManager.openShizukuApp(context) },
                    showDivider = false,
                )
            }
        }
        Spacer(Modifier.height(16.dp))
    }
}

private fun stateTitle(s: ShizukuManager.State): Int = when (s) {
    ShizukuManager.State.NOT_INSTALLED -> R.string.shizuku_state_not_installed
    ShizukuManager.State.NOT_RUNNING -> R.string.shizuku_state_not_running
    ShizukuManager.State.NEED_PERMISSION -> R.string.shizuku_state_need_permission
    ShizukuManager.State.READY -> R.string.shizuku_state_ready
}

private fun stateSubtitle(s: ShizukuManager.State): Int = when (s) {
    ShizukuManager.State.NOT_INSTALLED -> R.string.shizuku_state_not_installed_subtitle
    ShizukuManager.State.NOT_RUNNING -> R.string.shizuku_state_not_running_subtitle
    ShizukuManager.State.NEED_PERMISSION -> R.string.shizuku_state_need_permission_subtitle
    ShizukuManager.State.READY -> R.string.shizuku_state_ready
}

private fun stateBadge(s: ShizukuManager.State): Int = when (s) {
    ShizukuManager.State.NOT_INSTALLED -> R.string.shizuku_badge_not_installed
    ShizukuManager.State.NOT_RUNNING -> R.string.shizuku_badge_not_running
    ShizukuManager.State.NEED_PERMISSION -> R.string.shizuku_badge_need_permission
    ShizukuManager.State.READY -> R.string.shizuku_badge_ready
}

@Composable
private fun stateColor(s: ShizukuManager.State): Color = when (s) {
    ShizukuManager.State.READY -> MaterialTheme.colorScheme.primary
    ShizukuManager.State.NEED_PERMISSION -> MaterialTheme.colorScheme.tertiary
    ShizukuManager.State.NOT_RUNNING -> MaterialTheme.colorScheme.tertiary
    ShizukuManager.State.NOT_INSTALLED -> MaterialTheme.colorScheme.error
}
