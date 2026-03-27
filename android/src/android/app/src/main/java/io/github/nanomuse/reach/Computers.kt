package io.github.nanomuse.reach

import android.content.Context
import android.os.Build
import com.openminis.app.logging.AppLogger
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * The computers this phone is paired with (0.1.13 Reach) and the calls to them. One way:
 * the phone drives the computer through `host/nanomuse_host.py`, a small stdlib-only server
 * on the same network; the computer never reaches into the phone.
 *
 * Each computer has its own bearer token, kept in the app's private preferences. The host keeps
 * only a hash of it. Approvals for what runs there are decided here, on the phone, before a
 * request is sent — the host has no way to judge intent.
 */
object Computers {
    private const val PREFS = "nanomuse"
    private const val KEY = "reach.computers"
    const val DEEP_LINK = "minis://settings/computers"
    const val DEFAULT_PORT = 7333
    const val HOST_SCRIPT_URL = "https://raw.githubusercontent.com/nano-muse/nanoMuse/main/host/nanomuse_host.py"

    data class Computer(
        val id: String,
        val name: String,
        val os: String,
        val host: String,
        val port: Int,
        val token: String,
        val pairedAt: Long,
        val lastSeen: Long = 0L,
    ) {
        val address: String get() = "$host:$port"
        fun url(path: String): String = "http://$host:$port$path"
    }

    private val _list = MutableStateFlow<List<Computer>?>(null)

    /** The paired computers, loaded once; the settings page and the CLI observe it. */
    fun list(context: Context): List<Computer> {
        _list.value?.let { return it }
        val loaded = load(context)
        _list.value = loaded
        return loaded
    }

    fun flow(context: Context): StateFlow<List<Computer>?> { list(context); return _list.asStateFlow() }

    private fun load(context: Context): List<Computer> {
        val raw = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null) ?: return emptyList()
        return runCatching {
            val arr = JSONArray(raw)
            (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                Computer(
                    o.getString("id"), o.optString("name"), o.optString("os"), o.getString("host"), o.optInt("port", DEFAULT_PORT),
                    o.getString("token"), o.optLong("pairedAt"), o.optLong("lastSeen"),
                )
            }
        }.getOrElse { emptyList() }
    }

    private fun save(context: Context, list: List<Computer>) {
        val arr = JSONArray()
        list.forEach { c ->
            arr.put(
                JSONObject().put("id", c.id).put("name", c.name).put("os", c.os).put("host", c.host).put("port", c.port)
                    .put("token", c.token).put("pairedAt", c.pairedAt).put("lastSeen", c.lastSeen),
            )
        }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY, arr.toString()).apply()
        _list.value = list
    }

    fun forget(context: Context, id: String) = save(context, list(context).filterNot { it.id == id })

    private fun update(context: Context, c: Computer) = save(context, list(context).map { if (it.id == c.id) c else it })

    /** By name (case-insensitive), by address or by id; with none named, the only or the first one. */
    fun resolve(context: Context, nameOrNull: String?): Computer? {
        val all = list(context)
        if (nameOrNull.isNullOrBlank()) return all.firstOrNull()
        val q = nameOrNull.trim()
        return all.firstOrNull { it.name.equals(q, true) } ?: all.firstOrNull { it.address == q || it.host == q } ?: all.firstOrNull { it.id == q }
            ?: all.firstOrNull { it.name.contains(q, true) }
    }

    // ── the calls ──────────────────────────────────────────────────────────

    class ReachException(val code: Int, message: String) : IOException(message)

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .build()
    }

    private val JSON = "application/json; charset=utf-8".toMediaType()
    private val BYTES = "application/octet-stream".toMediaType()

    private fun deviceName(): String = listOf(Build.MANUFACTURER, Build.MODEL).filter { it.isNotBlank() }.joinToString(" ").ifBlank { "Android" } + " · nanoMuse"

    /** Pairs with the host at [host]:[port] using the code on its screen; saves and returns the computer. */
    @Throws(IOException::class)
    fun pair(context: Context, host: String, port: Int, code: String): Computer {
        val body = JSONObject().put("code", code.trim().replace(" ", "")).put("device", deviceName()).toString()
        val req = Request.Builder().url("http://$host:$port/pair").post(body.toRequestBody(JSON)).build()
        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ReachException(resp.code, errorMessage(text, resp.code))
            val o = JSONObject(text)
            val c = Computer(
                id = UUID.randomUUID().toString(),
                name = o.optString("name").ifBlank { host },
                os = o.optString("os"),
                host = host, port = port,
                token = o.getString("token"),
                pairedAt = System.currentTimeMillis(),
                lastSeen = System.currentTimeMillis(),
            )
            save(context, list(context).filterNot { it.host == host && it.port == port } + c)
            return c
        }
    }

    private fun errorMessage(text: String, code: Int): String =
        runCatching { JSONObject(text).optString("message").ifBlank { null } }.getOrNull() ?: "HTTP $code"

    private fun call(context: Context, c: Computer, req: Request.Builder): Pair<Int, ByteArray> {
        val r = req.header("Authorization", "Bearer ${c.token}").build()
        http.newCall(r).execute().use { resp ->
            val bytes = resp.body?.bytes() ?: ByteArray(0)
            if (!resp.isSuccessful) throw ReachException(resp.code, errorMessage(String(bytes), resp.code))
            update(context, c.copy(lastSeen = System.currentTimeMillis()))
            return resp.code to bytes
        }
    }

    private fun json(context: Context, c: Computer, req: Request.Builder): JSONObject = JSONObject(String(call(context, c, req).second))

    @Throws(IOException::class)
    fun info(context: Context, c: Computer): JSONObject = json(context, c, Request.Builder().url(c.url("/info")).get())

    /** Runs [command] in the computer's shell; the caller has already had it approved. */
    @Throws(IOException::class)
    fun shell(context: Context, c: Computer, command: String, cwd: String?, timeoutS: Int): JSONObject {
        val body = JSONObject().put("command", command).put("timeout", timeoutS).apply { if (!cwd.isNullOrBlank()) put("cwd", cwd) }
        return json(context, c, Request.Builder().url(c.url("/shell")).post(body.toString().toRequestBody(JSON)))
    }

    @Throws(IOException::class)
    fun files(context: Context, c: Computer, path: String?): JSONObject =
        json(context, c, Request.Builder().url(c.url("/files") + (path?.let { "?path=" + java.net.URLEncoder.encode(it, "UTF-8") } ?: "")).get())

    @Throws(IOException::class)
    fun getFile(context: Context, c: Computer, path: String, dest: File): Long {
        val (_, bytes) = call(context, c, Request.Builder().url(c.url("/file") + "?path=" + java.net.URLEncoder.encode(path, "UTF-8")).get())
        dest.parentFile?.mkdirs()
        dest.writeBytes(bytes)
        return bytes.size.toLong()
    }

    @Throws(IOException::class)
    fun putFile(context: Context, c: Computer, local: File, remotePath: String): JSONObject =
        json(
            context, c,
            Request.Builder().url(c.url("/file") + "?path=" + java.net.URLEncoder.encode(remotePath, "UTF-8")).put(local.readBytes().toRequestBody(BYTES)),
        )

    @Throws(IOException::class)
    fun open(context: Context, c: Computer, url: String): JSONObject =
        json(context, c, Request.Builder().url(c.url("/open")).post(JSONObject().put("url", url).toString().toRequestBody(JSON)))

    /** A picture of the computer's screen, or null when the host cannot take one. */
    @Throws(IOException::class)
    fun screen(context: Context, c: Computer): Pair<ByteArray, String>? {
        val r = Request.Builder().url(c.url("/screen")).get().header("Authorization", "Bearer ${c.token}").build()
        http.newCall(r).execute().use { resp ->
            if (resp.code == 501) return null
            val bytes = resp.body?.bytes() ?: ByteArray(0)
            if (!resp.isSuccessful) throw ReachException(resp.code, errorMessage(String(bytes), resp.code))
            update(context, c.copy(lastSeen = System.currentTimeMillis()))
            return bytes to (resp.header("Content-Type") ?: "image/png")
        }
    }

    /** True when the host answers /info within a few seconds. */
    fun reachable(context: Context, c: Computer): Boolean = try {
        info(context, c); true
    } catch (t: Throwable) {
        AppLogger.info(TAG, "${c.name} unreachable: ${t.message}"); false
    }

    // ── what the agent is told ─────────────────────────────────────────────

    fun promptParagraph(context: Context): String {
        val all = list(context)
        return buildString {
            append("## Your computers (nanoMuse)\n")
            if (all.isEmpty()) {
                append("No computer is paired. When the user wants something done on their PC or Mac — a command, a file, a page opened there — say in one line that it takes a one-time pairing: ")
                append("they run `python3 nanomuse_host.py` on the computer (one file, standard library only, from $HOST_SCRIPT_URL), read the address and the six-digit code off its screen, and enter them in [Computers]($DEEP_LINK). Then `nanomuse-pc` works.")
            } else {
                append("Paired: ").append(all.joinToString("; ") { "${it.name} (${it.os}, ${it.address})" }).append(". ")
                append("`nanomuse-pc run \"<command>\" [--on <computer>] [--cwd <dir>] [--timeout <s>]` runs a shell command there and returns exit code, stdout and stderr — the same approval rules as the phone's shell apply, decided on the phone before anything is sent; ")
                append("`nanomuse-pc ls [<path>]` lists a folder; `nanomuse-pc get <remote> [--name <file>]` copies a file into this chat's attachments (pictures then render with `![…](minis://attachments/<file>)`); `nanomuse-pc put <local> <remote>` copies one there; ")
                append("`nanomuse-pc open <url>` opens a page in the computer's browser; `nanomuse-pc screen` takes a picture of its screen into the attachments; `nanomuse-pc status` says which computers answer. ")
                append("One way only — the phone drives the computer. The computer's shell is the user's own account: same care as with `rm`, `git push --force` or anything that sends. When it does not answer, say the host is not running or the address changed, and point to [Computers]($DEEP_LINK).")
            }
        }
    }

    private const val TAG = "Computers"
}
