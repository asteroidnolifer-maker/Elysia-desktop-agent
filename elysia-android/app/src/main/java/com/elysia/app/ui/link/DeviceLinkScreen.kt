package com.elysia.app.ui.link

import android.content.Context
import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.elysia.app.link.HotUpdateManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Device Link: pair this phone with the Elysia host (laptop) via the 6-char
 * code shown in the desktop app, then control it: status, lock, remote prompt.
 * Everything is token-authenticated over the LAN.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DeviceLinkScreen() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("elysia_link", Context.MODE_PRIVATE) }
    var host by remember { mutableStateOf(prefs.getString("host", "192.168.0.5:8787") ?: "192.168.0.5:8787") }
    var token by remember { mutableStateOf(prefs.getString("token", "") ?: "") }
    var code by remember { mutableStateOf("") }
    var statusText by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    suspend fun api(path: String, method: String, body: String? = null, auth: Boolean = true): String =
        withContext(Dispatchers.IO) {
            val url = URL("http://$host$path")
            val conn = url.openConnection() as HttpURLConnection
            conn.connectTimeout = 5000
            conn.readTimeout = 15000
            conn.requestMethod = method
            if (auth && token.isNotEmpty()) conn.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            conn.disconnect()
            if (code in 200..299) text else "HTTP $code: ${text.take(200)}"
        }

    fun saveToken(t: String) {
        prefs.edit().putString("token", t).apply()
        token = t
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("Device Link — Elysia host", style = MaterialTheme.typography.titleLarge)
        Text(
            "Pair with the laptop: open the desktop app's Device Link panel, copy the elysia:// link, " +
                "enter the 6-char code below. Everything runs over your LAN with token auth.",
            style = MaterialTheme.typography.bodySmall
        )

        OutlinedTextField(
            value = host,
            onValueChange = { host = it },
            label = { Text("Host:port") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        OutlinedTextField(
            value = code,
            onValueChange = { code = it.uppercase() },
            label = { Text("Pairing code (6 chars)") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                enabled = !busy && code.length >= 6,
                onClick = {
                    scope.launch {
                        busy = true
                        statusText = "pairing..."
                        val res = api("/api/pair", "POST", "{\"code\":\"$code\",\"label\":\"android\"}")
                        busy = false
                        if (res.startsWith("{")) {
                            try {
                                val t = JSONObject(res).optString("token", "")
                                if (t.isNotEmpty()) {
                                    saveToken(t)
                                    statusText = "PAIRED. Token saved."
                                } else statusText = res
                            } catch (e: Exception) {
                                statusText = res
                            }
                        } else statusText = res
                    }
                }
            ) { Text("Pair") }
            Button(
                enabled = !busy && token.isNotEmpty(),
                onClick = {
                    scope.launch {
                        busy = true
                        statusText = api("/api/status", "GET")
                        busy = false
                    }
                }
            ) { Text("Status") }
            Button(
                enabled = !busy && token.isNotEmpty(),
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                onClick = {
                    scope.launch {
                        busy = true
                        statusText = api("/api/lock", "POST")
                        busy = false
                    }
                }
            ) { Text("Lock host") }
        }

        if (token.isNotEmpty()) {
            Text("Paired token: ${token.take(12)}…", style = MaterialTheme.typography.labelSmall)
            OutlinedTextField(
                value = remember { mutableStateOf("") }.value,
                onValueChange = {},
                enabled = false,
                label = { Text("Remote prompt (asks on desktop)") },
                modifier = Modifier.fillMaxWidth()
            )
            var prompt by remember { mutableStateOf("") }
            OutlinedTextField(
                value = prompt,
                onValueChange = { prompt = it },
                placeholder = { Text("e.g. summarize my memory") },
                modifier = Modifier.fillMaxWidth()
            )
            Button(
                enabled = !busy && prompt.isNotBlank(),
                onClick = {
                    scope.launch {
                        busy = true
                        statusText = api("/api/prompt", "POST", "{\"type\":\"chat\",\"prompt\":\"$prompt\"}")
                        busy = false
                        prompt = ""
                    }
                }
            ) { Text("Send to host agent") }

            // --- Live link / hot update: pull config+scripts without reinstalling ---
            val hotUpdate = remember { HotUpdateManager(context) }
            var bundleVersion by remember { mutableStateOf(hotUpdate.cachedVersion()) }
            Button(
                enabled = !busy && token.isNotEmpty(),
                onClick = {
                    scope.launch {
                        busy = true
                        statusText = hotUpdate.refresh()
                        bundleVersion = hotUpdate.cachedVersion()
                        busy = false
                    }
                }
            ) { Text(if (bundleVersion >= 0) "Check for updates (v$bundleVersion)" else "Pull live config") }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(
                    onClick = {
                        try {
                            context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                        } catch (_: Exception) {}
                    },
                    modifier = Modifier.weight(1f)
                ) { Text("Notification Access") }
                OutlinedButton(
                    onClick = {
                        try {
                            context.startActivity(Intent("android.settings.QS_TILE_SETTINGS").apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                        } catch (_: Exception) {
                            try { context.startActivity(Intent(Settings.ACTION_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) }) } catch (_: Exception) {}
                        }
                    },
                    modifier = Modifier.weight(1f)
                ) { Text("Add Quick Tile") }
            }
            Text(
                "Quick Tile hint: long-press QS edit (pencil) → drag 'Elysia Link' tile to active area for one-tap host status.",
                style = MaterialTheme.typography.labelSmall
            )
            Text(
                "Live link: edits to store/app-bundle.json on the laptop reach this phone " +
                    "over LAN — no reinstall needed. Also: grant Notification Access and add " +
                    "the 'Elysia Link' tile in Quick Settings for deep OxygenOS integration.",
                style = MaterialTheme.typography.labelSmall
            )

            TextButton(onClick = {
                prefs.edit().remove("token").apply()
                token = ""
                statusText = "unpaired"
            }) { Text("Unpair") }
        }

        Text(statusText, style = MaterialTheme.typography.bodySmall)
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
    }
}