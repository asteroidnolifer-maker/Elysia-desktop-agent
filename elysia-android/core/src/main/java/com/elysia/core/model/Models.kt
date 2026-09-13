package com.elysia.core.model

import kotlinx.serialization.Serializable

/** Coarse classification used to pick the correct runtime/model profile. */
@Serializable
enum class DeviceClass {
    VERY_LOW, LOW, MID, HIGH;

    companion object {
        fun fromRamMb(ramMb: Long): DeviceClass = when {
            ramMb <= 0 -> UNKNOWN
            ramMb <= 2048 -> VERY_LOW
            ramMb <= 3072 -> LOW
            ramMb <= 6144 -> MID
            else -> HIGH
        }

        val UNKNOWN: DeviceClass = LOW
    }
}

/** Model profile: trade-off between capability and resource usage. */
@Serializable
enum class ModelProfile {
    ULTRA_LIGHT, LIGHT, BALANCED, QUALITY
}

/** Result of a single inference call. */
@Serializable
data class InferenceResult(
    val text: String,
    val tokens: Long,
    val durationMs: Long,
    val backend: String,
    val modelId: String,
    val truncated: Boolean = false
)

@Serializable
enum class InstallPhase {
    PREFLIGHT, RUNTIME, MODEL, CONFIGURE, VERIFY, DONE, FAILED
}

@Serializable
data class InstallProgress(
    val phase: InstallPhase,
    val step: Int,
    val totalSteps: Int,
    val message: String,
    val percent: Int
)

/** Device-level info summary shared across modules. */
@Serializable
data class DeviceSummary(
    val manufacturer: String = "",
    val model: String = "",
    val androidVersion: String = "",
    val sdkInt: Int = 0,
    val abi: String = "",
    val supportedAbis: List<String> = emptyList(),
    val cpuCores: Int = 0,
    val cpuArchitecture: String = "",
    val ramTotalMb: Long = 0,
    val ramAvailableMb: Long = 0,
    val storageTotalMb: Long = 0,
    val storageAvailableMb: Long = 0,
    val batteryLevel: Int = -1,
    val isCharging: Boolean = false,
    val thermalState: String = "UNKNOWN",
    val isRooted: Boolean = false,
    val isZygiskDetected: Boolean = false,
    val gpuInfo: String = "Unknown",
    val deviceClass: DeviceClass = DeviceClass.LOW
) {
    fun toReportLines(): List<String> = listOf(
        "Manufacturer: $manufacturer",
        "Model: $model",
        "Android: $androidVersion (API $sdkInt)",
        "ABI: $abi",
        "Supported ABIs: ${supportedAbis.joinToString(", ")}",
        "CPU cores: $cpuCores",
        "CPU arch: $cpuArchitecture",
        "RAM total: ${ramTotalMb} MB",
        "RAM available: ${ramAvailableMb} MB",
        "Storage total: ${storageTotalMb} MB",
        "Storage available: ${storageAvailableMb} MB",
        "Battery: $batteryLevel% (${if (isCharging) "charging" else "not charging"})",
        "Thermal: $thermalState",
        "Rooted: $isRooted",
        "Zygisk: $isZygiskDetected",
        "GPU: $gpuInfo",
        "Device class: $deviceClass"
    )
}
