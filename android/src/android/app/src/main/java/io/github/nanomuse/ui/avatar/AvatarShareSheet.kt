package io.github.nanomuse.ui.avatar

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.agent.SoulStore
import io.github.nanomuse.avatar.AvatarShare
import io.github.nanomuse.avatar.AvatarStore
import io.github.nanomuse.ui.home.MuseTones
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Muse's "分享我的虚拟形象" sheet: five pastel cards, each with the character in one of its
 * poses and a speech bubble introducing it; pick one, share it through the system sheet.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AvatarShareSheet(onDismiss: () -> Unit) {
    val context = LocalContext.current
    val soul by SoulStore.cachedMetadata.collectAsState()
    val name = soul.name.trim().ifEmpty { stringResource(R.string.app_name) }
    val current by AvatarStore.current.collectAsState()
    var selected by remember { mutableIntStateOf(0) }
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)

    // Small previews of the five cards; re-rendered when the face or the name changes.
    val previews by produceState<List<Bitmap>?>(initialValue = null, current, name) {
        value = withContext(Dispatchers.Default) {
            AvatarShare.palettes.map { AvatarShare.render(context, it, name, scale = 0.3f) }
        }
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = state,
        containerColor = MuseTones.canvas,
    ) {
        Column(Modifier.padding(bottom = 28.dp)) {
            Text(
                text = stringResource(R.string.nm_avatar_share_title),
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(horizontal = 20.dp),
            )
            Spacer(Modifier.height(4.dp))
            Text(
                text = stringResource(R.string.nm_avatar_share_subtitle),
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp),
            )
            Spacer(Modifier.height(16.dp))
            val cards = previews
            if (cards == null) {
                Box(Modifier.fillMaxWidth().height(300.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(modifier = Modifier.size(28.dp), strokeWidth = 2.5.dp)
                }
            } else {
                LazyRow(
                    contentPadding = PaddingValues(horizontal = 20.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    itemsIndexed(cards) { i, bmp ->
                        val shape = RoundedCornerShape(18.dp)
                        Box(
                            modifier = Modifier
                                .width(220.dp)
                                .aspectRatio(AvatarShare.WIDTH / AvatarShare.HEIGHT.toFloat())
                                .clip(shape)
                                .then(if (i == selected) Modifier.border(2.5.dp, MuseTones.action, shape) else Modifier)
                                .clickable { selected = i },
                        ) {
                            Image(
                                bitmap = bmp.asImageBitmap(),
                                contentDescription = null,
                                contentScale = ContentScale.FillBounds,
                                modifier = Modifier.fillMaxSize(),
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(20.dp))
            Row(Modifier.padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                Button(
                    onClick = { AvatarShare.share(context, AvatarShare.palettes[selected], name) },
                    enabled = previews != null,
                    shape = CircleShape,
                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                ) {
                    Icon(Icons.Outlined.Share, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.nm_avatar_share_system), fontSize = 15.sp, fontWeight = FontWeight.Medium)
                }
            }
        }
    }
}
