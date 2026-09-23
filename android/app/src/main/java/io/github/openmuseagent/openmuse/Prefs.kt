package io.github.openmuseagent.openmuse

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri

/**
 * What the app remembers: which server, which token, whether to stay connected in the background.
 *
 * The web app keeps the same token in its localStorage; the phone keeps a copy so the
 * notification service can open its own WebSocket without the page being open.
 */
class Prefs(context: Context) {
    private val sp: SharedPreferences = context.getSharedPreferences("openmuse", Context.MODE_PRIVATE)

    /** Origin of the server, e.g. `http://192.168.1.20:8787` (no trailing slash). */
    var serverUrl: String
        get() = sp.getString("server_url", "") ?: ""
        set(v) = sp.edit().putString("server_url", v).apply()

    var token: String
        get() = sp.getString("token", "") ?: ""
        set(v) = sp.edit().putString("token", v).apply()

    /** Keep a WebSocket open in the background and turn events into notifications. */
    var notify: Boolean
        get() = sp.getBoolean("notify", true)
        set(v) = sp.edit().putBoolean("notify", v).apply()

    /** The agent's name, for notification titles; learnt from the server's `hello`. */
    var agentName: String
        get() = sp.getString("agent_name", "") ?: ""
        set(v) = sp.edit().putString("agent_name", v).apply()

    val connected: Boolean get() = serverUrl.isNotEmpty() && token.isNotEmpty()

    fun forget() {
        sp.edit().clear().apply()
    }

    /** Where the notification service connects: `ws(s)://host/ws?token=…`. */
    fun wsUrl(): String {
        val u = Uri.parse(serverUrl)
        val scheme = if (u.scheme == "https") "wss" else "ws"
        return "$scheme://${u.encodedAuthority}/ws?token=${Uri.encode(token)}"
    }

    /**
     * The page to open, optionally on one chat. The token rides along in the query: the web
     * app takes it into localStorage and strips it from the address on its first render.
     */
    fun pageUrl(thread: String? = null): String {
        val b = Uri.parse(serverUrl).buildUpon().path("/")
        if (!thread.isNullOrEmpty()) b.appendQueryParameter("thread", thread)
        b.appendQueryParameter("token", token)
        return b.build().toString()
    }

    companion object {
        /**
         * Pull the server origin and the token out of the link `openmuse serve` prints
         * (`http://host:8787/?token=XYZ`). A bare origin is accepted too when the token is
         * known already. Returns null when the text is not a server address at all.
         */
        fun parseLink(text: String): Pair<String, String>? {
            var s = text.trim()
            if (s.isEmpty()) return null
            if (!s.contains("://")) s = "http://$s"
            val u = Uri.parse(s)
            val host = u.host ?: return null
            if (u.scheme != "http" && u.scheme != "https") return null
            val port = if (u.port > 0) ":${u.port}" else ""
            val origin = "${u.scheme}://$host$port"
            val token = u.getQueryParameter("token") ?: u.fragment?.substringAfter("token=", "")?.substringBefore("&") ?: ""
            return origin to token
        }
    }
}
