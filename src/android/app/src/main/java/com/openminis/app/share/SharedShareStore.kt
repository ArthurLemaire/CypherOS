package com.openminis.app.share

import android.content.Context
import com.openminis.app.logging.AppLogger
import org.json.JSONObject
import java.io.File

/**
 * Mirrors iOS Shared/SharedContainerStore.swift. SharedPreferences-backed
 * read/write of [PendingShare]; staged binary attachments live under
 * `filesDir/share_extension/` so the producer (ShareReceiverActivity)
 * can copy ContentResolver streams into a path the consumer can read
 * after the producer activity finishes.
 */
object SharedShareStore {
    private const val TAG = "SharedShareStore"
    private const val PREFS_NAME = "share_prefs"
    private const val KEY_PENDING_SHARE = "pending_share"
    private const val SHARE_DIR = "share_extension"

    fun sharedFileDirectory(context: Context): File =
        File(context.filesDir, SHARE_DIR).apply { mkdirs() }

    fun savePendingShare(context: Context, share: PendingShare) {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_PENDING_SHARE, share.toJson().toString()).apply()
        AppLogger.info(TAG, "saved pending share with ${share.items.size} item(s)")
    }

    fun loadPendingShare(context: Context): PendingShare? {
        val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        val raw = prefs.getString(KEY_PENDING_SHARE, null) ?: return null
        return try {
            PendingShare.fromJson(JSONObject(raw))
        } catch (e: Exception) {
            AppLogger.warning(TAG, "failed to decode pending share: ${e.message}")
            null
        }
    }

    fun clearPendingShare(context: Context) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit().remove(KEY_PENDING_SHARE).apply()
    }

    /** Remove all staged binary attachments. Call after consumption or on stale buffer. */
    fun cleanSharedFiles(context: Context) {
        val dir = sharedFileDirectory(context)
        dir.listFiles()?.forEach { runCatching { it.delete() } }
    }
}
