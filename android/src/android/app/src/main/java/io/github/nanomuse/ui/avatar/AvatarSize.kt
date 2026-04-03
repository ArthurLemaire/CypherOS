package io.github.nanomuse.ui.avatar

import android.content.Context
import android.content.SharedPreferences
import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.ui.settings.getAppearancePrefs

/**
 * How big the face is on the home header — Muse's *Avatar size* in Settings → Appearance:
 * small, medium, large, extra large, hidden. A global display setting, separate from the
 * profile page where the face itself is changed. Stored in the appearance prefs under
 * [KEY]; the header observes it, so the choice applies at once.
 */
enum class AvatarSize(val id: String, val disc: Dp?, @StringRes val label: Int) {
    SMALL("s", 44.dp, R.string.nm_avatar_size_small),
    MEDIUM("m", 56.dp, R.string.nm_avatar_size_medium),
    LARGE("l", 66.dp, R.string.nm_avatar_size_large),
    EXTRA_LARGE("xl", 76.dp, R.string.nm_avatar_size_extra_large),
    HIDDEN("hidden", null, R.string.nm_avatar_size_hidden);

    val shown: Boolean get() = disc != null

    companion object {
        const val KEY = "nm.avatar_size"
        val DEFAULT = EXTRA_LARGE

        fun byId(id: String?): AvatarSize = entries.firstOrNull { it.id == id } ?: DEFAULT

        fun current(context: Context): AvatarSize = byId(getAppearancePrefs(context).getString(KEY, null))

        fun save(context: Context, size: AvatarSize) {
            getAppearancePrefs(context).edit().putString(KEY, size.id).apply()
        }
    }
}

/** The avatar size setting, observed. */
@Composable
fun rememberAvatarSize(): State<AvatarSize> {
    val context = LocalContext.current
    val state = remember { mutableStateOf(AvatarSize.current(context)) }
    DisposableEffect(Unit) {
        val prefs = getAppearancePrefs(context)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { p, key ->
            if (key == AvatarSize.KEY) state.value = AvatarSize.byId(p.getString(AvatarSize.KEY, null))
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        onDispose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }
    return state
}
