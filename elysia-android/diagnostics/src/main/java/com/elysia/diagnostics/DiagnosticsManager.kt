package com.elysia.diagnostics

import android.content.Context
import com.elysia.core.log.ElysiaLog
import com.elysia.core.log.LogEntry
import com.elysia.core.model.DeviceSummary
import com.elysia.core.rom.RomInfo
import com.elysia.core.settings.SettingsStore
import com.elysia.device.DeviceDetector
import com.elysia.models.ModelManager
import com.elysia.runtime.RuntimeManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Runs a full diagnostics pass and produces a report.
 */
class DiagnosticsManager(
    private val context: Context,
    private val deviceDetector: DeviceDetector,
    private val runtimeManager: RuntimeManager,
    private val modelManager: ModelManager,
    private val settingsStore: SettingsStore
) {

    private val tag = "Diagnostics"

    data class DiagnosticsResult(
        val device: DeviceSummary,
        val backend: String,
        val localOnly: Boolean,
        val modelInstalled: Boolean,
        val modelId: String,
        val runtimeInstalled: Boolean,
        val lastInferenceMs: Long,
        val inferenceCount: Long,
        val logCount: Int,
        val thermal: String,
        val root: Boolean,
        val romBrand: String
    )

    /** Perform a real diagnostics sweep. */
    suspend fun run(): DiagnosticsResult = withContext(Dispatchers.IO) {
        ElysiaLog.i(tag, "running diagnostics")
        runtimeManager.refreshDevice()
        val device = runtimeManager.deviceInfo() ?: deviceDetector.detect()
        val (lastMs, count) = settingsStore.lastInference()
        DiagnosticsResult(
            device = device,
            backend = runtimeManager.describeActiveEngine(),
            localOnly = settingsStore.localOnlyNow(),
            modelInstalled = settingsStore.modelInstalledNow(),
            modelId = settingsStore.selectedModelIdNow(),
            runtimeInstalled = settingsStore.runtimeInstalledNow(),
            lastInferenceMs = lastMs,
            inferenceCount = count,
            logCount = ElysiaLog.snapshot().size,
            thermal = device.thermalState,
            root = device.isRooted,
            romBrand = RomInfo.detectRomBrand()
        )
    }

    /** Run a real AI self-test through the active engine. */
    suspend fun runAiTest(): String = withContext(Dispatchers.IO) {
        ElysiaLog.i(tag, "running AI self-test")
        runtimeManager.loadSelectedModel()
        val engine = runtimeManager.activeEngine()
        val result = engine.selfTest()
        val testPrompt = "hi there"
        val sb = StringBuilder()
        sb.appendLine("Engine: ${engine.displayName}")
        sb.appendLine("Self-test: ${result ?: "no result"}")
        try {
            var response = ""
            engine.generate(testPrompt, maxTokens = 16).collect { chunk ->
                when (chunk) {
                    is com.elysia.runtime.InferenceChunk.Token -> response += chunk.text
                    is com.elysia.runtime.InferenceChunk.Done -> response = chunk.result.text
                    is com.elysia.runtime.InferenceChunk.Error -> sb.appendLine("Generate error: ${chunk.message}")
                }
            }
            sb.appendLine("Test response: \"$response\"")
            if (response.isBlank() && result != null) sb.appendLine("Note: engine reported ready but produced empty output")
        } catch (e: Exception) {
            sb.appendLine("AI test exception: ${e.message}")
        }
        sb.appendLine("Done.")
        sb.toString()
    }

    /** Benchmark real inference latency. */
    suspend fun benchmark(prompt: String = "hello elysia", iterations: Int = 3): BenchmarkResult =
        withContext(Dispatchers.IO) {
            ElysiaLog.i(tag, "running benchmark ($iterations iterations)")
            runtimeManager.loadSelectedModel()
            val engine = runtimeManager.activeEngine()
            val latencies = mutableListOf<Long>()
            var tokens = 0L
            repeat(iterations) {
                val start = System.currentTimeMillis()
                var generated = 0L
                engine.generate(prompt, maxTokens = 32).collect { chunk ->
                    when (chunk) {
                        is com.elysia.runtime.InferenceChunk.Token -> generated++
                        is com.elysia.runtime.InferenceChunk.Done -> {
                            generated = chunk.result.tokens
                            tokens = generated
                        }
                        is com.elysia.runtime.InferenceChunk.Error -> {}
                    }
                }
                latencies.add(System.currentTimeMillis() - start)
            }
            val avg = if (latencies.isEmpty()) 0 else latencies.average().toLong()
            val tokensPerSec = if (avg > 0) (tokens * 1000.0 / avg) else 0.0
            val ramMb = Runtime.getRuntime().totalMemory() / 1024 / 1024
            BenchmarkResult(
                engine = engine.displayName,
                avgLatencyMs = avg,
                tokensPerSec = tokensPerSec,
                ramUsedMb = ramMb,
                iterations = iterations
            )
        }

    /** Export a diagnostic report to a file in external/private storage. */
    suspend fun exportReport(result: DiagnosticsResult): File? = withContext(Dispatchers.IO) {
        val dir = File(context.filesDir, "reports")
        dir.mkdirs()
        val file = File(dir, "elysia_diagnostics_${System.currentTimeMillis()}.txt")
        val content = buildString {
            appendLine("===== ELYSIA DIAGNOSTIC REPORT =====")
            appendLine("Generated: ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())}")
            appendLine()
            appendLine("-- Device --")
            result.device.toReportLines().forEach { appendLine(it) }
            appendLine()
            appendLine("-- Runtime --")
            appendLine("Backend: ${result.backend}")
            appendLine("Runtime installed: ${result.runtimeInstalled}")
            appendLine("Local-only mode: ${result.localOnly}")
            appendLine("ROM brand: ${result.romBrand}")
            appendLine()
            appendLine("-- Model --")
            appendLine("Installed: ${result.modelInstalled}")
            appendLine("Selected model: ${result.modelId}")
            appendLine()
            appendLine("-- Inference --")
            appendLine("Last inference: ${result.lastInferenceMs} ms")
            appendLine("Inference count: ${result.inferenceCount}")
            appendLine()
            appendLine("-- System --")
            appendLine("Log entries: ${result.logCount}")
            appendLine("Thermal: ${result.thermal}")
            appendLine("Root: ${result.root}")
        }
        file.writeText(content)
        ElysiaLog.i(tag, "report exported to $file")
        file
    }
}

data class BenchmarkResult(
    val engine: String,
    val avgLatencyMs: Long,
    val tokensPerSec: Double,
    val ramUsedMb: Long,
    val iterations: Int
)
