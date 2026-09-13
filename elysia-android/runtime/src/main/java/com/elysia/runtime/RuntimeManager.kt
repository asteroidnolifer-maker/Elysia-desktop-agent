package com.elysia.runtime

import android.content.Context
import com.elysia.core.log.ElysiaLog
import com.elysia.core.model.DeviceSummary
import com.elysia.core.model.InferenceResult
import com.elysia.core.settings.SettingsStore
import com.elysia.device.DeviceDetector
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

/**
 * Selects and manages the best inference backend for the current device.
 * Rules:
 *  - If a real model is installed -> use the ONNX engine (auto picks threads).
 *  - Otherwise -> use the honest built-in light engine.
 *  - Model is unloaded when idle to save RAM (configurable).
 */
class RuntimeManager(
    private val context: Context,
    private val settingsStore: SettingsStore,
    private val deviceDetector: DeviceDetector = DeviceDetector(context)
) {

    private val tag = "RuntimeManager"
    private val mutex = Mutex()

    private val onnxEngine = OnnxRuntimeEngine(context)
    private val lightEngine = LightRuleEngine { latestDevice }

    @Volatile
    private var latestDevice: DeviceSummary? = null

    val availableEngines: List<ElysiaInferenceEngine> = listOf(onnxEngine, lightEngine)

    fun refreshDevice() {
        latestDevice = deviceDetector.detect()
    }

    fun deviceInfo(): DeviceSummary? = latestDevice

    /** Current active engine: ONNX if model installed & loadable, else light. */
    suspend fun activeEngine(): ElysiaInferenceEngine {
        mutex.withLock {
            return if (settingsStore.modelInstalledNow() && onnxEngine.isAvailable()) {
                onnxEngine
            } else {
                lightEngine
            }
        }
    }

    /** Load the selected model into the ONNX engine. */
    suspend fun loadSelectedModel(): Boolean {
        mutex.withLock {
            val modelId = settingsStore.selectedModelIdNow()
            if (modelId.isEmpty()) return false
            val modelDir = File(context.filesDir, "elysia_model")
            val model = modelDir.listFiles()?.firstOrNull { it.name == modelId } ?: return false
            if (!model.exists()) return false
            return try {
                onnxEngine.loadModel(model.absolutePath)
                true
            } catch (e: Exception) {
                ElysiaLog.e(tag, "loadSelectedModel failed: ${e.message}")
                false
            }
        }
    }

    suspend fun unloadModel() {
        mutex.withLock { onnxEngine.unloadModel() }
    }

    /** Generate a completion through the active engine. */
    fun generate(
        prompt: String,
        maxTokens: Int = 128,
        temperature: Float = 0.7f,
        topP: Float = 0.9f
    ): Flow<InferenceChunk> {
        return object : Flow<InferenceChunk> {
            override suspend fun collect(collector: kotlinx.coroutines.flow.FlowCollector<InferenceChunk>) {
                val engine = activeEngine()
                engine.generate(prompt, maxTokens, temperature, topP).collect(collector)
            }
        }
    }

    suspend fun selfTest(): String? {
        val engine = activeEngine()
        return engine.selfTest()
    }

    fun describeActiveEngine(): String {
        return if (onnxEngine.isModelLoaded()) onnxEngine.describe() else lightEngine.describe()
    }
}
