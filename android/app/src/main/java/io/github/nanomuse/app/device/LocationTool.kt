package io.github.nanomuse.app.device

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.location.Geocoder
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.CancellationSignal
import android.os.Looper
import androidx.core.content.getSystemService
import io.github.nanomuse.app.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject
import java.util.Locale
import kotlin.coroutines.resume

/** Where the phone is, through the platform `LocationManager` (no Play services needed). */
class LocationTool(private val context: Context) {
    @SuppressLint("MissingPermission") // checked through Ask.permissions just above each use
    suspend fun locate(accuracy: String, maxAgeSeconds: Int): JSONObject {
        val fine = accuracy != "coarse"
        val wanted = if (fine) arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION) else arrayOf(Manifest.permission.ACCESS_COARSE_LOCATION)
        Ask.require(context, wanted, context.getString(R.string.ask_why_location), "know the phone's location")
        val lm = context.getSystemService<LocationManager>() ?: throw ToolError("no location service")
        val haveFine = Ask.granted(context, Manifest.permission.ACCESS_FINE_LOCATION)
        val providers = lm.getProviders(true).filter { it != LocationManager.PASSIVE_PROVIDER && (haveFine || it != LocationManager.GPS_PROVIDER) }
        if (providers.isEmpty()) throw ToolError("location is turned off on this phone")
        val maxAge = maxAgeSeconds.coerceAtLeast(0) * 1000L
        // a recent fix from any provider is good enough
        val last = providers.mapNotNull { runCatching { lm.getLastKnownLocation(it) }.getOrNull() }
            .filter { System.currentTimeMillis() - it.time <= maxAge }
            .maxByOrNull { it.time }
        val fix = last ?: withTimeoutOrNull(FIX_TIMEOUT_MS) { fresh(lm, orderProviders(providers, haveFine && fine)) }
            ?: throw ToolError("no location fix within ${FIX_TIMEOUT_MS / 1000} s (indoors, or location off)")
        val out = JSONObject()
            .put("latitude", fix.latitude)
            .put("longitude", fix.longitude)
            .put("accuracy_m", if (fix.hasAccuracy()) fix.accuracy.toInt() else JSONObject.NULL)
            .put("age_s", ((System.currentTimeMillis() - fix.time) / 1000).coerceAtLeast(0))
            .put("provider", fix.provider ?: "")
        address(fix)?.let { out.put("address", it) }
        return out
    }

    private fun orderProviders(available: List<String>, preferGps: Boolean): List<String> {
        val order = if (preferGps) listOf("fused", LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER) else listOf("fused", LocationManager.NETWORK_PROVIDER, LocationManager.GPS_PROVIDER)
        return order.filter { it in available } + available.filter { it !in order }
    }

    @SuppressLint("MissingPermission")
    private suspend fun fresh(lm: LocationManager, providers: List<String>): Location? {
        for (p in providers) {
            val loc = withTimeoutOrNull(FIX_TIMEOUT_MS / providers.size.coerceAtLeast(1)) { one(lm, p) }
            if (loc != null) return loc
        }
        return null
    }

    @SuppressLint("MissingPermission")
    private suspend fun one(lm: LocationManager, provider: String): Location? = withContext(Dispatchers.Main) {
        suspendCancellableCoroutine { cont ->
            if (Build.VERSION.SDK_INT >= 30) {
                val signal = CancellationSignal()
                cont.invokeOnCancellation { signal.cancel() }
                lm.getCurrentLocation(provider, signal, context.mainExecutor) { loc -> if (cont.isActive) cont.resume(loc) }
            } else {
                val listener = object : LocationListener {
                    override fun onLocationChanged(location: Location) { if (cont.isActive) cont.resume(location) }
                    @Deprecated("Deprecated in Java") override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) = Unit
                    override fun onProviderEnabled(provider: String) = Unit
                    override fun onProviderDisabled(provider: String) { if (cont.isActive) cont.resume(null) }
                }
                @Suppress("DEPRECATION")
                lm.requestSingleUpdate(provider, listener, Looper.getMainLooper())
                cont.invokeOnCancellation { lm.removeUpdates(listener) }
            }
        }
    }

    /** A street address for the fix, when the phone can look one up; null when it cannot. */
    private suspend fun address(fix: Location): String? {
        if (!Geocoder.isPresent()) return null
        return withTimeoutOrNull(GEOCODE_TIMEOUT_MS) {
            withContext(Dispatchers.IO) {
                try {
                    @Suppress("DEPRECATION")
                    val list = Geocoder(context, Locale.getDefault()).getFromLocation(fix.latitude, fix.longitude, 1)
                    list?.firstOrNull()?.let { a -> (0..a.maxAddressLineIndex).map { a.getAddressLine(it) }.joinToString(", ") }
                } catch (_: Exception) {
                    null
                }
            }
        }
    }

    companion object {
        private const val FIX_TIMEOUT_MS = 25_000L
        private const val GEOCODE_TIMEOUT_MS = 5_000L
    }
}
