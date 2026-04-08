package io.github.nanomuse.ui.sysfiles

import android.content.Intent
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.SwapVert
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.ui.markdown.MarkdownText
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.sysfiles.MemoryImport
import io.github.nanomuse.sysfiles.SystemFiles
import io.github.nanomuse.ui.home.MuseRoundButton
import io.github.nanomuse.ui.home.MuseTones

const val ROUTE_SYSTEM_FILES = "nanomuse/system_files"
const val ROUTE_SYSTEM_FILE = "nanomuse/system_file/{key}"
const val ROUTE_MEMORY_IMPORT = "nanomuse/memory_import"
fun systemFileRoute(kind: SystemFiles) = "nanomuse/system_file/${kind.name}"

/** Muse's page chrome for these screens: round back button, centred title, a round action. */
@Composable
fun MuseTopBar(title: String, onBack: () -> Unit, trailing: (@Composable () -> Unit)? = null) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        MuseRoundButton(
            icon = Icons.AutoMirrored.Filled.ArrowBack,
            contentDescription = stringResource(R.string.nm_back),
            onClick = onBack,
            modifier = Modifier.align(Alignment.CenterStart),
        )
        Text(
            text = title,
            fontSize = 17.sp,
            fontWeight = FontWeight.SemiBold,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.align(Alignment.Center).padding(horizontal = 56.dp),
        )
        if (trailing != null) Box(Modifier.align(Alignment.CenterEnd)) { trailing() }
    }
}

// ── the list ────────────────────────────────────────────────────────────────

@Composable
fun SystemFilesScreen(onBack: () -> Unit, onOpen: (SystemFiles) -> Unit, onImport: () -> Unit, onOpenMemory: () -> Unit) {
    val context = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    var byRecent by remember { mutableStateOf(false) }
    var refresh by remember { mutableStateOf(0) }
    val entries = remember(byRecent, refresh) {
        val all = SystemFiles.entries.toList()
        if (byRecent) all.sortedByDescending { it.lastModified(context) ?: 0L } else all
    }
    Column(Modifier.fillMaxSize().background(ChatColors.background)) {
        MuseTopBar(
            title = stringResource(R.string.nm_sysfiles_title),
            onBack = onBack,
            trailing = {
                Box {
                    MuseRoundButton(icon = Icons.Filled.MoreHoriz, contentDescription = stringResource(R.string.nm_more), onClick = { menu = true })
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text(stringResource(R.string.nm_import_title)) }, onClick = { menu = false; onImport() })
                        DropdownMenuItem(text = { Text(stringResource(R.string.nm_sysfiles_open_memory)) }, onClick = { menu = false; onOpenMemory() })
                    }
                }
            },
        )
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).navigationBarsPadding()) {
            Row(
                Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 6.dp, bottom = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    stringResource(if (byRecent) R.string.nm_sysfiles_sort_recent else R.string.nm_sysfiles_sort_name),
                    fontSize = 14.sp,
                    color = ChatColors.secondaryText,
                    modifier = Modifier.weight(1f),
                )
                Surface(onClick = { byRecent = !byRecent }, shape = CircleShape, color = MuseTones.fill) {
                    Icon(
                        Icons.Outlined.SwapVert,
                        contentDescription = stringResource(R.string.nm_sysfiles_sort_toggle),
                        tint = MaterialTheme.colorScheme.onSurface,
                        modifier = Modifier.padding(8.dp).size(18.dp),
                    )
                }
            }
            entries.forEach { kind ->
                FileRow(
                    kind = kind,
                    subtitle = kind.subtitle(context),
                    onClick = { onOpen(kind) },
                    onCopied = { refresh++ },
                )
            }
            Spacer(Modifier.height(12.dp))
            Text(
                stringResource(R.string.nm_sysfiles_footer),
                fontSize = 13.sp,
                lineHeight = 18.sp,
                color = ChatColors.secondaryText,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
            )
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun FileRow(kind: SystemFiles, subtitle: String, onClick: () -> Unit, onCopied: () -> Unit) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    var menu by remember { mutableStateOf(false) }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(start = 16.dp, end = 4.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FileBadge(if (kind == SystemFiles.HEARTBEAT) "♥" else "MD")
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(kind.fileName, fontSize = 16.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface)
            Spacer(Modifier.height(2.dp))
            Text(subtitle, fontSize = 13.sp, color = ChatColors.secondaryText, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Box {
            Surface(onClick = { menu = true }, shape = CircleShape, color = Color.Transparent) {
                Icon(Icons.Filled.MoreVert, contentDescription = stringResource(R.string.nm_more), tint = ChatColors.secondaryText, modifier = Modifier.padding(10.dp).size(20.dp))
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.nm_sysfile_copy)) },
                    onClick = {
                        menu = false
                        clipboard.setText(AnnotatedString(kind.read(context)))
                        Toast.makeText(context, R.string.nm_sysfile_copied, Toast.LENGTH_SHORT).show()
                        onCopied()
                    },
                )
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.nm_sysfile_share)) },
                    onClick = {
                        menu = false
                        val send = Intent(Intent.ACTION_SEND).apply {
                            type = "text/plain"
                            putExtra(Intent.EXTRA_SUBJECT, kind.fileName)
                            putExtra(Intent.EXTRA_TEXT, kind.read(context))
                        }
                        context.startActivity(Intent.createChooser(send, kind.fileName))
                    },
                )
            }
        }
    }
}

@Composable
private fun FileBadge(label: String) {
    Box(
        modifier = Modifier
            .size(40.dp)
            .background(MuseTones.fill, RoundedCornerShape(10.dp)),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, fontSize = 10.sp, fontWeight = FontWeight.Bold, color = ChatColors.secondaryText, letterSpacing = 0.5.sp)
    }
}

// ── one file ────────────────────────────────────────────────────────────────

/** Muse's file page: "About this file" in an italic quote, then the rendered Markdown; a pencil turns it into an editor. */
@Composable
fun SystemFileScreen(kind: SystemFiles, onBack: () -> Unit, onOpenMemory: () -> Unit, onOpenRoutines: () -> Unit) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    var content by remember(kind) { mutableStateOf(kind.read(context)) }
    var editing by remember { mutableStateOf(false) }
    var draft by remember { mutableStateOf("") }
    var menu by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize().background(ChatColors.background)) {
        MuseTopBar(
            title = kind.fileName,
            onBack = { if (editing) editing = false else onBack() },
            trailing = {
                Surface(shape = CircleShape, color = MuseTones.surface, border = androidx.compose.foundation.BorderStroke(1.dp, MuseTones.hairline), shadowElevation = 1.dp) {
                    Row(Modifier.height(44.dp).padding(horizontal = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (kind.editable && !editing) {
                            Icon(
                                Icons.Outlined.Edit,
                                contentDescription = stringResource(R.string.nm_sysfile_edit),
                                tint = MaterialTheme.colorScheme.onSurface,
                                modifier = Modifier
                                    .clip(CircleShape)
                                    .clickable { draft = content; editing = true }
                                    .padding(8.dp)
                                    .size(20.dp),
                            )
                        }
                        Box {
                            Icon(
                                Icons.Filled.MoreHoriz,
                                contentDescription = stringResource(R.string.nm_more),
                                tint = MaterialTheme.colorScheme.onSurface,
                                modifier = Modifier.clip(CircleShape).clickable { menu = true }.padding(8.dp).size(20.dp),
                            )
                            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.nm_sysfile_copy)) },
                                    onClick = {
                                        menu = false
                                        clipboard.setText(AnnotatedString(content))
                                        Toast.makeText(context, R.string.nm_sysfile_copied, Toast.LENGTH_SHORT).show()
                                    },
                                )
                                if (kind == SystemFiles.MEMORY) {
                                    DropdownMenuItem(text = { Text(stringResource(R.string.nm_sysfiles_open_memory)) }, onClick = { menu = false; onOpenMemory() })
                                }
                                if (kind == SystemFiles.HEARTBEAT) {
                                    DropdownMenuItem(text = { Text(stringResource(R.string.nm_routine_all)) }, onClick = { menu = false; onOpenRoutines() })
                                }
                            }
                        }
                    }
                }
            },
        )
        if (editing) {
            val focus = remember { FocusRequester() }
            LaunchedEffect(Unit) { focus.requestFocus() }
            Column(Modifier.fillMaxSize().imePadding()) {
                BasicTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    textStyle = LocalTextStyle.current.copy(
                        fontFamily = FontFamily.Monospace,
                        fontSize = 14.sp,
                        lineHeight = 21.sp,
                        color = MaterialTheme.colorScheme.onSurface,
                    ),
                    cursorBrush = SolidColor(MuseTones.action),
                    decorationBox = { inner ->
                        Box {
                            if (draft.isEmpty()) {
                                Text(
                                    stringResource(R.string.nm_sysfile_edit_hint, kind.fileName),
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 14.sp,
                                    lineHeight = 21.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f),
                                )
                            }
                            inner()
                        }
                    },
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .verticalScroll(rememberScrollState())
                        .padding(horizontal = 20.dp, vertical = 12.dp)
                        .focusRequester(focus),
                )
                HorizontalDivider(color = MuseTones.hairline)
                Row(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 10.dp), horizontalArrangement = Arrangement.End) {
                    TextButton(onClick = { editing = false }) { Text(stringResource(R.string.nm_cancel), color = MaterialTheme.colorScheme.onSurface) }
                    Spacer(Modifier.width(8.dp))
                    Button(
                        onClick = {
                            kind.write(context, draft)
                            content = kind.read(context)
                            editing = false
                            Toast.makeText(context, R.string.nm_sysfile_saved, Toast.LENGTH_SHORT).show()
                        },
                        shape = CircleShape,
                        colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                    ) { Text(stringResource(R.string.nm_save), fontWeight = FontWeight.SemiBold) }
                }
            }
        } else {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp)
                    .navigationBarsPadding(),
            ) {
                Spacer(Modifier.height(6.dp))
                AboutQuote(stringResource(kind.about))
                Spacer(Modifier.height(18.dp))
                if (content.isBlank()) {
                    Text(
                        stringResource(if (kind.editable) R.string.nm_sysfile_empty_editable else R.string.nm_sysfile_empty),
                        fontSize = 15.sp,
                        color = ChatColors.secondaryText,
                    )
                } else {
                    MarkdownText(
                        markdown = content,
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.bodyMedium.copy(fontSize = 15.sp, lineHeight = 23.sp),
                    )
                }
                Spacer(Modifier.height(32.dp))
            }
        }
    }
}

/** Muse's "About this file." — italic, a hairline on the left, bold lead-in. */
@Composable
private fun AboutQuote(text: String) {
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Box(Modifier.width(3.dp).fillMaxHeight().background(MuseTones.hairline, CircleShape))
        Spacer(Modifier.width(14.dp))
        Text(
            text = buildAnnotatedAbout(stringResource(R.string.nm_sysfile_about_lead), text),
            fontSize = 14.sp,
            lineHeight = 21.sp,
            fontStyle = FontStyle.Italic,
            color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.8f),
            modifier = Modifier.weight(1f),
        )
    }
}

private fun buildAnnotatedAbout(lead: String, body: String): AnnotatedString = androidx.compose.ui.text.buildAnnotatedString {
    pushStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.Bold))
    append(lead)
    pop()
    append(" ")
    append(body)
}

// ── memory import ───────────────────────────────────────────────────────────

@Composable
fun MemoryImportScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    val prompt = stringResource(R.string.nm_import_prompt)
    var from by remember { mutableStateOf("") }
    var pasted by remember { mutableStateOf("") }

    Column(Modifier.fillMaxSize().background(ChatColors.background)) {
        MuseTopBar(title = stringResource(R.string.nm_import_title), onBack = onBack)
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .imePadding()
                .navigationBarsPadding()
                .padding(horizontal = 20.dp),
        ) {
            Text(stringResource(R.string.nm_import_intro), fontSize = 15.sp, lineHeight = 22.sp, color = MaterialTheme.colorScheme.onSurface)
            Spacer(Modifier.height(18.dp))
            StepLabel("1", stringResource(R.string.nm_import_step1))
            Spacer(Modifier.height(8.dp))
            Surface(shape = RoundedCornerShape(14.dp), color = MuseTones.fill, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text(prompt, fontSize = 14.sp, lineHeight = 21.sp, color = MaterialTheme.colorScheme.onSurface)
                    Spacer(Modifier.height(10.dp))
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        Surface(
                            onClick = {
                                clipboard.setText(AnnotatedString(prompt))
                                Toast.makeText(context, R.string.nm_sysfile_copied, Toast.LENGTH_SHORT).show()
                            },
                            shape = CircleShape,
                            color = MuseTones.surface,
                        ) {
                            Row(Modifier.padding(horizontal = 14.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Outlined.ContentCopy, contentDescription = null, modifier = Modifier.size(16.dp), tint = MaterialTheme.colorScheme.onSurface)
                                Spacer(Modifier.width(6.dp))
                                Text(stringResource(R.string.nm_import_copy_prompt), fontSize = 14.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface)
                            }
                        }
                    }
                }
            }
            Spacer(Modifier.height(20.dp))
            StepLabel("2", stringResource(R.string.nm_import_step2))
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = from,
                onValueChange = { from = it },
                singleLine = true,
                placeholder = { Text(stringResource(R.string.nm_import_from_hint)) },
                shape = RoundedCornerShape(14.dp),
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, unfocusedBorderColor = MuseTones.hairline),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(10.dp))
            OutlinedTextField(
                value = pasted,
                onValueChange = { pasted = it },
                placeholder = { Text(stringResource(R.string.nm_import_paste_hint)) },
                shape = RoundedCornerShape(14.dp),
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, unfocusedBorderColor = MuseTones.hairline),
                modifier = Modifier.fillMaxWidth().heightIn(min = 180.dp),
            )
            Spacer(Modifier.height(18.dp))
            Button(
                onClick = {
                    val ok = MemoryImport.append(context, pasted, from)
                    Toast.makeText(context, if (ok) R.string.nm_import_done else R.string.nm_import_empty, Toast.LENGTH_SHORT).show()
                    if (ok) onBack()
                },
                enabled = pasted.isNotBlank(),
                shape = CircleShape,
                colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                modifier = Modifier.fillMaxWidth().height(46.dp),
            ) { Text(stringResource(R.string.nm_import_append), fontSize = 15.sp, fontWeight = FontWeight.SemiBold) }
            Spacer(Modifier.height(10.dp))
            Text(stringResource(R.string.nm_import_footer), fontSize = 13.sp, lineHeight = 18.sp, color = ChatColors.secondaryText)
            Spacer(Modifier.height(32.dp))
        }
    }
}

@Composable
private fun StepLabel(n: String, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(22.dp).background(MuseTones.action, CircleShape), contentAlignment = Alignment.Center) {
            Text(n, fontSize = 12.sp, fontWeight = FontWeight.Bold, color = Color.White)
        }
        Spacer(Modifier.width(10.dp))
        Text(text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
    }
}
