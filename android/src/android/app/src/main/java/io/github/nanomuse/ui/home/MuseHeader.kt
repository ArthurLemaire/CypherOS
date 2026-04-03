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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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
import io.github.nanomuse.ui.avatar.AgentAvatarDisc
import io.github.nanomuse.ui.avatar.AgentMood
import io.github.nanomuse.ui.avatar.rememberAvatarSize

/** The soft disc the face sits on — Muse draws its character on a pale circle. */
@Composable
fun avatarDiscColor(): Color = MuseTones.disc

/**
 * Muse's page header, shared by the Ideas / Goals / Library tabs and, in a taller form, by the
 * main chat: the face centred on a disc (its size is the Appearance setting), the name in a
 * white pill hanging off its chin with the status as the pill's second line; a round button in
 * each top corner. With the face hidden, only the pill remains.
 */
@Composable
fun MuseHeader(
    mood: AgentMood,
    name: String,
    statusLine: String? = null,
    statusColor: Color = ChatColors.secondaryText,
    onAvatarClick: (() -> Unit)? = null,
    onNameClick: (() -> Unit)? = null,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val size by rememberAvatarSize()
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
            val disc = size.disc
            if (disc != null) {
                AgentAvatarDisc(
                    mood = mood,
                    discSize = disc,
                    onClick = onAvatarClick,
                )
            } else {
                Spacer(Modifier.height(10.dp))
            }
            // Two lines are always reserved so the bar does not jump when a status appears.
            Box(
                modifier = Modifier.height(PILL_AREA_HEIGHT).then(pullUp(if (disc != null) PILL_OVERLAP else 0.dp)),
                contentAlignment = Alignment.TopCenter,
            ) {
                MuseNamePill(
                    name = name,
                    statusLine = statusLine,
                    statusColor = statusColor,
                    onClick = onNameClick ?: onAvatarClick,
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

/** How far the name pill rides up over the chin of the face. */
val PILL_OVERLAP: Dp = 10.dp

/** Height reserved under the face for the pill (name + status line). */
val PILL_AREA_HEIGHT: Dp = 44.dp

/**
 * Muse's name tag: a small white tag, the name in regular weight (Muse's is 14sp on a 22dp tag,
 * not bold), a faint shadow. What the agent is doing right now ("Generating options",
 * "正在等待批准") is a second, smaller grey line inside the same tag.
 */
@Composable
fun MuseNamePill(
    name: String,
    statusLine: String? = null,
    statusColor: Color = ChatColors.secondaryText,
    onClick: (() -> Unit)? = null,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(14.dp)
    val base = modifier
        .shadow(2.dp, shape, clip = false, ambientColor = Color.Black.copy(alpha = 0.16f), spotColor = Color.Black.copy(alpha = 0.16f))
        .clip(shape)
        .background(MuseTones.surface)
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = (if (onClick != null) base.clickable(onClick = onClick) else base)
            .padding(horizontal = 12.dp, vertical = 4.dp),
    ) {
        Text(
            text = name,
            fontSize = 14.sp,
            lineHeight = 18.sp,
            fontWeight = FontWeight.Normal,
            color = MaterialTheme.colorScheme.onSurface,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = TextStyle(platformStyle = PlatformTextStyle(includeFontPadding = false)),
        )
        if (statusLine != null) {
            Spacer(Modifier.height(2.dp))
            Text(
                text = statusLine,
                fontSize = 11.5.sp,
                lineHeight = 14.sp,
                fontWeight = FontWeight.Normal,
                color = statusColor,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = TextStyle(platformStyle = PlatformTextStyle(includeFontPadding = false)),
            )
        }
    }
}

/** Muse's corner buttons: a white disc, one glyph. */
@Composable
fun MuseRoundButton(
    icon: ImageVector,
    contentDescription: String?,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    badge: Boolean = false,
) {
    Box(modifier = modifier) {
        // Muse's disc has no rule around it — a soft shadow lifts it off the page.
        Surface(
            onClick = onClick,
            shape = CircleShape,
            color = MuseTones.surface,
            border = if (MuseTones.isDark) BorderStroke(1.dp, MuseTones.hairline) else null,
            shadowElevation = 2.dp,
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
