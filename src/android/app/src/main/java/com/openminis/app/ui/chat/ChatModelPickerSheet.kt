package com.openminis.app.ui.chat

// [T-android-split-chat] ModelPickerSheet (+ its private helpers fuzzyMatch /
// providerDotColor) extracted verbatim from ChatScreen.kt. Full import block
// copied from ChatScreen.kt (unused imports are warnings, not errors);
// ModelPickerSheet flipped private->internal so ChatScreen can call it.

import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.OpenableColumns
import java.io.File
import androidx.core.content.ContextCompat
import androidx.compose.foundation.Image
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.graphics.rememberGraphicsLayer
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.gestures.verticalDrag
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.AudioFile
import androidx.compose.material.icons.filled.FolderZip
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.VideoFile
import androidx.compose.material.icons.automirrored.filled.Article
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.sample
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import androidx.compose.runtime.withFrameNanos
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.automirrored.filled.InsertDriveFile
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.AppShortcut
import androidx.compose.material.icons.filled.ArrowCircleUp
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Extension
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DataUsage
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.CloseFullscreen
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Lightbulb
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.StopCircle
import androidx.compose.material.icons.filled.Terminal
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.RadioButtonChecked
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import com.openminis.app.BuildConfig
import com.openminis.app.R
import com.openminis.app.data.FileMentionIndex
import com.openminis.app.logging.AppLogger
import com.openminis.app.ui.components.MinisAlertDialog
import com.openminis.app.ui.components.MinisMenu
import com.openminis.app.ui.components.MinisMenuDivider
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Surface
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.produceState
import androidx.compose.runtime.snapshotFlow
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onPlaced
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.isShiftPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.material.icons.automirrored.filled.FormatListBulleted
import androidx.compose.material.icons.filled.TextFields
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.outlined.Public
import androidx.compose.material.icons.filled.SkipNext
import androidx.compose.material.icons.filled.SkipPrevious
import androidx.compose.material.icons.automirrored.filled.NoteAdd
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Memory
import androidx.compose.material.icons.filled.ArrowCircleDown
import androidx.compose.material.icons.filled.AccountTree
import androidx.compose.material3.ButtonDefaults
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.openminis.app.offload.OffloadPermissionManager
import com.mikepenz.markdown.compose.components.markdownComponents
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.m3.markdownColor
import com.mikepenz.markdown.m3.markdownTypography
import org.intellij.markdown.ast.ASTNode
import org.intellij.markdown.ast.getTextInNode
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ModelGroup
import com.openminis.app.data.model.ProviderConfig
import com.openminis.app.data.model.ProviderType
import com.openminis.app.data.model.RoutingStrategy
import com.openminis.app.data.model.ThinkingLevel
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.data.repository.MemoryRepository
import com.openminis.app.data.repository.ProviderRepository
import com.openminis.app.ui.browser.BrowserSheet
import com.openminis.app.ui.theme.ChatColors
import com.openminis.app.ui.components.MinisTextButton

/**
 * Fuzzy match: substring first, then all query chars appear in order.
 * Matches iOS SessionModelPicker.fuzzyMatch.
 */
private fun fuzzyMatch(text: String, query: String): Boolean {
    if (query.isEmpty()) return true
    val q = query.lowercase()
    val t = text.lowercase()
    if (t.contains(q)) return true
    var idx = 0
    for (ch in q) {
        val found = t.indexOf(ch, idx)
        if (found < 0) return false
        idx = found + 1
    }
    return true
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ModelPickerSheet(
    groups: List<ModelGroup>,
    selectedGroupId: String?,
    activeEntryId: String?,
    defaultPrimaryGroupId: String?,
    config: ProviderConfig,
    providerRepository: ProviderRepository,
    onSelectGroup: (String) -> Unit,
    onSelectGroupEntry: (String, String) -> Unit,
    onSelectEntry: (String) -> Unit,
    onDismiss: () -> Unit,
    /** [T-android-modelpicker-group-edit] "Edit" affordance on the Model Groups
     *  section header — dismisses the sheet and navigates to the Model Groups
     *  management screen. Null hides the button (callers without a route). */
    onEditGroups: (() -> Unit)? = null,
) {
    val openTime = remember { System.nanoTime() }

    LaunchedEffect(Unit) {
        AppLogger.info("ModelPicker", "[ModelPicker] open triggered")
        withFrameNanos { frameTime ->
            val ms = (frameTime - openTime) / 1_000_000.0
            AppLogger.info("ModelPicker", "[ModelPicker] first frame rendered: ${"%.1f".format(ms)}ms (total since trigger)")
        }
    }

    var searchText by remember { mutableStateOf("") }
    var expandedGroupIds by remember { mutableStateOf(setOf<String>()) }
    // Note: the non-text-output "may not work as an Agent" confirmation lives
    // in ChatScreen's callback wrappers (ee828dba), NOT here — the sheet stays
    // a dumb list and the caller owns selection policy.
    val allInstanceIds = remember(config) {
        config.instances.filter { it.isEnabled }.map { it.id }.toSet()
    }
    var collapsedInstanceIds by remember(allInstanceIds) {
        mutableStateOf(allInstanceIds)
    }

    // Filtered groups
    val filteredGroups = remember(groups, searchText) {
        if (searchText.isEmpty()) groups
        else {
            val t0 = System.nanoTime()
            val result = groups.filter { fuzzyMatch(it.name, searchText) }
            val ms = (System.nanoTime() - t0) / 1_000_000.0
            AppLogger.info("ModelPicker", "[ModelPicker] filter groups: ${result.size}/${groups.size}, ${"%.1f".format(ms)}ms")
            result
        }
    }

    // Filtered entries by instance
    val allInstancesWithEntries = remember(config, searchText) {
        val t0 = System.nanoTime()
        var totalCount = 0
        val result = config.instances
            .filter { it.isEnabled }
            .map { instance ->
                val pt = System.nanoTime()
                val entries = config.modelEntries.filter {
                    it.providerInstanceId == instance.id && !it.isHidden
                }
                val filtered = if (searchText.isEmpty()) entries
                else entries.filter {
                    fuzzyMatch(it.model.displayName, searchText) || fuzzyMatch(it.model.id, searchText)
                }
                val pms = (System.nanoTime() - pt) / 1_000_000.0
                if (filtered.isNotEmpty()) {
                    totalCount += filtered.size
                    AppLogger.info("ModelPicker", "[ModelPicker] provider \"${instance.label.ifEmpty { instance.providerType.displayName }}\" models loaded: ${filtered.size} items, ${"%.1f".format(pms)}ms")
                }
                instance to filtered
            }
            .filter { it.second.isNotEmpty() }
        val ms = (System.nanoTime() - t0) / 1_000_000.0
        AppLogger.info("ModelPicker", "[ModelPicker] all providers loaded: total $totalCount items, ${"%.1f".format(ms)}ms")
        result
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        // Match the slim drag handle used by StandardChatSheet (6dp top / 4dp
        // bottom) so the title sits flush with the indicator instead of the
        // Material default's ~44dp whitespace gap above it.
        dragHandle = {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 6.dp, bottom = 4.dp),
                contentAlignment = Alignment.TopCenter,
            ) {
                Box(
                    modifier = Modifier
                        .width(32.dp)
                        .height(4.dp)
                        .background(
                            color = ChatColors.secondaryText.copy(alpha = 0.4f),
                            shape = RoundedCornerShape(2.dp),
                        ),
                )
            }
        },
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .fillMaxHeight(0.9f)
                .padding(bottom = 32.dp)
                .navigationBarsPadding(),
        ) {
            // ── Title bar (iOS: "Choose Model" + Done) ──
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Spacer(Modifier.weight(1f))
                Text(
                    stringResource(R.string.model_picker_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.CenterEnd) {
                    MinisTextButton(onClick = onDismiss) {
                        Text(stringResource(R.string.model_picker_done))
                    }
                }
            }

            // ── Search bar (iOS: capsule rounded) ──
            // T250: cap minHeight at 48dp so the field doesn't read as
            // visually heavy against the section cards below it (Material3
            // default is 56dp; ~14% drop matches the spec target of ~15%).
            OutlinedTextField(
                value = searchText,
                onValueChange = { searchText = it },
                placeholder = { Text(stringResource(R.string.model_picker_search_placeholder)) },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 4.dp)
                    .heightIn(min = 48.dp),
                singleLine = true,
                shape = RoundedCornerShape(50),
                textStyle = MaterialTheme.typography.bodyMedium,
                leadingIcon = {
                    Icon(
                        Icons.Default.Search,
                        contentDescription = null,
                        modifier = Modifier.size(18.dp),
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                },
                trailingIcon = {
                    if (searchText.isNotEmpty()) {
                        IconButton(onClick = { searchText = "" }) {
                            Icon(Icons.Default.Close, contentDescription = stringResource(R.string.model_picker_search_clear), modifier = Modifier.size(18.dp))
                        }
                    }
                },
            )

            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f, fill = false),
            ) {
                // ── Model Groups (grouped section card with embedded header) ──
                if (filteredGroups.isNotEmpty()) {
                    // Section card: header + rows live in the same surface so
                    // the visual unit is unambiguous. Header uses the
                    // titleSmall + onSurfaceVariant pair so it reads as a
                    // section label rather than another row.
                    item {
                        Column(
                            modifier = Modifier
                                .padding(horizontal = 16.dp, vertical = 6.dp)
                                .background(
                                    MaterialTheme.colorScheme.surfaceContainerHigh,
                                    RoundedCornerShape(14.dp),
                                ),
                        ) {
                            // [T-android-modelpicker-group-edit] Section header
                            // row: label on the left, an "Edit" button on the
                            // right that jumps to the Model Groups management
                            // screen (mirrors the iOS picker's group-section edit
                            // affordance). Button hidden when no route is wired.
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    stringResource(R.string.model_picker_groups_section),
                                    style = MaterialTheme.typography.titleSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier
                                        .weight(1f)
                                        .padding(start = 16.dp, top = 14.dp, bottom = 6.dp),
                                )
                                if (onEditGroups != null) {
                                    // Text button (not a pencil icon) matching the
                                    // sheet's other text actions like "Done".
                                    MinisTextButton(
                                        onClick = onEditGroups,
                                        modifier = Modifier.padding(end = 8.dp),
                                    ) {
                                        Text(stringResource(R.string.model_picker_groups_edit))
                                    }
                                }
                            }
                            filteredGroups.forEachIndexed { index, group ->
                                val isSelected = group.id == selectedGroupId
                                val isDefault = group.id == defaultPrimaryGroupId
                                val isExpanded = expandedGroupIds.contains(group.id)
                                val strategyLabel = when (group.strategy) {
                                    RoutingStrategy.fallback -> "FB"
                                    RoutingStrategy.loadBalance -> "LB"
                                }
                                // Resolve entry: try memberEntryIds first, fallback to activeEntryId ONLY if this group is selected
                                val resolvedEntry = group.memberEntryIds.firstNotNullOfOrNull { entryId ->
                                    config.modelEntries.find { it.id == entryId }
                                } ?: if (isSelected && activeEntryId != null) config.modelEntries.find { it.id == activeEntryId } else null
                                // Count of resolved members for display
                                val resolvedCount = group.memberEntryIds.count { entryId ->
                                    config.modelEntries.any { it.id == entryId }
                                }

                                // Header sits above the first row, so the
                                // first-row corners are no longer rounded
                                // (only the bottom row of the last group is).
                                val groupShape = when {
                                    index == filteredGroups.size - 1 -> RoundedCornerShape(bottomStart = 14.dp, bottomEnd = 14.dp)
                                    else -> RoundedCornerShape(0.dp)
                                }

                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(groupShape)
                                        .clickable { onSelectGroup(group.id) }
                                        .padding(horizontal = 16.dp, vertical = 12.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(
                                        if (isSelected) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
                                        contentDescription = null,
                                        tint = if (isSelected) Color(0xFF34C759)
                                        else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
                                        modifier = Modifier.size(22.dp),
                                    )
                                    Spacer(Modifier.width(10.dp))
                                    Column(modifier = Modifier.weight(1f)) {
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            Text(
                                                group.name,
                                                style = MaterialTheme.typography.bodyMedium,
                                                fontWeight = FontWeight.SemiBold,
                                            )
                                            Spacer(Modifier.width(6.dp))
                                            // iOS: ⊕ FB / ⊕ LB badge with icon
                                            Row(
                                                verticalAlignment = Alignment.CenterVertically,
                                                modifier = Modifier
                                                    .background(
                                                        MaterialTheme.colorScheme.surfaceContainerHigh,
                                                        RoundedCornerShape(8.dp),
                                                    )
                                                    .padding(horizontal = 5.dp, vertical = 1.dp),
                                            ) {
                                                Icon(
                                                    if (group.strategy == RoutingStrategy.fallback)
                                                        Icons.Default.ArrowCircleDown
                                                    else Icons.Default.AccountTree,
                                                    contentDescription = null,
                                                    modifier = Modifier.size(9.dp),
                                                    tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                                                )
                                                Spacer(Modifier.width(2.dp))
                                                Text(
                                                    strategyLabel,
                                                    fontSize = 9.sp,
                                                    fontWeight = FontWeight.Medium,
                                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                                                )
                                            }
                                        }
                                        // iOS: "→ ModelName" resolved entry
                                        if (resolvedEntry != null) {
                                            Text(
                                                "→ ${resolvedEntry.model.displayName}",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                            )
                                        } else if (resolvedCount > 0) {
                                            Text(
                                                pluralStringResource(R.plurals.model_picker_models_count, resolvedCount, resolvedCount),
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                            )
                                        } else {
                                            Text(
                                                stringResource(R.string.model_picker_models_count_unlinked, group.memberEntryIds.size),
                                                style = MaterialTheme.typography.bodySmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                                            )
                                        }
                                    }

                                    // iOS parity: "Default" badge — filled capsule
                                    if (isDefault) {
                                        Text(
                                            stringResource(R.string.model_picker_default_badge),
                                            fontSize = 10.sp,
                                            fontWeight = FontWeight.Medium,
                                            color = Color(0xFF007AFF),
                                            modifier = Modifier
                                                .background(
                                                    Color(0xFF007AFF).copy(alpha = 0.1f),
                                                    RoundedCornerShape(50),
                                                )
                                                .padding(horizontal = 6.dp, vertical = 2.dp),
                                        )
                                        Spacer(Modifier.width(8.dp))
                                    }

                                    // iOS: expand/collapse chevron button.
                                    // T295: bumped from surfaceContainerHigh
                                    // (which on light theme = #F7F7FA, almost
                                    // identical to the white card it sits on)
                                    // to secondaryContainer + onSecondaryContainer
                                    // tint, so the chevron actually reads as a
                                    // tonal button instead of a flat ghost
                                    // icon. Same shape + size as before.
                                    Box(
                                        modifier = Modifier
                                            .size(28.dp)
                                            .background(
                                                MaterialTheme.colorScheme.secondaryContainer,
                                                CircleShape,
                                            )
                                            .clip(CircleShape)
                                            .clickable {
                                                expandedGroupIds = if (isExpanded) {
                                                    expandedGroupIds - group.id
                                                } else {
                                                    expandedGroupIds + group.id
                                                }
                                            },
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        Icon(
                                            if (isExpanded) Icons.Default.KeyboardArrowUp else Icons.Default.KeyboardArrowDown,
                                            contentDescription = null,
                                            modifier = Modifier.size(16.dp),
                                            tint = MaterialTheme.colorScheme.onSecondaryContainer,
                                        )
                                    }
                                }

                                // Expanded group member entries
                                if (isExpanded) {
                                    // Resolve actual entries from memberEntryIds
                                    val resolvedMembers = group.memberEntryIds.mapNotNull { entryId ->
                                        config.modelEntries.find { it.id == entryId }
                                    }
                                    // Fallback: show active entry ONLY if this group is selected
                                    val displayMembers = resolvedMembers.ifEmpty {
                                        if (isSelected && activeEntryId != null)
                                            listOfNotNull(config.modelEntries.find { it.id == activeEntryId })
                                        else emptyList()
                                    }
                                    if (displayMembers.isEmpty()) {
                                        Text(
                                            stringResource(R.string.model_picker_no_linked_models),
                                            style = MaterialTheme.typography.bodySmall,
                                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                            modifier = Modifier.padding(start = 48.dp, top = 4.dp, bottom = 8.dp),
                                        )
                                    }
                                    displayMembers.forEach { entry ->
                                            val isActive = activeEntryId == entry.id
                                            val instance = config.instances.find { it.id == entry.providerInstanceId }
                                            Row(
                                                modifier = Modifier
                                                    .fillMaxWidth()
                                                    .clickable { onSelectGroupEntry(group.id, entry.id) }
                                                    .padding(start = 48.dp, end = 16.dp, top = 8.dp, bottom = 8.dp),
                                                verticalAlignment = Alignment.CenterVertically,
                                            ) {
                                                Icon(
                                                    if (isActive) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
                                                    contentDescription = null,
                                                    tint = if (isActive) Color(0xFF007AFF)
                                                    else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.2f),
                                                    modifier = Modifier.size(17.dp),
                                                )
                                                Spacer(Modifier.width(10.dp))
                                                Box(
                                                    modifier = Modifier
                                                        .size(6.dp)
                                                        .background(providerDotColor(instance?.providerType), CircleShape),
                                                )
                                                Spacer(Modifier.width(8.dp))
                                                Column(modifier = Modifier.weight(1f)) {
                                                    Text(entry.model.displayName, style = MaterialTheme.typography.bodyMedium)
                                                    Row {
                                                        if (instance != null) {
                                                            Text(
                                                                instance.label.ifEmpty { instance.providerType.displayName },
                                                                style = MaterialTheme.typography.labelSmall,
                                                                fontWeight = FontWeight.Medium,
                                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f),
                                                            )
                                                            Text(
                                                                " · ",
                                                                style = MaterialTheme.typography.labelSmall,
                                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                                                            )
                                                        }
                                                        Text(
                                                            entry.model.id,
                                                            style = MaterialTheme.typography.labelSmall,
                                                            color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.4f),
                                                        )
                                                    }
                                                }
                                                if (isActive) {
                                                    Text(
                                                        stringResource(R.string.model_picker_active_badge),
                                                        fontSize = 10.sp,
                                                        fontWeight = FontWeight.Medium,
                                                        color = Color(0xFF34C759),
                                                        modifier = Modifier
                                                            .background(
                                                                Color(0xFF34C759).copy(alpha = 0.1f),
                                                                RoundedCornerShape(8.dp),
                                                            )
                                                            .padding(horizontal = 5.dp, vertical = 1.dp),
                                                    )
                                                }
                                            }
                                    }
                                }

                                // Inset hairline between groups, matches MinisMenuDivider rhythm.
                                if (index < filteredGroups.size - 1) {
                                    HorizontalDivider(
                                        modifier = Modifier.padding(start = 48.dp, end = 16.dp),
                                        thickness = 0.5.dp,
                                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.35f),
                                    )
                                }
                            }
                        }
                    }

                    if (searchText.isEmpty()) {
                        item {
                            Text(
                                stringResource(R.string.model_picker_groups_footer),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                // T236: hint sits between Model Groups card and
                                // first Provider card — top 8 hugs the group
                                // card, bottom 12 separates from the next card.
                                modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 12.dp),
                            )
                        }
                    }
                }

                // ── Individual Models by Provider (one section card per provider) ──
                // Each provider becomes a single grouped card containing: an
                // embedded header row with the collapse chevron, then either
                // the collapsed summary row or the expanded entry list. Cards
                // are visually separated from each other by a 12dp gap, and
                // sit on a higher tonal surface so the boundary between
                // providers is unmistakable even on the dark sheet background.
                if (allInstancesWithEntries.isNotEmpty()) {
                    allInstancesWithEntries.forEach { (instance, entries) ->
                        val isCollapsed = collapsedInstanceIds.contains(instance.id)
                        item(key = "section_${instance.id}") {
                            Column(
                                modifier = Modifier
                                    .padding(horizontal = 16.dp, vertical = 6.dp)
                                    .background(
                                        MaterialTheme.colorScheme.surfaceContainerHigh,
                                        RoundedCornerShape(14.dp),
                                    ),
                            ) {
                                // Header row, embedded in the card.
                                Row(
                                    // T236: tightened provider header padding
                                    // (top=10/bottom=8) so the gap to the first
                                    // model row reads as ~8dp rather than the
                                    // earlier 12dp+row-padding stack.
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(start = 16.dp, end = 8.dp, top = 10.dp, bottom = 8.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(
                                        instance.label.ifEmpty { instance.providerType.displayName },
                                        style = MaterialTheme.typography.titleSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        modifier = Modifier.weight(1f),
                                    )
                                    // T295: same tonal upgrade as the model-
                                    // group chevron above — surfaceContainer-
                                    // Highest read as flat against the card
                                    // surface. Use secondaryContainer for a
                                    // visible pill shape.
                                    Box(
                                        modifier = Modifier
                                            .size(28.dp)
                                            .background(
                                                MaterialTheme.colorScheme.secondaryContainer,
                                                CircleShape,
                                            )
                                            .clip(CircleShape)
                                            .clickable {
                                                collapsedInstanceIds = if (isCollapsed) {
                                                    collapsedInstanceIds - instance.id
                                                } else {
                                                    collapsedInstanceIds + instance.id
                                                }
                                            },
                                        contentAlignment = Alignment.Center,
                                    ) {
                                        Icon(
                                            if (isCollapsed) Icons.Default.KeyboardArrowDown else Icons.Default.KeyboardArrowUp,
                                            contentDescription = null,
                                            modifier = Modifier.size(16.dp),
                                            tint = MaterialTheme.colorScheme.onSecondaryContainer,
                                        )
                                    }
                                }

                                if (isCollapsed) {
                                    // Collapsed summary — show selected or first entry + model count.
                                    val selectedEntry = entries.firstOrNull { it.id == activeEntryId && selectedGroupId == null }
                                    val displayEntry = selectedEntry ?: entries.firstOrNull()
                                    if (displayEntry != null) {
                                        val dotColor = providerDotColor(instance.providerType)
                                        Row(
                                            // T236: collapsed summary row —
                                            // vertical 14→8 + heightIn(min=48dp)
                                            // so tap target stays comfortable.
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .heightIn(min = 48.dp)
                                                .clip(RoundedCornerShape(bottomStart = 14.dp, bottomEnd = 14.dp))
                                                .clickable { onSelectEntry(displayEntry.id) }
                                                .padding(horizontal = 16.dp, vertical = 8.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Icon(
                                                if (selectedEntry != null) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
                                                contentDescription = null,
                                                tint = if (selectedEntry != null) Color(0xFF007AFF)
                                                else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
                                                modifier = Modifier.size(20.dp),
                                            )
                                            Spacer(Modifier.width(10.dp))
                                            Box(
                                                modifier = Modifier
                                                    .size(6.dp)
                                                    .background(dotColor, CircleShape),
                                            )
                                            Spacer(Modifier.width(10.dp))
                                            Row(
                                                modifier = Modifier.weight(1f),
                                                verticalAlignment = Alignment.CenterVertically,
                                            ) {
                                                Text(
                                                    displayEntry.model.displayName,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                )
                                                // [T-android-provider-voice] Modality chips
                                                // (iOS entryRow badges) — without them a
                                                // voice seed serving as the collapsed
                                                // representative is indistinguishable from
                                                // a chat model.
                                                com.openminis.app.ui.components.modalityBadges(displayEntry.model).forEach { badge ->
                                                    Spacer(Modifier.width(4.dp))
                                                    Text(
                                                        badge,
                                                        style = MaterialTheme.typography.labelSmall,
                                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                        modifier = Modifier
                                                            .background(
                                                                MaterialTheme.colorScheme.surfaceContainerHigh,
                                                                RoundedCornerShape(3.dp),
                                                            )
                                                            .padding(horizontal = 4.dp, vertical = 1.dp),
                                                    )
                                                }
                                            }
                                            Text(
                                                pluralStringResource(R.plurals.model_picker_models_count, entries.size, entries.size),
                                                style = MaterialTheme.typography.labelSmall,
                                                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                            )
                                        }
                                    }
                                } else {
                                    entries.forEachIndexed { index, entry ->
                                        val isSelected = activeEntryId == entry.id && selectedGroupId == null
                                        val dotColor = providerDotColor(instance.providerType)
                                        // Last row clips its own bottom so the
                                        // ripple respects the card corners.
                                        val rowShape = if (index == entries.size - 1) {
                                            RoundedCornerShape(bottomStart = 14.dp, bottomEnd = 14.dp)
                                        } else {
                                            RoundedCornerShape(0.dp)
                                        }
                                        Row(
                                            // T236: expanded entry row —
                                            // vertical 14→8 + heightIn(min=48dp)
                                            // for accessible tap target.
                                            modifier = Modifier
                                                .fillMaxWidth()
                                                .heightIn(min = 48.dp)
                                                .clip(rowShape)
                                                .clickable { onSelectEntry(entry.id) }
                                                .padding(horizontal = 16.dp, vertical = 8.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Icon(
                                                if (isSelected) Icons.Default.CheckCircle else Icons.Default.RadioButtonUnchecked,
                                                contentDescription = null,
                                                tint = if (isSelected) Color(0xFF007AFF)
                                                else MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
                                                modifier = Modifier.size(20.dp),
                                            )
                                            Spacer(Modifier.width(10.dp))
                                            Box(
                                                modifier = Modifier
                                                    .size(6.dp)
                                                    .background(dotColor, CircleShape),
                                            )
                                            Spacer(Modifier.width(10.dp))
                                            Column(modifier = Modifier.weight(1f)) {
                                                Text(
                                                    entry.model.displayName,
                                                    style = MaterialTheme.typography.bodyMedium,
                                                )
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                    Text(
                                                        entry.model.id,
                                                        style = MaterialTheme.typography.labelSmall,
                                                        color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                                    )
                                                    // [T-android-provider-voice] Modality
                                                    // chips (iOS entryRow badges).
                                                    com.openminis.app.ui.components.modalityBadges(entry.model).forEach { badge ->
                                                        Spacer(Modifier.width(4.dp))
                                                        Text(
                                                            badge,
                                                            style = MaterialTheme.typography.labelSmall,
                                                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                            modifier = Modifier
                                                                .background(
                                                                    MaterialTheme.colorScheme.surfaceContainerHigh,
                                                                    RoundedCornerShape(3.dp),
                                                                )
                                                                .padding(horizontal = 4.dp, vertical = 1.dp),
                                                        )
                                                    }
                                                }
                                            }
                                            if (selectedGroupId != null && activeEntryId == entry.id) {
                                                Text(
                                                    stringResource(R.string.model_picker_active_badge),
                                                    fontSize = 10.sp,
                                                    fontWeight = FontWeight.Medium,
                                                    color = Color(0xFF34C759),
                                                    modifier = Modifier
                                                        .background(
                                                            Color(0xFF34C759).copy(alpha = 0.1f),
                                                            RoundedCornerShape(8.dp),
                                                        )
                                                        .padding(horizontal = 5.dp, vertical = 1.dp),
                                                )
                                            }
                                        }
                                        // Inset hairline between entries.
                                        if (index < entries.size - 1) {
                                            HorizontalDivider(
                                                modifier = Modifier.padding(start = 52.dp, end = 16.dp),
                                                thickness = 0.5.dp,
                                                color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.35f),
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                // ── Empty / No Results ──
                if (filteredGroups.isEmpty() && allInstancesWithEntries.isEmpty()) {
                    item {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(32.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Icon(
                                if (searchText.isNotEmpty()) Icons.Default.Search else Icons.Default.Memory,
                                contentDescription = null,
                                modifier = Modifier.size(28.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.3f),
                            )
                            Spacer(Modifier.height(8.dp))
                            Text(
                                stringResource(if (searchText.isNotEmpty()) R.string.model_picker_no_results else R.string.model_picker_no_models),
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            if (searchText.isEmpty()) {
                                Spacer(Modifier.height(4.dp))
                                Text(
                                    stringResource(R.string.model_picker_configure_hint),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                    textAlign = TextAlign.Center,
                                )
                            } else {
                                Spacer(Modifier.height(4.dp))
                                Text(
                                    stringResource(R.string.model_picker_try_different_search),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                                )
                            }
                        }
                    }
                }
            }
        }
    }

}

// iOS: provider color dot helper
private fun providerDotColor(providerType: ProviderType?): Color = when (providerType) {
    ProviderType.anthropic -> Color(0xFFAB47BC) // purple
    ProviderType.gemini -> Color(0xFF42A5F5)    // blue
    ProviderType.openAI -> Color(0xFF4CAF50)    // green
    ProviderType.openRouter -> Color(0xFF00BCD4) // cyan
    ProviderType.xAI -> Color(0xFFFF7043)        // orange — Grok brand
    ProviderType.kimiCode -> Color(0xFF5C6BC0)   // indigo — Kimi accent
    null -> Color(0xFF8E8E93)                    // gray
}
