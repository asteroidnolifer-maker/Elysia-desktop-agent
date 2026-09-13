package com.elysia.permissions

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.content.ContextCompat
import com.elysia.core.log.ElysiaLog

/**
 * Permission audit and request tracking.
 * Elysia only requests permissions it actually needs, with an explanation for each.
 */
object PermissionManager {

    const val TAG = "Permissions"

    data class RequiredPermission(
        val permission: String,
        val label: String,
        val reason: String,
        val optional: Boolean = false,
        val requiresSettingsScreen: Boolean = false
    )

    /**
     * The complete set of permissions Elysia may request, each with a real reason.
     * Only permissions with `optional=false` are requested during first-run setup.
     */
    fun requiredPermissions(): List<RequiredPermission> = buildList {
        add(
            RequiredPermission(
                Manifest.permission.INTERNET,
                "Internet",
                "Only used when you explicitly enable online model downloads or online fallback. In Local Only mode no network calls are made."
            )
        )
        add(
            RequiredPermission(
                Manifest.permission.ACCESS_NETWORK_STATE,
                "Network state",
                "Detects connectivity to show offline status honestly."
            )
        )
        if (Build.VERSION.SDK_INT >= 33) {
            add(
                RequiredPermission(
                    Manifest.permission.POST_NOTIFICATIONS,
                    "Notifications",
                    "Optional: lets the assistant report long-running install or inference progress.",
                    optional = true
                )
            )
        }
        add(
            RequiredPermission(
                Manifest.permission.RECEIVE_SMS,
                "SMS (OTP)",
                "Optional: detects one-time codes from SMS so Elysia can offer to fill them into any app.",
                optional = true
            )
        )
    }

    /** Permission strings we actually require at first-run (non-optional). */
    fun nonOptionalPermissions(): List<String> =
        requiredPermissions().filter { !it.optional }.map { it.permission }

    fun isGranted(context: Context, permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    fun grantedPermissions(context: Context): List<String> =
        requiredPermissions().filter { isGranted(context, it.permission) }.map { it.permission }

    fun missingPermissions(context: Context): List<RequiredPermission> =
        requiredPermissions().filter { !isGranted(context, it.permission) }

    /** Persist granted permission state. */
    suspend fun recordGranted(context: Context, settingsStore: com.elysia.core.settings.SettingsStore) {
        val granted = grantedPermissions(context)
        settingsStore.setTelemetryEnabled(false) // ensure no telemetry by default
        ElysiaLog.i(TAG, "recorded granted permissions: $granted")
    }

    /** Full audit string for diagnostics. */
    fun auditReport(context: Context): String {
        return buildString {
            requiredPermissions().forEach { p ->
                val state = if (isGranted(context, p.permission)) "GRANTED" else "NOT GRANTED"
                appendLine("${p.label}: $state (${p.reason})")
            }
        }
    }
}
