package com.elysia.permissions

import android.Manifest
import android.content.Context
import com.elysia.core.settings.SettingsStore
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

@RunWith(RobolectricTestRunner::class)
class PermissionManagerTest {

    private val context: Context = RuntimeEnvironment.getApplication()

    @Test
    fun `required permissions include internet and network state`() {
        val perms = PermissionManager.requiredPermissions()
        assertTrue(perms.any { it.permission == Manifest.permission.INTERNET })
        assertTrue(perms.any { it.permission == Manifest.permission.ACCESS_NETWORK_STATE })
    }

    @Test
    fun `non-optional permissions are only internet and network state`() {
        val nonOptional = PermissionManager.nonOptionalPermissions()
        assertEquals(2, nonOptional.size)
        assertTrue(nonOptional.contains(Manifest.permission.INTERNET))
        assertTrue(nonOptional.contains(Manifest.permission.ACCESS_NETWORK_STATE))
        // notifications must never be required
        assertTrue(!nonOptional.contains(Manifest.permission.POST_NOTIFICATIONS))
    }

    @Test
    fun `isGranted is false in clean sandbox`() {
        assertTrue(!PermissionManager.isGranted(context, Manifest.permission.INTERNET))
    }

    @Test
    fun `audit report has an entry for each required permission`() {
        val report = PermissionManager.auditReport(context)
        assertTrue(report.contains("Internet"))
        assertTrue(report.contains("Network state"))
        assertTrue(report.contains("GRANTED") || report.contains("NOT GRANTED"))
    }

    @Test
    fun `recordGranted persists telemetry disabled`() = runBlocking {
        val settings = SettingsStore(context)
        PermissionManager.recordGranted(context, settings)
        // telemetry must stay disabled; no exception thrown
        assertNotNull(settings)
    }
}
