package io.github.nanomuse.ui.avatar

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.agent.SoulStore
import io.github.nanomuse.avatar.AvatarStore
import io.github.nanomuse.avatar.AvatarStudio
import io.github.nanomuse.avatar.ImageGen
import io.github.nanomuse.ui.home.MuseTones
import io.github.nanomuse.ui.home.avatarDiscColor
import io.github.nanomuse.ui.sysfiles.MuseTopBar

const val ROUTE_AVATAR_STUDIO = "nanomuse/avatar"

/**
 * "Appearance": the page behind a tap on the face. The face as it is now, one sentence and a
 * style to describe a new one, four candidates to pick from, and the moods being posed. Name
 * and voice stay on the Soul page, one tap away.
 */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun AvatarStudioScreen(onBack: () -> Unit, onOpenSoul: () -> Unit, onOpenMediaModels: () -> Unit = {}) {
    val context = LocalContext.current
    val current by AvatarStore.current.collectAsState()
    val slots by AvatarStudio.slots.collectAsState()
    val selected by AvatarStudio.selected.collectAsState()
    val progress by AvatarStudio.moodProgress.collectAsState()
    val error by AvatarStudio.error.collectAsState()
    val savedDescription by AvatarStudio.description.collectAsState()
    val savedStyle by AvatarStudio.style.collectAsState()
    val soul by SoulStore.cachedMetadata.collectAsState()
    val name = soul.name.trim().ifEmpty { stringResource(R.string.app_name) }

    var description by remember(savedDescription) { mutableStateOf(savedDescription) }
    var style by remember(savedStyle) { mutableStateOf(savedStyle) }
    var menu by remember { mutableStateOf(false) }
    var previewMood by remember { mutableStateOf(AgentMood.IDLE) }
    val generating = slots.any { it is AvatarStudio.Slot.Loading }
    // Read each time: the media page may have changed it while this screen was below it.
    val endpoint = ImageGen.endpoint(context)

    // The preview face cycles through its moods so the user sees what they got.
    LaunchedEffect(current?.createdAt) {
        previewMood = AgentMood.IDLE
        val order = listOf(AgentMood.IDLE, AgentMood.WORKING, AgentMood.WAITING, AgentMood.HAPPY, AgentMood.ERROR)
        var i = 0
        while (true) {
            kotlinx.coroutines.delay(if (previewMood == AgentMood.IDLE) 2600L else 2000L)
            i = (i + 1) % order.size
            previewMood = order[i]
        }
    }

    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        MuseTopBar(
            title = stringResource(R.string.nm_avatar_title),
            onBack = onBack,
            trailing = {
                Box {
                    Surface(onClick = { menu = true }, shape = CircleShape, color = MuseTones.surface, border = BorderStroke(1.dp, MuseTones.hairline)) {
                        Box(Modifier.size(44.dp), contentAlignment = Alignment.Center) {
                            Icon(Icons.Filled.MoreHoriz, contentDescription = null, tint = MaterialTheme.colorScheme.onSurface)
                        }
                    }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text(stringResource(R.string.nm_avatar_menu_soul)) }, onClick = { menu = false; onOpenSoul() })
                        DropdownMenuItem(text = { Text(stringResource(R.string.nm_avatar_menu_model)) }, onClick = { menu = false; onOpenMediaModels() })
                        if (current != null) {
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.nm_avatar_menu_regenerate_moods)) },
                                onClick = { menu = false; AvatarStudio.generateMoods(context, force = true) },
                            )
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.nm_avatar_menu_reset), color = MaterialTheme.colorScheme.error) },
                                onClick = { menu = false; AvatarStudio.reset(context) },
                            )
                        }
                    }
                }
            },
        )
        LazyColumn(Modifier.fillMaxSize(), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 32.dp)) {
            item(key = "face") {
                Column(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    val pop = remember { Animatable(1f) }
                    LaunchedEffect(current?.createdAt) {
                        if (current != null) {
                            pop.snapTo(0.6f)
                            pop.animateTo(1f, spring(dampingRatio = Spring.DampingRatioMediumBouncy, stiffness = Spring.StiffnessLow))
                        }
                    }
                    Box(
                        Modifier.size(148.dp).scale(pop.value).clip(CircleShape).background(avatarDiscColor()),
                        contentAlignment = Alignment.Center,
                    ) {
                        AgentAvatar(mood = previewMood, size = if (current != null) 148.dp else 128.dp)
                    }
                    Spacer(Modifier.height(12.dp))
                    Text(name, fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                    Spacer(Modifier.height(4.dp))
                    val moodLabel = when (previewMood) {
                        AgentMood.IDLE -> R.string.nm_avatar_mood_idle
                        AgentMood.WORKING -> R.string.nm_avatar_mood_working
                        AgentMood.WAITING -> R.string.nm_avatar_mood_waiting
                        AgentMood.HAPPY -> R.string.nm_avatar_mood_happy
                        AgentMood.ERROR -> R.string.nm_avatar_mood_error
                    }
                    Text(
                        stringResource(moodLabel),
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    val p = progress
                    if (p != null) {
                        Spacer(Modifier.height(10.dp))
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (p.running) {
                                CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp, color = MuseTones.action)
                                Spacer(Modifier.width(8.dp))
                                Text(stringResource(R.string.nm_avatar_moods_progress, p.done, p.total), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            } else {
                                Text(
                                    if (p.failed.isEmpty()) stringResource(R.string.nm_avatar_moods_done)
                                    else stringResource(R.string.nm_avatar_moods_partial, p.total - p.failed.size, p.total),
                                    fontSize = 13.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                if (p.failed.isNotEmpty()) {
                                    TextButton(onClick = { AvatarStudio.generateMoods(context) }) { Text(stringResource(R.string.nm_avatar_retry), fontSize = 13.sp) }
                                }
                            }
                        }
                    }
                }
            }
            item(key = "describe") {
                Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
                    Text(stringResource(R.string.nm_avatar_describe_title), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                    Spacer(Modifier.height(4.dp))
                    Text(stringResource(R.string.nm_avatar_describe_body), fontSize = 13.sp, lineHeight = 18.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.height(12.dp))
                    OutlinedTextField(
                        value = description,
                        onValueChange = { description = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 2,
                        maxLines = 4,
                        placeholder = { Text(stringResource(R.string.nm_avatar_default_description), color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.7f)) },
                        shape = RoundedCornerShape(16.dp),
                        colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, unfocusedBorderColor = MuseTones.hairline),
                    )
                    Spacer(Modifier.height(12.dp))
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        items(AvatarStudio.Style.entries.size) { i ->
                            val s = AvatarStudio.Style.entries[i]
                            val on = s == style
                            Surface(
                                onClick = { style = s },
                                shape = CircleShape,
                                color = if (on) MaterialTheme.colorScheme.onSurface else MuseTones.fill,
                                contentColor = if (on) MaterialTheme.colorScheme.surface else MaterialTheme.colorScheme.onSurface,
                            ) {
                                Text(stringResource(s.label), fontSize = 13.sp, fontWeight = FontWeight.Medium, modifier = Modifier.padding(horizontal = 14.dp, vertical = 8.dp))
                            }
                        }
                    }
                    Spacer(Modifier.height(14.dp))
                    Button(
                        onClick = { AvatarStudio.generateCandidates(context, description, style) },
                        enabled = !generating,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        shape = CircleShape,
                        colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White, disabledContainerColor = MuseTones.action.copy(alpha = 0.5f), disabledContentColor = Color.White),
                    ) {
                        if (generating) {
                            CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Color.White)
                            Spacer(Modifier.width(10.dp))
                            Text(stringResource(R.string.nm_avatar_generating), fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                        } else {
                            Icon(Icons.Outlined.AutoAwesome, contentDescription = null, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(8.dp))
                            Text(
                                stringResource(if (slots.any { it is AvatarStudio.Slot.Ready }) R.string.nm_avatar_generate_again else R.string.nm_avatar_generate),
                                fontSize = 15.sp,
                                fontWeight = FontWeight.SemiBold,
                            )
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(Modifier.fillMaxWidth().clickable { onOpenMediaModels() }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            if (endpoint == null) stringResource(R.string.nm_avatar_no_provider)
                            else stringResource(R.string.nm_avatar_using, endpoint.label, endpoint.model.ifBlank { "—" }),
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.weight(1f),
                        )
                        Text(stringResource(R.string.nm_avatar_change), fontSize = 12.sp, color = MuseTones.action, fontWeight = FontWeight.Medium)
                    }
                    if (error != null) {
                        Spacer(Modifier.height(6.dp))
                        Text(error.orEmpty(), fontSize = 13.sp, color = MaterialTheme.colorScheme.error)
                    }
                }
            }
            if (slots.any { it !is AvatarStudio.Slot.Empty }) {
                item(key = "candidates") {
                    Column(Modifier.padding(horizontal = 20.dp)) {
                        HorizontalDivider(color = MuseTones.hairline)
                        Spacer(Modifier.height(14.dp))
                        Text(stringResource(R.string.nm_avatar_pick_title), fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
                        Spacer(Modifier.height(4.dp))
                        Text(stringResource(R.string.nm_avatar_pick_body), fontSize = 13.sp, lineHeight = 18.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.height(12.dp))
                        for (row in 0 until 2) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                for (col in 0 until 2) {
                                    val i = row * 2 + col
                                    CandidateTile(
                                        slot = slots[i],
                                        selected = selected == i,
                                        onClick = {
                                            when (slots[i]) {
                                                is AvatarStudio.Slot.Ready -> AvatarStudio.select(if (selected == i) null else i)
                                                is AvatarStudio.Slot.Failed -> AvatarStudio.retrySlot(context, i)
                                                else -> {}
                                            }
                                        },
                                        modifier = Modifier.weight(1f),
                                    )
                                }
                            }
                            if (row == 0) Spacer(Modifier.height(12.dp))
                        }
                        AnimatedVisibility(visible = selected != null, enter = fadeIn(tween(180)) + scaleIn(initialScale = 0.96f), exit = fadeOut(tween(120))) {
                            Column {
                                Spacer(Modifier.height(14.dp))
                                Button(
                                    onClick = { selected?.let { AvatarStudio.adopt(context, it) } },
                                    modifier = Modifier.fillMaxWidth().height(48.dp),
                                    shape = CircleShape,
                                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                                ) {
                                    Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(18.dp))
                                    Spacer(Modifier.width(8.dp))
                                    Text(stringResource(R.string.nm_avatar_use_this), fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                                }
                                Spacer(Modifier.height(6.dp))
                                Text(
                                    stringResource(R.string.nm_avatar_use_this_hint),
                                    fontSize = 12.sp,
                                    lineHeight = 16.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    textAlign = TextAlign.Center,
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                        }
                    }
                }
            }
            item(key = "footer") {
                Text(
                    stringResource(R.string.nm_avatar_footer),
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 18.dp),
                )
            }
        }
    }

}

@Composable
private fun CandidateTile(slot: AvatarStudio.Slot, selected: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val shape = RoundedCornerShape(20.dp)
    val shimmer = rememberInfiniteTransition(label = "shimmer")
    val a by shimmer.animateFloat(0.45f, 1f, infiniteRepeatable(tween(900), RepeatMode.Reverse), label = "shimmerAlpha")
    Box(
        modifier
            .aspectRatio(1f)
            .clip(shape)
            .background(MuseTones.fill)
            .then(if (selected) Modifier.border(3.dp, MuseTones.action, shape) else Modifier)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        when (slot) {
            is AvatarStudio.Slot.Ready -> {
                Image(
                    bitmap = slot.bitmap.asImageBitmap(),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
                if (selected) {
                    Box(Modifier.align(Alignment.TopEnd).padding(10.dp).size(28.dp).background(MuseTones.action, CircleShape), contentAlignment = Alignment.Center) {
                        Icon(Icons.Filled.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
                    }
                }
            }
            AvatarStudio.Slot.Loading -> Box(Modifier.fillMaxSize().alpha(a).background(MuseTones.fill), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            is AvatarStudio.Slot.Failed -> Column(Modifier.padding(12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(6.dp))
                Text(slot.message, fontSize = 11.sp, lineHeight = 14.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center, maxLines = 3)
                Spacer(Modifier.height(4.dp))
                Text(stringResource(R.string.nm_avatar_retry), fontSize = 12.sp, fontWeight = FontWeight.Medium, color = MuseTones.action)
            }
            AvatarStudio.Slot.Empty -> {}
        }
    }
}
