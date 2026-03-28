package io.github.nanomuse.hands

import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.provider.Settings
import com.openminis.app.MinisApp
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.hasImageInput
import com.openminis.app.data.repository.ProviderRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The screen as a hand (0.1.12). Off by default; when the user switches it on and the three
 * prerequisites hold, the agent gets `nanomuse-hands` — a screenshot-driven operator that taps,
 * types and swipes in the apps that have no API — as the last rung of the ladder.
 *
 * The eyes are the screenshot alone: no accessibility tree is read for perception. The
 * accessibility service is the hand (gestures, the screenshot itself, the focused field to
 * type into) and nothing more.
 */
object Hands {
    private const val PREFS = "nanomuse"
    private const val KEY_ENABLED = "hands.enabled"
    private const val KEY_MODEL = "hands.model_entry"
    const val DEEP_LINK = "minis://settings/hands"
    const val MIN_SDK = Build.VERSION_CODES.R

    private fun prefs(context: Context): SharedPreferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun enabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, false)
    fun setEnabled(context: Context, on: Boolean) { prefs(context).edit().putBoolean(KEY_ENABLED, on).apply() }

    /** The chosen screen model's entry id; null means "pick one" ([screenModel]). */
    fun modelEntryId(context: Context): String? = prefs(context).getString(KEY_MODEL, null)?.takeIf { it.isNotBlank() }
    fun setModelEntryId(context: Context, id: String?) { prefs(context).edit().putString(KEY_MODEL, id ?: "").apply() }

    // ── readiness ──────────────────────────────────────────────────────────

    data class Readiness(
        val androidOk: Boolean,
        val serviceOn: Boolean,
        val overlayOk: Boolean,
        val model: ScreenModel?,
    ) {
        val ready: Boolean get() = androidOk && serviceOn && overlayOk && model != null
    }

    fun readiness(context: Context): Readiness = Readiness(
        androidOk = Build.VERSION.SDK_INT >= MIN_SDK,
        serviceOn = MinisAccessibilityService.getInstance() != null,
        overlayOk = Settings.canDrawOverlays(context),
        model = screenModel(context),
    )

    /** Usable right now: switched on and every prerequisite in place. */
    fun usable(context: Context): Boolean = enabled(context) && readiness(context).ready

    // ── the screen model ───────────────────────────────────────────────────

    /** A model that sees pictures, with the key to call it. */
    data class ScreenModel(val instance: ProviderInstance, val entry: ModelEntry, val apiKey: String) {
        val label: String get() = entry.model.displayName.ifBlank { entry.model.id } + " · " + instance.label.ifBlank { instance.providerType.name }
        val modelId: String get() = entry.model.id
    }

    /** Every enabled model that declares image input, for the picker. */
    fun visionEntries(context: Context): List<Pair<ProviderInstance, ModelEntry>> {
        val repo = repo(context) ?: return emptyList()
        val cfg = repo.config.value
        return cfg.modelEntries.filter { !it.isHidden && it.model.hasImageInput }.mapNotNull { e ->
            cfg.instances.firstOrNull { it.id == e.providerInstanceId && it.isEnabled }?.let { it to e }
        }
    }

    /**
     * The model that looks at the screen: the one chosen in Settings; else the chat model when
     * it can see; else the first member of the Vision Group; else any enabled vision model,
     * preferring names that say so (`vl`, `vision`). Null when none of the user's models sees.
     */
    fun screenModel(context: Context): ScreenModel? {
        val repo = repo(context) ?: return null
        val cfg = repo.config.value
        fun usable(inst: ProviderInstance?, entry: ModelEntry?): ScreenModel? {
            if (inst == null || entry == null || !inst.isEnabled || !entry.model.hasImageInput) return null
            val key = repo.usableApiKey(inst) ?: return null
            return ScreenModel(inst, entry, key)
        }
        modelEntryId(context)?.let { id ->
            cfg.modelEntries.firstOrNull { it.id == id }?.let { e -> usable(cfg.instances.firstOrNull { it.id == e.providerInstanceId }, e) }
        }?.let { return it }
        val defaultGroup = cfg.modelGroups.firstOrNull { it.id == cfg.defaultPrimaryGroupId } ?: cfg.modelGroups.firstOrNull()
        defaultGroup?.memberEntryIds?.firstNotNullOfOrNull { id ->
            cfg.modelEntries.firstOrNull { it.id == id }?.let { e -> usable(cfg.instances.firstOrNull { it.id == e.providerInstanceId }, e) }
        }?.let { return it }
        repo.resolveVisionCandidates().firstNotNullOfOrNull { (inst, e) -> usable(inst, e) }?.let { return it }
        val all = visionEntries(context).mapNotNull { (inst, e) -> usable(inst, e) }
        return all.firstOrNull { Regex("vl|vision", RegexOption.IGNORE_CASE).containsMatchIn(it.modelId) } ?: all.firstOrNull()
    }

    private fun repo(context: Context): ProviderRepository? = (context.applicationContext as? MinisApp)?.providerRepositoryOrNull

    // ── a run in progress ──────────────────────────────────────────────────

    /** True while the hands are working; the settings page and the overlay observer read it. */
    private val _active = MutableStateFlow(false)
    val active: StateFlow<Boolean> = _active.asStateFlow()
    internal fun setActive(on: Boolean) { _active.value = on }

    /** The run in progress, so Stop can reach it from anywhere. */
    @Volatile internal var current: HandsOperator? = null

    /** Ends the run in progress after the action in flight; a no-op when none. */
    fun stopCurrent(reason: String = "stopped from the app") { current?.requestStop(reason) }

    // ── what the agent is told ─────────────────────────────────────────────

    /**
     * The system-prompt paragraph: the ladder, and the CLI when the hands are usable. English,
     * like the rest of the prompt; honest about what is off so the agent explains and links the
     * setting instead of pretending to tap.
     */
    fun promptParagraph(context: Context): String {
        val on = enabled(context)
        val r = readiness(context)
        return buildString {
            append("## Apps without an API — the ladder (nanoMuse)\n")
            append("Most everyday apps here (12306, 微信, 支付宝, 美团, 淘宝, 京东…) have no API. Climb in this order and say which rung you are on before you start: ")
            append("(1) a skill, a CLI or an MCP server; (2) the page fetched with the user's login or `browser_use`; (3) the phone's own screen, last. ")
            append("A task is rarely all screen: find the number with a command, the button with the screen, and ask before it is pressed.\n")
            if (on && r.ready) {
                append("The screen is available: `nanomuse-hands run --task \"<one clear task, with every detail the hands need>\" [--app \"<app name>\"] [--max-steps 25]` ")
                append("(screen model: ${r.model?.label}). It looks at screenshots — never the accessibility tree — and taps, types and swipes; a capsule with Stop shows the user what it does. ")
                append("It never types passwords, codes or card numbers: for a login or a code it hands the phone to the user and waits. Taps that pay, send, post or delete go through the same approval card as the shell and the browser. ")
                append("It returns JSON: `outcome` is done (with `answer`), stopped (the user tapped Stop — do not restart it), needs_user (`question` — relay it and wait), infeasible or failed (with `message`); `last_screen` is a picture you can show with `![screen](<last_screen>)`. ")
                append("Tell the user in one line that you are about to use the screen and which app, then run it; give one task per run, and never a payment as the task. `nanomuse-hands apps` lists the installed apps; `nanomuse-hands status` says what is set up.")
            } else if (on) {
                val missing = buildList {
                    if (!r.androidOk) add("Android 11 or newer")
                    if (!r.serviceOn) add("the accessibility service is off")
                    if (!r.overlayOk) add("no permission to draw over other apps")
                    if (r.model == null) add("no model that can see pictures")
                }.joinToString(", ")
                append("The screen is switched on but not usable yet ($missing). If a task needs it, say so in one line and give the link [Hands]($DEEP_LINK) — it opens the setting; do not try android-a11y-cli instead.")
            } else {
                append("Operating the phone's screen is switched off (the default). If a task can only be done on the screen, say so in one line and give the link [Hands]($DEEP_LINK) so the user can switch it on; do not try android-a11y-cli instead, and do not pretend.")
            }
        }
    }
}
