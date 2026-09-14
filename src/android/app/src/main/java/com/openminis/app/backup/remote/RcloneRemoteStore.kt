package com.openminis.app.backup.remote

import android.content.Context
import com.openminis.app.logging.AppLogger
import com.openminis.app.util.EncryptedPrefsFactory
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.io.File

/**
 * User-configured rclone remotes (SMB / WebDAV / S3 / …) usable as backup
 * destinations. Mirrors `src/ios/Agent/Backup/Remote/RcloneRemoteStore.swift`.
 *
 * ## Where the credentials live
 *
 * rclone's own config file stores passwords "obscured", which is reversible by
 * design (`rclone reveal` undoes it) — so it is NOT protection. Writing a
 * user's NAS password into a file in the app's data dir would be the same
 * mistake §5.4 calls out for backup packages.
 *
 * So the split matches iOS exactly:
 *   - **EncryptedSharedPreferences** (Keystore-backed) holds the secrets —
 *     Android's equivalent of the iOS Keychain.
 *   - **Plain SharedPreferences** holds everything non-secret: name, backend
 *     type, host, share, user, path.
 *   - rclone's in-memory config is populated per launch via `config/create`,
 *     with its config file pointed at a throwaway path so rclone itself
 *     persists nothing.
 *
 * That keeps exactly one copy of each secret, in the place the platform
 * provides for it, and means deleting a remote actually removes the credential.
 */
class RcloneRemoteStore(private val context: Context) {

    /** A configured remote, minus its secret. */
    @Serializable
    data class Remote(
        /** rclone remote name — also the secret-store key. */
        val name: String,
        /** rclone backend type: "smb", "webdav", "s3", "sftp", … */
        val backend: String,
        /** Non-secret backend parameters (host, url, user, share, region…). */
        val params: Map<String, String> = emptyMap(),
        /** Directory inside the remote that backups are written to. */
        val path: String = "",
        val createdAt: Long = 0,
        /**
         * Whether new backups are delivered here.
         *
         * Disabling is NOT deleting: the server stays configured, with its
         * credential, so a user who wants to skip one destination for a while
         * doesn't have to re-enter an address and password to bring it back.
         * Defaults true so remotes stored before this field existed keep working.
         */
        val enabled: Boolean = true,
    ) {
        /** `remote:` as rclone expects it. */
        val fsSpec: String get() = "$name:"
    }

    class StoreException(message: String) : Exception(message)

    private val prefs by lazy { context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE) }
    private val secrets by lazy { EncryptedPrefsFactory.safeCreate(context, SECRETS_PREFS_NAME) }

    var remotes: List<Remote>
        get() = runCatching {
            prefs.getString(KEY_REMOTES, null)?.let { JSON.decodeFromString(REMOTE_LIST, it) }
        }.getOrNull() ?: emptyList()
        private set(value) {
            prefs.edit().putString(KEY_REMOTES, JSON.encodeToString(REMOTE_LIST, value)).apply()
        }

    fun remote(name: String): Remote? = remotes.firstOrNull { it.name == name }

    /** Remotes that new backups should actually be delivered to. */
    val enabledRemotes: List<Remote> get() = remotes.filter { it.enabled }

    // MARK: - Registration

    /** Add a remote. [secret] goes to the encrypted store; everything else to prefs. */
    fun add(name: String, backend: String, params: Map<String, String>, secret: String?, path: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty() || !trimmed.all { it.isLetterOrDigit() || it == '-' || it == '_' }) {
            throw StoreException("Choose a name using letters, numbers, - or _.")
        }
        if (remote(trimmed) != null) {
            throw StoreException("A destination named \"$trimmed\" already exists.")
        }
        if (!secret.isNullOrEmpty()) storeSecret(trimmed, secret)
        remotes = remotes + Remote(
            name = trimmed, backend = backend, params = params,
            path = path, createdAt = System.currentTimeMillis(),
        )
        AppLogger.info(TAG, "[Rclone] remote added: $trimmed ($backend)")
    }

    /** Remove a remote and its credential. */
    fun remove(name: String) {
        remotes = remotes.filterNot { it.name == name }
        secrets.edit().remove(name).apply()
        AppLogger.info(TAG, "[Rclone] remote removed: $name")
    }

    /** Flip a remote on or off without touching its config or credential. */
    fun setEnabled(name: String, on: Boolean) {
        val all = remotes
        if (all.none { it.name == name }) return
        remotes = all.map { if (it.name == name) it.copy(enabled = on) else it }
        AppLogger.info(TAG, "[Rclone] remote '$name' ${if (on) "enabled" else "disabled"}")
    }

    // MARK: - Secrets

    private fun storeSecret(name: String, secret: String) {
        secrets.edit().putString(name, secret).apply()
    }

    private fun loadSecret(name: String): String? = secrets.getString(name, null)

    /**
     * Which parameter carries the secret, per backend. rclone names these
     * differently and there is no generic "password" key, so the mapping is
     * explicit rather than guessed.
     */
    private fun secretKey(backend: String): String = when (backend) {
        "s3" -> "secret_access_key"
        else -> "pass"
    }

    // MARK: - Handing config to rclone

    /**
     * Push every configured remote into rclone's in-memory config.
     *
     * Runs per launch, off the main thread. rclone is told to use a config path
     * under cacheDir so it never writes credentials to a file we would then
     * have to protect — the encrypted store stays the only copy.
     */
    fun syncToRclone() {
        val configPath = File(context.cacheDir, "rclone-ephemeral.conf").absolutePath
        runCatching { RcloneBridge.rpc("config/setpath", mapOf("path" to configPath)) }

        for (r in remotes) {
            val params = r.params.toMutableMap<String, Any?>()
            params["type"] = r.backend
            loadSecret(r.name)?.let { secret ->
                // Obscure is rclone's expected on-the-wire form for passwords.
                // It is NOT encryption — the real protection is that the
                // plaintext lives in the Keystore-backed store and this copy is
                // in-memory only.
                val obscured = runCatching {
                    RcloneBridge.rpc("core/obscure", mapOf("clear" to secret))
                        .optString("obscured").takeIf { it.isNotEmpty() }
                }.getOrNull()
                params[secretKey(r.backend)] = obscured ?: secret
            }
            runCatching {
                RcloneBridge.rpc(
                    "config/create",
                    mapOf(
                        "name" to r.name,
                        "type" to r.backend,
                        "parameters" to params,
                        // Don't let rclone try to run an interactive OAuth flow.
                        "opt" to mapOf("nonInteractive" to true),
                    ),
                )
            }.onFailure {
                AppLogger.error(TAG, "[Rclone] config/create failed for '${r.name}': ${it.message}")
            }
        }
        AppLogger.info(TAG, "[Rclone] synced ${remotes.size} remote(s) into rclone config")
    }

    companion object {
        private const val TAG = "Rclone"
        private const val PREFS_NAME = "backup_rclone_remotes"
        private const val SECRETS_PREFS_NAME = "backup_rclone_secrets"
        private const val KEY_REMOTES = "remotes"
        private val JSON = Json { ignoreUnknownKeys = true; encodeDefaults = true }
        private val REMOTE_LIST = ListSerializer(Remote.serializer())
    }
}
