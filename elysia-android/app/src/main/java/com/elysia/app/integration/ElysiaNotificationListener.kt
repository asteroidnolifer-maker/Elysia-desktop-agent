package com.elysia.app.integration

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.content.Context
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Deep OxygenOS 13 integration: reads device notifications and relays them to
 * the Elysia host over the paired LAN link, so the desktop agent can see (and
 * optionally act on) phone activity. Requires the user to grant Notification
 * Access in system settings — the app deep-links there from Device Link.
 *
 * Privacy: only forwards when "relayNotifications" is enabled in the hot-update
 * bundle config AND an allowlist is empty or contains the package. Nothing is
 * sent while the link is unpaired.
 */
class ElysiaNotificationListener : NotificationListenerService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onListenerConnected() {
        super.onListenerConnected()
        // Mark liveness for the Diagnostics screen.
        getSharedPreferences("elysia_integration", Context.MODE_PRIVATE)
            .edit().putBoolean("notification_listener_connected", true).apply()
    }

    override fun onListenerDisconnected() {
        super.onListenerDisconnected()
        getSharedPreferences("elysia_integration", Context.MODE_PRIVATE)
            .edit().putBoolean("notification_listener_connected", false).apply()
    }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        val ctx = applicationContext
        val hot = ctx.getSharedPreferences("elysia_hotupdate", Context.MODE_PRIVATE)
        val bundle = try {
            JSONObject(hot.getString("bundle", null) ?: return)
        } catch (_: Exception) {
            return
        }
        val cfg = bundle.optJSONObject("config") ?: return
        if (!cfg.optBoolean("relayNotifications", false)) return

        val pkg = sbn.packageName ?: return
        if (pkg == contextPackageName) return
        val allow = cfg.optJSONArray("relayNotificationsAllowlist")
        if (allow != null && allow.length() > 0) {
            var allowed = false
            for (i in 0 until allow.length()) if (allow.optString(i) == pkg) allowed = true
            if (!allowed) return
        }

        val extras = sbn.notification?.extras ?: return
        val title = extras.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.take(120) ?: ""
        val text = extras.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.take(300) ?: ""
        if (title.isEmpty() && text.isEmpty()) return

        scope.launch {
            runCatching { relay(ctx, pkg, title, text) }
        }
    }

    private fun relay(ctx: Context, pkg: String, title: String, text: String) {
        val link = ctx.getSharedPreferences("elysia_link", Context.MODE_PRIVATE)
        val host = link.getString("host", "") ?: return
        val token = link.getString("token", "") ?: return
        val body = JSONObject().apply {
            put("pkg", pkg)
            put("title", title)
            put("text", text)
        }.toString()
        val conn = URL("http://$host/api/app/events").openConnection() as HttpURLConnection
        conn.connectTimeout = 4000
        conn.readTimeout = 10000
        conn.requestMethod = "POST"
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.setRequestProperty("Content-Type", "application/json")
        conn.doOutput = true
        conn.outputStream.use { it.write(body.toByteArray()) }
        conn.responseCode
        conn.disconnect()
    }

    private val contextPackageName: String
        get() = applicationContext.packageName
}
