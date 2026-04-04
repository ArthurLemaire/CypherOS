package io.github.nanomuse.ui.onboarding

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import io.github.nanomuse.ui.home.MuseTones

/**
 * nanoMuse's first run, in Muse's shape: the mark, "Welcome to nanoMuse", and the three steps
 * OpenMinis needs before the agent can answer — a provider, its models, the first conversation.
 * [io.github.nanomuse.ui.home.NanoMuseHome] shows it instead of the chat until the app has a
 * model to talk to. Muse asks for a phone number on this screen; we ask for a key, and the key
 * stays on the phone.
 *
 * Steps 1 and 2 are OpenMinis' own screens — `AddProviderScreen`, then
 * `OnboardingModelSelectionScreen`, which lists what the provider actually serves and turns the
 * pick into the default model group — reached from here and returning here.
 */
object FirstRunSetup {
    private const val PREFS = "nanomuse"
    private const val KEY_DONE = "setup.done"

    fun isDone(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_DONE, false)

    fun markDone(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_DONE, true).apply()
    }

    /**
     * Whether the home should show the setup instead of the chat. No provider means the chat
     * cannot answer, so the setup always comes back then. Otherwise it stays only for a brand-new
     * install — no conversation yet — until *Start* (or *Skip for now*) has been tapped, so the
     * third step is a real step and the hand-off into the first conversation is deliberate.
     */
    fun needed(hasProviders: Boolean, hasSessions: Boolean, done: Boolean): Boolean =
        !hasProviders || (!hasSessions && !done)

    /** The step the "Continue" button performs: 1 provider, 2 models, 3 start. */
    fun currentStep(hasProviders: Boolean, hasGroups: Boolean): Int = when {
        !hasProviders -> 1
        !hasGroups -> 2
        else -> 3
    }
}

private const val PRIVACY_URL = "https://github.com/nano-muse/nanoMuse/blob/main/docs/privacy.md"

@Composable
fun FirstRunSetupScreen(
    agentName: String,
    hasProviders: Boolean,
    hasGroups: Boolean,
    onAddProvider: () -> Unit,
    onSelectModels: () -> Unit,
    onStart: () -> Unit,
    onSkipModels: () -> Unit,
    onSettings: () -> Unit,
) {
    val context = LocalContext.current
    val step = FirstRunSetup.currentStep(hasProviders, hasGroups)
    val onSurface = MaterialTheme.colorScheme.onSurface
    val muted = MaterialTheme.colorScheme.onSurfaceVariant

    Surface(color = MuseTones.surface, modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .statusBarsPadding()
                .navigationBarsPadding(),
        ) {
            // Muse keeps a gear at the top right of its welcome screen; ours opens Settings,
            // where every OpenMinis page (providers, groups, appearance) is reachable anyway.
            Box(modifier = Modifier.fillMaxWidth().height(56.dp)) {
                IconButton(onClick = onSettings, modifier = Modifier.align(Alignment.CenterEnd).padding(end = 8.dp)) {
                    Icon(
                        imageVector = Icons.Outlined.Settings,
                        contentDescription = stringResource(R.string.nm_setup_settings),
                        tint = onSurface,
                    )
                }
            }

            Column(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Spacer(Modifier.height(20.dp))
                Icon(
                    painter = painterResource(R.drawable.ic_stat_nanomuse),
                    contentDescription = null,
                    tint = MuseTones.action,
                    modifier = Modifier.size(48.dp),
                )
                Spacer(Modifier.height(20.dp))
                Text(
                    text = stringResource(R.string.nm_setup_title),
                    fontSize = 22.sp,
                    lineHeight = 28.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = onSurface,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    text = stringResource(R.string.nm_setup_subtitle),
                    fontSize = 14.sp,
                    lineHeight = 20.sp,
                    color = muted,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(horizontal = 8.dp),
                )
                Spacer(Modifier.height(28.dp))

                SetupStep(
                    number = 1,
                    title = stringResource(R.string.nm_setup_step_provider),
                    subtitle = if (hasProviders) stringResource(R.string.nm_setup_done) else stringResource(R.string.nm_setup_step_provider_sub),
                    state = if (hasProviders) StepState.DONE else StepState.CURRENT,
                    onClick = onAddProvider,
                )
                Spacer(Modifier.height(10.dp))
                SetupStep(
                    number = 2,
                    title = stringResource(R.string.nm_setup_step_models),
                    subtitle = when {
                        hasGroups -> stringResource(R.string.nm_setup_done)
                        hasProviders -> stringResource(R.string.nm_setup_step_models_sub)
                        else -> stringResource(R.string.nm_setup_step_models_locked)
                    },
                    state = when {
                        hasGroups -> StepState.DONE
                        hasProviders -> StepState.CURRENT
                        else -> StepState.LOCKED
                    },
                    onClick = onSelectModels,
                )
                Spacer(Modifier.height(10.dp))
                SetupStep(
                    number = 3,
                    title = stringResource(R.string.nm_setup_step_start, agentName),
                    subtitle = if (hasGroups) stringResource(R.string.nm_setup_step_start_sub) else stringResource(R.string.nm_setup_step_start_locked),
                    state = if (hasGroups) StepState.CURRENT else StepState.LOCKED,
                    onClick = onStart,
                )
                Spacer(Modifier.height(24.dp))
            }

            // One blue pill that does the next thing, the way Muse's "Continue" does.
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 24.dp)
                    .padding(bottom = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Button(
                    onClick = {
                        when (step) {
                            1 -> onAddProvider()
                            2 -> onSelectModels()
                            else -> onStart()
                        }
                    },
                    shape = RoundedCornerShape(50),
                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                ) {
                    Text(
                        text = if (step == 3) stringResource(R.string.nm_setup_start) else stringResource(R.string.nm_setup_continue),
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Medium,
                    )
                }
                if (step == 2) {
                    TextButton(onClick = onSkipModels) {
                        Text(stringResource(R.string.nm_setup_skip_models), color = MuseTones.action, fontSize = 14.sp)
                    }
                } else {
                    Spacer(Modifier.height(12.dp))
                }
                Text(
                    text = stringResource(R.string.nm_setup_fine_print),
                    fontSize = 12.sp,
                    lineHeight = 16.sp,
                    color = muted,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(horizontal = 8.dp),
                )
                TextButton(
                    onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(PRIVACY_URL))) },
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp, vertical = 0.dp),
                    modifier = Modifier.height(28.dp),
                ) {
                    Text(stringResource(R.string.nm_setup_learn_more), color = MuseTones.action, fontSize = 12.sp)
                }
            }
        }
    }
}

private enum class StepState { DONE, CURRENT, LOCKED }

/** One step: a numbered disc, title and a line under it, on Muse's grey pill fill. */
@Composable
private fun SetupStep(
    number: Int,
    title: String,
    subtitle: String,
    state: StepState,
    onClick: () -> Unit,
) {
    val onSurface = MaterialTheme.colorScheme.onSurface
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    val enabled = state == StepState.CURRENT
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(16.dp),
        color = MuseTones.fill,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
        ) {
            when (state) {
                StepState.DONE -> Box(
                    modifier = Modifier.size(28.dp).clip(CircleShape).background(MuseTones.action),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Filled.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
                }
                StepState.CURRENT -> Surface(
                    shape = CircleShape,
                    color = Color.Transparent,
                    border = BorderStroke(2.dp, MuseTones.action),
                    modifier = Modifier.size(28.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text("$number", color = MuseTones.action, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                    }
                }
                StepState.LOCKED -> Surface(
                    shape = CircleShape,
                    color = Color.Transparent,
                    border = BorderStroke(1.5.dp, MuseTones.hairline),
                    modifier = Modifier.size(28.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text("$number", color = muted, fontSize = 13.sp, fontWeight = FontWeight.Medium)
                    }
                }
            }
            Spacer(Modifier.width(14.dp))
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = title,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    color = if (state == StepState.LOCKED) muted else onSurface,
                )
                Text(text = subtitle, fontSize = 13.sp, lineHeight = 17.sp, color = muted)
            }
            if (enabled) {
                Icon(Icons.Filled.ChevronRight, contentDescription = null, tint = muted, modifier = Modifier.size(22.dp))
            }
        }
    }
}
