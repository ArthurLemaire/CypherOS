package io.github.nanomuse.ui.media

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.PlayCircleOutline
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsChoiceRow
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import com.openminis.app.ui.settings.SettingsSwitchRow
import io.github.nanomuse.avatar.AvatarMotion
import io.github.nanomuse.avatar.AvatarStore
import io.github.nanomuse.avatar.ImageGen
import io.github.nanomuse.media.MediaModels
import io.github.nanomuse.ui.home.MuseTones

const val ROUTE_MEDIA_MODELS = "nanomuse/media"

/**
 * Settings → Image & video models. The one place that says what Muse never has to: nanoMuse
 * runs on three of the user's own models. The chat model is OpenMinis' default group (a row to
 * its picker); the image and video models are chosen here — a provider, then a model name with
 * the catalogue's quick picks — and each section says plainly what stops working without one.
 */
@Composable
fun MediaModelsScreen(
    onBack: () -> Unit,
    onOpenModelGroups: () -> Unit,
    onOpenProviders: () -> Unit,
) {
    val context = LocalContext.current
    val repo = (context.applicationContext as? MinisApp)?.providerRepositoryOrNull
    val config = repo?.config?.collectAsState()?.value
    val defaultGroup = config?.let { cfg -> cfg.modelGroups.firstOrNull { it.id == cfg.defaultPrimaryGroupId } ?: cfg.modelGroups.firstOrNull() }
    val chatEntry = config?.let { cfg -> defaultGroup?.memberEntryIds?.firstNotNullOfOrNull { id -> cfg.modelEntries.firstOrNull { it.id == id } } }
    val chatInstance = config?.instances?.firstOrNull { it.id == chatEntry?.providerInstanceId }

    // Image: the first eligible provider is the default, so it works without a visit here.
    val imageInstances = remember(config) { ImageGen.eligibleInstances(context) }
    var imageInstance by remember(config) { mutableStateOf(ImageGen.endpoint(context)?.instanceId ?: imageInstances.firstOrNull()?.id) }
    var imageModel by remember(config) { mutableStateOf(ImageGen.endpoint(context)?.model.orEmpty()) }

    // Video: opt-in — nothing until the user picks a provider.
    val videoInstances = remember(config) { MediaModels.eligibleVideoInstances(context) }
    var videoInstance by remember(config) { mutableStateOf(MediaModels.videoEndpoint(context)?.instanceId) }
    var videoModel by remember(config) { mutableStateOf(MediaModels.videoEndpoint(context)?.model ?: MediaModels.DEFAULT_VIDEO_MODEL) }
    var animate by remember { mutableStateOf(MediaModels.animateAvatar(context)) }
    val motion by AvatarMotion.progress.collectAsState()
    val clips by AvatarMotion.clips.collectAsState()
    val face by AvatarStore.current.collectAsState()

    SettingsScaffold(title = stringResource(R.string.nm_media_title), onBack = onBack) {
        Text(
            text = stringResource(R.string.nm_media_intro),
            fontSize = 14.sp,
            lineHeight = 20.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp).padding(top = 12.dp),
        )

        // ── chat ──
        SettingsSection(header = stringResource(R.string.nm_media_section_chat), footer = stringResource(R.string.nm_media_chat_footer)) {
            SettingsRow(
                title = defaultGroup?.name ?: stringResource(R.string.nm_settings_no_model),
                subtitle = listOfNotNull(chatInstance?.label, chatEntry?.model?.displayName).joinToString(" · ").ifEmpty { stringResource(R.string.nm_settings_no_model_sub) },
                icon = Icons.Outlined.ChatBubbleOutline,
                iconColor = MaterialTheme.colorScheme.onSurface,
                onClick = onOpenModelGroups,
                showDivider = false,
                minHeight = 72.dp,
            )
        }

        // ── image ──
        SettingsSection(
            header = stringResource(R.string.nm_media_section_image),
            footer = if (imageInstances.isEmpty()) stringResource(R.string.nm_media_image_none) else stringResource(R.string.nm_media_image_footer),
        ) {
            StatusRow(
                icon = Icons.Outlined.Image,
                ready = imageInstance != null && imageModel.isNotBlank(),
                line = when {
                    imageInstance != null && imageModel.isNotBlank() -> "$imageModel · ${imageInstances.firstOrNull { it.id == imageInstance }?.label.orEmpty()}"
                    imageInstance != null -> stringResource(R.string.nm_media_need_model)
                    else -> stringResource(R.string.nm_media_not_set)
                },
                offLine = stringResource(R.string.nm_media_image_off),
            )
            imageInstances.forEach { inst ->
                SettingsChoiceRow(
                    title = inst.label,
                    selected = imageInstance == inst.id,
                    onSelect = {
                        imageInstance = inst.id
                        imageModel = ImageGen.suggestedModel(context, inst)
                        ImageGen.save(context, inst.id, imageModel)
                    },
                )
            }
            if (imageInstance != null) {
                val inst = imageInstances.firstOrNull { it.id == imageInstance }
                val quick = remember(inst?.id) { inst?.let { ImageGen.imageEntries(context, it).map { e -> e.model.id } }.orEmpty() }
                ModelField(
                    value = imageModel,
                    quick = (quick + listOfNotNull(inst?.let { ImageGen.suggestedModel(context, it) }.takeIf { !it.isNullOrBlank() })).distinct(),
                    placeholder = "qwen-image-3.0-pro · gpt-image-1 · …",
                    onChange = { imageModel = it; imageInstance?.let { id -> ImageGen.save(context, id, it) } },
                )
            }
            if (imageInstances.isEmpty()) {
                SettingsRow(title = stringResource(R.string.nm_media_add_provider), onClick = onOpenProviders, showDivider = false)
            }
        }

        // ── video ──
        SettingsSection(
            header = stringResource(R.string.nm_media_section_video),
            footer = if (videoInstances.isEmpty()) stringResource(R.string.nm_media_video_none) else stringResource(R.string.nm_media_video_footer),
        ) {
            StatusRow(
                icon = Icons.Outlined.Movie,
                ready = videoInstance != null && videoModel.isNotBlank(),
                line = when {
                    videoInstance != null && videoModel.isNotBlank() -> "$videoModel · ${videoInstances.firstOrNull { it.id == videoInstance }?.label.orEmpty()}"
                    videoInstance != null -> stringResource(R.string.nm_media_need_model)
                    else -> stringResource(R.string.nm_media_not_set)
                },
                offLine = stringResource(R.string.nm_media_video_off),
            )
            SettingsChoiceRow(
                title = stringResource(R.string.nm_media_video_off_option),
                selected = videoInstance == null,
                onSelect = { videoInstance = null; MediaModels.saveVideo(context, null, videoModel) },
            )
            videoInstances.forEach { inst ->
                SettingsChoiceRow(
                    title = inst.label,
                    selected = videoInstance == inst.id,
                    onSelect = {
                        videoInstance = inst.id
                        if (videoModel.isBlank()) videoModel = MediaModels.DEFAULT_VIDEO_MODEL
                        MediaModels.saveVideo(context, inst.id, videoModel)
                    },
                )
            }
            if (videoInstance != null) {
                ModelField(
                    value = videoModel,
                    quick = listOf(MediaModels.DEFAULT_VIDEO_MODEL),
                    placeholder = MediaModels.DEFAULT_VIDEO_MODEL,
                    onChange = { videoModel = it; MediaModels.saveVideo(context, videoInstance, it) },
                )
                SettingsSwitchRow(
                    title = stringResource(R.string.nm_media_animate),
                    subtitle = stringResource(R.string.nm_media_animate_sub, AvatarMotion.animated.size, AvatarMotion.SECONDS),
                    checked = animate,
                    onCheckedChange = { animate = it; MediaModels.setAnimateAvatar(context, it) },
                    showDivider = face != null,
                )
                if (face != null) {
                    val running = motion?.running == true
                    SettingsRow(
                        title = stringResource(R.string.nm_media_clips_title, clips.size, AvatarMotion.animated.size),
                        subtitle = when {
                            running -> stringResource(R.string.nm_avatar_status_animating, (motion?.done ?: 0) + 1, motion?.total ?: 0)
                            motion?.error != null -> motion?.error
                            else -> stringResource(R.string.nm_media_clips_sub)
                        },
                        icon = Icons.Outlined.PlayCircleOutline,
                        iconColor = MaterialTheme.colorScheme.onSurface,
                        onClick = if (running) null else ({ AvatarMotion.animateAll(context, force = clips.size >= AvatarMotion.animated.size) }),
                        showChevron = false,
                        showDivider = false,
                        minHeight = 72.dp,
                        trailing = {
                            Text(
                                text = stringResource(if (running) R.string.nm_media_clips_running else if (clips.isEmpty()) R.string.nm_media_clips_make else R.string.nm_media_clips_redo),
                                fontSize = 14.sp,
                                fontWeight = FontWeight.Medium,
                                color = if (running) MaterialTheme.colorScheme.onSurfaceVariant else MuseTones.action,
                            )
                        },
                    )
                }
            }
        }
        Spacer(Modifier.height(32.dp))
    }
}

/** Ready / not set, with the one line of consequence when it is not. */
@Composable
private fun StatusRow(icon: androidx.compose.ui.graphics.vector.ImageVector, ready: Boolean, line: String, offLine: String) {
    SettingsRow(
        title = line,
        subtitle = if (ready) stringResource(R.string.nm_media_ready) else offLine,
        icon = icon,
        iconColor = if (ready) MuseTones.action else MaterialTheme.colorScheme.onSurfaceVariant,
        minHeight = 72.dp,
    )
}

/** The model name, with the catalogue's quick picks as chips above it. */
@Composable
private fun ModelField(value: String, quick: List<String>, placeholder: String, onChange: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        if (quick.isNotEmpty()) {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 10.dp)) {
                items(quick.size) { i ->
                    val id = quick[i]
                    Surface(
                        onClick = { onChange(id) },
                        shape = CircleShape,
                        color = if (value == id) MaterialTheme.colorScheme.onSurface else MuseTones.fill,
                        contentColor = if (value == id) MaterialTheme.colorScheme.surface else MaterialTheme.colorScheme.onSurface,
                    ) {
                        Text(id, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
                    }
                }
            }
        }
        OutlinedTextField(
            value = value,
            onValueChange = onChange,
            label = { Text(stringResource(R.string.nm_avatar_model_label)) },
            placeholder = { Text(placeholder) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(14.dp),
            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, unfocusedBorderColor = MuseTones.hairline),
        )
    }
}
