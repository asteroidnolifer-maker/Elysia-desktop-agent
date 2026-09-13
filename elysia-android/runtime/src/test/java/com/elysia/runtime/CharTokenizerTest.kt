package com.elysia.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CharTokenizerTest {

    private val tokenizer = CharTokenizer.default()

    @Test
    fun `default vocab contains pad unk eos then printable ascii`() {
        assertTrue(tokenizer.vocabSize >= 98) // 3 + 95 printable + newline/tab/cr
        assertEquals(0, CharTokenizer.PAD_ID)
        assertEquals(1, CharTokenizer.UNK_ID)
        assertEquals(2, CharTokenizer.EOS_ID)
    }

    @Test
    fun `encode decode round trips printable text`() {
        val text = "hello world, how are you?"
        val ids = tokenizer.encode(text)
        assertEquals("hello world, how are you?", tokenizer.decode(ids))
    }

    @Test
    fun `unknown chars map to unk`() {
        val ids = tokenizer.encode("héllo\uD83D\uDE00")
        assertTrue("expected some UNK ids", ids.contains(CharTokenizer.UNK_ID))
    }

    @Test
    fun `encode is truncated to max seq`() {
        val longText = "a".repeat(500)
        assertEquals(CharTokenizer.MAX_SEQ, tokenizer.encode(longText).size)
    }

    @Test
    fun `decodeId out of range returns question mark`() {
        assertEquals('?', tokenizer.decodeId(99999))
    }

    @Test
    fun `decode skips invalid ids`() {
        val ids = listOf(1, 0, 2) // unk, pad, eos
        val decoded = tokenizer.decode(ids)
        assertFalse(decoded.isEmpty())
    }
}
