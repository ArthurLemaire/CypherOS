package io.github.nanomuse.ui.library

import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.AudioFile
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.InsertDriveFile
import androidx.compose.material.icons.outlined.LibraryBooks
import androidx.compose.material.icons.outlined.PictureAsPdf
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material.icons.outlined.VideoFile
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.repeatOnLifecycle
import coil.compose.AsyncImage
import com.openminis.app.R
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.ui.sandbox.FileItem
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.library.LibraryEntry
import io.github.nanomuse.library.LibraryIndex
import io.github.nanomuse.library.LibraryKind
import io.github.nanomuse.ui.home.relativeDay

/**
 * Muse's Library: a two-way segmented control (artifacts / media) over what the agent made,
 * newest first, with Muse's empty states. Rows open the existing file preview; long-press
 * shares or jumps to the conversation the file came from.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun LibraryTab(
    header: @Composable () -> Unit,
    chatRepository: ChatRepository,
    onPreview: (FileItem) -> Unit,
    onOpenSession: (String) -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var segment by rememberSaveable { mutableStateOf(0) }
    var entries by remember { mutableStateOf<List<LibraryEntry>?>(null) }

    // Rescan whenever the tab comes back to the foreground: the agent may have written
    // something while the user was in the chat.
    LaunchedEffect(lifecycleOwner) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            entries = LibraryIndex.scan(context, chatRepository)
        }
    }

    val shown = remember(entries, segment) {
        val kind = if (segment == 0) LibraryKind.ARTIFACT else LibraryKind.MEDIA
        entries.orEmpty().filter { it.kind == kind }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(ChatColors.background),
        contentPadding = PaddingValues(bottom = 24.dp),
    ) {
        item(key = "header") { header() }
        item(key = "segments") {
            Segmented(
                labels = listOf(stringResource(R.string.nm_library_artifacts), stringResource(R.string.nm_library_media)),
                selected = segment,
                onSelect = { segment = it },
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            )
        }
        if (entries != null && shown.isEmpty()) {
            item(key = "empty") {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(top = 36.dp, start = 32.dp, end = 32.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Icon(
                        Icons.Outlined.LibraryBooks,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(34.dp),
                    )
                    Spacer(Modifier.height(14.dp))
                    Text(
                        stringResource(if (segment == 0) R.string.nm_library_empty_artifacts_title else R.string.nm_library_empty_media_title),
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        stringResource(if (segment == 0) R.string.nm_library_empty_artifacts_body else R.string.nm_library_empty_media_body),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        textAlign = TextAlign.Center,
                    )
                }
            }
        } else {
            items(shown, key = { it.item.file.absolutePath }) { entry ->
                LibraryRow(entry = entry, onClick = { onPreview(entry.item) }, onOpenSession = onOpenSession)
            }
        }
    }
}

/** Muse's pill-shaped two-way control: white track with a hairline, grey pill on the active side. */
@Composable
fun Segmented(labels: List<String>, selected: Int, onSelect: (Int) -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(48.dp)
            .clip(CircleShape)
            .border(BorderStroke(1.dp, io.github.nanomuse.ui.home.MuseTones.hairline), CircleShape)
            .background(io.github.nanomuse.ui.home.MuseTones.surface)
            .padding(4.dp),
    ) {
        labels.forEachIndexed { i, label ->
            val active = i == selected
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier
                    .weight(1f)
                    .fillMaxSize()
                    .clip(CircleShape)
                    .background(if (active) io.github.nanomuse.ui.home.MuseTones.fill else io.github.nanomuse.ui.home.MuseTones.surface)
                    .clickable { onSelect(i) },
            ) {
                Text(
                    label,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

private fun iconFor(item: FileItem): ImageVector = when (item.iconRes) {
    "text" -> Icons.Outlined.Description
    "code" -> Icons.Outlined.Code
    "terminal" -> Icons.Outlined.Terminal
    "image" -> Icons.Outlined.Image
    "audio" -> Icons.Outlined.AudioFile
    "video" -> Icons.Outlined.VideoFile
    "archive" -> Icons.Outlined.Archive
    "pdf" -> Icons.Outlined.PictureAsPdf
    else -> Icons.Outlined.InsertDriveFile
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun LibraryRow(entry: LibraryEntry, onClick: () -> Unit, onOpenSession: (String) -> Unit) {
    val context = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    val item = entry.item
    Box {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .combinedClickable(onClick = onClick, onLongClick = { menu = true })
                .padding(horizontal = 16.dp, vertical = 8.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(46.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(io.github.nanomuse.ui.home.MuseTones.fill),
                contentAlignment = Alignment.Center,
            ) {
                if (item.isImageFile) {
                    AsyncImage(model = item.file, contentDescription = null, modifier = Modifier.fillMaxSize(), contentScale = androidx.compose.ui.layout.ContentScale.Crop)
                } else {
                    Icon(iconFor(item), contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(22.dp))
                }
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    item.name,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    listOfNotNull(
                        relativeDay(item.modifiedMs),
                        android.text.format.Formatter.formatShortFileSize(LocalContext.current, item.size),
                        entry.sessionTitle ?: if (entry.sessionId == null) stringResource(R.string.nm_library_from_shared) else null,
                    ).joinToString(" · "),
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.nm_library_share)) },
                onClick = {
                    menu = false
                    runCatching {
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", item.file)
                        val send = Intent(Intent.ACTION_SEND).apply {
                            type = context.contentResolver.getType(uri) ?: "*/*"
                            putExtra(Intent.EXTRA_STREAM, uri)
                            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                        }
                        context.startActivity(Intent.createChooser(send, item.name))
                    }.onFailure { Toast.makeText(context, it.message ?: "share failed", Toast.LENGTH_SHORT).show() }
                },
            )
            entry.sessionId?.let { sid ->
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.nm_library_open_chat)) },
                    onClick = { menu = false; onOpenSession(sid) },
                )
            }
        }
    }
}
