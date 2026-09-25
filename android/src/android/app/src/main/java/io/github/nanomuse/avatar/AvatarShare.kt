package io.github.nanomuse.avatar

import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Typeface
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import androidx.core.content.FileProvider
import com.openminis.app.R
import io.github.nanomuse.ui.avatar.AgentMood
import java.io.File

/**
 * Muse's "share my avatar" cards: a pastel card with the character in one of its poses, a
 * speech bubble introducing it, and the app's name. Rendered with Canvas so the picture the
 * user sends is the same on every device, then handed to the system share sheet.
 */
object AvatarShare {
    /** One card design: a background, the pose it shows, an accent for the bubble text. */
    data class Palette(val id: String, val background: Int, val accent: Int, val mood: AgentMood)

    val palettes: List<Palette> = listOf(
        Palette("pink", 0xFFF9D9E3.toInt(), 0xFFB5476A.toInt(), AgentMood.IDLE),
        Palette("blue", 0xFFD6E6FA.toInt(), 0xFF2F5FA8.toInt(), AgentMood.WORKING),
        Palette("yellow", 0xFFFBEFC7.toInt(), 0xFF9A6B12.toInt(), AgentMood.WAITING),
        Palette("purple", 0xFFE4DDF7.toInt(), 0xFF5D44A6.toInt(), AgentMood.HAPPY),
        Palette("green", 0xFFD9F0DF.toInt(), 0xFF2E7D4F.toInt(), AgentMood.ERROR),
    )

    const val WIDTH = 1080
    const val HEIGHT = 1350

    /** The picture for [palette]: the pose if the face has one, otherwise the base picture. */
    fun render(context: Context, palette: Palette, agentName: String, scale: Float = 1f): Bitmap {
        val w = (WIDTH * scale).toInt()
        val h = (HEIGHT * scale).toInt()
        val out = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val c = Canvas(out)
        val s = w / WIDTH.toFloat()
        c.drawColor(palette.background)

        // The character, big, on the lower two thirds.
        val face = faceBitmap(context, palette.mood)
        if (face != null) {
            val target = RectF(0f, 0f, 760f * s, 760f * s)
            val ratio = face.width / face.height.toFloat()
            if (ratio > 1f) target.bottom = target.right / ratio else target.right = target.bottom * ratio
            target.offsetTo((w - target.width()) / 2f, 430f * s + (760f * s - target.height()) / 2f)
            val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
            // Generated faces sit on a white square; a soft shadow and rounded corners
            // make that square read as a card rather than an unmasked photo.
            val radius = 44f * s
            val shadow = Paint(Paint.ANTI_ALIAS_FLAG).apply {
                color = 0x22000000
                maskFilter = android.graphics.BlurMaskFilter(28f * s, android.graphics.BlurMaskFilter.Blur.NORMAL)
            }
            c.drawRoundRect(RectF(target).apply { offset(0f, 14f * s) }, radius, radius, shadow)
            val path = android.graphics.Path().apply { addRoundRect(target, radius, radius, android.graphics.Path.Direction.CW) }
            c.save()
            c.clipPath(path)
            c.drawBitmap(face, null, target, paint)
            c.restore()
        }

        // The speech bubble at the top.
        val bubbleText = context.getString(R.string.nm_avatar_share_bubble, agentName)
        val tp = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
            color = 0xFF1B1B1F.toInt()
            textSize = 42f * s
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.NORMAL)
        }
        val padX = 44f * s
        val padY = 36f * s
        val maxTextWidth = (w - 2 * 120f * s - 2 * padX).toInt()
        val measured = StaticLayout.Builder.obtain(bubbleText, 0, bubbleText.length, tp, maxTextWidth)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setLineSpacing(0f, 1.2f)
            .build()
        // Shrink the bubble to the longest line so a short introduction gets a small tag.
        val textWidth = minOf(maxTextWidth, (measured.maxLineWidth() + 2f).toInt())
        val layout = StaticLayout.Builder.obtain(bubbleText, 0, bubbleText.length, tp, textWidth)
            .setAlignment(Layout.Alignment.ALIGN_CENTER)
            .setLineSpacing(0f, 1.2f)
            .build()
        val bubbleW = textWidth + 2 * padX
        val bubbleH = layout.height + 2 * padY
        val bubble = RectF((w - bubbleW) / 2f, 150f * s, (w + bubbleW) / 2f, 150f * s + bubbleH)
        val white = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; setShadowLayer(18f * s, 0f, 6f * s, 0x22000000) }
        c.drawRoundRect(bubble, 40f * s, 40f * s, white)
        // The little tail toward the character.
        val tail = android.graphics.Path().apply {
            moveTo(w / 2f - 26f * s, bubble.bottom - 2f)
            lineTo(w / 2f, bubble.bottom + 34f * s)
            lineTo(w / 2f + 26f * s, bubble.bottom - 2f)
            close()
        }
        c.drawPath(tail, Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE })
        c.save()
        c.translate(bubble.left + padX, bubble.top + padY)
        layout.draw(c)
        c.restore()

        // Wordmark and tagline at the bottom.
        val brand = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
            color = palette.accent
            textSize = 40f * s
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
            letterSpacing = 0.02f
        }
        c.drawText("nanoMuse", 72f * s, h - 96f * s, brand)
        val tag = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
            color = 0x99000000.toInt()
            textSize = 28f * s
            typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.NORMAL)
        }
        val tagline = context.getString(R.string.nm_avatar_share_tagline)
        c.drawText(tagline, 72f * s, h - 52f * s, tag)
        return out
    }

    private fun StaticLayout.maxLineWidth(): Float {
        var m = 0f
        for (i in 0 until lineCount) m = maxOf(m, getLineWidth(i))
        return m
    }

    private fun faceBitmap(context: Context, mood: AgentMood): Bitmap? {
        val f = if (mood == AgentMood.IDLE) AvatarStore.baseFile() else AvatarStore.moodFile(mood)
        val custom = AvatarStore.decodeBitmap(if (f.exists()) f else AvatarStore.baseFile())
        if (custom != null) return custom
        // No custom face: the built-in character at this mood.
        return runCatching {
            val d = androidx.core.content.ContextCompat.getDrawable(context, mood.drawable) ?: return null
            val size = 900
            val b = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888)
            d.bounds = Rect(0, 0, size, size)
            d.draw(Canvas(b))
            b
        }.getOrNull()
    }

    /** Renders [palette] to the share cache and opens the system share sheet with it. */
    fun share(context: Context, palette: Palette, agentName: String) {
        val bitmap = render(context, palette, agentName)
        val dir = File(context.cacheDir, "share").apply { mkdirs() }
        val file = File(dir, "nanomuse-avatar-${palette.id}.png")
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        val uri = FileProvider.getUriForFile(context, context.packageName + ".fileprovider", file)
        val send = Intent(Intent.ACTION_SEND).apply {
            type = "image/png"
            putExtra(Intent.EXTRA_STREAM, uri)
            putExtra(Intent.EXTRA_TEXT, context.getString(R.string.nm_avatar_share_bubble, agentName) + "\nhttps://github.com/nano-muse/nanoMuse")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        val chooser = Intent.createChooser(send, context.getString(R.string.nm_avatar_share_title)).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        runCatching { context.startActivity(chooser) }
    }
}
