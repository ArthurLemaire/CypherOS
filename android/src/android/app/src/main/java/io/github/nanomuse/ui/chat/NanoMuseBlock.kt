package io.github.nanomuse.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CheckBox
import androidx.compose.material.icons.outlined.CheckBoxOutlineBlank
import androidx.compose.material.icons.outlined.Flag
import androidx.compose.material.icons.outlined.TrendingUp
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import io.github.nanomuse.goals.GoalFlow
import io.github.nanomuse.ui.home.HomeBus
import io.github.nanomuse.ui.home.HomeTab
import org.json.JSONObject

/**
 * Renders the app-protocol fences the model emits (`nanomuse-goal`, `nanomuse-goal-update`,
 * `nanomuse-feed`) as small cards inside the assistant bubble — the way Muse shows "goal created" and check-ins.
 * Unknown `nanomuse-*` tags fall back to the raw text so nothing is silently lost.
 */
@Composable
fun NanoMuseBlock(language: String, code: String) {
    val json = remember(code) { runCatching { JSONObject(code.trim()) }.getOrNull() }
    when {
        language == GoalFlow.BLOCK_GOAL && json != null -> GoalCreatedCard(json)
        language == GoalFlow.BLOCK_UPDATE && json != null -> GoalUpdateCard(json)
        language == io.github.nanomuse.feed.FeedFlow.BLOCK && json != null -> FeedPostedCard(json)
        language == io.github.nanomuse.avatar.AvatarFlow.BLOCK_OPTIONS && json != null -> io.github.nanomuse.ui.avatar.AvatarOptionsFenceCard(json)
        // The first conversation's naming block is for the app (FirstConversation.afterTurn), not for the eye.
        language == io.github.nanomuse.onboarding.FirstConversation.BLOCK -> Unit
        else -> Text(code, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun CardFrame(content: @Composable () -> Unit) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = io.github.nanomuse.ui.home.MuseTones.surface,
        border = BorderStroke(1.dp, io.github.nanomuse.ui.home.MuseTones.hairline),
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
    ) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) { content() }
    }
}

@Composable
private fun GoalCreatedCard(o: JSONObject) {
    val title = o.optString("title")
    val why = o.optString("why")
    val steps = o.optJSONArray("steps")?.let { arr -> List(arr.length()) { arr.optString(it) } }?.filter { it.isNotBlank() }.orEmpty()
    val everyHours = o.optInt("check_every_hours", 0)
    val checkTime = o.optString("check_time", "")
    CardFrame {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Flag, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text(
                stringResource(R.string.nm_goal_card_created),
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface)
        if (why.isNotBlank()) {
            Spacer(Modifier.height(2.dp))
            Text(why, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (steps.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                steps.take(5).forEach { step ->
                    Row(verticalAlignment = Alignment.Top) {
                        Icon(
                            Icons.Outlined.CheckBoxOutlineBlank,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 2.dp).size(15.dp),
                        )
                        Spacer(Modifier.width(8.dp))
                        Text(step, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurface)
                    }
                }
            }
        }
        Spacer(Modifier.height(6.dp))
        val cadence = if (everyHours > 0) {
            androidx.compose.ui.platform.LocalContext.current.resources.getQuantityString(R.plurals.nm_goal_every_hours, everyHours, everyHours)
        } else {
            stringResource(R.string.nm_goal_daily_at, checkTime.ifBlank { "09:00" })
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(cadence, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            TextButton(onClick = { HomeBus.showTab(HomeTab.GOALS) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp, vertical = 0.dp)) {
                Text(stringResource(R.string.nm_goal_card_open), fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun GoalUpdateCard(o: JSONObject) {
    val progress = o.optInt("progress", -1).coerceIn(-1, 100)
    val status = o.optString("status", "on_track")
    val note = o.optString("note")
    val done = status == "done"
    val attention = status == "attention"
    val statusText = when {
        done -> stringResource(R.string.nm_goal_status_done)
        attention -> stringResource(R.string.nm_goal_update_attention)
        else -> stringResource(R.string.nm_goal_update_on_track)
    }
    val tint = when {
        done -> MaterialTheme.colorScheme.primary
        attention -> MaterialTheme.colorScheme.error
        else -> MaterialTheme.colorScheme.primary
    }
    CardFrame {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                if (done) Icons.Outlined.CheckBox else Icons.Outlined.TrendingUp,
                contentDescription = null,
                tint = tint,
                modifier = Modifier.size(18.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                stringResource(R.string.nm_goal_update_card_title),
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.weight(1f),
            )
            Text(statusText, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = tint)
        }
        if (progress >= 0) {
            Spacer(Modifier.height(10.dp))
            LinearProgressIndicator(
                progress = { progress / 100f },
                modifier = Modifier.fillMaxWidth().height(6.dp),
                color = tint,
                trackColor = io.github.nanomuse.ui.home.MuseTones.fill,
            )
        }
        if (note.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(note, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurface)
        }
    }
}

/** A feed post the model just wrote: its tile, title and a first line; tap → the Feed tab. */
@Composable
private fun FeedPostedCard(o: JSONObject) {
    val title = o.optString("title")
    val emoji = o.optString("emoji").ifBlank { "📝" }
    val body = o.optString("body")
    CardFrame {
        Row(verticalAlignment = Alignment.CenterVertically) {
            androidx.compose.foundation.layout.Box(
                modifier = Modifier
                    .size(36.dp)
                    .background(io.github.nanomuse.ui.home.MuseTones.fill, RoundedCornerShape(10.dp)),
                contentAlignment = Alignment.Center,
            ) { Text(emoji, fontSize = 18.sp) }
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    stringResource(R.string.nm_feed_card_posted),
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(title, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurface, maxLines = 2)
                if (body.isNotBlank()) {
                    Text(
                        body.lineSequence().firstOrNull { it.isNotBlank() }?.trim('-', '*', ' ') ?: "",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                    )
                }
            }
            TextButton(
                onClick = { HomeBus.showTab(HomeTab.FEED) },
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp, vertical = 0.dp),
            ) { Text(stringResource(R.string.nm_feed_card_open), fontSize = 13.sp) }
        }
    }
}
