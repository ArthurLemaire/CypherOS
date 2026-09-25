package io.github.nanomuse.ui.guard

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Payments
import androidx.compose.material.icons.outlined.WarningAmber
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.guard.GuardKind
import io.github.nanomuse.guard.RiskClass
import io.github.nanomuse.guard.RiskDecision
import io.github.nanomuse.guard.RiskGate
import io.github.nanomuse.guard.RiskRequest
import io.github.nanomuse.guard.RiskText
import io.github.nanomuse.identity.NanoMuseIdentity
import io.github.nanomuse.ui.home.MuseTones

/**
 * Muse's "Needs approval" card, sitting between the messages and the composer of the chat
 * the request came from. When the request belongs to another chat, a one-line banner points
 * there instead. Nothing here is state: it reads [RiskGate.pending] and writes a decision.
 */
@Composable
fun RiskApprovalHost(sessionId: String, onOpenSession: (String) -> Unit) {
    val pending by RiskGate.pending.collectAsState()
    val request = pending
    val mine = request != null && request.sessionId == sessionId
    AnimatedVisibility(
        visible = request != null,
        enter = slideInVertically(tween(220)) { it / 2 } + fadeIn(tween(220)),
        exit = slideOutVertically(tween(160)) { it / 2 } + fadeOut(tween(160)),
    ) {
        // Keep drawing the last request through the exit animation.
        val shown = request ?: return@AnimatedVisibility
        if (mine) RiskApprovalCard(shown) else ElsewhereBanner(shown, onOpenSession)
    }
}

/** Dims the message list behind the card; drawn inside the list's own Box so the composer stays bright. */
@Composable
fun RiskScrim(sessionId: String) {
    val pending by RiskGate.pending.collectAsState()
    val visible = pending?.sessionId == sessionId
    AnimatedVisibility(visible = visible, enter = fadeIn(tween(220)), exit = fadeOut(tween(160))) {
        Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.28f)).clickable(enabled = false) {})
    }
}

@Composable
private fun RiskApprovalCard(request: RiskRequest) {
    val context = LocalContext.current
    val name = NanoMuseIdentity.name(context)
    val queued by RiskGate.queued.collectAsState()
    val icon: ImageVector = when {
        request.assessment.warnings.isNotEmpty() -> Icons.Outlined.WarningAmber
        request.assessment.riskClass == RiskClass.DESTRUCTIVE -> Icons.Outlined.DeleteOutline
        request.assessment.riskClass == RiskClass.MONEY -> Icons.Outlined.Payments
        else -> Icons.AutoMirrored.Outlined.Send
    }
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 8.dp)
            .shadow(6.dp, RoundedCornerShape(22.dp), clip = false, ambientColor = Color.Black.copy(alpha = 0.12f)),
        shape = RoundedCornerShape(22.dp),
        color = MuseTones.surface,
    ) {
        Column(Modifier.padding(horizontal = 16.dp, vertical = 16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(40.dp).clip(CircleShape).background(MuseTones.fill),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.onSurface, modifier = Modifier.size(22.dp))
                }
                Spacer(Modifier.width(12.dp))
                Text(
                    RiskText.title(context, request, name),
                    fontSize = 17.sp,
                    lineHeight = 22.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
            }
            Spacer(Modifier.height(10.dp))
            Text(
                RiskText.description(context, request, name),
                fontSize = 14.sp,
                lineHeight = 20.sp,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(Modifier.height(10.dp))
            Preview(request)
            if (queued > 0) {
                Spacer(Modifier.height(6.dp))
                Text(stringResource(R.string.nm_risk_queued, queued), fontSize = 12.sp, color = ChatColors.secondaryText)
            }
            Spacer(Modifier.height(14.dp))
            Button(
                onClick = { RiskGate.decide(request.id, RiskDecision.ALLOW_ONCE) },
                modifier = Modifier.fillMaxWidth().height(46.dp),
                shape = CircleShape,
                colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
            ) { Text(stringResource(R.string.nm_risk_allow_once), fontSize = 15.sp, fontWeight = FontWeight.SemiBold) }
            if (request.canRemember) {
                Spacer(Modifier.height(8.dp))
                GreyPill(stringResource(R.string.nm_risk_allow_session)) { RiskGate.decide(request.id, RiskDecision.ALLOW_SESSION) }
                if (request.canAlways) {
                    Spacer(Modifier.height(8.dp))
                    GreyPill(stringResource(R.string.nm_risk_allow_always, RiskText.targetLabel(context, request.assessment.target) ?: "")) {
                        RiskGate.decide(request.id, RiskDecision.ALLOW_ALWAYS)
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
            GreyPill(stringResource(R.string.nm_risk_deny)) { RiskGate.decide(request.id, RiskDecision.DENY) }
        }
    }
}

@Composable
private fun Preview(request: RiskRequest) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(MuseTones.fill)
            .padding(horizontal = 12.dp, vertical = 10.dp),
    ) {
        Text(
            stringResource(
                when (request.kind) {
                    GuardKind.SHELL -> R.string.nm_risk_preview_shell
                    GuardKind.BROWSER -> R.string.nm_risk_preview_browser
                    GuardKind.SCREEN -> R.string.nm_risk_preview_screen
                },
            ),
            fontSize = 11.sp,
            fontWeight = FontWeight.Medium,
            color = ChatColors.secondaryText,
        )
        Spacer(Modifier.height(4.dp))
        if (request.kind == GuardKind.SHELL) {
            Text(
                request.preview,
                fontFamily = FontFamily.Monospace,
                fontSize = 12.5.sp,
                lineHeight = 17.sp,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 8,
                overflow = TextOverflow.Ellipsis,
            )
        } else {
            Text(request.preview, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface, maxLines = 2, overflow = TextOverflow.Ellipsis)
            request.pageUrl?.let {
                Spacer(Modifier.height(2.dp))
                Text(it, fontSize = 12.sp, color = ChatColors.secondaryText, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun GreyPill(label: String, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth().height(44.dp),
        shape = CircleShape,
        colors = ButtonDefaults.buttonColors(containerColor = MuseTones.fill, contentColor = MaterialTheme.colorScheme.onSurface),
        elevation = null,
    ) { Text(label, fontSize = 15.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis) }
}

@Composable
private fun ElsewhereBanner(request: RiskRequest, onOpenSession: (String) -> Unit) {
    val context = LocalContext.current
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 6.dp)
            .clip(CircleShape)
            .background(MuseTones.surface)
            .border(1.dp, MuseTones.hairline, CircleShape)
            .clickable { onOpenSession(request.sessionId) }
            .padding(start = 16.dp, end = 6.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            stringResource(R.string.nm_risk_elsewhere, NanoMuseIdentity.name(context)),
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        TextButton(onClick = { onOpenSession(request.sessionId) }) {
            Text(stringResource(R.string.nm_risk_view), color = MuseTones.action, fontWeight = FontWeight.SemiBold)
        }
    }
}
