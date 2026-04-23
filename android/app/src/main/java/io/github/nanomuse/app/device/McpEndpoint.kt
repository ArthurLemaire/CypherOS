package io.github.nanomuse.app.device

import android.util.Log
import io.github.nanomuse.app.BuildConfig
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.selects.onTimeout
import kotlinx.coroutines.selects.select
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.util.UUID

/**
 * The Model Context Protocol over Streamable HTTP, the server side, just enough for one
 * client: `initialize`, `ping`, `tools/list`, `tools/call`. Every request is a POST with one
 * JSON-RPC message; a notification is answered `202`, a request with one JSON body — except
 * `tools/call`, which is answered as an event stream with a comment every few seconds until
 * the tool is done, because a tool may wait on the user (a permission, a photo) for longer
 * than a client waits for bytes. The standalone GET stream is not offered (`405`), which
 * the protocol allows.
 */
class McpEndpoint(private val tools: ToolSource) {
    suspend fun handle(req: LocalHttp.Request): LocalHttp.Response {
        return when (req.method) {
            "POST" -> post(req)
            "DELETE" -> LocalHttp.Response.Plain(200, JSON, "{}")
            "GET" -> LocalHttp.Response.Plain(405, "text/plain; charset=utf-8", "no standalone stream", mapOf("Allow" to "POST, DELETE"))
            else -> LocalHttp.Response.Plain(405, "text/plain; charset=utf-8", "method not allowed", mapOf("Allow" to "POST, DELETE"))
        }
    }

    private suspend fun post(req: LocalHttp.Request): LocalHttp.Response {
        val msg = try {
            val text = req.body.toString(Charsets.UTF_8)
            if (text.trimStart().startsWith("[")) {
                // a batch: answered in one array, no streaming
                val batch = JSONArray(text)
                val out = JSONArray()
                for (i in 0 until batch.length()) {
                    val m = batch.optJSONObject(i) ?: continue
                    if (m.has("id")) out.put(reply(m))
                }
                return if (out.length() == 0) accepted() else LocalHttp.Response.Plain(200, JSON, out.toString())
            }
            JSONObject(text)
        } catch (e: JSONException) {
            return LocalHttp.Response.Plain(400, JSON, error(JSONObject.NULL, -32700, "parse error: ${e.message}").toString())
        }
        if (!msg.has("id")) {
            Log.d(TAG, "notification ${msg.optString("method")}")
            return accepted()
        }
        val headers = HashMap<String, String>()
        if (msg.optString("method") == "initialize") headers["Mcp-Session-Id"] = UUID.randomUUID().toString().replace("-", "")
        if (msg.optString("method") == "tools/call") return streamed(msg)
        return LocalHttp.Response.Plain(200, JSON, reply(msg).toString(), headers)
    }

    /** `tools/call` as an SSE response, kept alive with comments while the tool runs. */
    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class) // select { onTimeout }
    private fun streamed(msg: JSONObject): LocalHttp.Response = LocalHttp.Response.Stream(200, "text/event-stream") { out ->
        coroutineScope {
            val result = async(Dispatchers.Default) { reply(msg) }
            var done: JSONObject? = null
            while (done == null) {
                done = select {
                    result.onAwait { it }
                    onTimeout(HEARTBEAT_MS) { null }
                }
                if (done == null) {
                    out.write(": keep-alive\n\n".toByteArray()); out.flush()
                }
            }
            out.write("event: message\ndata: ${done}\n\n".toByteArray(Charsets.UTF_8))
            out.flush()
        }
    }

    /** The JSON-RPC response to one request. Never throws: errors become error objects. */
    private suspend fun reply(msg: JSONObject): JSONObject {
        val id = msg.opt("id") ?: JSONObject.NULL
        val method = msg.optString("method")
        val params = msg.optJSONObject("params") ?: JSONObject()
        return try {
            when (method) {
                "initialize" -> result(id, JSONObject()
                    .put("protocolVersion", params.optString("protocolVersion").ifEmpty { PROTOCOL })
                    .put("capabilities", JSONObject().put("tools", JSONObject().put("listChanged", false)))
                    .put("serverInfo", JSONObject().put("name", "nanoMuse device").put("version", BuildConfig.VERSION_NAME))
                    .put("instructions", "The phone this nanoMuse runs on: its clipboard, notifications, calendar, contacts, location, alarms and photos."))
                "ping" -> result(id, JSONObject())
                "tools/list" -> result(id, JSONObject().put("tools", tools.describe()))
                "tools/call" -> {
                    val name = params.optString("name")
                    val args = params.optJSONObject("arguments") ?: JSONObject()
                    try {
                        val text = tools.call(name, args)
                        result(id, JSONObject().put("content", JSONArray().put(JSONObject().put("type", "text").put("text", text))).put("isError", false))
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        // a failed tool is a result the model reads, not a protocol error
                        val text = e.message ?: e.javaClass.simpleName
                        Log.w(TAG, "$name failed: $text")
                        result(id, JSONObject().put("content", JSONArray().put(JSONObject().put("type", "text").put("text", text))).put("isError", true))
                    }
                }
                "resources/list" -> result(id, JSONObject().put("resources", JSONArray()))
                "prompts/list" -> result(id, JSONObject().put("prompts", JSONArray()))
                else -> error(id, -32601, "method not found: $method")
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.w(TAG, "$method failed", e)
            error(id, -32603, e.message ?: "internal error")
        }
    }

    private fun result(id: Any, result: JSONObject) = JSONObject().put("jsonrpc", "2.0").put("id", id).put("result", result)

    private fun error(id: Any, code: Int, message: String) =
        JSONObject().put("jsonrpc", "2.0").put("id", id).put("error", JSONObject().put("code", code).put("message", message))

    private fun accepted() = LocalHttp.Response.Plain(202, JSON, ByteArray(0))

    companion object {
        private const val TAG = "McpEndpoint"
        private const val JSON = "application/json"
        private const val PROTOCOL = "2025-03-26"
        private const val HEARTBEAT_MS = 8_000L

    }
}
