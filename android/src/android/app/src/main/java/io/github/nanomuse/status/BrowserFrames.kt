package io.github.nanomuse.status

import android.graphics.Bitmap
import android.util.LruCache

/**
 * The last live frame seen for each browser tool block, so a finished step that saved no
 * screenshot of its own (get_text, execute_js, a refused type…) keeps showing the page it
 * ended on instead of a globe. In memory only; a fresh process falls back as before.
 */
object BrowserFrames {
    private val cache = object : LruCache<String, Bitmap>(24 * 1024) {
        override fun sizeOf(key: String, value: Bitmap): Int = (value.byteCount / 1024).coerceAtLeast(1)
    }

    fun remember(blockId: String, frame: Bitmap) { cache.put(blockId, frame) }

    fun get(blockId: String): Bitmap? = cache.get(blockId)?.takeIf { !it.isRecycled }
}
