package io.github.nanomuse.app.gui

import android.graphics.Rect
import android.view.accessibility.AccessibilityNodeInfo
import io.github.nanomuse.app.gui.MuseAccessibilityService.Companion.recycleQuietly
import org.json.JSONArray
import org.json.JSONObject

/**
 * The accessibility tree, flattened to what a model can use next to the screenshot: the nodes
 * that say or do something (text, a description, editable, clickable), each with a stable id
 * (its path of child indexes from the root, so the same element keeps its id across two dumps
 * of an unchanged screen), its class, its centre and box in screen pixels, and its flags.
 *
 * Decoration (layouts with nothing to say), nodes off the screen and text past a few dozen
 * characters are left out; the whole thing is capped, because a long list costs more tokens
 * than it saves taps. Web views, Flutter and games expose little or nothing here — that is why
 * the picture stays the first input and the tree the second.
 */
object NodeTree {
    private const val MAX_NODES = 120
    private const val MAX_TEXT = 60
    private const val MAX_DEPTH = 40

    fun dump(root: AccessibilityNodeInfo?, screenWidth: Int, screenHeight: Int): JSONArray {
        val out = JSONArray()
        if (root == null) return out
        val screen = Rect(0, 0, screenWidth, screenHeight)
        walk(root, "0", 0, screen, out, covered = false)
        return out
    }

    /**
     * [covered]: an ancestor is a clickable row that borrowed this subtree's words as its own
     * label (a Settings row is a clickable layout over two plain TextViews), so a node here that
     * only *says* something is left out — it is already on the row's line.
     */
    private fun walk(node: AccessibilityNodeInfo, id: String, depth: Int, screen: Rect, out: JSONArray, covered: Boolean) {
        if (out.length() >= MAX_NODES || depth > MAX_DEPTH) return
        if (!node.isVisibleToUser) return
        val bounds = Rect()
        node.getBoundsInScreen(bounds)
        if (!Rect.intersects(bounds, screen)) return

        var text = node.text?.toString()?.trim().orEmpty()
        val desc = node.contentDescription?.toString()?.trim().orEmpty()
        val hint = node.hintText?.toString()?.trim().orEmpty()
        val does = node.isClickable || node.isLongClickable || node.isEditable || node.isCheckable || node.isScrollable
        var borrowed = false
        val row = node.isClickable || node.isLongClickable || node.isCheckable
        if (row && !node.isEditable && text.isEmpty() && desc.isEmpty() && hint.isEmpty()) {
            text = childWords(node, 0)
            borrowed = text.isNotEmpty()
        }
        val says = text.isNotEmpty() || desc.isNotEmpty() || hint.isNotEmpty()
        val worth = (does || (says && !covered)) && bounds.width() > 0 && bounds.height() > 0
        if (worth) {
            val o = JSONObject()
                .put("id", id)
                .put("class", node.className?.toString()?.substringAfterLast('.') ?: "")
                .put("cx", bounds.centerX())
                .put("cy", bounds.centerY())
                .put("box", JSONArray().put(bounds.left).put(bounds.top).put(bounds.right).put(bounds.bottom))
            if (text.isNotEmpty()) o.put("text", text.take(MAX_TEXT))
            if (desc.isNotEmpty() && desc != text) o.put("desc", desc.take(MAX_TEXT))
            if (hint.isNotEmpty() && hint != text) o.put("hint", hint.take(MAX_TEXT))
            node.viewIdResourceName?.substringAfter('/')?.takeIf { it.isNotEmpty() }?.let { o.put("res", it.take(40)) }
            if (node.isClickable) o.put("clickable", true)
            if (node.isLongClickable) o.put("long_clickable", true)
            if (node.isEditable) o.put("editable", true)
            if (node.isPassword) o.put("password", true)
            if (node.isCheckable) o.put("checked", node.isChecked)
            if (node.isScrollable) o.put("scrollable", true)
            if (node.isFocused) o.put("focused", true)
            if (node.isSelected) o.put("selected", true)
            if (!node.isEnabled) o.put("disabled", true)
            out.put(o)
        }
        val n = node.childCount
        for (i in 0 until n) {
            if (out.length() >= MAX_NODES) break
            val child = node.getChild(i) ?: continue
            try {
                walk(child, "$id.$i", depth + 1, screen, out, covered || borrowed)
            } finally {
                child.recycleQuietly()
            }
        }
    }

    /** The words of the first few descendants that have any, joined — a row's label. */
    private fun childWords(node: AccessibilityNodeInfo, depth: Int): String {
        if (depth > 3) return ""
        val parts = ArrayList<String>(3)
        for (i in 0 until node.childCount) {
            if (parts.size >= 3) break
            val child = node.getChild(i) ?: continue
            try {
                if (!child.isVisibleToUser) continue
                val own = child.text?.toString()?.trim().orEmpty().ifEmpty { child.contentDescription?.toString()?.trim().orEmpty() }
                val words = if (own.isNotEmpty()) own else childWords(child, depth + 1)
                if (words.isNotEmpty()) parts.add(words)
            } finally {
                child.recycleQuietly()
            }
        }
        return parts.joinToString(" · ").take(MAX_TEXT)
    }

    /** The deepest node under (x, y) that is clickable, or the deepest one at all. Caller recycles. */
    fun nodeAt(root: AccessibilityNodeInfo?, x: Int, y: Int): AccessibilityNodeInfo? {
        if (root == null) return null
        var best: AccessibilityNodeInfo? = null
        var bestArea = Int.MAX_VALUE
        fun visit(node: AccessibilityNodeInfo, depth: Int) {
            if (depth > MAX_DEPTH || !node.isVisibleToUser) return
            val b = Rect()
            node.getBoundsInScreen(b)
            if (!b.contains(x, y)) return
            val area = b.width() * b.height()
            if ((node.isClickable || node.isEditable) && area <= bestArea) {
                best?.recycleQuietly()
                best = AccessibilityNodeInfo.obtain(node)
                bestArea = area
            }
            for (i in 0 until node.childCount) {
                val c = node.getChild(i) ?: continue
                try {
                    visit(c, depth + 1)
                } finally {
                    c.recycleQuietly()
                }
            }
        }
        visit(root, 0)
        return best
    }
}
