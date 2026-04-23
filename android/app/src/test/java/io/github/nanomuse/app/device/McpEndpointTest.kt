package io.github.nanomuse.app.device

import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.HttpURLConnection
import java.net.URL

/**
 * The loopback MCP server end to end over a real socket: initialize, tools/list, a tools/call
 * answered as an event stream (with a heartbeat when the tool is slow), a failing tool as an
 * `isError` result, a notification as 202, a bad token as 401.
 */
class McpEndpointTest {
    private lateinit var http: LocalHttp
    private var port = 0
    private val token = "t0ken"

    private val tools = object : ToolSource {
        override fun describe() = JSONArray().put(JSONObject().put("name", "echo").put("description", "says it back").put("inputSchema", JSONObject().put("type", "object")))
        override suspend fun call(name: String, args: JSONObject): String = when (name) {
            "echo" -> "echo: " + args.optString("text")
            "slow" -> { delay(300); "done" }
            else -> throw ToolError("this phone has no tool '$name'")
        }
    }

    @Before
    fun start() {
        val endpoint = McpEndpoint(tools)
        http = LocalHttp { req ->
            if (req.query["token"] != token) LocalHttp.Response.Plain(401, "text/plain", "bad token") else endpoint.handle(req)
        }
        port = http.start()
    }

    @After
    fun stop() = http.stop()

    private fun post(body: String, tok: String = token): Pair<Int, String> {
        val c = URL("http://127.0.0.1:$port/mcp?token=$tok").openConnection() as HttpURLConnection
        c.requestMethod = "POST"
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        c.setRequestProperty("Accept", "application/json, text/event-stream")
        c.outputStream.use { it.write(body.toByteArray()) }
        val code = c.responseCode
        val text = (if (code < 400) c.inputStream else c.errorStream)?.bufferedReader()?.readText() ?: ""
        return code to text
    }

    private fun rpc(id: Int, method: String, params: JSONObject = JSONObject()) =
        JSONObject().put("jsonrpc", "2.0").put("id", id).put("method", method).put("params", params).toString()

    @Test
    fun initialize_and_list() = runBlocking {
        val (code, body) = post(rpc(1, "initialize", JSONObject().put("protocolVersion", "2025-06-18")))
        assertEquals(200, code)
        val result = JSONObject(body).getJSONObject("result")
        assertEquals("2025-06-18", result.getString("protocolVersion"))
        assertEquals("nanoMuse device", result.getJSONObject("serverInfo").getString("name"))
        assertTrue(result.getJSONObject("capabilities").has("tools"))

        val (c2, notif) = post(JSONObject().put("jsonrpc", "2.0").put("method", "notifications/initialized").toString())
        assertEquals(202, c2)
        assertEquals("", notif)

        val (c3, list) = post(rpc(2, "tools/list"))
        assertEquals(200, c3)
        val listed = JSONObject(list).getJSONObject("result").getJSONArray("tools")
        assertEquals("echo", listed.getJSONObject(0).getString("name"))
    }

    @Test
    fun call_is_an_event_stream_with_heartbeats() = runBlocking {
        val (code, body) = post(rpc(3, "tools/call", JSONObject().put("name", "echo").put("arguments", JSONObject().put("text", "hi"))))
        assertEquals(200, code)
        val data = body.lines().first { it.startsWith("data: ") }.removePrefix("data: ")
        val result = JSONObject(data).getJSONObject("result")
        assertFalse(result.getBoolean("isError"))
        assertEquals("echo: hi", result.getJSONArray("content").getJSONObject(0).getString("text"))

        val (_, slow) = post(rpc(4, "tools/call", JSONObject().put("name", "slow")))
        assertTrue(slow.contains("data: "))
        assertTrue(JSONObject(slow.lines().first { it.startsWith("data: ") }.removePrefix("data: ")).getJSONObject("result").getJSONArray("content").getJSONObject(0).getString("text") == "done")
    }

    @Test
    fun a_failing_tool_is_a_result_the_model_reads() = runBlocking {
        val (_, body) = post(rpc(5, "tools/call", JSONObject().put("name", "nope")))
        val result = JSONObject(body.lines().first { it.startsWith("data: ") }.removePrefix("data: ")).getJSONObject("result")
        assertTrue(result.getBoolean("isError"))
        assertTrue(result.getJSONArray("content").getJSONObject(0).getString("text").contains("no tool 'nope'"))
    }

    @Test
    fun unknown_method_bad_token_and_get() = runBlocking {
        val (_, body) = post(rpc(6, "what/ever"))
        assertEquals(-32601, JSONObject(body).getJSONObject("error").getInt("code"))
        assertEquals(401, post(rpc(7, "ping"), tok = "wrong").first)
        val c = URL("http://127.0.0.1:$port/mcp?token=$token").openConnection() as HttpURLConnection
        assertEquals(405, c.responseCode)
    }
}
