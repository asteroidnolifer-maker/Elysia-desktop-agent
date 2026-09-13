package com.elysia.runtime

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import com.elysia.core.log.ElysiaLog
import com.elysia.core.model.InferenceResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Real ONNX inference backend using onnxruntime-android.
 *
 * Model contract (used by the bundled ULTRA_LIGHT model and downloadable models):
 *  - input  "input_ids": int64 [1, seq]
 *  - output "logits":    float [1, seq, vocab]
 *
 * A greedy / temperature sampler decodes character-level tokens.
 */
class OnnxRuntimeEngine(
    private val context: android.content.Context,
    private val tokenizer: CharTokenizer = CharTokenizer.default()
) : ElysiaInferenceEngine {

    companion object {
        private const val TAG = "OnnxRuntimeEngine"
        const val BACKEND_ID = "onnx"

        /** A single forward pass should never take this long even on slow hardware. */
        private const val STALL_LIMIT_MS = 20_000L
    }

    override val id = BACKEND_ID
    override val displayName = "ONNX Runtime (CPU)"

    private var env: OrtEnvironment? = null
    private var session: OrtSession? = null
    private var loadedPath: String? = null

    override fun isAvailable(): Boolean = true

    override fun isModelLoaded(): Boolean = session != null

    override suspend fun loadModel(modelPath: String) {
        withContext(Dispatchers.IO) {
            val f = File(modelPath)
            if (!f.exists()) throw IllegalStateException("Model file not found: $modelPath")
            unloadModel()
            val e = OrtEnvironment.getEnvironment()
            val options = OrtSession.SessionOptions()
            // Single-threaded inference: the char model is tiny, and onnxruntime's
            // threaded LSTM kernel can deadlock intermittently on some devices.
            options.setIntraOpNumThreads(1)
            options.setInterOpNumThreads(1)
            val s = e.createSession(f.absolutePath, options)
            env = e
            session = s
            loadedPath = modelPath
            ElysiaLog.i(TAG, "model loaded from $modelPath")
        }
    }

    override suspend fun unloadModel() {
        withContext(Dispatchers.IO) {
            try {
                session?.close()
                session = null
                loadedPath = null
                ElysiaLog.i(TAG, "model unloaded")
            } catch (e: Exception) {
                ElysiaLog.w(TAG, "unload error: ${e.message}")
            }
        }
    }

    override fun generate(
        prompt: String,
        maxTokens: Int,
        temperature: Float,
        topP: Float
    ): Flow<InferenceChunk> = flow {
        val sess = session ?: run {
            emit(InferenceChunk.Error("Model not loaded"))
            return@flow
        }
        val e = env ?: run {
            emit(InferenceChunk.Error("Runtime not initialized"))
            return@flow
        }

        val start = System.currentTimeMillis()
        var generated = 0L
        val sb = StringBuilder()

        try {
            val inputIds = tokenizer.encode(prompt).toMutableList()
            emit(InferenceChunk.Token("")) // signal start of streaming

            // autoregressive generation
            for (i in 0 until maxTokens) {
                val passStart = System.currentTimeMillis()
                val logits = runForward(e, sess, inputIds)
                val passMs = System.currentTimeMillis() - passStart
                if (passMs > STALL_LIMIT_MS) {
                    ElysiaLog.e(TAG, "inference stalled: single pass took ${passMs}ms")
                    emit(InferenceChunk.Error("Inference stalled on this device (pass took ${passMs}ms)"))
                    return@flow
                }
                val nextId = sample(logits, temperature, topP)
                if (nextId == CharTokenizer.EOS_ID) break
                val ch = tokenizer.decodeId(nextId)
                sb.append(ch)
                inputIds.add(nextId)
                generated++
                emit(InferenceChunk.Token(ch.toString()))
                // The model is trained on "user:/assistant:" turns and rarely emits EOS,
                // so stop as soon as it starts a new "user:" turn — the reply is done.
                if (sb.toString().contains("\nuser:")) break
            }
            val duration = System.currentTimeMillis() - start
            emit(
                InferenceChunk.Done(
                    InferenceResult(
                        text = sb.toString(),
                        tokens = generated,
                        durationMs = duration,
                        backend = id,
                        modelId = loadedPath?.substringAfterLast('/') ?: "unknown",
                        truncated = generated >= maxTokens
                    )
                )
            )
        } catch (e: Exception) {
            ElysiaLog.e(TAG, "inference error: ${e.message}")
            emit(InferenceChunk.Error("Inference error: ${e.message}"))
        }
    }.flowOn(Dispatchers.IO)

    /**
     * Runs a forward pass. The engine always sends the last [CharTokenizer.CTX_WINDOW]
     * tokens so the model contract (fixed-window next-char predictor) holds.
     */
    private fun runForward(e: OrtEnvironment, sess: OrtSession, ids: List<Int>): FloatArray {
        val window = ids.takeLast(CharTokenizer.CTX_WINDOW)
            .let { List(CharTokenizer.CTX_WINDOW - it.size) { CharTokenizer.PAD_ID } + it }
        val input = arrayOf(window.map { it.toLong() }.toLongArray())
        OnnxTensor.createTensor(e, input).use { tensor ->
            val result = sess.run(mapOf("input_ids" to tensor))
            val output = result.get(0).value
            result.close()
            // expected shape [1, CTX, vocab]
            val floatOutput = output as Array<Array<FloatArray>>
            val lastStep = floatOutput[0][floatOutput[0].size - 1]
            return lastStep
        }
    }

    private fun sample(logits: FloatArray, temperature: Float, topP: Float): Int {
        // temperature scaling
        val scaled = logits.map { it / temperature.coerceAtLeast(0.01f) }
        // softmax
        val max = scaled.maxOrNull() ?: return 0
        val exps = scaled.map { Math.exp((it - max).toDouble()) }
        val sum = exps.sum()
        val probs = exps.map { (it / sum).toFloat() }

        // top-p (nucleus) filtering
        val indexed = probs.mapIndexed { i, p -> i to p }.sortedByDescending { it.second }
        var cumulative = 0f
        var cutoff = indexed.lastIndex
        for ((i, pair) in indexed.withIndex()) {
            cumulative += pair.second
            if (cumulative >= topP) {
                cutoff = i
                break
            }
        }
        val candidates = indexed.subList(0, cutoff + 1)
        val total = candidates.sumOf { it.second.toDouble() }
        var r = Math.random() * total
        for ((idx, p) in candidates) {
            r -= p
            if (r <= 0) return idx
        }
        return candidates.last().first
    }

    override suspend fun selfTest(): String? {
        return withContext(Dispatchers.IO) {
            if (!isModelLoaded()) "model not loaded"
            else "onnxruntime ready: ${describe()}"
        }
    }

    override fun describe(): String {
        val threads = Runtime.getRuntime().availableProcessors()
        return "ONNX Runtime, intra-op threads=$threads, model=$loadedPath"
    }
}
