package io.github.nanomuse.ui.header

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material3.Text
import com.openminis.app.R
import com.openminis.app.service.SessionActivityTracker
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.ui.avatar.AgentMood

/**
 * The one line under the name in the chat header, Muse style: what the agent is doing right now
 * ("Starting browser", "Searching 12306…") or that it is waiting on you. Null when idle, and the
 * caller shows its usual provider · model rows instead — that is the one place nanoMuse differs
 * from Muse, which has a single model and nothing to pick.
 */
@Composable
fun rememberNanoMuseStatusLine(isStreaming: Boolean, mood: AgentMood): String? {
    val toolTitle by SessionActivityTracker.currentToolTitle.collectAsState()
    val toolRunning by SessionActivityTracker.isToolRunning.collectAsState()
    val pendingRisk by io.github.nanomuse.guard.RiskGate.pending.collectAsState()
    return when {
        mood == AgentMood.WAITING && pendingRisk != null -> stringResource(R.string.nm_risk_needs_approval)
        mood == AgentMood.WAITING -> stringResource(R.string.nm_status_waiting)
        isStreaming && toolRunning && !toolTitle.isNullOrBlank() -> toolTitle
        isStreaming -> stringResource(R.string.nm_status_thinking)
        else -> null
    }
}

/** Height of the two provider/model rows it replaces, so the app bar never jumps. */
private val STATUS_LINE_HEIGHT = 27.dp

@Composable
fun NanoMuseStatusLine(text: String, mood: AgentMood) {
    Box(
        modifier = Modifier.height(STATUS_LINE_HEIGHT).padding(horizontal = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = text,
            fontSize = 12.sp,
            lineHeight = 14.sp,
            fontWeight = FontWeight.Medium,
            color = if (mood == AgentMood.WAITING) ChatColors.sendButton else ChatColors.secondaryText,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = TextStyle(platformStyle = PlatformTextStyle(includeFontPadding = false)),
        )
    }
}

/** Opens Settings → Soul, where the name, icon and style live. Tapping the face is the shortcut. */
fun openSoulSettings(context: Context) {
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse("minis://settings/soul")).apply {
        setPackage(context.packageName)
        addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
    }
    runCatching { context.startActivity(intent) }
}
