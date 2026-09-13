package com.elysia.core.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SpellIntentsTest {

    @Test
    fun normalize_stripsPunctuationAndCase() {
        assertEquals("hi there", SpellIntents.normalize("Hi There!!"))
        assertEquals("what's up", SpellIntents.normalize("What's up?"))
        assertEquals("hello world", SpellIntents.normalize("  Hello,  World  "))
    }

    @Test
    fun expandShorthand_handlesTexting() {
        assertEquals("how are you", SpellIntents.expandShorthand("hw r u"))
        assertEquals("what is up", SpellIntents.expandShorthand("sup"))
        assertEquals("thanks", SpellIntents.expandShorthand("thx"))
        assertEquals("who is your name", SpellIntents.expandShorthand("whos ur name"))
    }

    @Test
    fun match_exactHits() {
        assertEquals("hi", SpellIntents.match("hi") ?: "")
        assertEquals("who are you", SpellIntents.match("who are you") ?: "")
        assertEquals("how are you doing", SpellIntents.match("how are you doing") ?: "")
        assertEquals("what can you do", SpellIntents.match("what can you do") ?: "")
    }

    @Test
    fun match_toleratesTypos() {
        assertEquals("hello", SpellIntents.match("helo") ?: "")
        assertEquals("hello", SpellIntents.match("helloo") ?: "")
        assertEquals("hi", SpellIntents.match("hii") ?: "")
        assertEquals("who are you", SpellIntents.match("who r you") ?: "")
        assertEquals("how are you", SpellIntents.match("hw r u") ?: "")
        assertEquals("help", SpellIntents.match("helpp") ?: "")
        assertEquals("what is my name", SpellIntents.match("whats my name") ?: "")
        assertEquals("thank you", SpellIntents.match("thank u") ?: "")
        assertEquals("joke", SpellIntents.match("jok") ?: "")
    }

    @Test
    fun match_tokenLevelFuzzy() {
        assertEquals("how are you doing", SpellIntents.match("how are yu doing") ?: "")
        assertEquals("who are you", SpellIntents.match("who r u") ?: "")
        assertEquals("what is my name", SpellIntents.match("wat my name") ?: "")
        assertEquals("do you remember my name", SpellIntents.match("do u remember my name") ?: "")
    }

    @Test
    fun match_greetingPrefix() {
        assertEquals("hello", SpellIntents.match("hello elysia") ?: "")
        assertEquals("hi", SpellIntents.match("hi there bot") ?: "")
        assertEquals("hey", SpellIntents.match("hey you") ?: "")
    }

    @Test
    fun match_newTargets() {
        assertEquals("i love you", SpellIntents.match("i luv you") ?: "")
        assertEquals("tell me more", SpellIntents.match("tel me mor") ?: "")
        assertEquals("another one", SpellIntents.match("another 1") ?: "")
    }

    @Test
    fun match_rejectsGarbage() {
        assertNull(SpellIntents.match(""))
        assertNull(SpellIntents.match("!!! ###"))
        assertNull(SpellIntents.match("supercalifragilisticexpialidocious"))
    }

    @Test
    fun levenshtein_knownDistances() {
        assertEquals(0, SpellIntents.levenshtein("hi", "hi"))
        assertEquals(1, SpellIntents.levenshtein("hi", "hii"))
        assertEquals(3, SpellIntents.levenshtein("kitten", "sitting"))
        assertEquals(5, SpellIntents.levenshtein("hello", ""))
    }

    @Test
    fun match_shortWordsTolerateTypos() {
        assertEquals("hi", SpellIntents.match("hi") ?: "")
        assertTrue(SpellIntents.match("hii") == "hi")
        // User-visible typos are tolerated: "halo" is a common misspelling of "hello".
        assertEquals("hello", SpellIntents.match("halo") ?: "")
    }
}