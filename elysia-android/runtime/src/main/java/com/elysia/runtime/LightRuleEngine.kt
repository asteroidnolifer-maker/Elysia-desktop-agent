package com.elysia.runtime

import com.elysia.core.log.ElysiaLog
import com.elysia.core.model.InferenceResult
import com.elysia.core.model.DeviceSummary
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn

/**
 * Lightweight offline engine used when no neural model is installed.
 * This is NOT a neural language model and it clearly says so.
 * It performs real local work: device info, simple math, help, basic utilities.
 */
class LightRuleEngine(private val device: () -> DeviceSummary?) : ElysiaInferenceEngine {

    companion object {
        const val BACKEND_ID = "light"
    }

    override val id = BACKEND_ID
    override val displayName = "Built-in Light Engine (no neural model)"

    override fun isAvailable(): Boolean = true
    override fun isModelLoaded(): Boolean = true

    override suspend fun loadModel(modelPath: String) { /* stateless */ }
    override suspend fun unloadModel() { /* stateless */ }

    override fun generate(prompt: String, maxTokens: Int, temperature: Float, topP: Float): Flow<InferenceChunk> =
        flow {
            val start = System.currentTimeMillis()
            val response = respond(prompt)
            emit(InferenceChunk.Token(response))
            emit(
                InferenceChunk.Done(
                    InferenceResult(
                        text = response,
                        tokens = response.length.toLong(),
                        durationMs = System.currentTimeMillis() - start,
                        backend = id,
                        modelId = "builtin-light"
                    )
                )
            )
        }.flowOn(Dispatchers.Default)

    private fun respond(prompt: String): String {
        val p = prompt.trim()
        return when {
            p.isEmpty() -> "Say something and I'll help with what I can do locally."
            p.equals("help", ignoreCase = true) ||
                p.startsWith("help") || p.contains("what can you do", ignoreCase = true) ->
                helpText()
            p.startsWith("device", ignoreCase = true) || p.contains("my device", ignoreCase = true) ||
                p.contains("about this phone", ignoreCase = true) ->
                deviceText()
            p.contains("who are you", ignoreCase = true) || p.contains("your name", ignoreCase = true) ->
                "I'm Elysia, a local-first AI assistant. No model is installed right now, " +
                    "so I'm running my tiny built-in utility engine. Open Model Manager to install a model."
            isArithmetic(p) -> mathText(p)
            else -> "I'm running in light mode with no neural model installed. " +
                "I can tell you about this device, help with simple math, or show what I can do. " +
                "For real conversation, install a model from Model Manager."
        }
    }

    private fun helpText(): String = buildString {
        appendLine("Local Light Engine — offline, no network.")
        appendLine("Commands I handle right now:")
        appendLine("  device          - show device info")
        appendLine("  help            - this help")
        appendLine("  <math>          - e.g. 2+3*4")
        appendLine("  who are you     - about Elysia")
        appendLine("Install a real model via Model Manager for conversation.")
    }

    private fun deviceText(): String {
        val d = device()
        return if (d == null) "Device info not available." else d.toReportLines().joinToString("\n")
    }

    /** Public access to the safe expression evaluator. Throws on invalid input. */
    fun evaluatePublic(expr: String): Double = evaluate(expr.replace("x", "*").replace("X", "*").replace("÷", "/"))

    private fun isArithmetic(s: String): Boolean =
        Regex("^[0-9+\\-*/().\\s]+$").matches(s)

    private fun mathText(expr: String): String {
        return try {
            val cleaned = expr.replace("x", "*").replace("÷", "/")
            val result = evaluate(cleaned)
            "$cleaned = $result"
        } catch (e: Exception) {
            "Could not evaluate that expression: ${e.message}"
        }
    }

    /** Tiny safe expression evaluator. Supports + - * / ( ). */
    private fun evaluate(expr: String): Double {
        val tokens = mutableListOf<String>()
        val sb = StringBuilder()
        expr.forEach { c ->
            when {
                c.isDigit() || c == '.' -> sb.append(c)
                else -> {
                    if (sb.isNotEmpty()) { tokens.add(sb.toString()); sb.clear() }
                    if (c != ' ') tokens.add(c.toString())
                }
            }
        }
        if (sb.isNotEmpty()) tokens.add(sb.toString())
        return ExprParser(tokens).parse()
    }

    private class ExprParser(private val tokens: List<String>) {
        private var pos = 0

        private fun peek(): String? = if (pos < tokens.size) tokens[pos] else null
        private fun next(): String = tokens[pos++]

        fun parse(): Double = parseExpr()

        private fun parseExpr(): Double {
            var value = parseTerm()
            while (peek() == "+" || peek() == "-") {
                val op = next()
                val rhs = parseTerm()
                value = if (op == "+") value + rhs else value - rhs
            }
            return value
        }

        private fun parseTerm(): Double {
            var value = parseFactor()
            while (peek() == "*" || peek() == "/") {
                val op = next()
                val rhs = parseFactor()
                value = if (op == "*") value * rhs else value / rhs
            }
            return value
        }

        private fun parseFactor(): Double {
            val t = peek() ?: throw IllegalArgumentException("unexpected end")
            if (t == "(") {
                next()
                val v = parseExpr()
                if (next() != ")") throw IllegalArgumentException("missing )")
                return v
            }
            if (t == "-") {
                next()
                return -parseFactor()
            }
            return next().toDouble()
        }
    }

    override suspend fun selfTest(): String? = "light engine ready"
    override fun describe(): String = "Built-in light engine: device info, math, help. Not a neural model."
}
