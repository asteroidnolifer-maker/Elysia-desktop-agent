package com.elysia.app.integration

import android.content.Context
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Deep OxygenOS 13 integration: a Quick Settings tile ("Elysia Link").
 * Tap = ping the paired laptop (/api/status) and show live state on the tile;
 * long-press opens the app. Works from the OOS 13 shade on any screen.
 */
class ElysiaQuickTile : TileService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onStartListening() {
        super.onStartListening()
        val tile = qsTile ?: return
        val linked = applicationContext
            .getSharedPreferences("elysia_link", Context.MODE_PRIVATE)
            .getString("token", "")?.isNotEmpty() == true
        tile.state = if (linked) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
        tile.subtitle = if (linked) "paired" else "not paired"
        tile.updateTile()
    }

    override fun onClick() {
        super.onClick()
        val tile = qsTile ?: return
        tile.state = Tile.STATE_ACTIVE
        tile.subtitle = "pinging…"
        tile.updateTile()
        scope.launch {
            val result = ping()
            val t = qsTile ?: return@launch
            t.state = Tile.STATE_ACTIVE
            t.subtitle = result
            t.updateTile()
        }
    }

    private fun ping(): String {
        val link = getSharedPreferences("elysia_link", Context.MODE_PRIVATE)
        val host = link.getString("host", "") ?: return "no host"
        val token = link.getString("token", "") ?: return "not paired"
        if (token.isEmpty()) return "not paired"
        return try {
            val conn = URL("http://$host/api/status").openConnection() as HttpURLConnection
            conn.connectTimeout = 3000
            conn.readTimeout = 6000
            conn.requestMethod = "GET"
            conn.setRequestProperty("Authorization", "Bearer $token")
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            conn.disconnect()
            if (code in 200..299) {
                val hostname = JSONObject(text).optString("hostname", "host")
                "$hostname online"
            } else "HTTP $code"
        } catch (e: Exception) {
            "offline: ${e.message?.take(40) ?: "timeout"}"
        }
    }
}
