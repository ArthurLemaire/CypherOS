package io.github.nanomuse.app.device

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URLDecoder
import kotlin.concurrent.thread

/**
 * The smallest HTTP/1.1 server that will do: bound to the loopback only, one request per
 * connection (`Connection: close`), bodies by `Content-Length`, and a streaming response for
 * the calls that take a while. It exists so the app can be an MCP server for the nanoMuse
 * process on the same phone without carrying a web framework.
 */
class LocalHttp(private val handler: suspend (Request) -> Response) {
    class Request(
        val method: String,
        val path: String,
        val query: Map<String, String>,
        val headers: Map<String, String>,
        val body: ByteArray,
    ) {
        fun header(name: String): String? = headers[name.lowercase()]
    }

    sealed class Response(val status: Int, val headers: Map<String, String>) {
        /** A whole body at once. */
        class Plain(status: Int, val contentType: String, val body: ByteArray, headers: Map<String, String> = emptyMap()) : Response(status, headers) {
            constructor(status: Int, contentType: String, text: String, headers: Map<String, String> = emptyMap()) :
                this(status, contentType, text.toByteArray(Charsets.UTF_8), headers)
        }

        /** A body written as it comes; the connection closing ends it. */
        class Stream(status: Int, val contentType: String, headers: Map<String, String> = emptyMap(), val write: suspend (OutputStream) -> Unit) :
            Response(status, headers)
    }

    private var server: ServerSocket? = null
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** The port it listens on. */
    val port: Int get() = server?.localPort ?: 0

    /** Bind to 127.0.0.1 on a free port and start accepting. */
    fun start(): Int {
        if (server != null) return port
        val s = ServerSocket(0, 16, InetAddress.getLoopbackAddress())
        server = s
        thread(name = "local-http", isDaemon = true) {
            while (!s.isClosed) {
                val client = try { s.accept() } catch (_: IOException) { break }
                scope.launch { serve(client) }
            }
        }
        return s.localPort
    }

    fun stop() {
        try { server?.close() } catch (_: IOException) { }
        server = null
        scope.cancel()
    }

    private suspend fun serve(client: Socket) {
        client.use { sock ->
            sock.soTimeout = 15_000
            val request = try { read(sock.getInputStream()) } catch (e: Exception) {
                Log.d(TAG, "bad request: ${e.message}")
                null
            }
            val out = sock.getOutputStream()
            if (request == null) {
                writeHead(out, 400, "text/plain; charset=utf-8", mapOf("Content-Length" to "11"))
                out.write("bad request".toByteArray()); out.flush()
                return
            }
            val response = try { handler(request) } catch (e: Exception) {
                Log.w(TAG, "handler failed", e)
                Response.Plain(500, "text/plain; charset=utf-8", e.message ?: "error")
            }
            when (response) {
                is Response.Plain -> {
                    writeHead(out, response.status, response.contentType, response.headers + ("Content-Length" to response.body.size.toString()))
                    out.write(response.body)
                    out.flush()
                }
                is Response.Stream -> {
                    sock.soTimeout = 0
                    writeHead(out, response.status, response.contentType, response.headers + ("Cache-Control" to "no-cache"))
                    out.flush()
                    response.write(out)
                    out.flush()
                }
            }
        }
    }

    private fun writeHead(out: OutputStream, status: Int, contentType: String, headers: Map<String, String>) {
        val sb = StringBuilder("HTTP/1.1 $status ${reason(status)}\r\n")
        sb.append("Content-Type: ").append(contentType).append("\r\n")
        for ((k, v) in headers) sb.append(k).append(": ").append(v).append("\r\n")
        sb.append("Connection: close\r\n\r\n")
        out.write(sb.toString().toByteArray(Charsets.ISO_8859_1))
    }

    private fun read(input: InputStream): Request {
        val head = ByteArrayOutputStream()
        var last4 = 0
        while (true) {
            val b = input.read()
            if (b < 0) throw IOException("connection closed in the headers")
            head.write(b)
            last4 = ((last4 shl 8) or b) and 0xFFFFFFFF.toInt()
            if (last4 == 0x0D0A0D0A) break
            if (head.size() > 64 * 1024) throw IOException("headers too large")
        }
        val lines = head.toString(Charsets.ISO_8859_1.name()).split("\r\n").filter { it.isNotEmpty() }
        val parts = lines.first().split(" ")
        if (parts.size < 2) throw IOException("bad request line")
        val method = parts[0].uppercase()
        val target = parts[1]
        val headers = HashMap<String, String>()
        for (line in lines.drop(1)) {
            val i = line.indexOf(':')
            if (i > 0) headers[line.substring(0, i).trim().lowercase()] = line.substring(i + 1).trim()
        }
        val q = target.indexOf('?')
        val path = if (q >= 0) target.substring(0, q) else target
        val query = HashMap<String, String>()
        if (q >= 0) {
            for (pair in target.substring(q + 1).split('&')) {
                if (pair.isEmpty()) continue
                val eq = pair.indexOf('=')
                val k = URLDecoder.decode(if (eq >= 0) pair.substring(0, eq) else pair, "UTF-8")
                val v = if (eq >= 0) URLDecoder.decode(pair.substring(eq + 1), "UTF-8") else ""
                query[k] = v
            }
        }
        val length = headers["content-length"]?.toIntOrNull() ?: 0
        if (length > 8 * 1024 * 1024) throw IOException("body too large")
        val body = ByteArray(length)
        var got = 0
        while (got < length) {
            val n = input.read(body, got, length - got)
            if (n < 0) throw IOException("connection closed in the body")
            got += n
        }
        return Request(method, path, query, headers, body)
    }

    private fun reason(status: Int) = when (status) {
        200 -> "OK"; 202 -> "Accepted"; 204 -> "No Content"
        400 -> "Bad Request"; 401 -> "Unauthorized"; 404 -> "Not Found"; 405 -> "Method Not Allowed"
        else -> if (status >= 500) "Internal Server Error" else "Unknown"
    }

    companion object {
        private const val TAG = "LocalHttp"
    }
}
