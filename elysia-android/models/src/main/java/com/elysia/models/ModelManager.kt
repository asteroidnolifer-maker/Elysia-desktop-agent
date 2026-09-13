package com.elysia.models

import android.content.Context
import com.elysia.core.log.ElysiaLog
import com.elysia.core.model.DeviceClass
import com.elysia.core.model.ModelProfile
import com.elysia.core.settings.SettingsStore
import com.elysia.device.DeviceDetector
import com.elysia.installer.DownloadManager
import com.elysia.installer.DownloadProgress
import com.elysia.installer.PackageVerifier
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.serialization.json.Json
import java.io.File

/**
 * Manages model metadata, downloads, and verification.
 * Models are stored under filesDir/elysia_model/<id>.
 */
class ModelManager(
    private val context: Context,
    private val settingsStore: SettingsStore,
    private val deviceDetector: DeviceDetector = DeviceDetector(context)
) {

    private val tag = "ModelManager"
    private val json = Json { ignoreUnknownKeys = true }

    fun modelsDir(): File = File(context.filesDir, "elysia_model")

    /** Load the bundled default manifest. */
    fun bundledManifest(): ModelManifest {
        return try {
            val text = context.assets.open("model_manifest.json").bufferedReader().use { it.readText() }
            json.decodeFromString<ModelManifest>(text)
        } catch (e: Exception) {
            ElysiaLog.e(tag, "bundled manifest failed: ${e.message}")
            ModelManifest()
        }
    }

    /** Load a manifest from a file path. */
    fun manifestFromFile(path: String): ModelManifest {
        return try {
            val text = File(path).readText()
            json.decodeFromString<ModelManifest>(text)
        } catch (e: Exception) {
            ElysiaLog.e(tag, "manifest file failed: ${e.message}")
            ModelManifest()
        }
    }

    /** Recommend the best model for the current device. */
    fun recommend(manifest: ModelManifest): ModelEntry? {
        val device = deviceDetector.detect()
        val ram = device.ramTotalMb
        val ranked = manifest.models.sortedWith(
            compareBy<ModelEntry> {
                when (it.profile) {
                    "ULTRA_LIGHT" -> 0
                    "LIGHT" -> 1
                    "BALANCED" -> 2
                    else -> 3
                }
            }.thenBy { it.sizeBytes }
        )
        return ranked.firstOrNull { entry ->
            entry.ramRequirementMb <= ram && isDeviceClassCompatible(device.deviceClass, entry.deviceClassMin)
        } ?: ranked.firstOrNull()
    }

    private fun isDeviceClassCompatible(actual: DeviceClass, min: String): Boolean {
        val rank = mapOf(
            "VERY_LOW" to 0, "LOW" to 1, "MID" to 2, "HIGH" to 3
        )
        val a = rank[actual.name] ?: 1
        val m = rank[min] ?: 1
        return a >= m
    }

    fun installedModels(): List<ModelEntry> {
        val dir = modelsDir()
        if (!dir.exists()) return emptyList()
        return dir.listFiles()?.filter { it.isFile && it.length() > 0 }
            ?.map { f ->
                ModelEntry(
                    id = f.name,
                    name = f.name,
                    version = "installed",
                    sizeBytes = f.length(),
                    sha256 = "",
                    url = "",
                    quantization = "unknown",
                    ramRequirementMb = 0,
                    deviceClassMin = "LOW",
                    profile = "UNKNOWN"
                )
            } ?: emptyList()
    }

    fun isInstalled(modelId: String): Boolean = File(modelsDir(), modelId).exists()

    fun installedModelFile(modelId: String): File = File(modelsDir(), modelId)

    /**
     * Install a model (bundled asset or verified network download).
     * Returns a flow of progress; the model file is atomically placed only after verification.
     */
    suspend fun downloadModel(entry: ModelEntry): Flow<DownloadProgress> = flow {
        val dir = modelsDir()
        dir.mkdirs()
        val target = File(dir, entry.id)
        if (target.exists() && PackageVerifier.verify(target, entry.sha256, entry.sizeBytes)) {
            ElysiaLog.i(tag, "model already installed & verified: ${entry.id}")
            settingsStore.setSelectedModelId(entry.id)
            settingsStore.setModelInstalled(true)
            return@flow
        }

        if (entry.url.startsWith("file:///asset")) {
            // Bundled model asset shipped inside the APK.
            val assetName = "model/${entry.id}"
            val assetSize = try {
                context.assets.openFd(assetName).length
            } catch (e: Exception) {
                -1L
            }
            context.assets.open(assetName).use { input ->
                target.outputStream().use { input.copyTo(it) }
            }
            if (!PackageVerifier.verify(target, entry.sha256, entry.sizeBytes)) {
                target.delete()
                error("Bundled model integrity check failed: ${entry.id}")
            }
            emit(DownloadProgress(target.length(), target.length(), 100))
            ElysiaLog.i(tag, "bundled model installed: ${entry.id}")
        } else {
            DownloadManager().download(entry.url, target, entry.sha256, entry.sizeBytes).collect { p ->
                emit(p)
            }
        }
        settingsStore.setSelectedModelId(entry.id)
        settingsStore.setModelInstalled(true)
        ElysiaLog.i(tag, "model installed: ${entry.id}")
    }.flowOn(Dispatchers.IO)

    /** Remove an installed model. */
    suspend fun removeModel(modelId: String): Boolean {
        val f = File(modelsDir(), modelId)
        val ok = f.delete()
        if (ok) {
            settingsStore.setModelInstalled(false)
            settingsStore.setSelectedModelId("")
            ElysiaLog.i(tag, "model removed: $modelId")
        }
        return ok
    }

    fun storageFreeMb(): Long {
        return try {
            val stat = android.os.StatFs(context.filesDir.absolutePath)
            stat.availableBlocksLong * stat.blockSizeLong / 1024 / 1024
        } catch (e: Exception) {
            0
        }
    }
}
