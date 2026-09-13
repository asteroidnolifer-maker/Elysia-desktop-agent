package com.elysia.runtime

import com.elysia.core.model.InferenceResult
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LightRuleEngineTest {

    private fun engine() = LightRuleEngine { null }

    @Test
    fun `arithmetic is evaluated`() = runBlocking {
        val chunks = engine().generate("2+3*4", maxTokens = 32).toList()
        val text = chunks.filterIsInstance<InferenceChunk.Token>().joinToString("") { it.text }
        assertTrue("response was: $text", text.contains("14.0"))
    }

    @Test
    fun `parenthesized arithmetic works`() = runBlocking {
        val chunks = engine().generate("(2+3)*4", maxTokens = 32).toList()
        val text = chunks.filterIsInstance<InferenceChunk.Token>().joinToString("") { it.text }
        assertTrue("response was: $text", text.contains("20.0"))
    }

    @Test
    fun `help command returns help text`() = runBlocking {
        val chunks = engine().generate("help", maxTokens = 64).toList()
        val text = chunks.filterIsInstance<InferenceChunk.Token>().joinToString("") { it.text }
        assertTrue(text.contains("Light Engine"))
    }

    @Test
    fun `empty prompt is handled`() = runBlocking {
        val chunks = engine().generate("", maxTokens = 32).toList()
        val done = chunks.filterIsInstance<InferenceChunk.Done>().first()
        assertTrue(done.result.text.isNotBlank())
    }

    @Test
    fun `generation emits done with metadata`() = runBlocking {
        val chunks = engine().generate("who are you", maxTokens = 32).toList()
        val done = chunks.filterIsInstance<InferenceChunk.Done>().first()
        assertEquals("builtin-light", done.result.modelId)
        assertEquals("light", done.result.backend)
        assertTrue(done.result.durationMs >= 0)
    }

    @Test
    fun `device command uses injected summary`() = runBlocking {
        val eng = LightRuleEngine {
            com.elysia.core.model.DeviceSummary(manufacturer = "TestCorp", model = "T-1", sdkInt = 30)
        }
        val chunks = eng.generate("device", maxTokens = 64).toList()
        val text = chunks.filterIsInstance<InferenceChunk.Token>().joinToString("") { it.text }
        assertTrue(text.contains("TestCorp"))
    }
}
