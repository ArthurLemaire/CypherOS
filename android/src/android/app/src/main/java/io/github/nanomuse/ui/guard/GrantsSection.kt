package io.github.nanomuse.ui.guard

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Payments
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsSection
import io.github.nanomuse.guard.Grant
import io.github.nanomuse.guard.Grants
import io.github.nanomuse.guard.RiskClass
import io.github.nanomuse.guard.RiskText
import java.text.DateFormat
import java.util.Date

/** Settings → Permissions: the "always allow for X" grants, one row each, tap to revoke. */
@Composable
fun GrantsSection() {
    val context = LocalContext.current
    val grants by Grants.always.collectAsState()
    var revoking by remember { mutableStateOf<Grant?>(null) }

    SettingsSection(
        header = stringResource(R.string.nm_grants_header),
        footer = stringResource(R.string.nm_grants_footer),
    ) {
        if (grants.isEmpty()) {
            SettingsRow(title = stringResource(R.string.nm_grants_empty), showDivider = false, showChevron = false)
        } else {
            grants.forEachIndexed { i, g ->
                SettingsRow(
                    title = RiskText.classLabel(context, g.riskClass) + " · " + (RiskText.targetLabel(context, g.target) ?: g.target ?: ""),
                    subtitle = DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(g.grantedAt)),
                    icon = when (g.riskClass) {
                        RiskClass.DESTRUCTIVE -> Icons.Outlined.DeleteOutline
                        RiskClass.MONEY -> Icons.Outlined.Payments
                        RiskClass.INSTALL -> Icons.Outlined.Download
                        else -> Icons.AutoMirrored.Outlined.Send
                    },
                    onClick = { revoking = g },
                    showChevron = false,
                    showDivider = i < grants.size - 1,
                    minHeight = 64.dp,
                )
            }
        }
    }

    revoking?.let { g ->
        AlertDialog(
            onDismissRequest = { revoking = null },
            title = { Text(RiskText.classLabel(context, g.riskClass) + " · " + (RiskText.targetLabel(context, g.target) ?: "")) },
            text = { Text(stringResource(R.string.nm_grants_revoke_confirm)) },
            confirmButton = {
                TextButton(onClick = { Grants.revoke(g.key); revoking = null }) { Text(stringResource(R.string.nm_grants_revoke)) }
            },
            dismissButton = { TextButton(onClick = { revoking = null }) { Text(stringResource(android.R.string.cancel)) } },
        )
    }
}
