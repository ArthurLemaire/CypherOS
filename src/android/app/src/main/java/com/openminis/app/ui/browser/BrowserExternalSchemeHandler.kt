package com.openminis.app.ui.browser

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.core.net.toUri
import com.openminis.app.logging.AppLogger

/**
 * Centralized router for non-http(s) URL schemes that show up inside our
 * various WebViews. Without this, schemes like `intent://`, `market://`,
 * `tel:`, `mailto:`, `sms:`, `geo:` would be handed to the page-load
 * pipeline and the user would see `net::ERR_UNKNOWN_URL_SCHEME` (T134).
 *
 * Behavior:
 *
 *   * `intent://...` — parsed via `Intent.parseUri(_, URI_INTENT_SCHEME)`
 *     so `action`, `category`, and extras encoded after `#Intent;` get
 *     restored. We strip `FLAG_ACTIVITY_NEW_DOCUMENT` and the package
 *     selector (set when the spec restricts to one app) before fanning
 *     out via `startActivity`. If no app handles the intent, the spec's
 *     `browser_fallback_url` extra is honoured; absent that, a Toast.
 *   * Other "open in app" schemes — fired as a plain `ACTION_VIEW`
 *     against the URI. ActivityNotFoundException → Toast.
 *   * `http`, `https`, `about`, `file` — return `false` so the WebView
 *     loads them normally.
 *
 * Returns `true` when the URL has been (or should have been) routed
 * away from the WebView; the caller should also return `true` from
 * `shouldOverrideUrlLoading` in that case.
 */
object BrowserExternalSchemeHandler {
    private const val TAG = "BrowserExternalScheme"

    private val INTERNAL_SCHEMES = setOf("http", "https", "about", "file")

    /**
     * `intent://` schemes that require Intent.parseUri (NOT plain
     * ACTION_VIEW) to round-trip correctly.
     */
    private val INTENT_SCHEME = "intent"
    private val ANDROID_APP_SCHEME = "android-app"

    /**
     * "Open in another app" schemes that are fine to dispatch as a bare
     * `ACTION_VIEW` (the system will resolve to dialer / mail / maps /
     * Play Store etc.). `intent`/`android-app` are NOT in this list —
     * they need `parseUri`.
     */
    private val EXTERNAL_VIEW_SCHEMES = setOf(
        "tel", "mailto", "sms", "smsto", "mms", "mmsto",
        "geo", "market", "whatsapp", "tg", "weixin",
    )

    /**
     * Whether [url] is an external scheme that this handler would route
     * away from any in-app WebView. Used by callers (e.g. the chat-link
     * resolver) that need to decide *before* a `loadUrl` whether the
     * URL should bypass the in-app browser entirely — `loadUrl` doesn't
     * trigger `shouldOverrideUrlLoading` for the initial URL, so an
     * `intent://...` would otherwise reach the WebView and produce
     * `ERR_UNKNOWN_URL_SCHEME` (T136).
     */
    fun shouldHandleExternally(url: String?): Boolean {
        if (url.isNullOrBlank()) return false
        val uri = runCatching { url.toUri() }.getOrNull() ?: return false
        val scheme = uri.scheme?.lowercase() ?: return false
        return scheme !in INTERNAL_SCHEMES
    }

    /**
     * Decide whether [uri] should be intercepted and, if so, route it to
     * an external Activity. Returns `true` when the WebView should NOT
     * load the URL itself.
     */
    fun handle(context: Context, url: String?): Boolean {
        if (url.isNullOrBlank()) return false
        val uri = runCatching { url.toUri() }.getOrNull() ?: return false
        return handle(context, uri)
    }

    fun handle(context: Context, uri: Uri?): Boolean {
        if (uri == null) return false
        val scheme = uri.scheme?.lowercase() ?: return false
        if (scheme in INTERNAL_SCHEMES) return false

        return when (scheme) {
            INTENT_SCHEME, ANDROID_APP_SCHEME -> handleIntentScheme(context, uri.toString())
            in EXTERNAL_VIEW_SCHEMES -> handleViewIntent(context, uri)
            else -> {
                // T318: Unknown app schemes (e.g. `toutiao://`, `snssdk141://`,
                // `weibo://`) used to fall through to ACTION_VIEW, which jumps
                // the user out into the matching app and breaks the agent's
                // browsing context (and surprises users who tapped a link
                // inside our in-app browser). Block them: swallow the load
                // and surface a Toast so the page still feels handled.
                AppLogger.info(TAG, "blocked unknown scheme: $scheme (uri=$uri)")
                Toast.makeText(
                    context,
                    "Blocked link to external app ($scheme)",
                    Toast.LENGTH_SHORT,
                ).show()
                true
            }
        }
    }

    private fun handleIntentScheme(context: Context, url: String): Boolean {
        val intent = runCatching {
            Intent.parseUri(url, Intent.URI_INTENT_SCHEME)
        }.getOrElse {
            AppLogger.warning(TAG, "parseUri failed for $url: ${it.message}")
            return true
        }

        // Drop selector + browser-only flags so the system resolves the
        // intent against any matching Activity, not just the package the
        // page suggested (which is often unavailable).
        intent.selector = null
        intent.addCategory(Intent.CATEGORY_BROWSABLE)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        val fallback = intent.getStringExtra("browser_fallback_url")

        try {
            context.startActivity(intent)
            return true
        } catch (_: ActivityNotFoundException) {
            AppLogger.info(TAG, "No app handles $url; fallback=${fallback != null}")
        } catch (e: Exception) {
            AppLogger.warning(TAG, "startActivity failed for $url: ${e.message}")
        }

        // No handler — try fallback URL if the page provided one.
        if (!fallback.isNullOrBlank()) {
            try {
                val fb = Intent(Intent.ACTION_VIEW, fallback.toUri()).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                context.startActivity(fb)
                return true
            } catch (e: Exception) {
                AppLogger.warning(TAG, "fallback $fallback failed: ${e.message}")
            }
        }

        Toast.makeText(
            context,
            "No app available to open this link.",
            Toast.LENGTH_SHORT,
        ).show()
        return true
    }

    private fun handleViewIntent(context: Context, uri: Uri): Boolean {
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        try {
            context.startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(
                context,
                "No app available to open this link.",
                Toast.LENGTH_SHORT,
            ).show()
        } catch (e: Exception) {
            AppLogger.warning(TAG, "ACTION_VIEW failed for $uri: ${e.message}")
        }
        return true
    }
}
