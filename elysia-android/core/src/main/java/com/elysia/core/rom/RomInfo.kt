package com.elysia.core.rom

import android.os.Build

/**
 * ROM brand detection for Project BigBell and other custom ROMs.
 * Elysia works on any ROM; these values are only used for branding/display.
 */
object RomInfo {
    const val DEFAULT_ROM_BRAND = "AOSP"

    /** Detected custom ROM build fingerprint marker when available. */
    fun detectRomBrand(): String {
        val fp = Build.FINGERPRINT ?: return DEFAULT_ROM_BRAND
        return when {
            fp.contains("bigbell", ignoreCase = true) -> "BigBell"
            fp.contains("lineage", ignoreCase = true) -> "LineageOS"
            fp.contains("graphene", ignoreCase = true) -> "GrapheneOS"
            fp.contains("crDroid", ignoreCase = true) -> "crDroid"
            else -> DEFAULT_ROM_BRAND
        }
    }

    fun romVersion(): String = Build.VERSION.INCREMENTAL ?: "unknown"
    fun deviceName(): String = Build.DEVICE ?: "unknown"
}
