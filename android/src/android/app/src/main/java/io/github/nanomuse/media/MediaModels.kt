package io.github.nanomuse.media

import android.content.Context
import android.content.SharedPreferences
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import io.github.nanomuse.avatar.ImageGen

/**
 * The three models nanoMuse runs on. Muse ships with all of them built in; here each is one of
 * the user's own providers, chosen in Settings → Image & video models:
 *
 *  - the **chat model** — OpenMinis' default model group, unchanged;
 *  - the **image model** — the avatar's four candidates and poses, and pictures the user asks
 *    for in the chat ([ImageGen]; any provider with the OpenAI images API, or Alibaba Cloud
 *    Model Studio's qwen-image);
 *  - the **video model** — the animated avatar and short clips the user asks for ([VideoGen];
 *    Model Studio's asynchronous video API, MiniMax-H3 by default).
 *
 * The image model is picked automatically from the first eligible provider so an avatar change
 * works out of the box; the video model is opt-in, since a clip costs real money and takes
 * minutes. [promptParagraph] tells the agent what is and is not set, so it can explain and point
 * at the setting instead of pretending.
 */
object MediaModels {
    private const val PREFS = "nanomuse"
    private const val KEY_VIDEO_INSTANCE = "media.video.provider_id"
    private const val KEY_VIDEO_MODEL = "media.video.model"
    private const val KEY_ANIMATE = "media.animate_avatar"
    const val DEFAULT_VIDEO_MODEL = "MiniMax/MiniMax-H3"
    const val DEEP_LINK = "minis://settings/media"

    fun prefs(context: Context): SharedPreferences = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // ── image ─────────────────────────────────────────────────────────────

    /** The image model when it is usable: a provider with a key *and* a model name (the catalogue may not know one). */
    fun imageEndpoint(context: Context): ImageGen.Endpoint? = ImageGen.endpoint(context)?.takeIf { it.model.isNotBlank() }

    // ── video ─────────────────────────────────────────────────────────────

    /** Providers whose host speaks Model Studio's asynchronous video API. */
    fun eligibleVideoInstances(context: Context): List<ProviderInstance> {
        val app = context.applicationContext as? MinisApp ?: return emptyList()
        val repo = app.providerRepositoryOrNull ?: return emptyList()
        return repo.config.value.instances.filter { inst ->
            inst.isEnabled && inst.credentialType == ProviderCredential.apiKey && VideoGen.speaksDashScope(ImageGen.baseUrlOf(inst))
        }
    }

    /** The chosen video model, or null when none is set (the avatar then stays still). */
    fun videoEndpoint(context: Context): VideoGen.Endpoint? {
        val app = context.applicationContext as? MinisApp ?: return null
        val repo = app.providerRepositoryOrNull ?: return null
        val p = prefs(context)
        val id = p.getString(KEY_VIDEO_INSTANCE, null) ?: return null
        val inst = eligibleVideoInstances(context).firstOrNull { it.id == id } ?: return null
        val model = p.getString(KEY_VIDEO_MODEL, null)?.takeIf { it.isNotBlank() } ?: DEFAULT_VIDEO_MODEL
        val key = repo.usableApiKey(inst) ?: return null
        return VideoGen.Endpoint(inst, key, model)
    }

    fun saveVideo(context: Context, instanceId: String?, model: String) {
        prefs(context).edit().apply {
            if (instanceId == null) remove(KEY_VIDEO_INSTANCE) else putString(KEY_VIDEO_INSTANCE, instanceId)
            putString(KEY_VIDEO_MODEL, model.trim())
        }.apply()
    }

    /** Whether a new face is animated after its poses (four short clips through the video model). */
    fun animateAvatar(context: Context): Boolean = prefs(context).getBoolean(KEY_ANIMATE, true)
    fun setAnimateAvatar(context: Context, on: Boolean) { prefs(context).edit().putBoolean(KEY_ANIMATE, on).apply() }

    // ── what the agent is told ────────────────────────────────────────────

    /** One line per model, for the settings page and the prompt. */
    fun imageLine(context: Context): String = imageEndpoint(context)?.let { "${it.model} · ${it.label}" }
        ?: context.getString(R.string.nm_media_not_set)

    fun videoLine(context: Context): String = videoEndpoint(context)?.let { "${it.model} · ${it.label}" }
        ?: context.getString(R.string.nm_media_not_set)

    /**
     * The system-prompt paragraph. English on purpose (the prompt is), short, and honest about
     * what is missing so the agent explains and links the setting instead of inventing a picture.
     */
    fun promptParagraph(context: Context): String {
        val image = imageEndpoint(context)
        val video = videoEndpoint(context)
        return buildString {
            append("Media models. Unlike Muse, whose image and video models are built in, nanoMuse runs on three models the user configures: ")
            append("the chat model (you), an image model (avatar changes, pictures the user asks for) and a video model (the animated avatar, short clips). ")
            append("Image model: ").append(image?.let { "${it.model} via ${it.label}" } ?: "NOT SET").append(". ")
            append("Video model: ").append(video?.let { "${it.model} via ${it.label}" } ?: "NOT SET").append(".\n")
            append("- To make a picture the user asks for, run `nanomuse-media image --prompt \"...\" [--from <image path>]`; ")
            append("for a short clip, `nanomuse-media video --prompt \"...\" [--from <image path>] [--seconds 4-15]` (takes 1-5 minutes; say so first). ")
            append("Both print JSON with a `markdown` field — put that line in your reply so the file shows inline. `nanomuse-media status` prints what is configured.\n")
            append("- Avatar changes are handled by the app itself when the user writes \"change your avatar to ...\"; you only need to explain when it cannot work.\n")
            if (image == null) {
                append("- No image model is set: if the user asks to change your avatar or for a picture, say plainly that this needs an image model on one of their providers ")
                append("(Alibaba Cloud Model Studio: qwen-image-3.0; any OpenAI-compatible provider with an images endpoint), and give the link [Image & video models](")
                append(DEEP_LINK).append(") — it opens the setting. Never pretend to have drawn something.\n")
            }
            if (video == null) {
                append("- No video model is set: the avatar stays as still pictures, and clips cannot be made. If asked, explain that a video model is needed ")
                append("(Alibaba Cloud Model Studio: MiniMax/MiniMax-H3, activated in their console) and give the link [Image & video models](").append(DEEP_LINK).append(").")
            }
        }.trimEnd()
    }

    /** The one-turn addendum when an avatar change was asked for but cannot be drawn. */
    fun missingImageAddendum(): String =
        "The user just asked you to change your avatar, but no image model is configured, so the app could not start the change. " +
            "Answer in the user's language: say that changing your look needs an image model on one of their providers " +
            "(for example qwen-image-3.0 on Alibaba Cloud Model Studio, or any OpenAI-compatible provider with an images endpoint), " +
            "that unlike Muse this is something they set up themselves, and give the link [Image & video models]($DEEP_LINK) to open the setting. " +
            "Keep it to a few sentences and do not describe or invent a new look."
}
