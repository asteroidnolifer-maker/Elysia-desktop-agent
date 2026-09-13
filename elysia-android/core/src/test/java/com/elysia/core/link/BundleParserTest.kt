package com.elysia.core.link

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class BundleParserTest {

    @Test(expected = IllegalArgumentException::class)
    fun `malformed JSON throws`() {
        parseBundle("{ not json")
    }

    @Test(expected = IllegalArgumentException::class)
    fun `missing version throws`() {
        parseBundle("""{"config":{},"scripts":[]}""")
    }

    @Test(expected = IllegalArgumentException::class)
    fun `negative version throws`() {
        parseBundle("""{"version":-1,"config":{}}""")
    }

    @Test
    fun `valid bundle parses`() {
        val json = """{"version":42,"config":{"greeting":"hi"},"scripts":[{"name":"a"}]}"""
        val b = parseBundle(json)
        assertEquals(42L, b.version)
        assertEquals("hi", b.config.optString("greeting"))
        assertEquals(1, b.scripts.length())
        assertEquals(json, b.raw)
    }

    @Test
    fun `missing config and scripts default to empty`() {
        val b = parseBundle("""{"version":0}""")
        assertEquals(0L, b.version)
        assertEquals(0, b.config.length())
        assertEquals(0, b.scripts.length())
    }

    @Test
    fun `version comparison`() {
        assertTrue(isNewer(1, 2))
        assertFalse(isNewer(2, 2))
        assertFalse(isNewer(2, 1))
        assertTrue(isNewer(-1, 0))
    }
}
