package io.github.nanomuse.identity

import android.content.Context
import android.graphics.Bitmap
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.core.graphics.drawable.toBitmap
import com.openminis.app.R
import com.openminis.app.agent.SoulMetadata
import com.openminis.app.agent.SoulStore

/**
 * The agent's name and face, for every surface outside the chat screen.
 *
 * SOUL.md is the single source of truth for the name (see [SoulStore]); this object only adds
 * the two things notification code needs: a name that is correct even in a process that never
 * warmed [SoulStore.cachedMetadata], and the red panda as a large-icon bitmap.
 */
object NanoMuseIdentity {

    /** The current name, read from disk so receivers and services get the live value. */
    fun name(context: Context): String {
        val cached = SoulStore.cachedMetadata.value.name.trim()
        val onDisk = SoulStore.load(context)?.metadata?.name?.trim()
        return (onDisk ?: cached).ifEmpty { SoulMetadata.DEFAULT.name }
    }

    /** True until the user (or the agent) has renamed it. */
    fun hasDefaultName(context: Context): Boolean = name(context) == SoulMetadata.DEFAULT.name

    @Volatile private var cachedFace: Bitmap? = null

    /**
     * The idle red panda rasterised for `setLargeIcon`; null if the drawable cannot be inflated.
     * Rasterised once per process: the foreground service rebuilds its notification on every
     * tool change. Any [Context] will do since the drawable is not themed.
     */
    fun face(context: Context): Bitmap? {
        cachedFace?.let { return it }
        val bitmap = runCatching {
            ContextCompat.getDrawable(context.applicationContext, R.drawable.nm_avatar_idle)
                ?.toBitmap(FACE_PX, FACE_PX)
        }.getOrNull()
        cachedFace = bitmap
        return bitmap
    }

    /** Puts the face on a notification the way Muse does: the agent is the sender. */
    fun NotificationCompat.Builder.withFace(context: Context): NotificationCompat.Builder {
        face(context)?.let { setLargeIcon(it) }
        return this
    }

    private const val FACE_PX = 192
}
