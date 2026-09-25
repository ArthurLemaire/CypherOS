package io.github.nanomuse.ui.media

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.PlayCircleOutline
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.model.ProviderInstance
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
import kotlinx.coroutines.launch

const val ROUTE_MEDIA_MODELS = "nanomuse/media"

/**
 * Settings → Image & video models. The one place that says what Muse never has to: nanoMuse
 * runs on three of the user's own models. The chat model is OpenMinis' default group (a row to
 * its picker); the image and video models are chosen here the same way the chat models are — a
 * provider, then one of the models the key turns out to have (the provider's list, filtered to
 * the ones that draw; for video, the known Model Studio models probed against the key) — and
 * each section says plainly what stops working without one.
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

    val scope = rememberCoroutineScope()

    // Image: the first eligible provider is the default, so it works without a visit here.
    val imageInstances = remember(config) { ImageGen.eligibleInstances(context) }
    var imageInstance by remember(config) { mutableStateOf(ImageGen.endpoint(context)?.instanceId ?: imageInstances.firstOrNull()?.id) }
    var imageModel by remember(config) { mutableStateOf(ImageGen.endpoint(context)?.model.orEmpty()) }
    val imageInst = imageInstances.firstOrNull { it.id == imageInstance }
    // The models this key can draw with — the provider's own list, filtered to the ones that
    // draw. Fetched once when the provider has no list yet, or on "Check again".
    val imageModels = remember(config, imageInstance) { imageInst?.let { ImageGen.availableModels(context, it) }.orEmpty() }
    var imageChecking by remember { mutableStateOf(false) }
    var imageChecked by remember { mutableStateOf(setOf<String>()) }
    fun checkImageModels(inst: ProviderInstance) {
        if (repo == null || imageChecking) return
        imageChecking = true
        scope.launch {
            runCatching { repo.refreshModels(inst) }
            imageChecked = imageChecked + inst.id
            imageChecking = false
        }
    }
    LaunchedEffect(imageInstance) {
        val inst = imageInst ?: return@LaunchedEffect
        if (imageModels.isEmpty() && inst.id !in imageChecked) checkImageModels(inst)
    }

    // Video: opt-in — nothing until the user picks a provider.
    val videoInstances = remember(config) { MediaModels.eligibleVideoInstances(context) }
    var videoInstance by remember(config) { mutableStateOf(MediaModels.videoEndpoint(context)?.instanceId) }
    var videoModel by remember(config) { mutableStateOf(MediaModels.videoEndpoint(context)?.model ?: MediaModels.DEFAULT_VIDEO_MODEL) }
    val videoInst = videoInstances.firstOrNull { it.id == videoInstance }
    var videoModels by remember(videoInstance) { mutableStateOf(videoInst?.let { MediaModels.availableVideoModels(context, it) }) }
    var videoChecking by remember { mutableStateOf(false) }
    fun checkVideoModels(inst: ProviderInstance) {
        if (videoChecking) return
        videoChecking = true
        scope.launch {
            MediaModels.checkVideoModels(context, inst)?.let { videoModels = it }
            videoChecking = false
        }
    }
    LaunchedEffect(videoInstance) {
        val inst = videoInst ?: return@LaunchedEffect
        if (videoModels == null || !MediaModels.videoCheckIsFresh(context, inst)) checkVideoModels(inst)
    }
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
            if (imageInst != null) {
                ModelList(
                    header = stringResource(R.string.nm_media_models_on, imageInst.label),
                    models = imageModels,
                    recommended = ImageGen.recommendedModel(imageInst),
                    selected = imageModel,
                    checking = imageChecking,
                    empty = stringResource(R.string.nm_media_image_none_found),
                    onSelect = { imageModel = it; ImageGen.save(context, imageInst.id, it) },
                    onCheck = { checkImageModels(imageInst) },
                )
                ModelField(
                    value = imageModel,
                    placeholder = "qwen-image-3.0-pro · gpt-image-1 · …",
                    onChange = { imageModel = it; ImageGen.save(context, imageInst.id, it) },
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
            if (videoInst != null) {
                ModelList(
                    header = stringResource(R.string.nm_media_models_on, videoInst.label),
                    models = videoModels.orEmpty(),
                    recommended = MediaModels.DEFAULT_VIDEO_MODEL,
                    selected = videoModel,
                    checking = videoChecking,
                    empty = stringResource(R.string.nm_media_video_none_found),
                    onSelect = { videoModel = it; MediaModels.saveVideo(context, videoInst.id, it) },
                    onCheck = { checkVideoModels(videoInst) },
                )
                ModelField(
                    value = videoModel,
                    placeholder = MediaModels.DEFAULT_VIDEO_MODEL,
                    onChange = { videoModel = it; MediaModels.saveVideo(context, videoInst.id, it) },
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

/**
 * The models the key can use, one row each like the chat model picker, the recommended one
 * marked; a "checking…" line while the provider is asked, and a row to ask again.
 */
@Composable
private fun ModelList(
    header: String,
    models: List<String>,
    recommended: String,
    selected: String,
    checking: Boolean,
    empty: String,
    onSelect: (String) -> Unit,
    onCheck: () -> Unit,
) {
    Text(
        text = header,
        fontSize = 13.sp,
        fontWeight = FontWeight.Medium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 16.dp).padding(top = 14.dp, bottom = 4.dp),
    )
    models.forEach { id ->
        SettingsChoiceRow(
            title = id,
            selected = selected == id,
            onSelect = { onSelect(id) },
            leading = if (id == recommended) ({
                Text(
                    text = stringResource(R.string.nm_media_recommended),
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Medium,
                    color = MuseTones.action,
                    modifier = Modifier.padding(end = 8.dp),
                )
            }) else null,
        )
    }
    when {
        checking -> SettingsRow(
            title = stringResource(R.string.nm_media_checking),
            titleColor = MaterialTheme.colorScheme.onSurfaceVariant,
            showDivider = false,
            trailing = { CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = MuseTones.action) },
        )
        models.isEmpty() -> SettingsRow(
            title = empty,
            subtitle = stringResource(R.string.nm_media_recheck),
            titleColor = MaterialTheme.colorScheme.onSurfaceVariant,
            onClick = onCheck,
            showChevron = false,
            showDivider = false,
            minHeight = 72.dp,
        )
        else -> SettingsRow(
            title = stringResource(R.string.nm_media_recheck),
            titleColor = MuseTones.action,
            onClick = onCheck,
            showChevron = false,
            showDivider = false,
        )
    }
}

/** Any other model name, typed. */
@Composable
private fun ModelField(value: String, placeholder: String, onChange: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp)) {
        OutlinedTextField(
            value = value,
            onValueChange = onChange,
            label = { Text(stringResource(R.string.nm_media_other_model)) },
            placeholder = { Text(placeholder) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(14.dp),
            colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, unfocusedBorderColor = MuseTones.hairline),
        )
    }
}
