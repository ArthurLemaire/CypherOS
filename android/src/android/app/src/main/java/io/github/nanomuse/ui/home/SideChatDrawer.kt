package io.github.nanomuse.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding

import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.repository.ChatRepository
import java.text.DateFormat
import java.util.Date

/**
 * Muse's chats drawer: the agent's name, the "main chat" row, then side chats by topic, with
 * search, settings and "new" along the bottom. The archive glyph beside the section title opens
 * the full OpenMinis session list (folders, groups, search, bulk actions) — nothing upstream is
 * lost, it just moved one tap away.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SideChatDrawer(
    agentName: String,
    chatRepository: ChatRepository,
    mainSessionId: String?,
    currentSessionId: String?,
    onOpenMain: () -> Unit,
    onOpenSession: (String) -> Unit,
    onNewChat: () -> Unit,
    onAllChats: () -> Unit,
    onSettings: () -> Unit,
    onSetMain: (String) -> Unit,
    onSystemFiles: (() -> Unit)? = null,
) {
    val sessions by chatRepository.observeSessions().collectAsState(initial = emptyList())
    var query by remember { mutableStateOf("") }
    val sideChats = remember(sessions, mainSessionId, query) {
        sessions
            .filter { it.id != mainSessionId }
            .filter { query.isBlank() || (it.title ?: "").contains(query, ignoreCase = true) }
            .sortedWith(compareByDescending<ChatSessionEntity> { it.pinnedAt ?: 0L }.thenByDescending { it.updatedAt })
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MuseTones.surface)
            .statusBarsPadding()
            .navigationBarsPadding(),
    ) {
        Text(
            text = agentName,
            fontSize = 24.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.padding(start = 20.dp, top = 18.dp, end = 20.dp, bottom = 14.dp),
        )

        // Main chat row — selected when it is what the chat tab shows.
        val mainSelected = currentSessionId == null || currentSessionId == mainSessionId
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .padding(horizontal = 12.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(14.dp))
                .background(if (mainSelected) MuseTones.fill else MuseTones.surface)
                .clickable(onClick = onOpenMain)
                .padding(horizontal = 14.dp, vertical = 14.dp),
        ) {
            Icon(Icons.Outlined.Home, contentDescription = null, modifier = Modifier.size(20.dp), tint = MaterialTheme.colorScheme.onSurface)
            Spacer(Modifier.size(12.dp))
            Text(
                text = stringResource(R.string.nm_drawer_main_chat),
                fontSize = 16.sp,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface,
            )
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(start = 26.dp, end = 12.dp, top = 12.dp),
        ) {
            Text(
                text = stringResource(R.string.nm_drawer_side_chats),
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onAllChats) {
                Icon(
                    Icons.Outlined.Archive,
                    contentDescription = stringResource(R.string.nm_drawer_all_chats),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(20.dp),
                )
            }
        }

        if (sideChats.isEmpty()) {
            Column(
                modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 32.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(
                    Icons.Outlined.Forum,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(30.dp),
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    text = stringResource(R.string.nm_drawer_empty_title),
                    fontSize = 17.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = stringResource(R.string.nm_drawer_empty_body),
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                )
            }
        } else {
            LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 4.dp)) {
                items(sideChats, key = { it.id }) { session ->
                    SideChatRow(
                        session = session,
                        selected = session.id == currentSessionId,
                        onClick = { onOpenSession(session.id) },
                        onSetMain = { onSetMain(session.id) },
                    )
                }
            }
        }

        // Bottom strip: settings · search · new
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 8.dp, end = 8.dp, bottom = 8.dp, top = 6.dp),
        ) {
            IconButton(onClick = onSettings) {
                Icon(Icons.Outlined.Settings, contentDescription = stringResource(R.string.nm_drawer_settings), tint = MaterialTheme.colorScheme.onSurface)
            }
            if (onSystemFiles != null) {
                IconButton(onClick = onSystemFiles) {
                    Icon(Icons.Outlined.Description, contentDescription = stringResource(R.string.nm_sysfiles_title), tint = MaterialTheme.colorScheme.onSurface)
                }
            }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .weight(1f)
                    .height(40.dp)
                    .clip(CircleShape)
                    .background(MuseTones.fill)
                    .padding(horizontal = 12.dp),
            ) {
                Icon(Icons.Outlined.Search, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(18.dp))
                Spacer(Modifier.size(8.dp))
                Box(Modifier.weight(1f)) {
                    if (query.isEmpty()) {
                        Text(
                            stringResource(R.string.nm_drawer_search),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            fontSize = 15.sp,
                        )
                    }
                    BasicTextField(
                        value = query,
                        onValueChange = { query = it },
                        singleLine = true,
                        textStyle = LocalTextStyle.current.copy(color = MaterialTheme.colorScheme.onSurface, fontSize = 15.sp),
                        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            IconButton(onClick = onNewChat) {
                Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.nm_drawer_new_chat), tint = MaterialTheme.colorScheme.onSurface)
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SideChatRow(
    session: ChatSessionEntity,
    selected: Boolean,
    onClick: () -> Unit,
    onSetMain: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Box {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .padding(horizontal = 12.dp, vertical = 1.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(if (selected) MuseTones.fill else MuseTones.surface)
                .combinedClickable(onClick = onClick, onLongClick = { menu = true })
                .padding(horizontal = 14.dp, vertical = 11.dp),
        ) {
            Text(
                text = session.title?.takeIf { it.isNotBlank() } ?: stringResource(R.string.nm_drawer_untitled),
                fontSize = 15.sp,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.size(10.dp))
            Text(
                text = relativeDay(session.updatedAt),
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.nm_drawer_set_main)) },
                onClick = { menu = false; onSetMain() },
            )
        }
    }
}

internal fun relativeDay(ms: Long): String {
    val now = System.currentTimeMillis()
    val diff = now - ms
    return when {
        diff < 60_000L -> "now"
        android.text.format.DateUtils.isToday(ms) -> DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(ms))
        diff < 7L * 24 * 3600_000L -> java.text.SimpleDateFormat("EEE", java.util.Locale.getDefault()).format(Date(ms))
        else -> DateFormat.getDateInstance(DateFormat.SHORT).format(Date(ms))
    }
}
