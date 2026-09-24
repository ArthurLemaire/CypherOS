package io.github.nanomuse.ui.onboarding

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.onboarding.NamingCardState

/**
 * Muse's name chooser: a grey card with the suggestions as full-width rows and a dashed
 * "something else…" row that hands over to the composer. After a pick the chosen row gets a
 * check and the others fade; the card stays in the transcript as the record of the choice.
 */
@Composable
fun NamingCard(
    state: NamingCardState,
    onPick: (String) -> Unit,
    onCustom: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val chosen = state.chosen
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(top = 6.dp, bottom = 10.dp)
            .clip(RoundedCornerShape(18.dp))
            .background(ChatColors.toolBg)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            text = stringResource(R.string.nm_naming_title),
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
            color = ChatColors.secondaryText,
            modifier = Modifier.padding(start = 4.dp, bottom = 2.dp),
        )
        val options = if (chosen != null && chosen !in state.suggestions) state.suggestions + chosen else state.suggestions
        options.forEach { name ->
            NameRow(
                label = name,
                selected = chosen == name,
                dimmed = chosen != null && chosen != name,
                enabled = chosen == null,
                onClick = { onPick(name) },
            )
        }
        if (chosen == null) {
            CustomRow(onClick = onCustom)
        }
    }
}

@Composable
private fun NameRow(label: String, selected: Boolean, dimmed: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    val border = if (selected) BorderStroke(1.5.dp, ChatColors.sendButton) else BorderStroke(1.dp, ChatColors.toolBorder)
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(ChatColors.background)
            .border(border, shape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 13.dp),
    ) {
        Text(
            text = label,
            fontSize = 15.sp,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
            color = if (dimmed) ChatColors.tertiaryText else ChatColors.primaryText,
            modifier = Modifier.weight(1f),
        )
        if (selected) {
            Icon(
                imageVector = Icons.Filled.CheckCircle,
                contentDescription = null,
                tint = ChatColors.sendButton,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

@Composable
private fun CustomRow(onClick: () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    val dashColor = ChatColors.tertiaryText.copy(alpha = 0.6f)
    val density = LocalDensity.current
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .drawBehind {
                val stroke = Stroke(
                    width = with(density) { 1.dp.toPx() },
                    pathEffect = PathEffect.dashPathEffect(floatArrayOf(with(density) { 5.dp.toPx() }, with(density) { 4.dp.toPx() }), 0f),
                )
                val radius = with(density) { 12.dp.toPx() }
                drawRoundRect(
                    color = dashColor,
                    topLeft = Offset(stroke.width / 2, stroke.width / 2),
                    size = androidx.compose.ui.geometry.Size(size.width - stroke.width, size.height - stroke.width),
                    cornerRadius = androidx.compose.ui.geometry.CornerRadius(radius, radius),
                    style = stroke,
                )
            }
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 13.dp),
    ) {
        Text(
            text = stringResource(R.string.nm_naming_custom),
            fontSize = 15.sp,
            color = ChatColors.secondaryText,
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.size(20.dp))
    }
}
