package io.github.nanomuse.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.HourglassBottom
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.agent.SoulStore
import com.openminis.app.ui.chat.ChatViewModel
import io.github.nanomuse.ui.home.MuseTones

/**
 * When a long task reaches the step ceiling, Muse-style: a card asks whether to keep going
 * rather than an error telling the user the model "kept calling tools". Continue resumes from
 * where it stopped; Stop leaves the upstream Resume banner available.
 */
@Composable
fun ContinueAskHost(viewModel: ChatViewModel) {
    val steps by viewModel.nmContinueAsk.collectAsState()
    AnimatedVisibility(
        visible = steps != null,
        enter = slideInVertically(tween(220)) { it / 2 } + fadeIn(tween(220)),
        exit = slideOutVertically(tween(160)) { it / 2 } + fadeOut(tween(160)),
    ) {
        val n = steps ?: 0
        val soul by SoulStore.cachedMetadata.collectAsState()
        val name = soul.name.trim().ifEmpty { stringResource(R.string.app_name) }
        Surface(
            shape = RoundedCornerShape(22.dp),
            color = MuseTones.surface,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 6.dp)
                .shadow(6.dp, RoundedCornerShape(22.dp), ambientColor = Color.Black.copy(alpha = 0.06f), spotColor = Color.Black.copy(alpha = 0.12f)),
        ) {
            Column(Modifier.padding(horizontal = 18.dp, vertical = 16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(40.dp).background(MuseTones.fill, CircleShape), contentAlignment = Alignment.Center) {
                        Icon(Icons.Outlined.HourglassBottom, contentDescription = null, tint = MaterialTheme.colorScheme.onSurface, modifier = Modifier.size(22.dp))
                    }
                    Spacer(Modifier.width(12.dp))
                    Text(
                        stringResource(R.string.nm_continue_title, n),
                        fontSize = 17.sp,
                        lineHeight = 22.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                Spacer(Modifier.height(10.dp))
                Text(
                    stringResource(R.string.nm_continue_body, name, n),
                    fontSize = 14.sp,
                    lineHeight = 20.sp,
                    color = MaterialTheme.colorScheme.onSurface.copy(alpha = 0.85f),
                )
                Spacer(Modifier.height(14.dp))
                Button(
                    onClick = { viewModel.nmContinue(keepGoing = true) },
                    modifier = Modifier.fillMaxWidth().height(46.dp),
                    shape = CircleShape,
                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                ) { Text(stringResource(R.string.nm_continue_yes), fontSize = 15.sp, fontWeight = FontWeight.SemiBold) }
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = { viewModel.nmContinue(keepGoing = false) },
                    modifier = Modifier.fillMaxWidth().height(44.dp),
                    shape = CircleShape,
                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.fill, contentColor = MaterialTheme.colorScheme.onSurface),
                    elevation = null,
                ) { Text(stringResource(R.string.nm_continue_no), fontSize = 15.sp, fontWeight = FontWeight.Medium) }
            }
        }
    }
}
