package com.elysia.app.ui.integration

import android.content.Context
import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import com.elysia.app.link.HotUpdateManager

@Composable
fun IntegrationScreen() {
    val context = LocalContext.current
    var refreshTick by remember { mutableStateOf(0) }

    val notificationGranted = remember(refreshTick) {
        try {
            NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)
        } catch (_: Exception) {
            val flat = Settings.Secure.getString(context.contentResolver, "enabled_notification_listeners") ?: ""
            flat.contains(context.packageName)
        }
    }
    val accessibilityGranted = remember(refreshTick) {
        try {
            val enabled = Settings.Secure.getString(context.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: ""
            enabled.contains(context.packageName)
        } catch (_: Exception) { false }
    }
    val hotUpdate = remember { HotUpdateManager(context) }
    val bundleVersion = remember(refreshTick) { hotUpdate.cachedVersion() }
    val bundleUpdated = remember(refreshTick) { hotUpdate.cached()?.optString("updated", "") ?: "" }
    val notificationPref = remember(refreshTick) {
        context.getSharedPreferences("elysia_integration", Context.MODE_PRIVATE)
            .getBoolean("notification_listener_connected", false)
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text("OxygenOS Integrations", style = MaterialTheme.typography.titleLarge)
        Text(
            "Live status of deep integrations on OnePlus / OxygenOS 13. Grant each permission to unlock its feature.",
            style = MaterialTheme.typography.bodySmall
        )

        IntegrationRow(
            title = "Notification Listener",
            subtitle = if (notificationGranted) "Granted — relaying when bundle allows it" else "Not granted — relay disabled",
            granted = notificationGranted,
            actionLabel = "Open Notification Access",
            onAction = {
                try {
                    context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                } catch (_: Exception) {}
            }
        )
        IntegrationRow(
            title = "Accessibility Service",
            subtitle = if (accessibilityGranted) "Enabled" else "Not enabled — autofill/overlay disabled",
            granted = accessibilityGranted,
            actionLabel = "Open Accessibility Settings",
            onAction = {
                try {
                    context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                } catch (_: Exception) {}
            }
        )
        IntegrationRow(
            title = "Quick Tile — Elysia Link",
            subtitle = "Add via Quick Settings edit (tap pencil, drag Elysia Link tile). Shows host status in shade.",
            granted = null,
            actionLabel = "Open QS Settings",
            onAction = {
                try {
                    context.startActivity(Intent("android.settings.QS_TILE_SETTINGS").apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                } catch (_: Exception) {
                    try {
                        context.startActivity(Intent(Settings.ACTION_SETTINGS).apply { addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                    } catch (_: Exception) {}
                }
            }
        )
        IntegrationRow(
            title = "Hot-Update Bundle",
            subtitle = if (bundleVersion >= 0) "v$bundleVersion${if (bundleUpdated.isNotEmpty()) " — $bundleUpdated" else ""}" else "Not fetched yet — pair then refresh",
            granted = bundleVersion >= 0,
            actionLabel = "Check in Device Link",
            onAction = {}
        )

        if (notificationPref) {
            Text("Listener liveness: connected (onListenerConnected true)", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
        }

        OutlinedButton(onClick = { refreshTick++ }, modifier = Modifier.fillMaxWidth()) {
            Text("Refresh status")
        }
        Text(
            "Tip: after granting Notification Access, return here and tap Refresh. Bundle version updates when the laptop's store/app-bundle.json is bumped and Device Link → Check for updates is pressed (now also auto-refreshes on app launch).",
            style = MaterialTheme.typography.labelSmall
        )
    }
}

@Composable
private fun IntegrationRow(
    title: String,
    subtitle: String,
    granted: Boolean?,
    actionLabel: String,
    onAction: () -> Unit
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                when (granted) {
                    true -> Icon(Icons.Filled.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    false -> Icon(Icons.Filled.Error, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                    null -> {}
                }
                Column(Modifier.weight(1f)) {
                    Text(title, style = MaterialTheme.typography.titleSmall)
                    Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Button(onClick = onAction, modifier = Modifier.fillMaxWidth()) {
                Text(actionLabel)
            }
        }
    }
}
