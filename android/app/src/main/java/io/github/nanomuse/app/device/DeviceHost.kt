package io.github.nanomuse.app.device

import android.annotation.SuppressLint
import android.content.Context
import android.util.Log
import io.github.nanomuse.app.Prefs

/**
 * The app as an MCP server for the nanoMuse process on the same phone: `http://127.0.0.1:<port>/mcp`,
 * one token, the phone's capabilities as tools ([DeviceTools]). `RuntimeService` starts it before
 * the Python process and passes the address as `NANOMUSE_HOST_URL` / `NANOMUSE_HOST_TOKEN`;
 * the server registers it as the MCP server `device` (`nanomuse/runtime.py`).
 *
 * Loopback only, a token in the URL query or as a bearer, no other routes. Nothing about it
 * is reachable from the network.
 */
@SuppressLint("StaticFieldLeak") // holds the application context
object DeviceHost {
    private var http: LocalHttp? = null
    private var context: Context? = null
    val token: String by lazy { Prefs.newToken() }

    /** The URL the Python side gets (no token in it). */
    val url: String get() = http?.let { "http://127.0.0.1:${it.port}" } ?: ""

    val running: Boolean get() = http != null

    /** Start, or return the one already running. */
    fun start(ctx: Context): DeviceHost {
        if (http != null) return this
        val app = ctx.applicationContext
        context = app
        val endpoint = McpEndpoint(DeviceTools(app))
        val server = LocalHttp { req ->
            when {
                req.path != "/mcp" -> LocalHttp.Response.Plain(404, "text/plain; charset=utf-8", "not found")
                !authorised(req) -> LocalHttp.Response.Plain(401, "text/plain; charset=utf-8", "bad token")
                else -> endpoint.handle(req)
            }
        }
        val port = server.start()
        http = server
        Log.i(TAG, "device MCP server on 127.0.0.1:$port")
        return this
    }

    fun stop() {
        http?.stop()
        http = null
    }

    private fun authorised(req: LocalHttp.Request): Boolean {
        val given = req.query["token"] ?: req.header("authorization")?.removePrefix("Bearer ")?.trim() ?: return false
        return constantTimeEquals(given, token)
    }

    private fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.length != b.length) return false
        var diff = 0
        for (i in a.indices) diff = diff or (a[i].code xor b[i].code)
        return diff == 0
    }

    private const val TAG = "DeviceHost"
}
