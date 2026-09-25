package io.github.nanomuse.ui.reach

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Computer
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import io.github.nanomuse.reach.Computers
import io.github.nanomuse.ui.home.MuseTones
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

const val ROUTE_COMPUTERS = "nanomuse/computers"

/**
 * Settings → Computers. The computers this phone drives: each with its name, system, address
 * and when it last answered, a tap to check it, *Forget* to drop it; and the three steps to pair
 * a new one — run the host script there, read the address and the code, type them here.
 */
@Composable
fun ComputersScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val computers by Computers.flow(context).collectAsState()
    val checks = remember { mutableStateMapOf<String, String>() }
    var address by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var pairing by remember { mutableStateOf(false) }
    var pairError by remember { mutableStateOf<String?>(null) }
    var pairedName by remember { mutableStateOf<String?>(null) }

    SettingsScaffold(title = stringResource(R.string.nm_pc_title), onBack = onBack) {
        Text(
            text = stringResource(R.string.nm_pc_intro),
            fontSize = 14.sp,
            lineHeight = 20.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp).padding(top = 12.dp),
        )

        // ── paired ──
        val list = computers.orEmpty()
        SettingsSection(
            header = stringResource(R.string.nm_pc_section_paired),
            footer = if (list.isEmpty()) stringResource(R.string.nm_pc_none_footer) else stringResource(R.string.nm_pc_paired_footer),
        ) {
            if (list.isEmpty()) {
                SettingsRow(title = stringResource(R.string.nm_pc_none), showDivider = false)
            }
            list.forEachIndexed { i, c ->
                val seen = if (c.lastSeen > 0) SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date(c.lastSeen)) else "—"
                SettingsRow(
                    title = c.name,
                    subtitle = checks[c.id] ?: listOf(c.os.ifBlank { "?" }, c.address, stringResource(R.string.nm_pc_last_seen, seen)).joinToString(" · "),
                    icon = Icons.Outlined.Computer,
                    iconColor = MaterialTheme.colorScheme.onSurface,
                    onClick = {
                        checks[c.id] = context.getString(R.string.nm_pc_checking)
                        scope.launch {
                            val up = withContext(Dispatchers.IO) { Computers.reachable(context, c) }
                            checks[c.id] = context.getString(if (up) R.string.nm_pc_answering else R.string.nm_pc_not_answering, c.address)
                        }
                    },
                    showChevron = false,
                    showDivider = i < list.lastIndex,
                    minHeight = 64.dp,
                    trailing = {
                        Text(
                            text = stringResource(R.string.nm_pc_forget),
                            fontSize = 14.sp,
                            fontWeight = FontWeight.Medium,
                            color = MaterialTheme.colorScheme.error,
                            modifier = Modifier.padding(start = 8.dp).clickable { Computers.forget(context, c.id) },
                        )
                    },
                )
            }
        }

        // ── pair ──
        SettingsSection(header = stringResource(R.string.nm_pc_section_pair), footer = stringResource(R.string.nm_pc_pair_footer)) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp)) {
                Text(stringResource(R.string.nm_pc_step1), fontSize = 14.sp, lineHeight = 20.sp)
                Text(
                    "python3 nanomuse_host.py",
                    fontSize = 13.sp,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 6.dp),
                )
                Text(stringResource(R.string.nm_pc_step2), fontSize = 14.sp, lineHeight = 20.sp)
                Spacer(Modifier.height(10.dp))
                Row(Modifier.fillMaxWidth()) {
                    OutlinedTextField(
                        value = address,
                        onValueChange = { address = it; pairError = null; pairedName = null },
                        label = { Text(stringResource(R.string.nm_pc_address)) },
                        placeholder = { Text("192.168.1.23:7333") },
                        singleLine = true,
                        modifier = Modifier.weight(1.6f),
                        shape = RoundedCornerShape(14.dp),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, unfocusedBorderColor = MuseTones.hairline),
                    )
                    Spacer(Modifier.width(10.dp))
                    OutlinedTextField(
                        value = code,
                        onValueChange = { code = it.filter { ch -> ch.isDigit() || ch == ' ' }.take(7); pairError = null; pairedName = null },
                        label = { Text(stringResource(R.string.nm_pc_code)) },
                        placeholder = { Text("483 921") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(14.dp),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, unfocusedBorderColor = MuseTones.hairline),
                    )
                }
                Spacer(Modifier.height(10.dp))
                val canPair = !pairing && address.isNotBlank() && code.replace(" ", "").length == 6
                Button(
                    onClick = {
                        val (host, port) = parseAddress(address) ?: run { pairError = context.getString(R.string.nm_pc_bad_address); return@Button }
                        pairing = true; pairError = null
                        scope.launch {
                            val result = withContext(Dispatchers.IO) { runCatching { Computers.pair(context, host, port, code) } }
                            pairing = false
                            result.onSuccess { pairedName = it.name; address = ""; code = "" }
                                .onFailure { pairError = it.message ?: it.javaClass.simpleName }
                        }
                    },
                    enabled = canPair,
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(stringResource(if (pairing) R.string.nm_pc_pairing else R.string.nm_pc_pair))
                }
                pairError?.let {
                    Text(it, fontSize = 13.sp, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 8.dp))
                }
                pairedName?.let {
                    Text(stringResource(R.string.nm_pc_paired_with, it), fontSize = 13.sp, color = MuseTones.action, modifier = Modifier.padding(top = 8.dp))
                }
            }
        }

        // ── how it works ──
        SettingsSection(header = stringResource(R.string.nm_pc_section_how)) {
            SettingsRow(title = stringResource(R.string.nm_pc_how_1), minHeight = 48.dp)
            SettingsRow(title = stringResource(R.string.nm_pc_how_2), minHeight = 48.dp)
            SettingsRow(title = stringResource(R.string.nm_pc_how_3), minHeight = 48.dp)
            SettingsRow(title = stringResource(R.string.nm_pc_how_4), minHeight = 48.dp, showDivider = false)
        }
        Spacer(Modifier.height(32.dp))
    }
}

/** `host`, `host:port`, `http://host:port/` → host and port. */
internal fun parseAddress(raw: String): Pair<String, Int>? {
    var s = raw.trim().removePrefix("http://").removePrefix("https://").trimEnd('/')
    if (s.isEmpty()) return null
    var port = Computers.DEFAULT_PORT
    val idx = s.lastIndexOf(':')
    if (idx > 0 && s.indexOf(':') == idx) {
        port = s.substring(idx + 1).toIntOrNull() ?: return null
        s = s.substring(0, idx)
    }
    if (s.isBlank() || s.contains(' ') || port !in 1..65535) return null
    return s to port
}
