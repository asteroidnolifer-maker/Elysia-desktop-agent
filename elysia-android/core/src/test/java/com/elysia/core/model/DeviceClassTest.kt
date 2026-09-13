package com.elysia.core.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class DeviceClassTest {

    @Test
    fun `fromRamMb classifies low ram as very low`() {
        assertEquals(DeviceClass.VERY_LOW, DeviceClass.fromRamMb(1024))
        assertEquals(DeviceClass.VERY_LOW, DeviceClass.fromRamMb(2048))
    }

    @Test
    fun `fromRamMb classifies mid ram`() {
        assertEquals(DeviceClass.LOW, DeviceClass.fromRamMb(3000))
        assertEquals(DeviceClass.MID, DeviceClass.fromRamMb(4096))
        assertEquals(DeviceClass.HIGH, DeviceClass.fromRamMb(8192))
    }

    @Test
    fun `fromRamMb falls back on zero or negative`() {
        assertEquals(DeviceClass.LOW, DeviceClass.fromRamMb(0))
        assertEquals(DeviceClass.LOW, DeviceClass.fromRamMb(-5))
    }

    @Test
    fun `deviceSummary report has all lines`() {
        val d = DeviceSummary(
            manufacturer = "Samsung",
            model = "SM-M015G",
            sdkInt = 30,
            ramTotalMb = 3072,
            ramAvailableMb = 1500,
            storageTotalMb = 32768,
            storageAvailableMb = 10240,
            deviceClass = DeviceClass.LOW
        )
        val lines = d.toReportLines()
        assertTrue(lines.any { it.contains("Manufacturer: Samsung") })
        assertTrue(lines.any { it.contains("RAM total: 3072 MB") })
        assertTrue(lines.any { it.contains("Device class: LOW") })
    }

    @Test
    fun `inference result serializable defaults`() {
        val r = InferenceResult(text = "hi", tokens = 3, durationMs = 5, backend = "onnx", modelId = "m")
        assertEquals(false, r.truncated)
    }
}
