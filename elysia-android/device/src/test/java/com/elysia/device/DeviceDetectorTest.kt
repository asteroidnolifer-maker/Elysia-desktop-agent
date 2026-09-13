package com.elysia.device

import android.content.Context
import com.elysia.core.model.DeviceClass
import com.elysia.core.model.DeviceSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class DeviceDetectorTest {

    private val context: Context = RuntimeEnvironment.getApplication()

    @Test
    fun `detect returns a populated summary`() {
        val d = DeviceDetector(context).detect()
        assertTrue("manufacturer blank", d.manufacturer.isNotBlank())
        assertTrue("model blank", d.model.isNotBlank())
        assertTrue("sdk too low", d.sdkInt >= 24)
        assertTrue("no abis", d.supportedAbis.isNotEmpty())
        assertTrue(d.ramTotalMb >= 0)
        assertTrue(d.storageTotalMb >= 0)
        assertNotNull(d.deviceClass)
    }

    @Test
    fun `screen info is either dimensions or unknown`() {
        val info = DeviceDetector(context).screenInfo()
        assertTrue("screen info was '$info'", info.matches(Regex("\\d+x\\d+")) || info == "unknown")
    }

    @Test
    fun `device class matches ram`() {
        val d: DeviceSummary = DeviceDetector(context).detect()
        assertEquals(DeviceClass.fromRamMb(d.ramTotalMb), d.deviceClass)
    }

    @Test
    fun `root detection does not throw`() {
        // should return false in the robolectric sandbox without throwing
        assertFalse(RootDetector.isRooted())
        assertFalse(RootDetector.isZygiskDetected())
    }
}
