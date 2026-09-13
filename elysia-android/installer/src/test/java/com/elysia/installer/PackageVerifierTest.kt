package com.elysia.installer

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File
import java.security.MessageDigest

@RunWith(RobolectricTestRunner::class)
class PackageVerifierTest {

    private fun tempFile(name: String, content: ByteArray): File {
        val f = File.createTempFile(name, ".bin")
        f.writeBytes(content)
        f.deleteOnExit()
        return f
    }

    private fun sha256(bytes: ByteArray): String {
        val md = MessageDigest.getInstance("SHA-256")
        return md.digest(bytes).joinToString("") { "%02x".format(it) }
    }

    @Test
    fun `sha256 matches known digest`() {
        val f = tempFile("known", "hello world".toByteArray())
        // sha256 of "hello world"
        val expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assertEquals(expected, PackageVerifier.sha256(f))
    }

    @Test
    fun `verify accepts matching hash and size`() {
        val bytes = "some model bytes".toByteArray()
        val f = tempFile("okfile", bytes)
        assertTrue(PackageVerifier.verify(f, sha256(bytes), bytes.size.toLong()))
    }

    @Test
    fun `verify rejects wrong hash`() {
        val bytes = "some model bytes".toByteArray()
        val f = tempFile("badhash", bytes)
        assertFalse(PackageVerifier.verify(f, "a".repeat(64), null))    }

    @Test
    fun `verify rejects wrong size`() {
        val bytes = "some model bytes".toByteArray()
        val f = tempFile("badsize", bytes)
        assertFalse(PackageVerifier.verify(f, null, bytes.size + 1L))
    }

    @Test
    fun `verify accepts empty sha256 as no-check`() {
        val bytes = "some model bytes".toByteArray()
        val f = tempFile("emptysha", bytes)
        assertTrue(PackageVerifier.verify(f, "", bytes.size.toLong()))
    }

    @Test
    fun `verify accepts blank sha256 as no-check`() {
        val bytes = "some model bytes".toByteArray()
        val f = tempFile("blanksha", bytes)
        assertTrue(PackageVerifier.verify(f, "   ", bytes.size.toLong()))
        assertTrue(PackageVerifier.verify(f, " \n\t ", null))
    }

    @Test
    fun `verify rejects empty sha256 when file missing`() {
        assertFalse(PackageVerifier.verify(File("/nonexistent/x.bin"), "", null))
    }

    @Test
    fun `verify rejects mismatch even with empty sha256 if size wrong`() {
        val bytes = "some model bytes".toByteArray()
        val f = tempFile("sizestillchecked", bytes)
        assertFalse(PackageVerifier.verify(f, "", bytes.size + 1L))
    }

    @Test
    fun `verifyOrDelete keeps file when sha256 empty`() {
        val bytes = "data".toByteArray()
        val f = tempFile("emptyok", bytes)
        assertTrue(PackageVerifier.verifyOrDelete(f, "", null))
        assertTrue("file should be kept", f.exists())
    }

    @Test
    fun `verify rejects missing file`() {
        assertFalse(PackageVerifier.verify(File("/nonexistent/x.bin"), null, null))
    }

    @Test
    fun `verifyOrDelete removes corrupt file`() {
        val bytes = "data".toByteArray()
        val f = tempFile("corrupt", bytes)
        assertFalse(PackageVerifier.verifyOrDelete(f, "b".repeat(64), null))
        assertFalse("file should be deleted", f.exists())
    }

    @Test
    fun `sha256 of stream works`() {
        val bytes = "streamed".toByteArray()
        val digest = PackageVerifier.sha256(bytes.inputStream())
        assertNotNull(digest)
        assertTrue(digest!!.length == 64)
    }
}
