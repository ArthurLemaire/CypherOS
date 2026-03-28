package io.github.nanomuse.hands

import org.json.JSONArray
import org.json.JSONObject

/**
 * What the screen model can do on the phone — one action per turn, in the shape of the
 * `mobile_use` action space of MemGUI-Bench (MIT) and Open-AutoGLM: coordinates on a 0–999
 * grid over the screenshot, so the same reply works on any screen size, and a `target` on
 * every tap saying what is under the finger, which is what the approval card reads.
 */
sealed class HandsAction {
    /** A point on the 0–999 grid of the screenshot. */
    data class Point(val gx: Int, val gy: Int) {
        fun toPixels(screenW: Int, screenH: Int): Pair<Int, Int> =
            Math.round(gx * screenW / GRID.toDouble()).toInt().coerceIn(0, screenW - 1) to
                Math.round(gy * screenH / GRID.toDouble()).toInt().coerceIn(0, screenH - 1)
    }

    data class Click(val at: Point, val target: String) : HandsAction()
    data class DoubleTap(val at: Point, val target: String) : HandsAction()
    data class LongPress(val at: Point, val target: String) : HandsAction()
    data class Swipe(val from: Point, val to: Point) : HandsAction()
    /** Scroll the content in [direction]: `down` reveals what is below. */
    data class Scroll(val direction: String) : HandsAction()
    data class InputText(val text: String, val field: String) : HandsAction()
    object KeyboardEnter : HandsAction()
    data class OpenApp(val appName: String) : HandsAction()
    object Back : HandsAction()
    object Home : HandsAction()
    data class Wait(val seconds: Int) : HandsAction()
    /** Logins, passwords, codes, captchas, protected pages: the user does it and taps Continue. */
    data class TakeOver(val reason: String) : HandsAction()
    /** The model needs something only the user knows; the task pauses and the chat asks. */
    data class AskUser(val question: String) : HandsAction()
    data class Status(val complete: Boolean, val answer: String) : HandsAction()

    /** The label the guard reads, for taps; null for everything else. */
    val tapTarget: String?
        get() = when (this) {
            is Click -> target
            is DoubleTap -> target
            is LongPress -> target
            else -> null
        }

    /** One line for the capsule and the trace. */
    fun describe(): String = when (this) {
        is Click -> if (target.isNotBlank()) "tap “${target.take(40)}”" else "tap"
        is DoubleTap -> if (target.isNotBlank()) "double-tap “${target.take(40)}”" else "double-tap"
        is LongPress -> if (target.isNotBlank()) "hold “${target.take(40)}”" else "long press"
        is Swipe -> "swipe"
        is Scroll -> "scroll $direction"
        is InputText -> if (field.isNotBlank()) "type into ${field.take(40)}" else "type"
        KeyboardEnter -> "enter"
        is OpenApp -> "open ${appName.take(40)}"
        Back -> "back"
        Home -> "home"
        is Wait -> "wait ${seconds}s"
        is TakeOver -> "your turn"
        is AskUser -> "question for you"
        is Status -> if (complete) "done" else "cannot finish"
    }

    companion object {
        const val GRID = 1000

        /** `Thought:` and `Action:` pulled out of a reply. */
        data class Parsed(val thought: String, val action: HandsAction, val raw: String)

        class FormatError(message: String) : Exception(message)

        private val aliases = mapOf(
            "click" to "click", "tap" to "click", "press" to "click", "touch" to "click",
            "long_press" to "long_press", "long_tap" to "long_press", "hold" to "long_press", "longpress" to "long_press",
            "double_tap" to "double_tap", "double_click" to "double_tap", "doubletap" to "double_tap",
            "swipe" to "swipe", "drag" to "swipe", "fling" to "swipe",
            "scroll" to "scroll",
            "input_text" to "input_text", "type" to "input_text", "enter_text" to "input_text", "write" to "input_text", "type_text" to "input_text",
            "keyboard_enter" to "keyboard_enter", "enter" to "keyboard_enter", "press_enter" to "keyboard_enter",
            "open_app" to "open_app", "launch" to "open_app", "launch_app" to "open_app", "open" to "open_app",
            "navigate_back" to "navigate_back", "back" to "navigate_back",
            "navigate_home" to "navigate_home", "home" to "navigate_home",
            "wait" to "wait",
            "take_over" to "take_over", "takeover" to "take_over", "handoff" to "take_over", "hand_over" to "take_over",
            "ask_user" to "ask_user", "ask" to "ask_user",
            "status" to "status", "answer" to "status", "finish" to "status", "done" to "status", "complete" to "status", "terminate" to "status",
        )

        /**
         * Reads a reply of the form `Thought: … Action: {json}`. Tolerant of a missing
         * `Thought:` label, of a fenced code block around the JSON and of text after it.
         */
        fun parse(reply: String): Parsed {
            val text = reply.trim()
            val idx = text.lastIndexOf("Action:")
            if (idx < 0) throw FormatError("no `Action:` line")
            var thought = text.substring(0, idx).replace(Regex("<think>[\\s\\S]*?</think>"), "").trim()
            if (thought.startsWith("Thought:")) thought = thought.removePrefix("Thought:").trim()
            val json = extractJson(text.substring(idx + "Action:".length))
                ?: throw FormatError("the action is not a JSON object")
            return Parsed(thought, fromJson(json), text)
        }

        internal fun extractJson(tail: String): JSONObject? {
            val s = tail.trim().removePrefix("```json").removePrefix("```").trim()
            val start = s.indexOf('{')
            if (start < 0) return null
            var depth = 0
            var inString = false
            var escaped = false
            for (i in start until s.length) {
                val c = s[i]
                if (inString) {
                    when {
                        escaped -> escaped = false
                        c == '\\' -> escaped = true
                        c == '"' -> inString = false
                    }
                    continue
                }
                when (c) {
                    '"' -> inString = true
                    '{' -> depth++
                    '}' -> {
                        depth--
                        if (depth == 0) return runCatching { JSONObject(s.substring(start, i + 1)) }.getOrNull()
                    }
                }
            }
            return null
        }

        fun fromJson(o: JSONObject): HandsAction {
            val rawType = (o.optString("action_type").ifBlank { o.optString("action") }).trim().lowercase().replace(' ', '_')
            val type = aliases[rawType] ?: throw FormatError("unknown action_type “$rawType”")
            fun point(key: String): Point {
                val arr: JSONArray = o.optJSONArray(key)
                    ?: o.optJSONArray("element")?.takeIf { key == "coordinate" }
                    ?: o.optJSONArray("coordinates")?.takeIf { key == "coordinate" }
                    ?: throw FormatError("missing $key")
                if (arr.length() != 2) throw FormatError("$key must be [x, y]")
                return Point(clampGrid(arr.optDouble(0)), clampGrid(arr.optDouble(1)))
            }
            val target = o.optString("target").ifBlank { o.optString("element_description") }.ifBlank { o.optString("label") }.trim()
            return when (type) {
                "click" -> Click(point("coordinate"), target)
                "double_tap" -> DoubleTap(point("coordinate"), target)
                "long_press" -> LongPress(point("coordinate"), target)
                "swipe" -> {
                    val from = if (o.has("start_coordinate")) point("start_coordinate") else point("coordinate")
                    val to = if (o.has("end_coordinate")) point("end_coordinate") else {
                        // `swipe` with a direction and no end point: half a screen in that direction.
                        val dir = o.optString("direction", "up").lowercase()
                        Point(
                            (from.gx + when (dir) { "left" -> -400; "right" -> 400; else -> 0 }).coerceIn(0, GRID - 1),
                            (from.gy + when (dir) { "up" -> -400; "down" -> 400; else -> 0 }).coerceIn(0, GRID - 1),
                        )
                    }
                    Swipe(from, to)
                }
                "scroll" -> {
                    val dir = o.optString("direction", "down").lowercase()
                    if (dir !in setOf("up", "down", "left", "right")) throw FormatError("scroll direction must be up|down|left|right")
                    Scroll(dir)
                }
                "input_text" -> InputText(o.optString("text"), o.optString("field").ifBlank { target })
                "keyboard_enter" -> KeyboardEnter
                "open_app" -> OpenApp(o.optString("app_name").ifBlank { o.optString("app") }.ifBlank { o.optString("name") }.trim())
                "navigate_back" -> Back
                "navigate_home" -> Home
                "wait" -> Wait(o.optDouble("seconds", 2.0).toInt().coerceIn(1, 10))
                "take_over" -> TakeOver(o.optString("reason").ifBlank { o.optString("message") })
                "ask_user" -> AskUser(o.optString("question").ifBlank { o.optString("text") })
                "status" -> {
                    val status = o.optString("goal_status").ifBlank { o.optString("status") }.lowercase()
                    val answer = o.optString("answer").ifBlank { o.optString("text") }.ifBlank { o.optString("message") }
                    val complete = status in setOf("complete", "completed", "success", "done", "finished") ||
                        (status.isBlank() && rawType in setOf("answer", "finish", "done", "complete"))
                    Status(complete, answer)
                }
                else -> throw FormatError("unknown action_type “$rawType”")
            }
        }

        private fun clampGrid(v: Double): Int {
            if (v.isNaN()) throw FormatError("coordinate is not a number")
            // A model that answers in pixels of a ~1000-wide image lands in range anyway; one that
            // answers 0–1 fractions is scaled up.
            val n = if (v > 0 && v <= 1.0) v * GRID else v
            return n.toInt().coerceIn(0, GRID - 1)
        }
    }
}
