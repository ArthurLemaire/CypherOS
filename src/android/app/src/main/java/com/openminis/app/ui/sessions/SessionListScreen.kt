package com.openminis.app.ui.sessions

import android.content.Context
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PushPin
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Share
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.Book
import androidx.compose.material.icons.outlined.Brush
import androidx.compose.material.icons.outlined.Calculate
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.outlined.ChecklistRtl
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Favorite
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material.icons.outlined.GridView
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material.icons.outlined.MoreHoriz
import androidx.compose.material.icons.outlined.Palette
import androidx.compose.material.icons.outlined.Payments
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Translate
import android.content.Intent
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import com.openminis.app.ui.components.MinisAlertDialog
import com.openminis.app.ui.components.MinisMenu
import com.openminis.app.ui.components.MinisMenuDivider
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.FloatingActionButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.withFrameNanos
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.foundation.Canvas
import androidx.compose.ui.geometry.Size
import com.openminis.app.service.SessionActivityTracker
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.ui.theme.ChatColors
import com.openminis.app.ui.theme.minisFabColor
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.data.repository.ProviderRepository
import kotlin.math.roundToInt
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import java.util.Calendar
import java.util.Date
import java.util.concurrent.TimeUnit
import com.openminis.app.ui.components.MinisTextButton

// FAB color — use shared theme values

private data class CategoryStyle(val icon: ImageVector, val color: Color)

// 16 categories matching iOS (ContentView.swift:1897-1916)
private fun categoryStyle(category: String?): CategoryStyle {
    return when (category?.lowercase()) {
        "code"         -> CategoryStyle(Icons.Outlined.Code, Color(0xFFF09A37))
        "writing"      -> CategoryStyle(Icons.Outlined.Description, Color(0xFF3478F6))
        "research"     -> CategoryStyle(Icons.Outlined.Language, Color(0xFF30B0C7))
        "analysis"     -> CategoryStyle(Icons.Outlined.BarChart, Color(0xFF5856D6))
        "creative"     -> CategoryStyle(Icons.Outlined.Brush, Color(0xFFFF2D55))
        "chat"         -> CategoryStyle(Icons.Outlined.Forum, Color(0xFF34C759))
        "math"         -> CategoryStyle(Icons.Outlined.Calculate, Color(0xFF9B59B6))
        "translation"  -> CategoryStyle(Icons.Outlined.Translate, Color(0xFF00BCD4))
        "health"       -> CategoryStyle(Icons.Outlined.Favorite, Color(0xFFFF3B30))
        "finance"      -> CategoryStyle(Icons.Outlined.Payments, Color(0xFF00C7BE))
        "travel"       -> CategoryStyle(Icons.Outlined.Map, Color(0xFFF09A37))
        "education"    -> CategoryStyle(Icons.Outlined.Book, Color(0xFF3478F6))
        "design"       -> CategoryStyle(Icons.Outlined.Palette, Color(0xFFFF2D55))
        "productivity" -> CategoryStyle(Icons.Outlined.CalendarMonth, Color(0xFFFFCC00))
        "support"      -> CategoryStyle(Icons.Outlined.Settings, Color(0xFF8B6914))
        "other"        -> CategoryStyle(Icons.Outlined.GridView, Color(0xFF8E8E93))
        else           -> CategoryStyle(Icons.Outlined.Forum, Color(0xFF8E8E93))
    }
}

// Date period for section grouping (matching iOS)
private enum class DatePeriod(val label: String) {
    PINNED("Pinned"),     // labels are i18n'd at render time via sectionLabelFor
    TODAY("Today"),
    YESTERDAY("Yesterday"),
    THIS_WEEK("This Week"),
    THIS_MONTH("This Month"),
    EARLIER("Earlier"),
}

/**
 * Map a session's updatedAt timestamp to its display bucket. Mirrors iOS
 * `ContentView.groupedSessions`:
 *   - Today / Yesterday: calendar-day match
 *   - This Week: within the last 7 days (rolling window, not current week)
 *   - This Month: within the last 30 days (rolling window, NOT current calendar month)
 *   - Earlier: everything else
 */
private fun datePeriod(timestamp: Long): DatePeriod {
    val now = Calendar.getInstance()
    val cal = Calendar.getInstance().apply { time = Date(timestamp) }

    if (cal.get(Calendar.YEAR) == now.get(Calendar.YEAR) &&
        cal.get(Calendar.DAY_OF_YEAR) == now.get(Calendar.DAY_OF_YEAR)
    ) return DatePeriod.TODAY

    val yesterday = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -1) }
    if (cal.get(Calendar.YEAR) == yesterday.get(Calendar.YEAR) &&
        cal.get(Calendar.DAY_OF_YEAR) == yesterday.get(Calendar.DAY_OF_YEAR)
    ) return DatePeriod.YESTERDAY

    val diffDays = TimeUnit.MILLISECONDS.toDays(now.timeInMillis - timestamp)
    if (diffDays < 7) return DatePeriod.THIS_WEEK

    // iOS uses `monthAgo = now - 1 month` (rolling window). A calendar-month
    // match would push e.g. a March 30 session into "Earlier" on April 2 —
    // iOS still shows it in "This Month" until May 2.
    val monthAgo = Calendar.getInstance().apply { add(Calendar.MONTH, -1) }.timeInMillis
    if (timestamp > monthAgo) return DatePeriod.THIS_MONTH

    return DatePeriod.EARLIER
}

private fun groupSessionsByDate(sessions: List<ChatSessionEntity>): List<Pair<DatePeriod, List<ChatSessionEntity>>> {
    val pinned = sessions.filter { it.pinnedAt != null }.sortedByDescending { it.pinnedAt }
    val unpinned = sessions.filter { it.pinnedAt == null }
    val grouped = unpinned.groupBy { datePeriod(it.updatedAt) }
    val result = mutableListOf<Pair<DatePeriod, List<ChatSessionEntity>>>()
    if (pinned.isNotEmpty()) {
        result.add(DatePeriod.PINNED to pinned)
    }
    for (period in DatePeriod.entries) {
        if (period == DatePeriod.PINNED) continue
        grouped[period]?.let { result.add(period to it) }
    }
    return result
}

private fun relativeDate(context: Context, timestamp: Long): String {
    val now = System.currentTimeMillis()
    val diff = now - timestamp
    val seconds = TimeUnit.MILLISECONDS.toSeconds(diff)
    val minutes = TimeUnit.MILLISECONDS.toMinutes(diff)
    val hours = TimeUnit.MILLISECONDS.toHours(diff)

    if (seconds < 60) return context.getString(R.string.time_just_now)
    if (minutes < 60) return context.getString(R.string.time_minutes_ago, minutes.toInt())
    if (hours < 24) return context.getString(R.string.time_hours_ago, hours.toInt())

    val dateCal = Calendar.getInstance().apply { time = Date(timestamp) }
    val yesterdayCal = Calendar.getInstance().apply { add(Calendar.DAY_OF_YEAR, -1) }
    if (dateCal.get(Calendar.YEAR) == yesterdayCal.get(Calendar.YEAR) &&
        dateCal.get(Calendar.DAY_OF_YEAR) == yesterdayCal.get(Calendar.DAY_OF_YEAR)
    ) {
        return context.getString(R.string.time_yesterday)
    }

    val days = TimeUnit.MILLISECONDS.toDays(diff)
    if (days < 7) {
        // T172: device-locale weekday names via java.text.DateFormatSymbols.
        val dayNames = java.text.DateFormatSymbols(java.util.Locale.getDefault()).weekdays
        return dayNames[dateCal.get(Calendar.DAY_OF_WEEK)]
    }

    val month = dateCal.get(Calendar.MONTH) + 1
    val day = dateCal.get(Calendar.DAY_OF_MONTH)
    return "$month/$day"
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun SessionListScreen(
    chatRepository: ChatRepository,
    providerRepository: ProviderRepository,
    onSessionClick: (String) -> Unit,
    onNewChat: (String) -> Unit,
    onSettingsClick: () -> Unit,
    onAddProviderClick: () -> Unit = {},
    onSelectModelsClick: () -> Unit = {},
    onTerminalClick: () -> Unit = {},
    onRootfsClick: () -> Unit = {},
    // [T-android-scheduled-tasks-design] Entry to the scheduled-tasks list.
    onScheduledTasksClick: () -> Unit = {},
) {
    val context = LocalContext.current
    // T46: hoist VM ownership to the NavBackStackEntry's ViewModelStore so
    // [searchQuery] / [isSearchActive] survive navigation. The previous
    // `remember {}` scoping tied the VM to the composable's lifetime — pushing
    // to chat detail destroyed it, then pop-back rebuilt a fresh VM with
    // empty search state. Mirrors iOS where ContentView's `@State searchText`
    // survives a NavigationLink push because the parent view never unmounts.
    val viewModel: SessionListViewModel = androidx.lifecycle.viewmodel.compose.viewModel(
        factory = SessionListViewModel.factory(chatRepository, providerRepository, context),
    )
    val sessions by viewModel.displayedSessions.collectAsState()
    val isInitialLoadComplete by viewModel.isInitialLoadComplete.collectAsState()
    val isSearchActive by viewModel.isSearchActive.collectAsState()
    val searchQuery by viewModel.searchQuery.collectAsState()
    val isSearching by viewModel.isSearching.collectAsState()
    val searchSnippets by viewModel.searchSnippets.collectAsState()
    val isSelecting by viewModel.isSelecting.collectAsState()
    val selectedIds by viewModel.selectedIds.collectAsState()
    val regeneratingIds by viewModel.regeneratingIds.collectAsState()
    val providerConfig by providerRepository.config.collectAsState()
    val hasProviders = providerConfig.instances.isNotEmpty()
    val hasGroups = providerConfig.modelGroups.isNotEmpty()
    // [T-android-startup-config-stall] Provider config now loads off-thread, so
    // for a brief startup window `providerConfig` is the empty placeholder.
    // Gate the onboarding/list render on this too (alongside the sessions
    // initial-load flag) so an existing user with providers but zero sessions
    // doesn't flash the "add a provider" onboarding before the real config emits.
    val configLoaded by providerRepository.configLoaded.collectAsState()
    val scope = rememberCoroutineScope()
    val isDark = isSystemInDarkTheme()

    // [T-android-search-focus-sticky] When the user opens search but types
    // nothing (or only whitespace) and then navigates into a chat, the
    // VM-backed search state survives the navigation, so on return the search
    // bar is still open and focused — the user has to manually tap the X to
    // close it. Collapse search BEFORE navigating when the query is blank;
    // keep it (query + results) when there's a real query so returning lands
    // back on the same search. Collapsing flips isSearchActive false, which
    // removes the search TextField from composition and releases its focus.
    fun exitSearchIfQueryBlank() {
        if (viewModel.isSearchActive.value && viewModel.searchQuery.value.isBlank()) {
            viewModel.searchQuery.value = ""
            viewModel.isSearchActive.value = false
        }
    }
    // Wrapped navigation callbacks: run the search-collapse check first, then
    // navigate. Used everywhere a session tap / new-chat creation navigates.
    // [T-session-paused-badge-active-false-positive] Do NOT clear the PAUSED
    // badge on open: merely opening an interrupted session does not resolve it.
    // The badge is now driven by ChatViewModel's canResume flow — it clears only
    // when the interruption is actually resolved (Resume tapped / new message
    // sent / loop completed), and the ChatViewModel re-asserts it on load if the
    // session is still interrupted. Clearing here just caused a flicker.
    val onSessionClickGuarded: (String) -> Unit = { id ->
        exitSearchIfQueryBlank()
        onSessionClick(id)
    }
    val onNewChatGuarded: (String) -> Unit = { id -> exitSearchIfQueryBlank(); onNewChat(id) }

    var showDeleteDialog by remember { mutableStateOf(false) }
    var deleteTargetId by remember { mutableStateOf<String?>(null) }
    var showBulkDeleteDialog by remember { mutableStateOf(false) }
    var showOverflowMenu by remember { mutableStateOf(false) }
    var editSession by remember { mutableStateOf<ChatSessionEntity?>(null) }
    var showBrowserSheet by remember { mutableStateOf(false) }
    var showBrowserSettings by remember { mutableStateOf(false) }
    val browserTabPool = remember { com.openminis.app.browser.BrowserTabPool(context) }

    val groupedSessions = remember(sessions) { groupSessionsByDate(sessions) }

    // [T-android-newchat-list-autoscroll] Hoisted scroll state so the VM's
    // new-session signal can drive it. The list is ORDER BY updated_at DESC,
    // so a freshly-used session lands at index 0 (top of the TODAY bucket).
    // But the LazyColumn retains its scroll offset across navigation (open
    // chat → back), so if the user had scrolled down, the new session sits
    // above the viewport and they have to scroll up to find it (Jackson 41429).
    //
    // The new-session DETECTION lives in the VM (retained across navigation)
    // because the list composable is disposed during the chat-detail push — a
    // composable-scoped tracker would reset its baseline on pop-back and miss
    // the new session that appeared while we were in the chat. Here we just
    // collect the one-shot event and scroll, skipping it during search (which
    // reorders the list) and selection mode (so it can't fight #765 multi-select).
    val listState = rememberLazyListState()
    LaunchedEffect(Unit) {
        viewModel.newTopSessionEvent.collect {
            if (!viewModel.isSearchActive.value && !viewModel.isSelecting.value) {
                listState.animateScrollToItem(0)
            }
        }
    }

    // [T-android-scheduled-tasks-full] Live count of scheduled tasks for the
    // toolbar clock-icon badge. Observes the SharedPreferences-backed store so
    // the badge updates when tasks are added / removed without a manual refresh.
    // [T-android-scheduled-badge-enabled-only] Count only enabled tasks so the
    // badge reflects what's actually active — disabled tasks don't contribute,
    // and with none enabled the count is 0 (badge hidden by the >0 gate below).
    val scheduledTaskCount by remember {
        com.openminis.app.scheduled.ScheduledTaskStore(context).observe()
            .map { list -> list.count { it.enabled } }
    }.collectAsState(initial = 0)

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    if (isSelecting) {
                        Text(
                            if (selectedIds.isEmpty())
                                stringResource(R.string.sessionlist_select_title)
                            else
                                stringResource(R.string.sessionlist_n_selected, selectedIds.size),
                            fontWeight = FontWeight.Bold,
                            fontSize = 20.sp,
                        )
                    } else {
                        Text(
                            stringResource(R.string.app_name),
                            fontWeight = FontWeight.Bold,
                            fontSize = 20.sp,
                        )
                    }
                },
                navigationIcon = {
                    if (isSelecting) {
                        MinisTextButton(onClick = { viewModel.clearSelection() }) {
                            Text(stringResource(R.string.cancel))
                        }
                    } else {
                        IconButton(onClick = onSettingsClick) {
                            Icon(Icons.Default.Settings, contentDescription = stringResource(R.string.sessionlist_settings))
                        }
                    }
                },
                actions = {
                    if (isSelecting) {
                        MinisTextButton(onClick = { viewModel.selectAll() }) {
                            Text(
                                stringResource(
                                    if (selectedIds.size == sessions.size) R.string.sessionlist_deselect_all
                                    else R.string.sessionlist_select_all
                                )
                            )
                        }
                    } else {
                        // [T-android-scheduled-tasks-design] Scheduled-tasks entry,
                        // sits to the left of the Shell button on the home toolbar.
                        // [T-android-scheduled-tasks-full] Badge shows the count of
                        // scheduled tasks so the user can see at a glance how many
                        // are configured without opening the list.
                        IconButton(onClick = onScheduledTasksClick) {
                            if (scheduledTaskCount > 0) {
                                BadgedBox(badge = { Badge { Text("$scheduledTaskCount") } }) {
                                    Icon(
                                        Icons.Outlined.Schedule,
                                        contentDescription = stringResource(R.string.sessionlist_scheduled_tasks),
                                    )
                                }
                            } else {
                                Icon(
                                    Icons.Outlined.Schedule,
                                    contentDescription = stringResource(R.string.sessionlist_scheduled_tasks),
                                )
                            }
                        }
                        // Shell menu (matching iOS trailing shell button: Terminal, Rootfs, Browser)
                        Box {
                            IconButton(onClick = { showOverflowMenu = true }) {
                                Icon(Icons.Outlined.Terminal, contentDescription = stringResource(R.string.sessionlist_shell))
                            }
                            MinisMenu(
                                expanded = showOverflowMenu,
                                onDismissRequest = { showOverflowMenu = false },
                                offset = DpOffset(0.dp, 0.dp),
                            ) {
                                if (sessions.isNotEmpty()) {
                                    DropdownMenuItem(
                                        text = { Text(stringResource(R.string.sessionlist_select_action)) },
                                        onClick = {
                                            showOverflowMenu = false
                                            viewModel.isSelecting.value = true
                                        },
                                        leadingIcon = {
                                            Icon(Icons.Outlined.ChecklistRtl, contentDescription = null)
                                        },
                                    )
                                    MinisMenuDivider()
                                }
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.sessionlist_shell_terminal)) },
                                    onClick = {
                                        showOverflowMenu = false
                                        onTerminalClick()
                                    },
                                    leadingIcon = {
                                        Icon(Icons.Outlined.Terminal, contentDescription = null)
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.sessionlist_rootfs_management)) },
                                    onClick = {
                                        showOverflowMenu = false
                                        onRootfsClick()
                                    },
                                    leadingIcon = {
                                        Icon(Icons.Outlined.Settings, contentDescription = null)
                                    },
                                )
                                MinisMenuDivider()
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.sessionlist_open_browser)) },
                                    onClick = {
                                        showOverflowMenu = false
                                        browserTabPool.ensureTabForUI()
                                        showBrowserSheet = true
                                    },
                                    leadingIcon = {
                                        Icon(Icons.Outlined.Language, contentDescription = null)
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.sessionlist_browser_settings)) },
                                    onClick = {
                                        showOverflowMenu = false
                                        showBrowserSettings = true
                                    },
                                    leadingIcon = {
                                        Icon(Icons.Outlined.Settings, contentDescription = null)
                                    },
                                )
                            }
                        }
                    }
                },
            )
        },
        // No default FAB — we draw dual FABs manually at bottom
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // Main content — render an empty frame until the first DB
            // emission lands. Otherwise `sessions.isEmpty()` reads true for
            // the brief window before Room delivers real data and the
            // onboarding flashes on top of existing user history. Mirrors
            // iOS `didInitialLoad` on ContentView. The transition is usually
            // sub-200ms, so no spinner.
            if (isInitialLoadComplete) Column(modifier = Modifier.fillMaxSize()) {
                if (sessions.isEmpty()) {
                    if (isSearchActive && searchQuery.isNotBlank()) {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                text = stringResource(R.string.search_no_results, searchQuery),
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    } else if (configLoaded) {
                        // Show the 3-step onboarding whenever there are no sessions —
                        // Step 3 (Start a Conversation) is the call-to-action after the
                        // user finishes Steps 1 and 2, so we must keep the landing
                        // visible even when hasProviders && hasGroups. Mirrors iOS
                        // ContentView.emptyState.
                        // [T-android-startup-config-stall] Gated on configLoaded so
                        // hasProviders/hasGroups reflect the real persisted config —
                        // otherwise a returning user with providers but no sessions
                        // would briefly see the "add a provider" step before the
                        // async config load emits. The list branch (sessions present)
                        // is intentionally NOT gated, so users with history still see
                        // it immediately without waiting on the config decode.
                        OnboardingLanding(
                            hasProviders = hasProviders,
                            hasGroups = hasGroups,
                            onAddProvider = onAddProviderClick,
                            onSelectModels = onSelectModelsClick,
                            onStartConversation = {
                                scope.launch {
                                    val sessionId = viewModel.createNewSession()
                                    if (sessionId != null) onNewChatGuarded(sessionId)
                                }
                            },
                        )
                    }
                } else {
                    LazyColumn(
                        // [T-android-newchat-list-autoscroll] Hoisted state so
                        // the new-session autoscroll effect above can drive it.
                        state = listState,
                        modifier = Modifier.fillMaxSize(),
                        // Leave space for bottom FAB row
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 96.dp),
                    ) {
                        // T25: search-active path used to flatten the list and skip
                        // section headers entirely. Now reuses the same grouped
                        // rendering — `displayedSessions` is already filtered by
                        // the VM when active && query.isNotBlank, so the same
                        // groupSessionsByDate(sessions) computation produces
                        // header buckets over the filtered set.
                        groupedSessions.forEach { (period, periodSessions) ->
                            item(key = "header_${period.name}") {
                                SectionHeader(title = stringResource(when (period) {
                                    DatePeriod.PINNED -> R.string.sessionlist_section_pinned
                                    DatePeriod.TODAY -> R.string.sessionlist_section_today
                                    DatePeriod.YESTERDAY -> R.string.sessionlist_section_yesterday
                                    DatePeriod.THIS_WEEK -> R.string.sessionlist_section_this_week
                                    DatePeriod.THIS_MONTH -> R.string.sessionlist_section_this_month
                                    DatePeriod.EARLIER -> R.string.sessionlist_section_earlier
                                }))
                            }
                            items(periodSessions, key = { it.id }) { session ->
                                val activeQuery = if (isSearchActive && searchQuery.isNotBlank()) searchQuery else ""
                                SessionItemContent(
                                    session = session,
                                    isSelecting = isSelecting,
                                    selectedIds = selectedIds,
                                    onSessionClick = onSessionClickGuarded,
                                    onToggleSelect = { viewModel.toggleSelect(it) },
                                    onEnterSelect = { viewModel.enterSelection(it) },
                                    onPinToggle = { viewModel.togglePin(it) },
                                    onEditRequest = { editSession = it },
                                    onExportRequest = { session, fmt -> exportSession(context, session, chatRepository, scope, fmt) },
                                    onRegenerateTitle = { viewModel.regenerateTitle(it) },
                                    onDuplicate = { viewModel.duplicateSession(it) },
                                    onDeleteRequest = { id ->
                                        deleteTargetId = id
                                        showDeleteDialog = true
                                    },
                                    isRegenerating = session.id in regeneratingIds,
                                    searchQuery = activeQuery,
                                    searchSnippet = searchSnippets[session.id],
                                )
                            }
                        }
                    }
                }
            }

            // Bottom area: dual FABs or selection toolbar (matching iOS fabRow / selectionToolbar)
            if (isSelecting) {
                // Selection toolbar at bottom (matching iOS: Export + Delete)
                SelectionToolbar(
                    selectedCount = selectedIds.size,
                    onExport = { /* TODO: export */ },
                    onDelete = { showBulkDeleteDialog = true },
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            } else if (hasProviders && (sessions.isNotEmpty() || isSearchActive)) {
                // Dual FAB row (matching iOS: New Chat left + Search right, or vice versa).
                // Hidden while the onboarding landing is showing — Step 3 provides the CTA.
                // T46: stay visible while search is active even when the result
                // set is empty, so the user can edit / clear the query without
                // having to rediscover the search FAB after a 0-hit query.
                DualFabRow(
                    isDark = isDark,
                    isSearchActive = isSearchActive,
                    searchQuery = searchQuery,
                    isSearching = isSearching,
                    hasSessions = sessions.isNotEmpty() || isSearchActive,
                    onNewChat = {
                        scope.launch {
                            val sessionId = viewModel.createNewSession()
                            if (sessionId != null) onNewChatGuarded(sessionId)
                        }
                    },
                    onNewChatWithGroup = { groupId ->
                        scope.launch {
                            val sessionId = viewModel.createNewSession(groupId = groupId)
                            if (sessionId != null) onNewChatGuarded(sessionId)
                        }
                    },
                    modelGroups = providerConfig.modelGroups,
                    onSearchToggle = {
                        if (isSearchActive) {
                            viewModel.searchQuery.value = ""
                            viewModel.isSearchActive.value = false
                        } else {
                            viewModel.isSearchActive.value = true
                        }
                    },
                    onSearchQueryChange = { viewModel.searchQuery.value = it },
                    onSearchDismiss = {
                        viewModel.searchQuery.value = ""
                        viewModel.isSearchActive.value = false
                    },
                    modifier = Modifier.align(Alignment.BottomCenter),
                )
            }
        }
    }

    // Single delete confirmation
    if (showDeleteDialog && deleteTargetId != null) {
        MinisAlertDialog(
            onDismissRequest = {
                showDeleteDialog = false
                deleteTargetId = null
            },
            title = stringResource(R.string.sessionlist_delete_one_title),
            text = stringResource(R.string.sessionlist_delete_message),
            confirmText = stringResource(R.string.delete),
            isDestructive = true,
            onConfirm = {
                deleteTargetId?.let { viewModel.deleteSession(it) }
                showDeleteDialog = false
                deleteTargetId = null
            },
        )
    }

    // Bulk delete confirmation
    if (showBulkDeleteDialog) {
        MinisAlertDialog(
            onDismissRequest = { showBulkDeleteDialog = false },
            title = stringResource(R.string.sessionlist_delete_n_title, selectedIds.size),
            confirmText = stringResource(R.string.delete),
            isDestructive = true,
            onConfirm = {
                viewModel.deleteSelected()
                showBulkDeleteDialog = false
            },
        )
    }

    // Edit Title & Category sheet (matching iOS SessionEditSheet)
    editSession?.let { session ->
        // Track the live DB-backed row for this session so a Regenerate-Title
        // run (which writes title/category to the DB) flows back into the sheet
        // without the user reopening it. displayedSessions observes the DB.
        val liveSession = sessions.firstOrNull { it.id == session.id } ?: session
        SessionEditSheet(
            session = session,
            liveSession = liveSession,
            isRegenerating = session.id in regeneratingIds,
            onRegenerate = { viewModel.regenerateTitle(session.id) },
            onDismiss = { editSession = null },
            onSave = { title, category ->
                viewModel.updateTitleAndCategory(session.id, title, category)
                editSession = null
            },
        )
    }

    // Browser sheet
    if (showBrowserSheet) {
        com.openminis.app.ui.browser.BrowserSheet(
            tabPool = browserTabPool,
            onDismiss = { showBrowserSheet = false },
        )
    }

    // Browser Settings sheet
    if (showBrowserSettings) {
        com.openminis.app.ui.browser.BrowserSettingsSheet(
            tabPool = browserTabPool,
            onDismiss = { showBrowserSettings = false },
        )
    }
}

// ─── Dual FAB Row (matching iOS fabRow) ─────────────────────────────────────

/** Persisted preference key for FAB order swap. */
private const val PREF_FAB_SWAPPED = "fab_swapped"

@Composable
private fun DualFabRow(
    isDark: Boolean,
    isSearchActive: Boolean,
    searchQuery: String,
    isSearching: Boolean,
    hasSessions: Boolean,
    onNewChat: () -> Unit,
    onNewChatWithGroup: (String) -> Unit,
    modelGroups: List<com.openminis.app.data.model.ModelGroup>,
    onSearchToggle: () -> Unit,
    onSearchQueryChange: (String) -> Unit,
    onSearchDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("ui_prefs", Context.MODE_PRIVATE) }
    var isSwapped by remember { mutableStateOf(prefs.getBoolean(PREF_FAB_SWAPPED, false)) }

    // T120: focus + IME control for the inline search field. The field appears
    // inside an AnimatedVisibility, so we drive focus from the parent and
    // request it when isSearchActive flips true. Showing the keyboard
    // explicitly via the SoftwareKeyboardController covers devices where
    // requestFocus() alone doesn't trigger the IME (e.g. some Pixel + Gboard
    // combinations under edge-to-edge layouts).
    val searchFocusRequester = remember { FocusRequester() }
    val keyboardController = LocalSoftwareKeyboardController.current
    LaunchedEffect(isSearchActive) {
        if (isSearchActive) {
            // AnimatedVisibility runs a 200ms enter animation; the TextField
            // isn't attached to the composition tree until the first frame of
            // that animation lands. Yield once so requestFocus() targets a
            // composed node rather than throwing IllegalStateException.
            kotlinx.coroutines.delay(50)
            runCatching { searchFocusRequester.requestFocus() }
            keyboardController?.show()
        }
    }

    // Drag offset for the currently-dragged FAB
    var chatDragX by remember { mutableFloatStateOf(0f) }
    var searchDragX by remember { mutableFloatStateOf(0f) }

    // Threshold to trigger swap (half screen width roughly)
    val density = LocalDensity.current
    val swapThreshold = with(density) { 100.dp.toPx() }

    var showGroupMenu by remember { mutableStateOf(false) }
    val topGroups = remember(modelGroups) { modelGroups.take(10) }

    val chatFab: @Composable () -> Unit = {
        Box(
            modifier = Modifier
                .offset { IntOffset(chatDragX.roundToInt(), 0) }
                .pointerInput(Unit) {
                    detectHorizontalDragGestures(
                        onDragEnd = {
                            if (kotlin.math.abs(chatDragX) > swapThreshold) {
                                isSwapped = !isSwapped
                                prefs.edit().putBoolean(PREF_FAB_SWAPPED, isSwapped).apply()
                            }
                            chatDragX = 0f
                        },
                        onDragCancel = { chatDragX = 0f },
                        onHorizontalDrag = { _, dragAmount -> chatDragX += dragAmount },
                    )
                },
        ) {
            FloatingActionButton(
                onClick = onNewChat,
                shape = CircleShape,
                containerColor = minisFabColor(),
                modifier = Modifier
                    .size(56.dp)
                    .combinedClickable(
                        onClick = onNewChat,
                        onLongClick = {
                            if (topGroups.isNotEmpty()) showGroupMenu = true
                        },
                    )
                    .shadow(8.dp, CircleShape, ambientColor = Color.Black.copy(alpha = 0.2f)),
                elevation = FloatingActionButtonDefaults.elevation(defaultElevation = 6.dp),
            ) {
                Icon(Icons.Outlined.Forum, contentDescription = "New Chat", tint = Color.White, modifier = Modifier.size(24.dp))
            }
            DropdownMenu(
                expanded = showGroupMenu,
                onDismissRequest = { showGroupMenu = false },
            ) {
                topGroups.forEach { group ->
                    DropdownMenuItem(
                        text = { Text(group.name) },
                        leadingIcon = { Icon(Icons.Outlined.Forum, contentDescription = null) },
                        onClick = {
                            showGroupMenu = false
                            onNewChatWithGroup(group.id)
                        },
                    )
                }
            }
        }
    }

    val searchFab: @Composable () -> Unit = {
        if (hasSessions) {
            AnimatedVisibility(
                visible = !isSearchActive,
                enter = fadeIn(tween(200)) + scaleIn(tween(200), initialScale = 0.85f),
                exit = fadeOut(tween(150)) + scaleOut(tween(150), targetScale = 0.85f),
            ) {
                FloatingActionButton(
                    onClick = onSearchToggle,
                    shape = CircleShape,
                    // iOS: UIColor.secondarySystemBackground = #F2F2F7 (light) / #1C1C1E (dark).
                    // ChatColors.secondaryBg already matches these values across themes.
                    containerColor = ChatColors.secondaryBg,
                    modifier = Modifier
                        .size(56.dp)
                        .offset { IntOffset(searchDragX.roundToInt(), 0) }
                        .pointerInput(Unit) {
                            detectHorizontalDragGestures(
                                onDragEnd = {
                                    if (kotlin.math.abs(searchDragX) > swapThreshold) {
                                        isSwapped = !isSwapped
                                        prefs.edit().putBoolean(PREF_FAB_SWAPPED, isSwapped).apply()
                                    }
                                    searchDragX = 0f
                                },
                                onDragCancel = { searchDragX = 0f },
                                onHorizontalDrag = { _, dragAmount -> searchDragX += dragAmount },
                            )
                        }
                        .shadow(6.dp, CircleShape, ambientColor = Color.Black.copy(alpha = 0.15f)),
                    elevation = FloatingActionButtonDefaults.elevation(defaultElevation = 4.dp),
                ) {
                    Icon(Icons.Outlined.Search, contentDescription = stringResource(R.string.sessionlist_search_action), tint = MaterialTheme.colorScheme.onSurface, modifier = Modifier.size(24.dp))
                }
            }
        }
    }

    Row(
        modifier = modifier
            .fillMaxWidth()
            // T24: lift the FAB+search row above the IME so the text field
            // remains visible while typing. Compose-managed inset — handles
            // the IME open/close animation in lockstep.
            .imePadding()
            .padding(horizontal = 16.dp, vertical = 20.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Render in swapped or normal order
        if (isSwapped) { searchFab(); } else { chatFab() }

        // Middle: Inline search bar (when active)
        AnimatedVisibility(
            visible = isSearchActive,
            enter = fadeIn(tween(200)) + scaleIn(tween(200), initialScale = 0.85f),
            exit = fadeOut(tween(150)) + scaleOut(tween(150), targetScale = 0.85f),
        ) {
            OutlinedTextField(
                value = searchQuery,
                onValueChange = onSearchQueryChange,
                singleLine = true,
                placeholder = { Text(stringResource(R.string.search_chats_placeholder)) },
                leadingIcon = {
                    Icon(Icons.Outlined.Search, contentDescription = null, modifier = Modifier.size(18.dp))
                },
                trailingIcon = {
                    // T46: while debounce is in flight, swap the close icon
                    // for an indeterminate progress ring so the user sees the
                    // search is working — avoids the stale-results-then-snap
                    // transition on slow stores. Snaps back to the close
                    // button as soon as results land.
                    if (isSearching) {
                        androidx.compose.material3.CircularProgressIndicator(
                            modifier = Modifier
                                .padding(end = 12.dp)
                                .size(18.dp),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        IconButton(onClick = onSearchDismiss) {
                            Icon(Icons.Default.Close, contentDescription = stringResource(R.string.sessionlist_dismiss), modifier = Modifier.size(18.dp))
                        }
                    }
                },
                // T46: full-capsule shape mirrors iOS searchable-field style
                // (see ContentView.fabRow — `.clipShape(Capsule())` over a
                // 56pt-tall HStack). RoundedCornerShape(50) is Compose's
                // canonical "pill" radius — guaranteed circular ends at any
                // height. Pair with a fixed 48dp height so the field aligns
                // with the flanking 56dp FABs without overpowering them.
                shape = androidx.compose.foundation.shape.RoundedCornerShape(percent = 50),
                // T10: Material3's default OutlinedTextField containerColor is
                // Color.Transparent, which lets the LazyColumn's session rows
                // bleed through and overlap the typed query text. Set both
                // focused and unfocused container colors to surfaceContainerHigh
                // (matches the grouped-section card background already used
                // throughout settings) so the field reads as a discrete
                // surface above the list. Also drop both border colors —
                // capsule shape with no outline reads more like iOS's filled
                // search bar than the M3 outlined field default.
                colors = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
                    focusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    unfocusedContainerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
                    focusedBorderColor = MaterialTheme.colorScheme.outline.copy(alpha = 0.8f),
                    unfocusedBorderColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                ),
                modifier = Modifier
                    .weight(1f)
                    .padding(horizontal = 10.dp)
                    .heightIn(min = 48.dp)
                    .focusRequester(searchFocusRequester),
            )
        }

        if (isSwapped) { chatFab() } else { searchFab() }
    }
}

// ─── Selection Toolbar (matching iOS selectionToolbar) ──────────────────────

@Composable
private fun SelectionToolbar(
    selectedCount: Int,
    onExport: () -> Unit,
    onDelete: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.95f))
            .padding(vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceEvenly,
    ) {
        // Export button (matching iOS)
        MinisTextButton(
            onClick = onExport,
            enabled = selectedCount > 0,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(
                    Icons.Default.Share,
                    contentDescription = stringResource(R.string.sessionlist_export),
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.height(4.dp))
                Text(stringResource(R.string.sessionlist_export), fontSize = 11.sp)
            }
        }

        // Delete button (matching iOS)
        MinisTextButton(
            onClick = onDelete,
            enabled = selectedCount > 0,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(
                    Icons.Default.Delete,
                    contentDescription = stringResource(R.string.delete),
                    tint = if (selectedCount > 0) MaterialTheme.colorScheme.error else Color.Gray,
                    modifier = Modifier.size(20.dp),
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    stringResource(R.string.delete),
                    fontSize = 11.sp,
                    color = if (selectedCount > 0) MaterialTheme.colorScheme.error else Color.Gray,
                )
            }
        }
    }
}

// ─── Section Header (matching iOS .subheadline.weight(.semibold)) ───────────

@Composable
private fun SectionHeader(title: String) {
    // T172: title may now be a localized string, so compare against the
    // localized "Pinned" rather than the hardcoded enum label.
    val isPinned = title == stringResource(R.string.sessionlist_section_pinned)
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .padding(top = 4.dp),
    ) {
        if (isPinned) {
            Icon(
                imageVector = Icons.Default.PushPin,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .size(14.dp)
                    .padding(end = 0.dp),
            )
            Spacer(modifier = Modifier.width(4.dp))
        }
        Text(
            text = title,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

// ─── Session Item (context menu replaces swipe-to-delete, matching iOS) ─────

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SessionItemContent(
    session: ChatSessionEntity,
    isSelecting: Boolean,
    selectedIds: Set<String>,
    onSessionClick: (String) -> Unit,
    onToggleSelect: (String) -> Unit,
    // [T-android-sessionlist-longpress-select] Context-menu Select: enters
    // selection mode with this row selected (distinct from onToggleSelect,
    // which only flips set membership while ALREADY selecting).
    onEnterSelect: (String) -> Unit,
    onPinToggle: (String) -> Unit,
    onEditRequest: (ChatSessionEntity) -> Unit,
    onExportRequest: (ChatSessionEntity, String) -> Unit,
    onRegenerateTitle: (String) -> Unit,
    onDuplicate: (String) -> Unit,
    onDeleteRequest: (String) -> Unit,
    isRegenerating: Boolean = false,
    searchQuery: String = "",
    searchSnippet: String? = null,
) {
    if (isSelecting) {
        val isSelected = session.id in selectedIds
        SessionRow(
            session = session,
            onClick = { onToggleSelect(session.id) },
            onLongClick = null,
            searchQuery = searchQuery,
            searchSnippet = searchSnippet,
            leadingIcon = {
                Icon(
                    imageVector = if (isSelected) Icons.Filled.CheckCircle else Icons.Outlined.Circle,
                    contentDescription = null,
                    tint = if (isSelected) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(24.dp),
                )
            },
        )
    } else {
        var showContextMenu by remember { mutableStateOf(false) }
        var pressOffset by remember { mutableStateOf(DpOffset.Zero) }
        val density = LocalDensity.current
        val isPinned = session.pinnedAt != null

        Box(modifier = Modifier.fillMaxWidth()) {
            SessionRow(
                session = session,
                onClick = { onSessionClick(session.id) },
                searchQuery = searchQuery,
                searchSnippet = searchSnippet,
                onLongClick = { offsetPx ->
                    pressOffset = with(density) {
                        DpOffset(offsetPx.x.toDp(), offsetPx.y.toDp())
                    }
                    showContextMenu = true
                },
            )
            // Loading overlay when regenerating title
            if (isRegenerating) {
                Box(
                    modifier = Modifier
                        .matchParentSize()
                        .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.7f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        androidx.compose.material3.CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                        )
                        Text(
                            stringResource(R.string.sessionlist_regenerating_title),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                }
            }
            // Invisible zero-size anchor at the press position — DropdownMenu
            // will open from here so it follows the touch point.
            Box(
                modifier = Modifier
                    .offset(x = pressOffset.x, y = pressOffset.y)
                    .size(1.dp),
            ) {
                MinisMenu(
                    expanded = showContextMenu,
                    onDismissRequest = { showContextMenu = false },
                ) {
                // Pin / Unpin
                DropdownMenuItem(
                    text = { Text(stringResource(if (isPinned) R.string.sessionlist_unpin else R.string.sessionlist_pin)) },
                    onClick = {
                        showContextMenu = false
                        onPinToggle(session.id)
                    },
                    leadingIcon = {
                        Icon(
                            if (isPinned) Icons.Default.Close else Icons.Default.PushPin,
                            contentDescription = null,
                        )
                    },
                )
                // Export submenu (JSON / Plain Text)
                var showExportSub by remember { mutableStateOf(false) }
                DropdownMenuItem(
                    text = {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Text(stringResource(R.string.sessionlist_export))
                            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, modifier = Modifier.size(16.dp))
                        }
                    },
                    onClick = { showExportSub = !showExportSub },
                    leadingIcon = {
                        Icon(Icons.Default.Share, contentDescription = null)
                    },
                )
                if (showExportSub) {
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.sessionlist_export_json), modifier = Modifier.padding(start = 24.dp)) },
                        onClick = {
                            showContextMenu = false
                            onExportRequest(session, "json")
                        },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.sessionlist_export_plain), modifier = Modifier.padding(start = 24.dp)) },
                        onClick = {
                            showContextMenu = false
                            onExportRequest(session, "text")
                        },
                    )
                }
                // Edit Title & Category
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.sessionlist_edit_title_category)) },
                    onClick = {
                        showContextMenu = false
                        onEditRequest(session)
                    },
                    leadingIcon = {
                        Icon(Icons.Default.Edit, contentDescription = null)
                    },
                )
                // Regenerate Title
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.sessionlist_regenerate_title)) },
                    onClick = {
                        showContextMenu = false
                        onRegenerateTitle(session.id)
                    },
                    leadingIcon = {
                        Icon(Icons.Default.Refresh, contentDescription = null)
                    },
                )
                // Duplicate
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.sessionlist_duplicate)) },
                    onClick = {
                        showContextMenu = false
                        onDuplicate(session.id)
                    },
                    leadingIcon = {
                        Icon(Icons.Default.ContentCopy, contentDescription = null)
                    },
                )
                // Select
                // [T-android-sessionlist-longpress-select] Must ENTER
                // selection mode, not just toggle the hidden set —
                // onToggleSelect alone never set isSelecting, so nothing
                // visibly happened and the id sat invisibly pre-selected.
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.sessionlist_select_action)) },
                    onClick = {
                        showContextMenu = false
                        onEnterSelect(session.id)
                    },
                    leadingIcon = {
                        Icon(Icons.Outlined.ChecklistRtl, contentDescription = null)
                    },
                )
                MinisMenuDivider()
                // Delete
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) },
                    onClick = {
                        showContextMenu = false
                        onDeleteRequest(session.id)
                    },
                    leadingIcon = {
                        Icon(
                            Icons.Default.Delete,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.error,
                        )
                    },
                )
                }
            }
        }
    }
}

// ─── Session Row (matching iOS SessionRow) ──────────────────────────────────

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SessionRow(
    session: ChatSessionEntity,
    onClick: () -> Unit,
    onLongClick: ((androidx.compose.ui.geometry.Offset) -> Unit)? = null,
    leadingIcon: (@Composable () -> Unit)? = null,
    searchQuery: String = "",
    searchSnippet: String? = null,
) {
    val style = remember(session.category) { categoryStyle(session.category) }
    val ctx = androidx.compose.ui.platform.LocalContext.current
    val timeText = remember(session.updatedAt, ctx) { relativeDate(ctx, session.updatedAt) }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .then(
                if (onLongClick != null) {
                    Modifier.pointerInput(Unit) {
                        detectTapGestures(
                            onTap = {
                                com.openminis.app.diagnostics.PerfLongCtx.click(session.id)
                                onClick()
                            },
                            onLongPress = { offset -> onLongClick(offset) },
                        )
                    }
                } else {
                    Modifier.clickable {
                        com.openminis.app.diagnostics.PerfLongCtx.click(session.id)
                        onClick()
                    }
                }
            )
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (leadingIcon != null) {
            leadingIcon()
        }

        // Category icon in colored circle (18% opacity matching iOS)
        val activeSessions by SessionActivityTracker.activeSessions.collectAsState()
        val isActive = session.id in activeSessions
        // [T-android-session-paused-badge] Head of this session's badge queue
        // — null for the common case. Renders as an overlay in the icon's
        // bottom-right corner, mirroring where iOS's iCloud badge sits so
        // future ICLOUD_SYNCING uses the same anchor.
        val badgeMap by com.openminis.app.service.SessionBadgeStore.byId.collectAsState()
        val badgeHead = badgeMap[session.id]?.firstOrNull()
        Box(
            modifier = Modifier.size(44.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .background(
                        color = style.color.copy(alpha = 0.18f),
                        shape = CircleShape,
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = style.icon,
                    contentDescription = null,
                    tint = style.color,
                    modifier = Modifier.size(20.dp),
                )
            }
            if (isActive) {
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .align(Alignment.Center),
                    contentAlignment = Alignment.Center,
                ) {
                    SpinningRing(
                        color = style.color,
                        modifier = Modifier.size(42.dp),
                    )
                }
            }
            if (badgeHead != null) {
                SessionBadgeOverlay(
                    state = badgeHead,
                    modifier = Modifier.align(Alignment.BottomEnd),
                )
            }
        }

        // Title + last message (or highlighted snippet during search)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(1.dp),
        ) {
            val titleText = session.title ?: "New Chat"
            if (searchQuery.isNotBlank()) {
                Text(
                    text = highlightedAnnotatedString(titleText, searchQuery),
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            } else {
                Text(
                    text = titleText,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            // During an active search, prefer the matched message snippet
            // (content hit) over the generic lastMessage preview. Falls back
            // to lastMessage when match was title-only (snippet is null).
            if (searchQuery.isNotBlank() && searchSnippet != null) {
                Text(
                    text = highlightedAnnotatedString(searchSnippet, searchQuery),
                    fontSize = 14.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            } else {
                Text(
                    text = session.lastMessage ?: "No messages yet",
                    fontSize = 14.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }

        // Relative timestamp
        Text(
            text = timeText,
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.outline,
        )
    }
}

/**
 * Spinning arc overlaid on the session icon while the agent loop is active.
 * Mirrors iOS `SpinningRing` (ContentView.swift:2405): 1.5dp stroke at 30%
 * opacity, 30% arc length, full rotation every ~1 second. Uses
 * `withFrameNanos` instead of an `animate*` API so recomposition across
 * onAppear calls does not stack multiple rotation animations.
 */
@Composable
private fun SpinningRing(
    color: Color,
    modifier: Modifier = Modifier,
) {
    var angle by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(Unit) {
        val startNanos = withFrameNanos { it }
        while (true) {
            withFrameNanos { now ->
                val elapsedSec = (now - startNanos) / 1_000_000_000f
                angle = (elapsedSec * 360f) % 360f
            }
        }
    }
    Canvas(modifier = modifier.rotate(angle)) {
        val stroke = Stroke(width = 1.5.dp.toPx(), cap = StrokeCap.Round)
        drawArc(
            color = color.copy(alpha = 0.8f),
            startAngle = 0f,
            sweepAngle = 360f * 0.3f,
            useCenter = false,
            size = Size(size.width, size.height),
            style = stroke,
        )
    }
}

/**
 * [T-android-session-paused-badge] Corner overlay for [SessionBadgeStore]
 * states. Anchored bottom-end inside the 44dp icon Box. Mirrors where the
 * iOS iCloud-sync badge sits so future ICLOUD_SYNCING uses the same anchor.
 *
 * Sizing: 14dp circle, ~2/3 the size of the 20dp category icon — visible
 * but doesn't overwhelm the icon glyph. Translated 2dp down/right so the
 * badge sits *on* the icon edge instead of flush with the row padding
 * (matches the visual weight of iOS's badge offset).
 */
@Composable
private fun SessionBadgeOverlay(
    state: com.openminis.app.service.SessionBadgeStore.SessionBadgeState,
    modifier: Modifier = Modifier,
) {
    when (state) {
        com.openminis.app.service.SessionBadgeStore.SessionBadgeState.PAUSED -> {
            Box(
                modifier = modifier
                    .offset(x = 2.dp, y = 2.dp)
                    .size(14.dp)
                    .background(
                        // Solid system-orange. Picked over yellow so the
                        // alert reads as "attention" rather than "info".
                        color = Color(0xFFFF9500),
                        shape = CircleShape,
                    )
                    .border(
                        width = 1.5.dp,
                        color = MaterialTheme.colorScheme.surface,
                        shape = CircleShape,
                    ),
                contentAlignment = Alignment.Center,
            ) {
                // Pause glyph (⏸) — mirrors iOS's "pause.fill" badge so the
                // cross-platform "this task was paused" affordance matches.
                Icon(
                    imageVector = Icons.Filled.Pause,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(9.dp),
                )
            }
        }
        com.openminis.app.service.SessionBadgeStore.SessionBadgeState.ICLOUD_SYNCING -> {
            // Reserved for the upcoming iCloud-equivalent sync surface;
            // not produced yet. Render nothing rather than a placeholder
            // so a stray persisted entry from a future build doesn't
            // surface a debug-looking icon on the current build.
        }
    }
}

// ─── Onboarding Landing (iOS-style 3-step setup) ───────────────────────────

@Composable
private fun OnboardingLanding(
    hasProviders: Boolean,
    hasGroups: Boolean,
    onAddProvider: () -> Unit,
    onSelectModels: () -> Unit,
    onStartConversation: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            // Bottom padding ≈ top-bar height so the content visually centers
            // relative to the whole screen, not just the Scaffold inner area.
            .padding(horizontal = 32.dp)
            .padding(bottom = 64.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = Icons.Default.AutoAwesome,
            contentDescription = null,
            modifier = Modifier.size(56.dp),
            tint = MaterialTheme.colorScheme.primary,
        )
        Spacer(Modifier.height(16.dp))

        Text(
            text = stringResource(R.string.sessionlist_welcome_title),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(8.dp))
        Text(
            text = stringResource(R.string.sessionlist_welcome_subtitle),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )

        Spacer(Modifier.height(32.dp))

        Column(
            verticalArrangement = Arrangement.spacedBy(12.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            SetupStepCard(
                number = 1,
                title = stringResource(R.string.sessionlist_welcome_step1_title),
                subtitle = if (hasProviders) {
                    stringResource(R.string.sessionlist_welcome_step_done)
                } else {
                    stringResource(R.string.sessionlist_welcome_step1_subtitle)
                },
                isDone = hasProviders,
                isLocked = false,
                onClick = { if (!hasProviders) onAddProvider() },
            )

            SetupStepCard(
                number = 2,
                title = stringResource(R.string.sessionlist_welcome_step2_title),
                subtitle = when {
                    hasGroups -> stringResource(R.string.sessionlist_welcome_step_done)
                    hasProviders -> stringResource(R.string.sessionlist_welcome_step2_subtitle)
                    else -> stringResource(R.string.sessionlist_welcome_step2_locked)
                },
                isDone = hasGroups,
                isLocked = !hasProviders,
                onClick = { if (hasProviders && !hasGroups) onSelectModels() },
            )

            SetupStepCard(
                number = 3,
                title = stringResource(R.string.sessionlist_welcome_step3_title),
                subtitle = if (hasGroups) {
                    stringResource(R.string.sessionlist_welcome_step3_subtitle)
                } else {
                    stringResource(R.string.sessionlist_welcome_step3_locked)
                },
                isDone = false,
                isLocked = !hasGroups,
                onClick = { if (hasGroups) onStartConversation() },
            )
        }
    }
}

@Composable
private fun SetupStepCard(
    number: Int,
    title: String,
    subtitle: String,
    isDone: Boolean,
    isLocked: Boolean,
    onClick: () -> Unit,
) {
    val isEnabled = !isDone && !isLocked

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f),
                shape = RoundedCornerShape(12.dp),
            )
            .clickable(enabled = isEnabled, onClick = onClick)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(
            modifier = Modifier
                .size(32.dp)
                .background(
                    color = if (isDone) Color(0xFF34C759) else MaterialTheme.colorScheme.primary,
                    shape = CircleShape,
                ),
            contentAlignment = Alignment.Center,
        ) {
            if (isDone) {
                Icon(
                    imageVector = Icons.Default.Check,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(16.dp),
                )
            } else {
                Text(
                    text = "$number",
                    color = Color.White,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
        }

        Column(
            modifier = Modifier.weight(1f).height(56.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.Medium,
                color = if (isDone) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (!isDone && isEnabled) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
            )
        }
    }
}

// ─── Edit Title & Category Sheet (matching iOS SessionEditSheet) ──────────

private val allCategories = listOf(
    "Code", "Writing", "Research", "Analysis",
    "Creative", "Chat", "Math", "Translation",
    "Health", "Finance", "Travel", "Education",
    "Design", "Productivity", "Support", "Other",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SessionEditSheet(
    session: ChatSessionEntity,
    onDismiss: () -> Unit,
    onSave: (title: String, category: String?) -> Unit,
    // [T-android-sessionedit-regenerate-button] Regenerate-Title support,
    // matching iOS SessionEditSheet. `liveSession` is the DB-backed row that
    // updates when regeneration writes a new title/category; `isRegenerating`
    // drives the button's loading/disabled state; `onRegenerate` reuses the
    // existing SessionListViewModel.regenerateTitle logic. Defaults make the
    // button a no-op when a caller doesn't wire them up.
    liveSession: ChatSessionEntity = session,
    isRegenerating: Boolean = false,
    onRegenerate: () -> Unit = {},
) {
    var title by remember { mutableStateOf(session.title ?: "") }
    var selectedCategory by remember { mutableStateOf(session.category) }

    // [T-android-sessionedit-regenerate-button] When a regeneration run writes a
    // new title/category to the DB, `liveSession` updates — mirror those values
    // into the sheet's local edit state so the Title field and Category grid
    // refresh in place (iOS reads the fresh ChatStore session on completion).
    LaunchedEffect(liveSession.title, liveSession.category) {
        liveSession.title?.let { title = it }
        selectedCategory = liveSession.category
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 32.dp)
                .navigationBarsPadding(),
        ) {
            // Title bar
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MinisTextButton(onClick = onDismiss) { Text("Cancel") }
                Spacer(Modifier.weight(1f))
                Text(
                    "Edit Session",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.weight(1f))
                MinisTextButton(
                    onClick = { onSave(title.ifBlank { "New Chat" }, selectedCategory) },
                ) { Text("Save") }
            }

            Spacer(Modifier.height(16.dp))

            // Title field
            OutlinedTextField(
                value = title,
                onValueChange = { title = it },
                label = { Text("Title") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )

            Spacer(Modifier.height(20.dp))

            Text(
                "Category",
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.padding(bottom = 8.dp),
            )

            // Category grid (4 columns, matching iOS LazyVGrid)
            LazyVerticalGrid(
                columns = GridCells.Fixed(4),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.height(240.dp),
            ) {
                items(allCategories) { cat ->
                    val isSelected = selectedCategory?.equals(cat, ignoreCase = true) == true
                    val style = categoryStyle(cat.lowercase())
                    Box(
                        modifier = Modifier
                            .clip(RoundedCornerShape(10.dp))
                            .background(
                                if (isSelected) style.color.copy(alpha = 0.2f)
                                else MaterialTheme.colorScheme.surfaceContainerHigh
                            )
                            .clickable {
                                selectedCategory = if (isSelected) null else cat.lowercase()
                            }
                            .padding(vertical = 10.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Icon(
                                imageVector = style.icon,
                                contentDescription = null,
                                tint = style.color,
                                modifier = Modifier.size(20.dp),
                            )
                            Spacer(Modifier.height(4.dp))
                            Text(
                                cat,
                                fontSize = 11.sp,
                                color = if (isSelected) style.color
                                else MaterialTheme.colorScheme.onSurfaceVariant,
                                fontWeight = if (isSelected) FontWeight.SemiBold else FontWeight.Normal,
                            )
                        }
                    }
                }
            }

            Spacer(Modifier.height(20.dp))

            // [T-android-sessionedit-regenerate-button] Regenerate Title —
            // matches iOS SessionEditSheet's dedicated section below Category.
            // Reuses SessionListViewModel.regenerateTitle; shows a spinner and
            // disables while running (regeneratingIds) to prevent double taps.
            OutlinedButton(
                onClick = onRegenerate,
                enabled = !isRegenerating,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (isRegenerating) {
                    androidx.compose.material3.CircularProgressIndicator(
                        modifier = Modifier.size(16.dp),
                        strokeWidth = 2.dp,
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.sessionlist_regenerating_title))
                } else {
                    Icon(
                        Icons.Default.Refresh,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.sessionlist_regenerate_title))
                }
            }
        }
    }
}

// ─── Export Session ────────────────────────────────────────────────────────

/**
 * Long-chat export (T-export-optimize b443b54d, iOS sister c9d1087d).
 *
 * Pre-fix: this loaded every [MessageEntity] for the session at once,
 * built the whole JSON / TXT payload in memory, and shoved it into
 * [Intent.EXTRA_TEXT]. Hundreds of messages caused jank, "ghost" frames
 * and OOM crashes — see linked feedback.
 *
 * Now: hand off to [com.openminis.app.share.ChatExporter] which paginates
 * (50 rows / batch) on [kotlinx.coroutines.Dispatchers.IO], streams to a
 * staging file under `cacheDir/export-staging/`, then zips into
 * `cacheDir/shared/` and hands the resulting [android.net.Uri] to the
 * share sheet as a real file attachment. Peak memory stays bounded by
 * batch size regardless of session length.
 */
private fun exportSession(
    context: Context,
    session: ChatSessionEntity,
    chatRepository: ChatRepository,
    scope: kotlinx.coroutines.CoroutineScope,
    format: String,
) {
    scope.launch {
        try {
            val (uri, _) = com.openminis.app.share.ChatExporter.exportToZip(
                context = context,
                session = session,
                repository = chatRepository,
                format = format,
            )
            val intent = Intent(Intent.ACTION_SEND).apply {
                type = "application/zip"
                putExtra(Intent.EXTRA_SUBJECT, session.title ?: "Conversation")
                putExtra(Intent.EXTRA_STREAM, uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            val chooser = Intent.createChooser(
                intent,
                context.getString(R.string.sessionlist_export),
            ).apply { addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION) }
            context.startActivity(chooser)
        } catch (t: Throwable) {
            android.widget.Toast.makeText(
                context,
                context.getString(R.string.export_progress_failed),
                android.widget.Toast.LENGTH_LONG,
            ).show()
        }
    }
}

