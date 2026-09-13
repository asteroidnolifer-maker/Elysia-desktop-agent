package com.elysia.app.link

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import com.elysia.core.link.isNewer
import com.elysia.core.link.parseBundle
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Live link to the Elysia host: pulls the hot-update bundle from the companion
 * server (`/api/app/bundle`) so behavior/config/scripts change on the phone
 * WITHOUT reinstalling the APK. The laptop is the source of truth; this caches
 * the last bundle locally so everything still works offline.
 *
 * Flow: edit store/app-bundle.json on the laptop (bump `version`) -> phone
 * refreshes (app launch, manual button, or tile) -> new config applies instantly.
 */
class HotUpdateManager(private val context: Context) {

    data class Bundle(
        val version: Long,
        val updated: String,
        val note: String,
        val config: JSONObject,
        val scripts: JSONArray,
        val raw: String,
    )

    private val prefs = context.getSharedPreferences("elysia_hotupdate", Context.MODE_PRIVATE)

    /** Cached bundle (last successful pull), as raw JSON. */
    fun cached(): JSONObject? {
        val raw = prefs.getString("bundle", null) ?: return null
        return try {
            JSONObject(raw)
        } catch (_: Exception) {
            null
        }
    }

    fun cachedVersion(): Long = prefs.getLong("version", -1L)

    fun configValue(key: String, fallback: String): String {
        val cfg = cached()?.optJSONObject("config") ?: return fallback
        return cfg.optString(key, fallback)
    }

    /**
     * Pull the latest bundle from the host. Returns a user-readable result.
     * host/token come from the Device Link prefs ("elysia_link").
     */
    suspend fun refresh(): String = withContext(Dispatchers.IO) {
        val link = context.getSharedPreferences("elysia_link", Context.MODE_PRIVATE)
        val host = link.getString("host", "") ?: ""
        val token = link.getString("token", "") ?: ""
        if (host.isEmpty() || token.isEmpty()) {
            return@withContext "Link not paired yet — pair in Device Link first."
        }
        try {
            val conn = URL("http://$host/api/app/bundle").openConnection() as HttpURLConnection
            conn.connectTimeout = 4000
            conn.readTimeout = 10000
            conn.requestMethod = "GET"
            conn.setRequestProperty("Authorization", "Bearer $token")
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            conn.disconnect()
            if (code !in 200..299) return@withContext "HTTP $code: ${text.take(160)}"
            val parsed = try {
                parseBundle(text)
            } catch (e: IllegalArgumentException) {
                return@withContext "Bundle malformed (${e.message})"
            }
            val version = parsed.version
            val prev = cachedVersion()
            prefs.edit()
                .putString("bundle", parsed.raw)
                .putLong("version", version)
                .putLong("fetchedAt", System.currentTimeMillis())
                .apply()
            when {
                prev < 0 -> "Bundle v$version cached (first sync)."
                isNewer(prev, version) -> "UPDATED: v$prev → v$version. New config applied."
                else -> "Already up to date (v$version)."
            }
        } catch (e: Exception) {
            "Live link failed: ${e.message?.take(120) ?: e.javaClass.simpleName}"
        }
    }
}
