package com.openminis.app.backup.remote

import com.openminis.app.logging.AppLogger
import com.openminis.rclone.gomobile.Gomobile
import org.json.JSONObject

/**
 * Kotlin access to the bundled rclone library, mirroring
 * `src/ios/Agent/Backup/Remote/RcloneBridge.swift`.
 *
 * Everything rclone can do goes through ONE entry point — a JSON-RPC call:
 *
 *     RcloneBridge.rpc("operations/list", mapOf("fs" to "remote:", "remote" to "dir"))
 *
 * That is rclone's own librclone API, not an interface invented here. The
 * binding comes from `deps/rclone-mobile/gomobile`, built by
 * `deps/build_rclone_android.sh`; backends linked in are decided by
 * `deps/rclone-mobile/backends/backends.go` — the same list the iOS build uses,
 * so a remote configured on one platform behaves identically on the other.
 *
 * Every call blocks on network I/O. Callers must be off the main thread.
 */
object RcloneBridge {

    private const val TAG = "Rclone"

    /** rclone's RPC returns an HTTP-style status; anything but 200 is a failure. */
    class RPCException(val status: Int, payload: String) :
        Exception(extractMessage(status, payload)) {
        companion object {
            // rclone puts a human-readable reason in `error` when it can.
            private fun extractMessage(status: Int, payload: String): String =
                runCatching { JSONObject(payload).optString("error").takeIf { it.isNotEmpty() } }
                    .getOrNull() ?: "rclone RPC failed (status $status)"
        }
    }

    @Volatile
    private var initialised = false

    /** Idempotent. Must run before any RPC; safe to call from anywhere. */
    @Synchronized
    fun initializeIfNeeded() {
        if (initialised) return
        Gomobile.rcloneInitialize()
        initialised = true
        AppLogger.info(TAG, "[Rclone] initialised")
    }

    /**
     * One RPC call. [params] is encoded to JSON; the reply is decoded from it.
     *
     * Values may be primitives, maps, or lists — `config/create` needs a nested
     * object for `parameters` and `opt`, so a flat string map isn't enough.
     */
    fun rpc(method: String, params: Map<String, Any?> = emptyMap()): JSONObject {
        initializeIfNeeded()
        val input = JSONObject(params.mapValues { toJsonValue(it.value) }).toString()
        val result = Gomobile.rcloneRPC(method, input)
        val output = result.output ?: ""
        // gobind maps Go's int to a Java long here.
        if (result.status != 200L) throw RPCException(result.status.toInt(), output)
        return runCatching { JSONObject(output) }.getOrDefault(JSONObject())
    }

    private fun toJsonValue(value: Any?): Any = when (value) {
        null -> JSONObject.NULL
        is Map<*, *> -> JSONObject(value.entries.associate { (k, v) -> k.toString() to toJsonValue(v) })
        is List<*> -> org.json.JSONArray(value.map { toJsonValue(it) })
        else -> value
    }

    /**
     * Smoke test: prove the Go runtime starts and answers on-device.
     *
     * `core/version` needs no config, no network and no credentials, so a
     * successful reply isolates exactly one thing — that the linked-in Go
     * runtime is alive inside this app, next to PRoot.
     */
    fun smokeTest(): String = try {
        val v = rpc("core/version")
        val version = v.optString("version", "?")
        val goVersion = v.optString("goVersion", "?")
        val arch = v.optString("arch", "?")
        AppLogger.info(TAG, "[Rclone] smoke OK version=$version go=$goVersion arch=$arch")
        "rclone $version ($goVersion, $arch)"
    } catch (e: Exception) {
        AppLogger.error(TAG, "[Rclone] smoke FAILED: ${e.message}")
        "FAILED: ${e.message}"
    }

    /** Backends actually compiled in — confirms the trim did what it claims. */
    fun supportedBackends(): List<String> = runCatching {
        val providers = rpc("config/providers").optJSONArray("providers") ?: return emptyList()
        (0 until providers.length())
            .mapNotNull { providers.optJSONObject(it)?.optString("Name") }
            .filter { it.isNotEmpty() }
            .sorted()
    }.getOrDefault(emptyList())
}
