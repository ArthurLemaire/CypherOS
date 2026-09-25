package io.github.nanomuse.ui.profile

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.outlined.List
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Fingerprint
import androidx.compose.material.icons.outlined.Payments
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.VerifiedUser
import androidx.compose.material.icons.outlined.Widgets
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.agent.SoulStore
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskStore
import com.openminis.app.ui.scheduled.formatScheduleSummary
import io.github.nanomuse.guard.Grant
import io.github.nanomuse.guard.Grants
import io.github.nanomuse.guard.RiskClass
import io.github.nanomuse.guard.RiskText
import io.github.nanomuse.sysfiles.SystemFiles
import io.github.nanomuse.ui.avatar.AgentAvatar
import io.github.nanomuse.ui.avatar.AgentMood
import io.github.nanomuse.ui.avatar.AvatarShareSheet
import io.github.nanomuse.ui.home.MuseRoundButton
import io.github.nanomuse.ui.home.MuseTones
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.DateFormat
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale

const val ROUTE_AGENT_PROFILE = "nanomuse/profile"

/**
 * Muse's agent page — tap the face to get here: the face with its edit badge, the name,
 * "online", and four panes: what it did today, the approvals it holds, its daily routines,
 * and its soul & memory. The pen on the face offers "Change avatar" (back to the chat with the
 * request pre-typed) and "Edit name".
 */
@Composable
fun AgentProfileScreen(
    chatRepository: ChatRepository,
    onBack: () -> Unit,
    onEditName: () -> Unit,
    onChangeAvatar: () -> Unit,
    onOpenAvatarStudio: () -> Unit,
    onOpenSession: (String) -> Unit,
    onOpenPermissions: () -> Unit,
    onOpenRoutines: () -> Unit,
    onOpenSystemFile: (SystemFiles) -> Unit,
) {
    val context = LocalContext.current
    val soul by SoulStore.cachedMetadata.collectAsState()
    val name = soul.name.trim().ifEmpty { stringResource(R.string.app_name) }
    var pane by rememberSaveable { mutableIntStateOf(0) }
    var penMenu by remember { mutableStateOf(false) }
    var share by remember { mutableStateOf(false) }

    Scaffold(containerColor = MuseTones.canvas) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // ×, the face with its pen, share.
            Box(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                MuseRoundButton(
                    icon = Icons.Outlined.Close,
                    contentDescription = stringResource(R.string.nm_back),
                    onClick = onBack,
                    modifier = Modifier.align(Alignment.TopStart).padding(start = 16.dp),
                )
                MuseRoundButton(
                    icon = Icons.Outlined.Share,
                    contentDescription = stringResource(R.string.nm_avatar_share_button),
                    onClick = { share = true },
                    modifier = Modifier.align(Alignment.TopEnd).padding(end = 16.dp),
                )
                Box(Modifier.align(Alignment.TopCenter)) {
                    AgentAvatar(
                        mood = AgentMood.IDLE,
                        size = 72.dp,
                        contentDescription = stringResource(R.string.nm_avatar_content_description),
                        onClick = { penMenu = true },
                    )
                    // The pen badge, bottom-right of the face.
                    Box(Modifier.align(Alignment.BottomEnd)) {
                        Surface(
                            onClick = { penMenu = true },
                            shape = CircleShape,
                            color = MuseTones.surface,
                            shadowElevation = 2.dp,
                            modifier = Modifier.size(24.dp),
                        ) {
                            Box(contentAlignment = Alignment.Center) {
                                Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.nm_profile_edit), modifier = Modifier.size(13.dp), tint = MaterialTheme.colorScheme.onSurface)
                            }
                        }
                        DropdownMenu(expanded = penMenu, onDismissRequest = { penMenu = false }) {
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.nm_profile_change_avatar)) },
                                onClick = { penMenu = false; onChangeAvatar() },
                            )
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.nm_profile_edit_name)) },
                                onClick = { penMenu = false; onEditName() },
                            )
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.nm_profile_avatar_studio), color = MaterialTheme.colorScheme.onSurfaceVariant) },
                                onClick = { penMenu = false; onOpenAvatarStudio() },
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(10.dp))
            Text(name, fontSize = 21.sp, lineHeight = 26.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
            Spacer(Modifier.height(2.dp))
            Text(stringResource(R.string.nm_profile_online), fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(18.dp))

            PaneSwitch(
                selected = pane,
                onSelect = { pane = it },
                icons = listOf(Icons.AutoMirrored.Outlined.List, Icons.Outlined.VerifiedUser, Icons.Outlined.Schedule, Icons.Outlined.Fingerprint),
                labels = listOf(
                    stringResource(R.string.nm_profile_pane_activity),
                    stringResource(R.string.nm_profile_pane_approvals),
                    stringResource(R.string.nm_profile_pane_daily),
                    stringResource(R.string.nm_profile_pane_soul),
                ),
            )
            Spacer(Modifier.height(20.dp))

            when (pane) {
                0 -> ActivityPane(chatRepository, onOpenSession)
                1 -> ApprovalsPane(onOpenPermissions)
                2 -> DailyPane(onOpenRoutines)
                else -> SoulPane(name, onEditName, onOpenSystemFile)
            }
            Spacer(Modifier.height(32.dp))
        }
    }
    if (share) AvatarShareSheet(onDismiss = { share = false })
}

/** Muse's four-way segmented control: glyphs on a white bar, a grey pill under the current one. */
@Composable
private fun PaneSwitch(selected: Int, onSelect: (Int) -> Unit, icons: List<ImageVector>, labels: List<String>) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MuseTones.surface,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
    ) {
        Row(Modifier.padding(4.dp)) {
            icons.forEachIndexed { i, icon ->
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(44.dp)
                        .clip(RoundedCornerShape(13.dp))
                        .background(if (i == selected) MuseTones.fill else Color.Transparent)
                        .clickable { onSelect(i) },
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(icon, contentDescription = labels.getOrNull(i), tint = MaterialTheme.colorScheme.onSurface, modifier = Modifier.size(22.dp))
                }
            }
        }
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text = text,
        fontSize = 15.sp,
        color = MaterialTheme.colorScheme.onSurface,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    )
}

@Composable
private fun EmptyNote(text: String) {
    Text(
        text = text,
        fontSize = 14.sp,
        lineHeight = 20.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
    )
}

// ── activity ────────────────────────────────────────────────────────────────

private data class ActivityEntry(val time: Long, val title: String, val subtitle: String, val sessionId: String)

@Composable
private fun ActivityPane(chatRepository: ChatRepository, onOpenSession: (String) -> Unit) {
    val context = LocalContext.current
    val sessions by chatRepository.observeSessions().collectAsState(initial = null)
    val entries by produceState<List<ActivityEntry>?>(initialValue = null, sessions) {
        val list = sessions ?: return@produceState
        value = withContext(Dispatchers.IO) { loadActivity(chatRepository, list) }
    }
    val list = entries
    when {
        list == null -> Unit
        list.isEmpty() -> EmptyNote(stringResource(R.string.nm_profile_activity_empty))
        else -> {
            val groups = list.groupBy { dayLabel(context, it.time) }
            groups.forEach { (label, items) ->
                SectionLabel(label)
                items.forEach { e ->
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onOpenSession(e.sessionId) }
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Box(
                            modifier = Modifier.size(36.dp).clip(CircleShape).background(Color(0xFFE6E3F2)),
                            contentAlignment = Alignment.Center,
                        ) {
                            Icon(Icons.Outlined.Widgets, contentDescription = null, tint = Color(0xFF6B5FA5), modifier = Modifier.size(18.dp))
                        }
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(e.title, fontSize = 16.sp, lineHeight = 21.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            if (e.subtitle.isNotBlank()) {
                                Spacer(Modifier.height(2.dp))
                                Text(e.subtitle, fontSize = 14.sp, lineHeight = 19.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                            Spacer(Modifier.height(2.dp))
                            Text(timeLabel(e.time), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

/**
 * The last two days of conversation as a log: each request the user made, with what the agent
 * did about it (its tool titles, or the first line of its answer).
 */
private suspend fun loadActivity(
    chatRepository: ChatRepository,
    sessions: List<com.openminis.app.data.db.ChatSessionEntity>,
): List<ActivityEntry> {
    val since = startOfDay(System.currentTimeMillis()) - 24L * 60 * 60 * 1000
    val recent = sessions.filter { it.updatedAt >= since }.sortedByDescending { it.updatedAt }.take(12)
    val out = ArrayList<ActivityEntry>()
    for (s in recent) {
        val messages = runCatching { chatRepository.loadMessages(s.id) }.getOrDefault(emptyList())
        var i = 0
        while (i < messages.size) {
            val m = messages[i]
            if (m.role == "user" && m.createdAt >= since) {
                val title = firstLine(userText(m.partsJson))
                if (title.isNotBlank()) {
                    val doing = ArrayList<String>()
                    var j = i + 1
                    while (j < messages.size && messages[j].role != "user") {
                        doing += assistantSummary(messages[j].partsJson)
                        j++
                    }
                    val tools = doing.filter { it.startsWith("\u0001") }.map { it.drop(1) }
                    val texts = doing.filter { !it.startsWith("\u0001") && it.isNotBlank() }
                    val subtitle = when {
                        tools.isNotEmpty() -> tools.distinct().take(3).joinToString(" · ")
                        texts.isNotEmpty() -> firstLine(texts.last())
                        else -> ""
                    }
                    out += ActivityEntry(m.createdAt, title, subtitle, s.id)
                }
            }
            i++
        }
    }
    return out.sortedByDescending { it.time }.take(60)
}

private fun userText(partsJson: String): String = runCatching {
    val arr = org.json.JSONArray(partsJson)
    buildString {
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            if (o.optString("type") == "text") append(o.optString("value"))
        }
    }
}.getOrDefault("")
    .replace(Regex("<system-reminder>[\\s\\S]*?</system-reminder>"), "")
    .replace(Regex("<user-attached-files>[\\s\\S]*?</user-attached-files>"), "")
    .trim()

/** Tool titles are returned with a \u0001 prefix so the caller can tell them from prose. */
private fun assistantSummary(partsJson: String): String = runCatching {
    val arr = org.json.JSONArray(partsJson)
    var text = ""
    val tools = ArrayList<String>()
    for (i in 0 until arr.length()) {
        val o = arr.optJSONObject(i) ?: continue
        when (o.optString("type")) {
            "text" -> if (text.isBlank()) text = o.optString("value")
            "toolUse" -> o.optJSONObject("value")?.let { tu ->
                val title = runCatching { org.json.JSONObject(tu.optString("input", "")).optString("tool_title", "") }.getOrDefault("")
                tools += title.ifBlank { tu.optString("name", "") }
            }
        }
    }
    if (tools.isNotEmpty()) "\u0001" + tools.first() else text
}.getOrDefault("")

private fun firstLine(text: String): String {
    val line = text.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() && !it.startsWith("```") } ?: ""
    return if (line.length > 72) line.take(72).trimEnd() + "…" else line
}

private fun startOfDay(ms: Long): Long = Calendar.getInstance().apply {
    timeInMillis = ms
    set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
}.timeInMillis

private fun dayLabel(context: android.content.Context, ms: Long): String {
    val today = startOfDay(System.currentTimeMillis())
    return when {
        ms >= today -> context.getString(R.string.nm_profile_today)
        ms >= today - 24L * 60 * 60 * 1000 -> context.getString(R.string.nm_profile_yesterday)
        else -> DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(ms))
    }
}

private fun timeLabel(ms: Long): String = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(ms))

// ── approvals ───────────────────────────────────────────────────────────────

@Composable
private fun ApprovalsPane(onOpenPermissions: () -> Unit) {
    val context = LocalContext.current
    val grants by Grants.always.collectAsState()
    if (grants.isEmpty()) {
        EmptyNote(stringResource(R.string.nm_profile_approvals_empty))
    } else {
        SectionLabel(stringResource(R.string.nm_profile_approvals_always))
        grants.sortedByDescending { it.grantedAt }.forEach { g -> GrantRow(g) }
    }
    Spacer(Modifier.height(8.dp))
    ManageRow(stringResource(R.string.nm_profile_manage_permissions), onOpenPermissions)
}

@Composable
private fun GrantRow(g: Grant) {
    val context = LocalContext.current
    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            modifier = Modifier.size(36.dp).clip(CircleShape).background(Color(0xFFDDEBFA)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                if (g.riskClass == RiskClass.MONEY) Icons.Outlined.Payments else Icons.Outlined.VerifiedUser,
                contentDescription = null, tint = Color(0xFF2F5FA8), modifier = Modifier.size(18.dp),
            )
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(
                g.label.ifBlank { RiskText.classLabel(context, g.riskClass) },
                fontSize = 16.sp, lineHeight = 21.sp, fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface, maxLines = 2, overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                stringResource(R.string.nm_profile_always_allowed, RiskText.targetLabel(context, g.target) ?: g.target ?: ""),
                fontSize = 14.sp, lineHeight = 19.sp, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(2.dp))
            Text(SystemFiles.relative(context, g.grantedAt), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ManageRow(text: String, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        color = MuseTones.surface,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
    ) {
        Row(Modifier.padding(horizontal = 16.dp).heightIn(min = 50.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(text, fontSize = 15.sp, color = MaterialTheme.colorScheme.onSurface, modifier = Modifier.weight(1f))
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.55f))
        }
    }
}

// ── daily ───────────────────────────────────────────────────────────────────

@Composable
private fun DailyPane(onOpenRoutines: () -> Unit) {
    val context = LocalContext.current
    val tasks = remember { ScheduledTaskStore(context).all().filterNot { it.hidden }.sortedBy { it.timeOfDayHour * 60 + it.timeOfDayMinute } }
    if (tasks.isEmpty()) {
        EmptyNote(stringResource(R.string.nm_profile_daily_empty))
    } else {
        SectionLabel(stringResource(R.string.nm_profile_pane_daily))
        tasks.forEach { t -> RoutineRow(t, onOpenRoutines) }
    }
    Spacer(Modifier.height(8.dp))
    ManageRow(stringResource(R.string.nm_profile_manage_routines), onOpenRoutines)
}

@Composable
private fun RoutineRow(t: ScheduledTask, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier.size(36.dp).clip(RoundedCornerShape(10.dp)).background(Color(0xFFFBEFC7)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Outlined.Schedule, contentDescription = null, tint = Color(0xFF9A6B12), modifier = Modifier.size(18.dp))
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(t.label, fontSize = 16.sp, lineHeight = 21.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(2.dp))
            Text(
                if (t.enabled) formatScheduleSummary(t) else stringResource(R.string.nm_routine_paused) + " · " + formatScheduleSummary(t),
                fontSize = 14.sp, lineHeight = 19.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.55f))
    }
}

// ── soul & memory ───────────────────────────────────────────────────────────

@Composable
private fun SoulPane(name: String, onEditName: () -> Unit, onOpenSystemFile: (SystemFiles) -> Unit) {
    val context = LocalContext.current
    SectionLabel(name)
    Spacer(Modifier.height(4.dp))
    Surface(
        onClick = onEditName,
        shape = RoundedCornerShape(16.dp),
        color = MuseTones.surface,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
    ) {
        Row(Modifier.height(50.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Edit, contentDescription = null, modifier = Modifier.size(18.dp), tint = MaterialTheme.colorScheme.onSurface)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.nm_profile_edit), fontSize = 15.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface)
        }
    }
    Spacer(Modifier.height(16.dp))
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        val fmt = remember { SimpleDateFormat("M/d/yy", Locale.getDefault()) }
        FileCard(
            title = stringResource(R.string.nm_profile_card_soul),
            date = SystemFiles.SOUL.lastModified(context)?.let { fmt.format(Date(it)) } ?: "",
            colors = listOf(Color(0xFF7D6BC7), Color(0xFF574494)),
            modifier = Modifier.weight(1f),
            onClick = { onOpenSystemFile(SystemFiles.SOUL) },
        )
        FileCard(
            title = stringResource(R.string.nm_profile_card_memory),
            date = SystemFiles.MEMORY.lastModified(context)?.let { fmt.format(Date(it)) } ?: "",
            colors = listOf(Color(0xFFB0413E), Color(0xFF7A1F1F)),
            modifier = Modifier.weight(1f),
            onClick = { onOpenSystemFile(SystemFiles.MEMORY) },
        )
    }
}

@Composable
private fun FileCard(title: String, date: String, colors: List<Color>, modifier: Modifier, onClick: () -> Unit) {
    Box(
        modifier = modifier
            .height(130.dp)
            .clip(RoundedCornerShape(18.dp))
            .background(Brush.verticalGradient(colors))
            .clickable(onClick = onClick)
            .padding(14.dp),
    ) {
        Column {
            Text(title, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = Color.White)
            Spacer(Modifier.height(2.dp))
            Text(stringResource(R.string.nm_profile_handle_with_care), fontSize = 11.sp, color = Color.White.copy(alpha = 0.85f))
        }
        Text(date, fontSize = 12.sp, color = Color.White.copy(alpha = 0.9f), modifier = Modifier.align(Alignment.BottomStart))
    }
}
