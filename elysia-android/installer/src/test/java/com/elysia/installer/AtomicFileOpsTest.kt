package com.elysia.installer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

@RunWith(RobolectricTestRunner::class)
class AtomicFileOpsTest {

    private fun tmpDir(): File {
        val dir = File.createTempFile("atomic", "")
        dir.delete()
        dir.mkdirs()
        return dir
    }

    @Test
    fun `stageAndMove places file at target`() {
        val dir = tmpDir()
        val source = File(dir, "source.bin")
        source.writeText("payload")
        val target = File(dir, "target.bin")
        val staging = File(dir, "staging")
        assertTrue(AtomicFileOps.stageAndMove(source, target, staging))
        assertTrue("target should exist", target.exists())
        assertEquals("payload", target.readText())
        assertTrue("staging should be empty", staging.listFiles()?.isEmpty() != false)
    }

    @Test
    fun `replace swaps old file for new`() {
        val dir = tmpDir()
        val old = File(dir, "old.bin")
        val target = File(dir, "target.bin")
        old.writeText("new")
        target.writeText("old")
        assertTrue(AtomicFileOps.replace(old, target))
        assertTrue(target.exists())
        assertEquals("new", target.readText())
    }

    @Test
    fun `stageAndMove fails gracefully on missing source`() {
        val dir = tmpDir()
        val source = File(dir, "nope.bin")
        val target = File(dir, "target.bin")
        val staging = File(dir, "staging")
        assertFalse(AtomicFileOps.stageAndMove(source, target, staging))
        assertFalse(target.exists())
    }
}
