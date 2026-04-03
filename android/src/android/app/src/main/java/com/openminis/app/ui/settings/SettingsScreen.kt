package com.openminis.app.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.BarChart
import androidx.compose.material.icons.outlined.BatteryFull
import androidx.compose.material.icons.outlined.BugReport
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Face
import androidx.compose.material.icons.outlined.Email
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Feedback
import androidx.compose.material.icons.outlined.Backup
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.FolderShared
import androidx.compose.material.icons.outlined.FrontHand
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Palette
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState // nanoMuse
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.res.stringResource
import com.openminis.app.BuildConfig
import com.openminis.app.R
import com.openminis.app.ui.components.openExternalUrl
import com.openminis.app.i18n.uppercaseForDisplay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(
    onBack: () -> Unit,
    onProvidersClick: () -> Unit,
    onModelGroupsClick: () -> Unit,
    onRootfsClick: () -> Unit = {},
    onBackupClick: () -> Unit = {},
    onEnvVarsClick: () -> Unit = {},
    onSkillsClick: () -> Unit = {},
    onTerminalClick: () -> Unit = {},
    onMemoryClick: () -> Unit = {},
    // [T-mcp-integration-android] MCP Integrations page, listed directly below
    // Memory. Default no-op for callers that haven't wired the route yet.
    onMcpClick: () -> Unit = {},
    // [T-soul-md] Soul settings page lives between Skills and Memory in the
    // Agent Runtime section; default no-op for callers that haven't wired
    // the route yet.
    onSoulClick: () -> Unit = {},
    onSystemFilesClick: () -> Unit = {}, // nanoMuse
    onAvatarClick: () -> Unit = {}, // nanoMuse
    onPermissionsClick: () -> Unit = {},
    onUsageClick: () -> Unit = {},
    onAppearanceClick: () -> Unit = {},
    onLogsClick: () -> Unit = {},
    // T219-2: Mount External Folders entry. Default no-op for any caller
    // that hasn't wired the route yet.
    onMountedFoldersClick: () -> Unit = {},
    // T235: Shared Folders entry (Shared / Skills / Memory). Default no-op
    // for back-compat with callers wired before T235.
    onSharedFoldersClick: () -> Unit = {},
    // T50: Background & Notifications screen (battery optimisation +
    // OEM autostart guidance). Default no-op so older callers/tests
    // don't need to be retrofitted.
    onBackgroundClick: () -> Unit = {},
    // Hook accepted for forward-compat with AppNavigation's About route. The
    // About row below still has a TODO onClick in HEAD; future settings-bucket
    // work will wire this through.
    onAboutClick: () -> Unit = {},
) {
    val context = LocalContext.current
    var showFeedbackSheet by remember { mutableStateOf(false) }
    // nanoMuse: Muse's settings page — the round back glyph, the title centred,
    // white cards of outlined-glyph rows on the grey canvas, no section headers
    // or subtitles. Every OpenMinis entry is kept; they are regrouped the way
    // Muse groups its own (the agent, the data on the phone, the app, about).
    // The card at the top stands where Muse's plan card stands and shows the
    // model the agent talks to, now that the home header no longer does.
    val providerRepo = (context.applicationContext as? com.openminis.app.MinisApp)?.providerRepositoryOrNull
    val providerConfig = providerRepo?.config?.collectAsState()?.value
    val defaultGroup = providerConfig?.let { cfg -> cfg.modelGroups.firstOrNull { it.id == cfg.defaultPrimaryGroupId } ?: cfg.modelGroups.firstOrNull() }
    val firstEntry = providerConfig?.let { cfg -> defaultGroup?.memberEntryIds?.firstNotNullOfOrNull { id -> cfg.modelEntries.firstOrNull { it.id == id } } }
    val firstInstance = providerConfig?.instances?.firstOrNull { it.id == firstEntry?.providerInstanceId }
    val modelLine = listOfNotNull(firstInstance?.label, firstEntry?.model?.displayName).joinToString(" · ")
    Scaffold(
        containerColor = io.github.nanomuse.ui.home.MuseTones.canvas,
        topBar = {
            io.github.nanomuse.ui.muse.MuseTopAppBar(
                title = { Text(stringResource(R.string.settings_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = stringResource(R.string.settings_back),
                        )
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState()),
        ) {
            Spacer(Modifier.height(8.dp))

            // -- The model (Muse: the plan card) --
            io.github.nanomuse.ui.muse.MuseCard {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clickable(onClick = onModelGroupsClick)
                        .padding(horizontal = 16.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            text = defaultGroup?.name ?: stringResource(R.string.nm_settings_no_model),
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = if (defaultGroup == null) stringResource(R.string.nm_settings_no_model_sub)
                                else modelLine.ifEmpty { stringResource(R.string.settings_model_groups) },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                    Text(
                        text = stringResource(R.string.nm_settings_change_model),
                        style = MaterialTheme.typography.labelLarge,
                        color = io.github.nanomuse.ui.home.MuseTones.action,
                    )
                }
                io.github.nanomuse.ui.muse.MuseRowDivider(inset = 16.dp)
                io.github.nanomuse.ui.muse.MuseRow(
                    title = stringResource(R.string.settings_manage_providers),
                    icon = Icons.Outlined.Lock,
                    onClick = onProvidersClick,
                )
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(
                    title = stringResource(R.string.settings_token_usage),
                    icon = Icons.Outlined.BarChart,
                    onClick = onUsageClick,
                )
            }
            io.github.nanomuse.ui.muse.MuseGap()

            // -- The agent --
            io.github.nanomuse.ui.muse.MuseCard {
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_soul), icon = Icons.Outlined.AutoAwesome, onClick = onSoulClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.nm_avatar_title), icon = Icons.Outlined.Face, onClick = onAvatarClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_memory), icon = Icons.Outlined.Psychology, onClick = onMemoryClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.nm_sysfiles_title), icon = Icons.Outlined.Description, onClick = onSystemFilesClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_skills), icon = Icons.Outlined.Extension, onClick = onSkillsClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_mcp), icon = Icons.Outlined.Dashboard, onClick = onMcpClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_env_vars), icon = Icons.Outlined.Terminal, onClick = onEnvVarsClick)
            }
            io.github.nanomuse.ui.muse.MuseGap()

            // -- The phone: what the agent may touch, where its files live --
            io.github.nanomuse.ui.muse.MuseCard {
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_section_permissions), icon = Icons.Outlined.Shield, onClick = onPermissionsClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.bg_section_header), icon = Icons.Outlined.BatteryFull, onClick = onBackgroundClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_section_storage), icon = Icons.Outlined.Inventory2, onClick = onRootfsClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_shared_folders), icon = Icons.Outlined.Folder, onClick = onSharedFoldersClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_mount_external_folders), icon = Icons.Outlined.FolderShared, onClick = onMountedFoldersClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_backup_restore), icon = Icons.Outlined.Backup, onClick = onBackupClick)
            }
            io.github.nanomuse.ui.muse.MuseGap()

            // -- The app --
            io.github.nanomuse.ui.muse.MuseCard {
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_section_appearance), icon = Icons.Outlined.Palette, onClick = onAppearanceClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_section_logs), icon = Icons.Outlined.Description, onClick = onLogsClick)
            }
            io.github.nanomuse.ui.muse.MuseGap()

            // -- About --
            io.github.nanomuse.ui.muse.MuseCard {
                io.github.nanomuse.ui.muse.MuseRow(title = stringResource(R.string.settings_about_minis), icon = Icons.Outlined.Info, onClick = onAboutClick)
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(
                    title = stringResource(R.string.settings_privacy_policy),
                    icon = Icons.Outlined.FrontHand,
                    // iOS canonical URL — ContentView.swift / AddProviderView.swift
                    onClick = { openExternalUrl(context, "https://github.com/nano-muse/nanoMuse/blob/main/docs/privacy.md") },
                )
                io.github.nanomuse.ui.muse.MuseRowDivider()
                io.github.nanomuse.ui.muse.MuseRow(
                    title = stringResource(R.string.settings_feedback),
                    icon = Icons.Outlined.Feedback,
                    // nanoMuse: GitHub Issues is the one feedback channel (no
                    // Telegram group, no mailbox), so skip the chooser sheet.
                    onClick = { openExternalUrl(context, buildBugReportUrl()) },
                )
            }
            io.github.nanomuse.ui.muse.MuseCaption(
                text = stringResource(R.string.nm_settings_version, BuildConfig.VERSION_NAME, BuildConfig.VERSION_CODE),
            )

            Spacer(Modifier.height(24.dp))
        }
    }

    if (showFeedbackSheet) {
        ModalBottomSheet(onDismissRequest = { showFeedbackSheet = false }) {
            Column(modifier = Modifier.padding(bottom = 24.dp)) {
                FeedbackSheetItem(
                    icon = Icons.Outlined.BugReport,
                    title = stringResource(R.string.settings_submit_github_issues),
                    onClick = {
                        showFeedbackSheet = false
                        openExternalUrl(context, buildBugReportUrl())
                    },
                )
                FeedbackSheetItem(
                    icon = Icons.AutoMirrored.Outlined.Send,
                    title = stringResource(R.string.settings_feedback_telegram),
                    onClick = {
                        showFeedbackSheet = false
                        openExternalUrl(context, "https://t.me/+2NzhOJuzRyI1YmM1")
                    },
                )
                FeedbackSheetItem(
                    icon = Icons.Outlined.Email,
                    title = stringResource(R.string.settings_feedback_email),
                    onClick = {
                        showFeedbackSheet = false
                        openExternalUrl(context, buildFeedbackMailto())
                    },
                )
            }
        }
    }
}

@Composable
private fun FeedbackSheetItem(
    icon: ImageVector,
    title: String,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.size(22.dp),
        )
        Spacer(Modifier.width(16.dp))
        Text(
            text = title,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

/**
 * Build the GitHub Issues "new bug report" URL with the body pre-filled
 * from the existing bug-report template. Platform / OS version / app
 * version / device model are injected so the report arrives ready to
 * triage instead of asking the user to fill in environment details.
 *
 * URL shape:
 *   https://github.com/OpenMinis/OpenMinis/issues/new
 *     ?template=bug_report.md
 *     &title=[Bug]
 *     &body=<percent-encoded markdown>
 *
 * The body is a Markdown template with sections for Problem Summary,
 * Basic Information (table — auto-filled), Steps to Reproduce, Error
 * Details (fenced code block), Expected Behavior, and Additional
 * Information.
 */
private fun buildBugReportUrl(): String {
    val osVersion = android.os.Build.VERSION.RELEASE
    val sdkInt = android.os.Build.VERSION.SDK_INT
    val versionName = BuildConfig.VERSION_NAME
    val versionCode = BuildConfig.VERSION_CODE
    val manufacturer = android.os.Build.MANUFACTURER
    val model = android.os.Build.MODEL

    // Body matches the spec template. Triple-backtick fences are written
    // as "```" — they survive percent-encoding cleanly. Indentation here
    // is significant: trimIndent() removes the common Kotlin indentation
    // but preserves the Markdown structure as-is.
    val body = """
        ## 📝 Problem Summary

        <!-- Briefly describe the issue you encountered -->


        ## 📱 Basic Information

        | Field | Value |
        |-------|-------|
        | Platform | Android |
        | OS Version | Android $osVersion (API $sdkInt) |
        | nanoMuse Version | $versionName (build $versionCode) |
        | Device Model | $manufacturer $model |

        ## 🔁 Steps to Reproduce

        1.
        2.
        3.

        ## ❌ Error Details

        ```
        paste error here
        ```

        ## ✅ Expected Behavior



        ## 🗂️ Additional Information

    """.trimIndent()

    val encodedBody = java.net.URLEncoder.encode(body, "UTF-8")
    // Title carries a "[Bug] " prefix with a trailing space so the cursor
    // lands after it on GitHub's page; encode the space as %20 explicitly
    // since URLEncoder turns spaces into '+' which GitHub also accepts but
    // the spec calls for the literal "[Bug] " form.
    val title = java.net.URLEncoder.encode("[Bug] ", "UTF-8")
    // nanoMuse: the repository uses an issue form (app_bug_report.yml), which
    // takes its fields as query parameters; `body` is ignored by forms.
    val version = java.net.URLEncoder.encode("$versionName ($versionCode)", "UTF-8")
    val device = java.net.URLEncoder.encode("Android $osVersion (API $sdkInt), $manufacturer $model", "UTF-8")
    return "https://github.com/nano-muse/nanoMuse/issues/new" +
        "?template=app_bug_report.yml" +
        "&title=$title" +
        "&version=$version" +
        "&device=$device" +
        "&body=$encodedBody"
}

/**
 * Compose a `mailto:` URL with a prefilled subject and body that include
 * app version, Android version, and device model. Mirrors iOS
 * `ContentView.makeFeedbackEmailURL()`.
 */
private fun buildFeedbackMailto(): String {
    val body = """
        Please describe your feedback:


        ---
        App Version: ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})
        Android Version: ${android.os.Build.VERSION.RELEASE} (SDK ${android.os.Build.VERSION.SDK_INT})
        Device: ${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}

        Screenshot (optional): Please attach a screenshot if relevant.
    """.trimIndent()
    val subject = java.net.URLEncoder.encode("nanoMuse Feedback", "UTF-8")
    val encodedBody = java.net.URLEncoder.encode(body, "UTF-8")
    return "mailto:dev@openminis.app?subject=$subject&body=$encodedBody"
}

/**
 * A grouped settings section with header and optional footer, matching iOS grouped List sections.
 */
@Composable
private fun SettingsSection(
    title: String,
    footer: String? = null,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = 20.dp),
    ) {
        // Section header
        Text(
            text = title.uppercaseForDisplay(),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            fontWeight = FontWeight.Medium,
            letterSpacing = 0.5.sp,
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
        )

        // Section card
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(color = MaterialTheme.colorScheme.surfaceContainerLow),
        ) {
            content()
        }

        // Section footer
        if (footer != null) {
            Text(
                text = footer,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
                lineHeight = 16.sp,
            )
        }
    }
}

/**
 * A single settings row item with colored icon, title, optional subtitle, and chevron.
 * Styled to match iOS settings rows with SF Symbol-like colored circle icons.
 */
@Composable
private fun SettingsItem(
    icon: ImageVector,
    iconColor: Color,
    title: String,
    subtitle: String?,
    onClick: () -> Unit,
    showDivider: Boolean = true,
) {
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable(onClick = onClick)
                .padding(horizontal = 14.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // Colored circle icon (matching iOS settings style)
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .background(
                        color = iconColor,
                        shape = CircleShape,
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = Color.White,
                    modifier = Modifier.size(16.dp),
                )
            }

            Spacer(Modifier.width(14.dp))

            // Title + subtitle
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(1.dp),
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                if (subtitle != null) {
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            // Chevron
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.5f),
                modifier = Modifier.size(20.dp),
            )
        }

        // Divider between items (inset to match icon alignment)
        if (showDivider) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 58.dp, end = 14.dp)
                    .height(0.5.dp)
                    .background(MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f)),
            )
        }
    }
}

