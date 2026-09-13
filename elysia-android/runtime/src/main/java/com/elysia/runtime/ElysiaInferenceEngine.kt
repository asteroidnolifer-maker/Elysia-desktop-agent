package com.elysia.runtime

import com.elysia.core.model.InferenceResult
import kotlinx.coroutines.flow.Flow

/**
 * Pluggable local inference engine.
 * Different backends (ONNX CPU, NNAPI, GPU, etc.) implement this interface.
 */
interface ElysiaInferenceEngine {

    val id: String
    val displayName: String

    /** Whether this backend is usable on the current device. */
    fun isAvailable(): Boolean

    /** Whether a model is loaded and ready for inference. */
    fun isModelLoaded(): Boolean

    /** Load a model file for inference. */
    suspend fun loadModel(modelPath: String)

    /** Unload the model, releasing memory. */
    suspend fun unloadModel()

    /**
     * Generate a completion for the given prompt.
     * Returns a flow of streaming tokens plus the final result.
     */
    fun generate(
        prompt: String,
        maxTokens: Int = 64,
        temperature: Float = 0.7f,
        topP: Float = 0.9f
    ): Flow<InferenceChunk>

    /** Run a tiny self-test to confirm the engine works. */
    suspend fun selfTest(): String?

    /** Report current backend configuration details. */
    fun describe(): String
}

sealed interface InferenceChunk {
    data class Token(val text: String) : InferenceChunk
    data class Done(val result: InferenceResult) : InferenceChunk
    data class Error(val message: String) : InferenceChunk
}
