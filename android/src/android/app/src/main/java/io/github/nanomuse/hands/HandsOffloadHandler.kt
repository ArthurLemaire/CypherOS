package io.github.nanomuse.hands

import android.content.Context
import com.openminis.app.logging.AppLogger
import com.openminis.app.sandbox.NativeOffloadHandler
import com.openminis.app.sandbox.NativeOffloadRequest
import com.openminis.app.sandbox.NativeOffloadResult
import io.github.nanomuse.identity.NanoMuseIdentity
import io.github.nanomuse.media.MediaOffloadHandler
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/**
 * `nanomuse-hands` — the phone's screen as a hand, from the sandbox shell:
 *
 *     nanomuse-hands status
 *     nanomuse-hands apps
 *     nanomuse-hands run --task "<one clear task>" [--app "<app name>"] [--max-steps 25]
 *
 * `run` blocks for the whole task (minutes) and answers with one JSON object. Off by default;
 * with the switch off or a prerequisite missing it exits 3 with the reason and the settings
 * link, so the agent tells the user instead of guessing. Registered in `MinisApp` next to
 * `nanomuse-media`.
 */
class HandsOffloadHandler(private val context: Context) : NativeOffloadHandler {

    override fun handle(request: NativeOffloadRequest): NativeOffloadResult {
        val args = MediaOffloadHandler.Args(request.argv.drop(1))
        return when (args.positional.firstOrNull()) {
            null, "help", "--help", "-h" -> NativeOffloadResult(0, HELP)
            "status" -> ok(status())
            "apps" -> ok(apps())
            "run" -> run(args, request.sessionId)
            "stop" -> { Hands.stopCurrent("stopped from the shell"); ok(JSONObject().put("ok", true)) }
            else -> NativeOffloadResult(2, "nanomuse-hands: unknown subcommand '${args.positional.first()}'\n$HELP")
        }
    }

    private fun status(): JSONObject {
        val r = Hands.readiness(context)
        return JSONObject()
            .put("enabled", Hands.enabled(context))
            .put("ready", r.ready)
            .put("android_11_or_newer", r.androidOk)
            .put("accessibility_service", r.serviceOn)
            .put("draw_over_apps", r.overlayOk)
            .put("screen_model", r.model?.let { JSONObject().put("model", it.modelId).put("provider", it.instance.label) } ?: JSONObject.NULL)
            .put("running", Hands.active.value)
            .put("settings", Hands.DEEP_LINK)
    }

    private fun apps(): JSONObject {
        val list = HandsApps.launchable(context)
        return JSONObject()
            .put("count", list.size)
            .put("apps", JSONArray().apply { list.forEach { put(JSONObject().put("name", it.label).put("package", it.packageName)) } })
    }

    private fun run(args: MediaOffloadHandler.Args, sessionId: String?): NativeOffloadResult {
        val task = args.get("task")?.trim().orEmpty()
        if (task.isEmpty()) return NativeOffloadResult(2, "nanomuse-hands run: --task is required\n")
        if (!Hands.enabled(context)) return refused("off", "Operating the screen is switched off in Settings → Hands.")
        val r = Hands.readiness(context)
        if (!r.ready) {
            val missing = buildList {
                if (!r.androidOk) add("Android 11 or newer is needed for screenshots")
                if (!r.serviceOn) add("the accessibility service is off")
                if (!r.overlayOk) add("nanoMuse may not draw over other apps")
                if (r.model == null) add("no model that can see pictures is configured")
            }
            return refused("not_ready", missing.joinToString("; ") + ".")
        }
        if (Hands.active.value) return refused("busy", "The hands are already working on something; wait for it to finish or stop it.")
        val maxSteps = args.get("max-steps")?.toIntOrNull()?.coerceIn(1, HandsOperator.MAX_STEPS) ?: HandsOperator.DEFAULT_MAX_STEPS
        val opts = HandsOperator.Options(
            task = task,
            appHint = args.get("app")?.trim()?.takeIf { it.isNotEmpty() },
            maxSteps = maxSteps,
            sessionId = sessionId,
            agentName = NanoMuseIdentity.name(context),
            language = Locale.getDefault().getDisplayLanguage(Locale.ENGLISH).ifBlank { "the user's language" },
        )
        AppLogger.info(TAG, "run: ${task.take(80)} app=${opts.appHint} maxSteps=$maxSteps")
        val result = HandsOperator(context).run(opts)
        val body = JSONObject()
            .put("ok", result.outcome is HandsOperator.Outcome.Done)
            .put("outcome", result.outcome.code)
            .put("steps", result.steps)
            .put("run_id", result.runId)
            .put("model", result.model ?: JSONObject.NULL)
            .put("last_screen", result.lastScreen ?: JSONObject.NULL)
            .put("trace", result.tracePath ?: JSONObject.NULL)
            .put("log", JSONArray(result.log))
        when (val o = result.outcome) {
            is HandsOperator.Outcome.Done -> body.put("answer", o.answer)
            is HandsOperator.Outcome.Infeasible -> body.put("message", o.message)
                .put("tell_user", "Say plainly what could not be done and why; do not retry on your own.")
            is HandsOperator.Outcome.Stopped -> body.put("message", o.message)
                .put("tell_user", "The user stopped it. Say so in one line and do not start it again.")
            is HandsOperator.Outcome.NeedsUser -> body.put("question", o.question)
                .put("tell_user", "Ask the user this question in their language and wait; then run again with the answer in the task.")
            is HandsOperator.Outcome.Failed -> body.put("message", o.message)
                .put("tell_user", "Tell the user what went wrong in their language; the settings are at ${Hands.DEEP_LINK}.")
        }
        val code = when (result.outcome) {
            is HandsOperator.Outcome.Done -> 0
            is HandsOperator.Outcome.Failed -> 1
            else -> 4
        }
        return NativeOffloadResult(code, body.toString(2) + "\n")
    }

    private fun refused(error: String, message: String): NativeOffloadResult = NativeOffloadResult(
        3,
        JSONObject().put("ok", false).put("error", error).put("message", message)
            .put("tell_user", "Tell the user in one line, in their language, and give the link ${Hands.DEEP_LINK} so they can switch it on or fix the setting. Do not use android-a11y-cli instead.")
            .toString(2) + "\n",
    )

    private fun ok(body: JSONObject): NativeOffloadResult = NativeOffloadResult(0, body.toString(2) + "\n")

    companion object {
        private const val TAG = "nanomuse-hands"
        const val HELP = """nanomuse-hands — the phone's screen as a hand: taps, types and swipes in apps that have no API

Usage:
  nanomuse-hands status
  nanomuse-hands apps
  nanomuse-hands run --task "<one clear task, with every detail the hands need>" [--app "<app name>"] [--max-steps 25]
  nanomuse-hands stop

The screen model sees screenshots only. It never types passwords or codes (the user takes over), and taps that
pay, send, post or delete wait for the same approval card as the shell and the browser. Off by default:
Settings → Hands. Exit codes: 0 done · 1 failed · 2 usage · 3 off or not ready · 4 stopped, infeasible or needs the user.
"""
    }
}
