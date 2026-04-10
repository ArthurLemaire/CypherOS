package io.github.nanomuse.ui.ideas

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.Flag
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.goals.GoalCategory
import io.github.nanomuse.ideas.Idea
import io.github.nanomuse.ideas.IdeaKind
import io.github.nanomuse.ideas.Ideas

/**
 * Muse's Ideas page: a big title, then rows of "emoji · bold pitch · grey detail" grouped under
 * section headers (the first group has none). Tapping a row opens a small sheet that says what
 * the idea will create and offers to do it — send to the chat, create a routine, or start a goal.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun IdeasTab(
    header: @Composable () -> Unit,
    onSendToChat: (String) -> Unit,
    onCreateRoutine: (Idea) -> Unit,
    onStartGoal: (GoalCategory, String) -> Unit,
) {
    val context = LocalContext.current
    val sections = remember { Ideas.load(context) }
    var selected by remember { mutableStateOf<Idea?>(null) }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(ChatColors.background),
        contentPadding = PaddingValues(bottom = 24.dp),
    ) {
        item(key = "header") { header() }
        item(key = "title") { io.github.nanomuse.ui.home.MusePageTitle(stringResource(R.string.nm_ideas_title)) }
        sections.forEachIndexed { index, section ->
            if (index > 0) {
                item(key = "section-" + section.id) {
                    Text(
                        section.title,
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 22.dp, bottom = 4.dp),
                    )
                }
            }
            items(section.ideas, key = { it.id }) { idea ->
                IdeaRow(idea = idea, onClick = { selected = idea })
                HorizontalDivider(
                    modifier = Modifier.padding(start = 76.dp, end = 20.dp),
                    color = io.github.nanomuse.ui.home.MuseTones.hairline,
                )
            }
        }
    }

    selected?.let { idea ->
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(
            onDismissRequest = { selected = null },
            sheetState = sheetState,
            containerColor = ChatColors.background,
        ) {
            Column(
                Modifier
                    .padding(horizontal = 24.dp)
                    .padding(bottom = 20.dp)
                    .navigationBarsPadding(),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(idea.emoji, fontSize = 30.sp)
                    Spacer(Modifier.width(12.dp))
                    Text(
                        idea.title,
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        lineHeight = 24.sp,
                        color = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(12.dp))
                Text(idea.body, fontSize = 15.sp, lineHeight = 22.sp, color = MaterialTheme.colorScheme.onSurface)
                Spacer(Modifier.height(14.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val (kindIcon, kindText) = when (idea.kind) {
                        IdeaKind.CHAT -> Icons.Outlined.ChatBubbleOutline to stringResource(R.string.nm_idea_kind_chat)
                        IdeaKind.ROUTINE -> Icons.Outlined.Schedule to stringResource(R.string.nm_idea_kind_routine)
                        IdeaKind.GOAL -> Icons.Outlined.Flag to stringResource(R.string.nm_idea_kind_goal)
                    }
                    Icon(kindIcon, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(
                        if (idea.kind == IdeaKind.ROUTINE && idea.time != null) "$kindText · ${idea.time}" else kindText,
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(22.dp))
                val primaryLabel = when (idea.kind) {
                    IdeaKind.CHAT -> stringResource(R.string.nm_idea_action_chat)
                    IdeaKind.ROUTINE -> stringResource(R.string.nm_idea_action_routine)
                    IdeaKind.GOAL -> stringResource(R.string.nm_idea_action_goal)
                }
                Button(
                    onClick = {
                        selected = null
                        when (idea.kind) {
                            IdeaKind.CHAT -> onSendToChat(idea.prompt)
                            IdeaKind.ROUTINE -> onCreateRoutine(idea)
                            IdeaKind.GOAL -> onStartGoal(GoalCategory.fromKey(idea.category), idea.prompt)
                        }
                    },
                    shape = CircleShape,
                    colors = ButtonDefaults.buttonColors(containerColor = io.github.nanomuse.ui.home.MuseTones.action, contentColor = Color.White),
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                ) {
                    Icon(Icons.Outlined.ChatBubbleOutline, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(primaryLabel, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                }
                if (idea.kind != IdeaKind.CHAT) {
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(
                        onClick = { selected = null; onSendToChat(idea.prompt) },
                        shape = CircleShape,
                        modifier = Modifier.fillMaxWidth().height(46.dp),
                    ) {
                        Text(stringResource(R.string.nm_idea_action_chat), fontSize = 15.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun IdeaRow(idea: Idea, onClick: () -> Unit) {
    Row(
        verticalAlignment = Alignment.Top,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 14.dp),
    ) {
        Box(Modifier.width(40.dp), contentAlignment = Alignment.TopCenter) {
            Text(idea.emoji, fontSize = 28.sp, lineHeight = 34.sp)
        }
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(
                idea.title,
                fontSize = 16.sp,
                lineHeight = 22.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                idea.body,
                fontSize = 13.5.sp,
                lineHeight = 19.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}
