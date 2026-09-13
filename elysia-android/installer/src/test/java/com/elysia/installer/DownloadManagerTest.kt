package com.elysia.installer

import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File

@RunWith(RobolectricTestRunner::class)
class DownloadManagerTest {

    @Test
    fun `download fetches content and reports progress`() = runBlocking {
        val payload = ByteArray(200_000) { (it % 251).toByte() }
        val server = MockWebServer()
        val body = Buffer()
        body.write(payload)
        server.enqueue(MockResponse().setBody(body))
        server.start()
        val url = server.url("/model.onnx").toString()
        try {
            val target = File.createTempFile("dltest", ".onnx")
            target.delete()
            val progress = DownloadManager().download(url, target, null, payload.size.toLong()).toList()
            assertTrue(target.exists())
            assertEquals(payload.size.toLong(), target.length())
            assertTrue("no progress reported", progress.isNotEmpty())
            assertEquals(100, progress.last().percent)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun `download verifies sha256 and deletes on mismatch`() = runBlocking {
        val payload = "tampered-bytes".toByteArray()
        val server = MockWebServer()
        val body = Buffer()
        body.write(payload)
        server.enqueue(MockResponse().setBody(body))
        server.start()
        val url = server.url("/bad.onnx").toString()
        try {
            val target = File.createTempFile("dltest", ".onnx")
            target.delete()
            val failed = try {
                DownloadManager().download(url, target, "f".repeat(64), null).toList()
                false
            } catch (e: Exception) {
                true
            }
            assertTrue("expected integrity failure", failed)
            assertTrue(!target.exists())
        } finally {
            server.shutdown()
        }
    }
}
