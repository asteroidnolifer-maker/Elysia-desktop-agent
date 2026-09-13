package com.elysia.core.log

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class ElysiaLogTest {

    @Before
    fun setUp() {
        ElysiaLog.clear()
    }

    @After
    fun tearDown() {
        ElysiaLog.clear()
    }

    @Test
    fun `entries are captured in order`() {
        ElysiaLog.i("test", "first")
        ElysiaLog.e("test", "second")
        val entries = ElysiaLog.snapshot()
        assertEquals(2, entries.size)
        assertEquals("first", entries[0].message)
        assertEquals(LogSeverity.ERROR, entries[1].severity)
    }

    @Test
    fun `ring buffer is capped`() {
        for (i in 0 until 1100) {
            ElysiaLog.d("test", "msg $i")
        }
        val entries = ElysiaLog.snapshot()
        assertTrue("expected <= 1000 entries, got ${entries.size}", entries.size <= 1000)
        assertTrue(entries.isNotEmpty())
    }

    @Test
    fun `renderReport contains entries`() {
        ElysiaLog.w("test", "hello world")
        val report = ElysiaLog.renderReport()
        assertTrue(report.contains("hello world"))
        assertTrue(report.contains("WARNING"))
    }

    @Test
    fun `formatted entry has timestamp and severity`() {
        val entry = LogEntry(0L, "comp", LogSeverity.INFO, "msg")
        val formatted = entry.formatted
        assertTrue(formatted.contains("[INFO]"))
        assertTrue(formatted.contains("(comp)"))
    }
}
