package com.elysia.core.rom

import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class RomInfoTest {

    @Test
    fun `rom brand never empty`() {
        val brand = RomInfo.detectRomBrand()
        assertTrue(brand.isNotBlank())
        assertNotNull(RomInfo.romVersion())
        assertNotNull(RomInfo.deviceName())
    }
}
