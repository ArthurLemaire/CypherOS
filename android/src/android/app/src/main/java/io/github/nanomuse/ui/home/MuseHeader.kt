package io.github.nanomuse.ui.home

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.ui.avatar.AgentAvatar
import io.github.nanomuse.ui.avatar.AgentMood

/** The soft disc the face sits on — Muse draws its character on a pale circle. */
@Composable
fun avatarDiscColor(): Color = MuseTones.disc

/**
 * Muse's page header, shared by the Ideas / Goals / Library tabs and, in a taller form, by the
 * main chat: the face centred on a disc, the name in a white pill hanging off its chin, and an
 * optional status line beneath; a round button in each top corner.
 */
@Composable
fun MuseHeader(
    mood: AgentMood,
    name: String,
    statusLine: String? = null,
    statusColor: Color = ChatColors.secondaryText,
    avatarSize: Dp = 92.dp,
    onAvatarClick: (() -> Unit)? = null,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .padding(top = 6.dp, bottom = 4.dp),
    ) {
        Column(
            modifier = Modifier.align(Alignment.TopCenter),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(contentAlignment = Alignment.BottomCenter) {
                Box(
                    modifier = Modifier
                        .padding(bottom = 12.dp)
                        .size(avatarSize)
                        .clip(CircleShape)
                        .background(avatarDiscColor()),
                    contentAlignment = Alignment.Center,
                ) {
                    AgentAvatar(
                        mood = mood,
                        size = avatarSize * 0.86f,
                        onClick = onAvatarClick,
                    )
                }
                MuseNamePill(name = name, onClick = onAvatarClick)
            }
            if (statusLine != null) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = statusLine,
                    fontSize = 12.sp,
                    lineHeight = 14.sp,
                    fontWeight = FontWeight.Medium,
                    color = statusColor,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    style = TextStyle(platformStyle = PlatformTextStyle(includeFontPadding = false)),
                )
            }
        }
        if (leading != null) {
            Box(Modifier.align(Alignment.TopStart).padding(start = 16.dp, top = 6.dp)) { leading() }
        }
        if (trailing != null) {
            Box(Modifier.align(Alignment.TopEnd).padding(end = 16.dp, top = 6.dp)) { trailing() }
        }
    }
}

@Composable
fun MuseNamePill(name: String, onClick: (() -> Unit)? = null, modifier: Modifier = Modifier) {
    val base = modifier
        .shadow(3.dp, CircleShape, clip = false, ambientColor = Color.Black.copy(alpha = 0.18f))
        .clip(CircleShape)
        .background(MuseTones.surface)
    Text(
        text = name,
        fontSize = 15.sp,
        lineHeight = 18.sp,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSurface,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        style = TextStyle(platformStyle = PlatformTextStyle(includeFontPadding = false)),
        modifier = (if (onClick != null) base.clickable(onClick = onClick) else base)
            .padding(horizontal = 14.dp, vertical = 7.dp),
    )
}

/** Muse's corner buttons: a white disc with a hairline, one glyph. */
@Composable
fun MuseRoundButton(
    icon: ImageVector,
    contentDescription: String?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    badge: Boolean = false,
) {
    Box(modifier = modifier) {
        Surface(
            onClick = onClick,
            shape = CircleShape,
            color = MuseTones.surface,
            border = BorderStroke(1.dp, MuseTones.hairline),
            shadowElevation = 1.dp,
            modifier = Modifier.size(44.dp),
        ) {
            Box(contentAlignment = Alignment.Center) {
                Icon(
                    imageVector = icon,
                    contentDescription = contentDescription,
                    tint = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.size(22.dp),
                )
            }
        }
        if (badge) {
            Box(
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = 2.dp, end = 2.dp)
                    .size(9.dp)
                    .clip(CircleShape)
                    .background(MaterialTheme.colorScheme.primary)
                    .border(1.5.dp, MuseTones.surface, CircleShape),
            )
        }
    }
}

/** Muse's big left-aligned page title ("目标", "点子"). */
@Composable
fun MusePageTitle(text: String, modifier: Modifier = Modifier) {
    Text(
        text = text,
        fontSize = 26.sp,
        lineHeight = 32.sp,
        fontWeight = FontWeight.Bold,
        color = MaterialTheme.colorScheme.onSurface,
        modifier = modifier.padding(horizontal = 20.dp, vertical = 6.dp),
    )
}
