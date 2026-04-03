package io.github.nanomuse.ui.avatar

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
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
import io.github.nanomuse.avatar.AvatarFlow
import io.github.nanomuse.avatar.AvatarStore
import io.github.nanomuse.avatar.AvatarStudio
import io.github.nanomuse.ui.home.MuseTones
import org.json.JSONObject
import java.io.File

/**
 * The card Muse puts in the chat when you ask for a new face: four candidates in a 2×2 grid,
 * placeholders first, each picture as it lands. Tap one to make it the face; "again" for a
 * fresh set. Live state comes from [AvatarStudio] / [AvatarFlow].
 */
@Composable
fun AvatarOptionsCard(
    onPick: (Int) -> Unit,
    onAgain: () -> Unit,
    onDismiss: () -> Unit,
) {
    val context = LocalContext.current
    val slots by AvatarStudio.slots.collectAsState()
    val stage by AvatarFlow.stage.collectAsState()
    val description = (stage as? AvatarFlow.Stage.Choosing)?.description
        ?: (stage as? AvatarFlow.Stage.Finalizing)?.description ?: ""
    val loading = slots.any { it is AvatarStudio.Slot.Loading }
    val readyCount = slots.count { it is AvatarStudio.Slot.Ready }
    val allFailed = slots.isNotEmpty() && slots.all { it is AvatarStudio.Slot.Failed }

    ChatCardFrame {
        OptionsGrid(
            slots = slots,
            chosen = null,
            enabled = stage is AvatarFlow.Stage.Choosing,
            onPick = onPick,
            onRetry = { i -> AvatarStudio.retrySlot(context, i) },
        )
        Spacer(Modifier.height(10.dp))
        Text(
            text = when {
                allFailed -> (slots.first() as AvatarStudio.Slot.Failed).message.ifBlank { stringResource(R.string.nm_avatar_options_failed) }
                loading -> stringResource(R.string.nm_avatar_options_drawing, description)
                else -> stringResource(R.string.nm_avatar_options_pick_hint)
            },
            fontSize = 13.sp,
            lineHeight = 18.sp,
            color = if (allFailed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(2.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onAgain, enabled = !loading || readyCount > 0) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.nm_avatar_options_again), fontSize = 13.sp)
            }
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.nm_avatar_options_keep), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** The options card once the choice is made and persisted as a `nanomuse-avatar` fence. */
@Composable
fun AvatarOptionsFenceCard(json: JSONObject) {
    val chosen = json.optInt("chosen", -1)
    val files = json.optJSONArray("files")?.let { arr -> List(arr.length()) { arr.optString(it) } }.orEmpty()
    val slots = remember(files) {
        List(AvatarStudio.CANDIDATES) { i ->
            val path = files.getOrNull(i).orEmpty()
            val f = File(path)
            val bmp = if (path.isNotEmpty() && f.exists()) AvatarStore.decodeBitmap(f) else null
            if (bmp != null) AvatarStudio.Slot.Ready(bmp, f) else AvatarStudio.Slot.Empty
        }
    }
    ChatCardFrame {
        OptionsGrid(slots = slots, chosen = chosen, enabled = false, onPick = {}, onRetry = {})
    }
}

@Composable
private fun OptionsGrid(
    slots: List<AvatarStudio.Slot>,
    chosen: Int?,
    enabled: Boolean,
    onPick: (Int) -> Unit,
    onRetry: (Int) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        for (row in 0 until 2) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (col in 0 until 2) {
                    val i = row * 2 + col
                    OptionTile(
                        slot = slots.getOrElse(i) { AvatarStudio.Slot.Empty },
                        index = i,
                        state = when {
                            chosen == null -> TileState.OPEN
                            chosen == i -> TileState.CHOSEN
                            else -> TileState.DIMMED
                        },
                        enabled = enabled,
                        onClick = { onPick(i) },
                        onRetry = { onRetry(i) },
                        modifier = Modifier.weight(1f).aspectRatio(1f),
                    )
                }
            }
        }
    }
}

private enum class TileState { OPEN, CHOSEN, DIMMED }

@Composable
private fun OptionTile(
    slot: AvatarStudio.Slot,
    index: Int,
    state: TileState,
    enabled: Boolean,
    onClick: () -> Unit,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(18.dp)
    val ready = slot is AvatarStudio.Slot.Ready
    val base = modifier
        .clip(shape)
        .background(if (state == TileState.CHOSEN) Color.White else MuseTones.disc)
        .then(if (state == TileState.CHOSEN) Modifier.border(2.dp, MuseTones.action, shape) else Modifier)
        .alpha(if (state == TileState.DIMMED) 0.45f else 1f)
    Box(
        modifier = when {
            slot is AvatarStudio.Slot.Failed -> base.clickable(onClick = onRetry)
            ready && enabled -> base.clickable(onClick = onClick)
            else -> base
        },
        contentAlignment = Alignment.Center,
    ) {
        when (slot) {
            is AvatarStudio.Slot.Ready -> Image(
                bitmap = slot.bitmap.asImageBitmap(),
                contentDescription = stringResource(R.string.nm_avatar_option_n, index + 1),
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
            )
            is AvatarStudio.Slot.Loading -> Placeholder()
            is AvatarStudio.Slot.Failed -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(4.dp))
                Text(stringResource(R.string.nm_avatar_option_retry), fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            AvatarStudio.Slot.Empty -> Unit
        }
        // The number, for "the second one".
        Box(
            modifier = Modifier
                .align(Alignment.BottomStart)
                .padding(8.dp)
                .size(22.dp)
                .clip(CircleShape)
                .background(Color.Black.copy(alpha = 0.35f)),
            contentAlignment = Alignment.Center,
        ) {
            Text("${index + 1}", fontSize = 12.sp, color = Color.White, fontWeight = FontWeight.Medium)
        }
    }
}

/** A soft breathing placeholder while a picture is on its way. */
@Composable
private fun Placeholder() {
    val t = rememberInfiniteTransition(label = "avatar-placeholder")
    val a by t.animateFloat(
        initialValue = 0.35f,
        targetValue = 0.9f,
        animationSpec = infiniteRepeatable(tween(900), RepeatMode.Reverse),
        label = "alpha",
    )
    Box(
        modifier = Modifier
            .size(44.dp)
            .alpha(a)
            .clip(CircleShape)
            .background(MuseTones.surface),
    )
}

/**
 * Muse's "my new look is here" card: the new face big, one line about it, a Share button
 * that opens the card picker.
 */
@Composable
fun AvatarShareCard(description: String, onDismiss: () -> Unit) {
    val set by AvatarStore.current.collectAsState()
    var sheet by remember { mutableStateOf(false) }
    ChatCardFrame {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .aspectRatio(1.35f)
                .clip(RoundedCornerShape(18.dp))
                .background(MuseTones.disc),
            contentAlignment = Alignment.Center,
        ) {
            val bmp = set?.base
            if (bmp != null) {
                Image(bitmap = bmp, contentDescription = null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize().padding(12.dp))
            } else {
                AgentAvatar(mood = AgentMood.HAPPY, size = 140.dp)
            }
        }
        Spacer(Modifier.height(12.dp))
        Text(
            text = stringResource(R.string.nm_avatar_share_text, description),
            fontSize = 15.sp,
            lineHeight = 21.sp,
            color = MaterialTheme.colorScheme.onSurface,
        )
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Button(
                onClick = { sheet = true },
                shape = CircleShape,
                colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
            ) {
                Text(stringResource(R.string.nm_avatar_share_button), fontSize = 14.sp, fontWeight = FontWeight.Medium)
            }
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.nm_avatar_share_later), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
    if (sheet) AvatarShareSheet(onDismiss = { sheet = false })
}

@Composable
private fun ChatCardFrame(content: @Composable () -> Unit) {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = MuseTones.surface,
        border = BorderStroke(1.dp, MuseTones.hairline),
        modifier = Modifier
            .fillMaxWidth()
            .widthIn(max = 360.dp)
            .padding(vertical = 4.dp),
    ) {
        Column(Modifier.padding(12.dp)) { content() }
    }
}
