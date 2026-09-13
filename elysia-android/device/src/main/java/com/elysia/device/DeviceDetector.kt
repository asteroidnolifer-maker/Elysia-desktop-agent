package com.elysia.device

import android.app.ActivityManager
import android.content.Context
import android.os.BatteryManager
import android.os.Build
import android.os.Environment
import android.os.PowerManager
import android.os.StatFs
import android.util.DisplayMetrics
import android.view.WindowManager
import com.elysia.core.log.ElysiaLog
import com.elysia.core.model.DeviceClass
import com.elysia.core.model.DeviceSummary
import java.io.File

/**
 * Real device detection. Every value is read from the OS / filesystem.
 * Nothing is hard-coded or faked.
 */
class DeviceDetector(private val context: Context) {

    private val tag = "DeviceDetector"

    /** Refresh and return a full snapshot of the device. */
    fun detect(): DeviceSummary {
        val ram = readRamMb()
        val abis = Build.SUPPORTED_ABIS.toList().ifEmpty { listOf(Build.CPU_ABI ?: "unknown") }
        return DeviceSummary(
            manufacturer = Build.MANUFACTURER ?: "unknown",
            model = Build.MODEL ?: "unknown",
            androidVersion = Build.VERSION.RELEASE ?: "unknown",
            sdkInt = Build.VERSION.SDK_INT,
            abi = Build.SUPPORTED_ABIS.firstOrNull() ?: (Build.CPU_ABI ?: "unknown"),
            supportedAbis = abis,
            cpuCores = Runtime.getRuntime().availableProcessors(),
            cpuArchitecture = readCpuArchitecture(),
            ramTotalMb = ram.first,
            ramAvailableMb = ram.second,
            storageTotalMb = readStorageMb(Environment.getDataDirectory()).first,
            storageAvailableMb = readStorageMb(Environment.getDataDirectory()).second,
            batteryLevel = readBatteryLevel(),
            isCharging = readCharging(),
            thermalState = readThermalState(),
            isRooted = RootDetector.isRooted(),
            isZygiskDetected = RootDetector.isZygiskDetected(),
            gpuInfo = readGpuInfo(),
            deviceClass = DeviceClass.fromRamMb(ram.first)
        )
    }

    private fun readRamMb(): Pair<Long, Long> {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return 0L to 0L
        val mi = ActivityManager.MemoryInfo()
        am.getMemoryInfo(mi)
        return (mi.totalMem / 1024 / 1024) to (mi.availMem / 1024 / 1024)
    }

    private fun readStorageMb(path: File): Pair<Long, Long> {
        return try {
            val stat = StatFs(path.absolutePath)
            val blockSize = stat.blockSizeLong
            val total = stat.blockCountLong * blockSize
            val avail = stat.availableBlocksLong * blockSize
            (total / 1024 / 1024) to (avail / 1024 / 1024)
        } catch (e: Exception) {
            ElysiaLog.w(tag, "storage read failed: ${e.message}")
            0L to 0L
        }
    }

    private fun readBatteryLevel(): Int {
        val bm = context.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager ?: return -1
        return bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
    }

    private fun readCharging(): Boolean {
        return try {
            val intent = context.registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
            val plugged = intent?.getIntExtra(android.os.BatteryManager.EXTRA_PLUGGED, 0) ?: 0
            plugged != 0
        } catch (e: Exception) {
            false
        }
    }

    private fun readThermalState(): String {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val pm = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
                pm?.currentThermalStatus?.toString() ?: "UNKNOWN"
            } else "UNSUPPORTED_PRE_Q"
        } catch (e: Exception) {
            "UNKNOWN"
        }
    }

    private fun readCpuArchitecture(): String {
        return try {
            val abi = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown"
            when {
                abi.contains("arm64") -> "ARM64"
                abi.contains("armeabi") || abi.contains("armv7") || abi.contains("armv8") -> "ARM32"
                abi.contains("x86_64") -> "x86_64"
                abi.contains("x86") -> "x86"
                else -> abi
            }
        } catch (e: Exception) {
            "unknown"
        }
    }

    private fun readGpuInfo(): String {
        val candidates = listOf(
            "/proc/gpuinfo",
            "/sys/class/kgsl/kgsl-3d0/gpu_model",
            "/sys/class/kgsl/kgsl-3d0/gpuinfo",
            "/dri/0"
        )
        for (p in candidates) {
            try {
                val f = File(p)
                if (f.exists()) {
                    val content = f.readText().trim().take(120)
                    if (content.isNotEmpty()) return content
                }
            } catch (_: Exception) {
            }
        }
        return "Unknown"
    }

    /** Display resolution for diagnostics/UI sizing. */
    fun screenInfo(): String {
        return try {
            val wm = context.getSystemService(Context.WINDOW_SERVICE) as? WindowManager
            val dm = DisplayMetrics()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                wm?.defaultDisplay?.getRealMetrics(dm)
            } else {
                @Suppress("DEPRECATION")
                wm?.defaultDisplay?.getMetrics(dm)
            }
            "${dm.widthPixels}x${dm.heightPixels}"
        } catch (e: Exception) {
            "unknown"
        }
    }
}

object RootDetector {
    private val TAG = "RootDetector"

    fun isRooted(): Boolean {
        val paths = arrayOf(
            "/system/app/Superuser.apk",
            "/system/xbin/su",
            "/system/bin/su",
            "/sbin/su",
            "/system/etc/init.d/99SuperSUDaemon",
            "/system/etc/.has_su_daemon",
            "/data/adb/magisk"
        )
        for (p in paths) {
            try {
                if (File(p).exists()) return true
            } catch (_: Exception) {
            }
        }
        return false
    }

    fun isZygiskDetected(): Boolean {
        return try {
            val files = arrayOf(
                "/data/adb/zygisk",
                "/data/adb/modules/zygisk",
                "/data/adb/magisk/zygisk"
            )
            files.any { File(it).exists() }
        } catch (_: Exception) {
            false
        }
    }
}
