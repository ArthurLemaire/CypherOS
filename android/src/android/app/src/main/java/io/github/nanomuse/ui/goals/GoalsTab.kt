package io.github.nanomuse.ui.goals

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.outlined.AttachMoney
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.CheckBox
import androidx.compose.material.icons.outlined.CheckBoxOutlineBlank
import androidx.compose.material.icons.outlined.FavoriteBorder
import androidx.compose.material.icons.outlined.Group
import androidx.compose.material.icons.outlined.Laptop
import androidx.compose.material.icons.outlined.Palette
import androidx.compose.material.icons.outlined.RadioButtonUnchecked
import androidx.compose.material.icons.outlined.WorkOutline
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.scheduled.ScheduledAgentRunner
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskManager
import com.openminis.app.scheduled.ScheduledTaskStore
import com.openminis.app.ui.scheduled.formatScheduleSummary
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.goals.Goal
import io.github.nanomuse.goals.GoalCategory
import io.github.nanomuse.goals.GoalFlow
import io.github.nanomuse.goals.GoalStatus
import io.github.nanomuse.goals.GoalStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

private val trackingGreen = Color(0xFF34A853)

/**
 * Muse's Goals page: "Tracking" (goals with a checkbox and a two-line status), then
 * "Create a goal" with its seven categories. Between them, nanoMuse's routines — OpenMinis'
 * scheduled tasks, in the same visual language, since a routine is what a goal's check-in is
 * made of.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun GoalsTab(
    header: @Composable () -> Unit,
    onStartGoal: (GoalCategory) -> Unit,
    onOpenSession: (String) -> Unit,
    onEditRoutine: (String?) -> Unit,
    onRoutineRuns: (String) -> Unit,
    onAllRoutines: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val store = remember { GoalStore.get(context) }
    val goals by store.goals.collectAsState()
    val taskStore = remember { ScheduledTaskStore(context) }
    val routines by taskStore.observe().collectAsState(initial = taskStore.all())
    val visibleRoutines = remember(routines) { routines.filterNot { it.hidden }.sortedByDescending { it.createdAt } }
    val listState = rememberLazyListState()
    var sheetCategory by remember { mutableStateOf<GoalCategory?>(null) }

    val activeGoals = remember(goals) { goals.filter { it.status != GoalStatus.DONE } + goals.filter { it.status == GoalStatus.DONE } }
    // Index of the "Create a goal" header, for the tracking "+" to scroll to.
    val createIndex = 1 + 1 + maxOf(activeGoals.size, 1) + 1 + maxOf(visibleRoutines.size, 1) + 1

    LazyColumn(
        state = listState,
        modifier = Modifier.fillMaxSize().background(ChatColors.background),
        contentPadding = PaddingValues(bottom = 24.dp),
    ) {
        item(key = "header") { header() }
        item(key = "title") {
            io.github.nanomuse.ui.home.MusePageTitle(stringResource(R.string.nm_goals_title))
        }

        // ── Tracking ─────────────────────────────────────────────────
        item(key = "tracking") {
            SectionHeader(
                label = stringResource(R.string.nm_goals_tracking),
                dot = trackingGreen,
                labelColor = trackingGreen,
                onAdd = { scope.launch { listState.animateScrollToItem(createIndex) } },
            )
        }
        if (activeGoals.isEmpty()) {
            item(key = "tracking-empty") {
                Text(
                    stringResource(R.string.nm_goals_tracking_empty),
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 12.dp),
                )
            }
        } else {
            items(activeGoals, key = { "goal-" + it.id }) { goal ->
                GoalRow(goal = goal, onOpenSession = onOpenSession)
            }
        }

        // ── Routines ─────────────────────────────────────────────────
        item(key = "routines") {
            Spacer(Modifier.height(6.dp))
            SectionHeader(
                label = stringResource(R.string.nm_goals_routines),
                onAdd = { onEditRoutine(null) },
                trailing = if (visibleRoutines.isNotEmpty()) {
                    { TextButton(onClick = onAllRoutines) { Text(stringResource(R.string.nm_routine_all), fontSize = 13.sp) } }
                } else null,
            )
        }
        if (visibleRoutines.isEmpty()) {
            item(key = "routines-empty") {
                Text(
                    stringResource(R.string.nm_goals_routines_empty),
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 12.dp),
                )
            }
        } else {
            items(visibleRoutines, key = { "routine-" + it.id }) { task ->
                RoutineRow(
                    task = task,
                    onEdit = { onEditRoutine(task.id) },
                    onRuns = { onRoutineRuns(task.id) },
                    onOpenSession = onOpenSession,
                )
            }
        }

        // ── Create a goal ────────────────────────────────────────────
        item(key = "create") {
            HorizontalDivider(
                modifier = Modifier.padding(top = 10.dp, bottom = 14.dp),
                color = io.github.nanomuse.ui.home.MuseTones.hairline,
            )
            Column(Modifier.padding(horizontal = 20.dp)) {
                Text(
                    stringResource(R.string.nm_goals_create),
                    fontSize = 17.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    stringResource(R.string.nm_goals_create_body),
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(6.dp))
            }
        }
        items(GoalCategory.entries, key = { "cat-" + it.key }) { category ->
            CategoryRow(category = category, onClick = { sheetCategory = category })
        }
    }

    sheetCategory?.let { category ->
        val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
        ModalBottomSheet(
            onDismissRequest = { sheetCategory = null },
            sheetState = sheetState,
            containerColor = ChatColors.background,
        ) {
            val label = GoalFlow.categoryLabel(context, category)
            Column(
                Modifier
                    .padding(horizontal = 24.dp)
                    .padding(bottom = 20.dp)
                    .navigationBarsPadding(),
            ) {
                Text(
                    stringResource(R.string.nm_goal_sheet_title, label),
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.height(14.dp))
                Text(
                    stringResource(R.string.nm_goal_sheet_body1),
                    fontSize = 15.sp,
                    lineHeight = 22.sp,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.height(14.dp))
                Text(
                    stringResource(R.string.nm_goal_sheet_body2),
                    fontSize = 15.sp,
                    lineHeight = 22.sp,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                Spacer(Modifier.height(26.dp))
                Button(
                    onClick = {
                        sheetCategory = null
                        onStartGoal(category)
                    },
                    shape = CircleShape,
                    colors = ButtonDefaults.buttonColors(containerColor = io.github.nanomuse.ui.home.MuseTones.action, contentColor = Color.White),
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                ) {
                    Icon(Icons.Outlined.ChatBubbleOutline, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.nm_goal_sheet_go), fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun SectionHeader(
    label: String,
    dot: Color? = null,
    labelColor: Color = MaterialTheme.colorScheme.onSurface,
    onAdd: () -> Unit,
    trailing: (@Composable () -> Unit)? = null,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = 20.dp, end = 8.dp, top = 4.dp),
    ) {
        if (dot != null) {
            Box(Modifier.size(8.dp).background(dot, CircleShape))
            Spacer(Modifier.width(10.dp))
        }
        Text(label, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = labelColor, modifier = Modifier.weight(1f))
        trailing?.invoke()
        IconButton(onClick = onAdd) {
            Icon(Icons.Filled.Add, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun GoalRow(goal: Goal, onOpenSession: (String) -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val done = goal.status == GoalStatus.DONE
    val subtitle = remember(goal) {
        buildString {
            val note = goal.lastNote?.takeIf { it.isNotBlank() }
            if (note != null) append(note)
            else if (goal.steps.isNotEmpty()) append(goal.steps.first().text)
            else append(goal.why)
        }
    }
    val cadence = remember(goal, goal.lastCheckedAt) {
        when (goal.status) {
            GoalStatus.PAUSED -> context.getString(R.string.nm_goal_status_paused)
            GoalStatus.DONE -> context.getString(R.string.nm_goal_status_done)
            GoalStatus.ACTIVE -> if (goal.taskId == null) context.getString(R.string.nm_goal_no_check_yet) else GoalFlow.cadenceLabel(context, goal)
        }
    }
    Row(
        verticalAlignment = Alignment.Top,
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                onClick = { goal.sessionId?.let(onOpenSession) },
                onLongClick = { menu = true },
            )
            .padding(start = 18.dp, end = 4.dp, top = 8.dp, bottom = 10.dp),
    ) {
        IconButton(
            onClick = { GoalFlow.markDone(context, goal, !done) },
            modifier = Modifier.size(28.dp),
        ) {
            Icon(
                if (done) Icons.Outlined.CheckBox else Icons.Outlined.CheckBoxOutlineBlank,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(22.dp),
            )
        }
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f).padding(top = 3.dp)) {
            Text(
                goal.title,
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                color = if (done) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            if (subtitle.isNotBlank()) {
                Spacer(Modifier.height(2.dp))
                Text(
                    subtitle,
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.height(2.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(cadence, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.8f), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                if (goal.progress > 0 && !done) {
                    Spacer(Modifier.width(8.dp))
                    Text("${goal.progress}%", fontSize = 12.sp, color = trackingGreen, fontWeight = FontWeight.Medium)
                }
            }
        }
        Box {
            IconButton(onClick = { menu = true }) {
                Icon(Icons.Filled.MoreVert, contentDescription = stringResource(R.string.nm_more), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                if (goal.sessionId != null) {
                    DropdownMenuItem(text = { Text(stringResource(R.string.nm_goal_open_chat)) }, onClick = { menu = false; onOpenSession(goal.sessionId) })
                }
                if (goal.taskId != null && !done) {
                    DropdownMenuItem(text = { Text(stringResource(R.string.nm_goal_check_now)) }, onClick = {
                        menu = false
                        scope.launch(Dispatchers.IO) { GoalFlow.checkNow(context, goal) }
                    })
                    DropdownMenuItem(
                        text = { Text(stringResource(if (goal.status == GoalStatus.PAUSED) R.string.nm_goal_resume else R.string.nm_goal_pause)) },
                        onClick = { menu = false; GoalFlow.setPaused(context, goal, goal.status != GoalStatus.PAUSED) },
                    )
                }
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.nm_goal_delete), color = MaterialTheme.colorScheme.error) },
                    onClick = { menu = false; confirmDelete = true },
                )
            }
        }
    }
    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text(goal.title) },
            text = { Text(stringResource(R.string.nm_goal_delete_confirm)) },
            confirmButton = {
                TextButton(onClick = { confirmDelete = false; GoalFlow.delete(context, goal) }) {
                    Text(stringResource(R.string.nm_goal_delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(android.R.string.cancel)) } },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun RoutineRow(
    task: ScheduledTask,
    onEdit: () -> Unit,
    onRuns: () -> Unit,
    onOpenSession: (String) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var menu by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val summary = remember(task) { formatScheduleSummary(task) }
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onEdit, onLongClick = { menu = true })
            .padding(start = 20.dp, end = 4.dp, top = 6.dp, bottom = 6.dp),
    ) {
        Icon(
            if (task.enabled) Icons.Outlined.Bolt else Icons.Outlined.RadioButtonUnchecked,
            contentDescription = null,
            tint = if (task.enabled) trackingGreen else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp),
        )
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(
                task.label,
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(1.dp))
            Text(
                if (task.enabled) summary else stringResource(R.string.nm_routine_paused) + " · " + summary,
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Switch(
            checked = task.enabled,
            onCheckedChange = { ScheduledTaskManager(context).setEnabled(task.id, it) },
            modifier = Modifier.padding(start = 8.dp),
        )
        Box {
            IconButton(onClick = { menu = true }) {
                Icon(Icons.Filled.MoreVert, contentDescription = stringResource(R.string.nm_more), tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(text = { Text(stringResource(R.string.nm_routine_edit)) }, onClick = { menu = false; onEdit() })
                DropdownMenuItem(text = { Text(stringResource(R.string.nm_routine_run_now)) }, onClick = {
                    menu = false
                    scope.launch(Dispatchers.Default) { ScheduledAgentRunner.run(context.applicationContext, task, waitForCompletion = false) }
                })
                DropdownMenuItem(text = { Text(stringResource(R.string.nm_routine_runs)) }, onClick = { menu = false; onRuns() })
                task.lastResultSessionId?.let { sid ->
                    DropdownMenuItem(text = { Text(stringResource(R.string.nm_goal_open_chat)) }, onClick = { menu = false; onOpenSession(sid) })
                }
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.nm_routine_delete), color = MaterialTheme.colorScheme.error) },
                    onClick = { menu = false; confirmDelete = true },
                )
            }
        }
    }
    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text(task.label) },
            confirmButton = {
                TextButton(onClick = { confirmDelete = false; ScheduledTaskManager(context).delete(task.id) }) {
                    Text(stringResource(R.string.nm_routine_delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(android.R.string.cancel)) } },
        )
    }
}

private fun GoalCategory.icon(): ImageVector = when (this) {
    GoalCategory.HEALTH -> Icons.Outlined.FavoriteBorder
    GoalCategory.RELATIONSHIPS -> Icons.Outlined.Group
    GoalCategory.FINANCE -> Icons.Outlined.AttachMoney
    GoalCategory.CAREER -> Icons.Outlined.WorkOutline
    GoalCategory.INTERESTS -> Icons.Outlined.Palette
    GoalCategory.PRODUCTIVITY -> Icons.Outlined.Laptop
    GoalCategory.OTHER -> Icons.Outlined.RadioButtonUnchecked
}

@Composable
private fun CategoryRow(category: GoalCategory, onClick: () -> Unit) {
    val context = LocalContext.current
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(start = 20.dp, end = 8.dp)
            .height(50.dp),
    ) {
        Icon(category.icon(), contentDescription = null, tint = MaterialTheme.colorScheme.onSurface, modifier = Modifier.size(22.dp))
        Spacer(Modifier.width(14.dp))
        Text(
            GoalFlow.categoryLabel(context, category),
            fontSize = 15.sp,
            fontWeight = FontWeight.Medium,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onClick) {
            Icon(Icons.Filled.Add, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
