package com.elysia.installer

import com.elysia.core.log.ElysiaLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.TimeUnit

data class DownloadProgress(
    val downloadedBytes: Long,
    val totalBytes: Long,
    val percent: Int
)

/**
 * Robust downloader supporting:
 * - interrupted download recovery (resume)
 * - safe temporary files
 * - atomic rename on completion
 * - integrity verification
 */
class DownloadManager(private val client: OkHttpClient = defaultClient()) {

    private val tag = "DownloadManager"

    companion object {
        fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .writeTimeout(60, TimeUnit.SECONDS)
                .build()
    }

    /**
     * Download [url] to [destination] with resume support and SHA-256 verification.
     * Emits progress; throws on failure.
     */
    suspend fun download(
        url: String,
        destination: File,
        expectedSha256: String? = null,
        expectedSizeBytes: Long? = null
    ): Flow<DownloadProgress> = flow {
        destination.parentFile?.mkdirs()
        val partFile = File(destination.parentFile, destination.name + ".part")

        var start = partFile.length()
        ElysiaLog.i(tag, "downloading $url (resume from $start bytes)")

        val request = Request.Builder()
            .url(url)
            .header("Range", "bytes=$start-")
            .build()

        var success = false
        client.newCall(request).execute().use { response ->
            if (response.isSuccessful) {
                success = streamTo(response, partFile, start, response.code == 206) { d, t, p ->
                    emit(DownloadProgress(d, t, p))
                }
            }
        }

        if (!success) {
            // Server did not accept the range (e.g. 200 or 416). Restart from scratch.
            partFile.delete()
            start = 0
            val retryRequest = Request.Builder().url(url).build()
            client.newCall(retryRequest).execute().use { retry ->
                if (!retry.isSuccessful) error("HTTP ${retry.code} for $url")
                success = streamTo(retry, partFile, 0, false) { d, t, p ->
                    emit(DownloadProgress(d, t, p))
                }
            }
        }

        if (!success) error("download failed for $url")

        val ok = PackageVerifier.verify(partFile, expectedSha256, expectedSizeBytes)
        if (!ok) {
            partFile.delete()
            error("Integrity verification failed for $url")
        }

        if (!partFile.renameTo(destination)) {
            destination.delete()
            if (!partFile.renameTo(destination)) error("atomic rename failed for $destination")
        }
        ElysiaLog.i(tag, "download complete: $destination (${destination.length()} bytes)")
    }.flowOn(Dispatchers.IO)

    /**
     * Stream the response body into [file]. When [append] is true the bytes are
     * appended to the existing partial file (HTTP 206 resume).
     * Returns true on success.
     */
    private suspend fun streamTo(
        response: okhttp3.Response,
        file: File,
        startOffset: Long,
        append: Boolean,
        onProgress: suspend (Long, Long, Int) -> Unit
    ): Boolean {
        val body = response.body ?: return false
        val total = if (append) {
            startOffset + body.contentLength()
        } else {
            body.contentLength()
        }.coerceAtLeast(0)

        return try {
            FileOutputStream(file, append).use { out ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                var downloaded = startOffset
                body.byteStream().use { input ->
                    var read = input.read(buffer)
                    while (read != -1) {
                        out.write(buffer, 0, read)
                        downloaded += read
                        if (total > 0) {
                            val pct = ((downloaded * 100) / total).toInt().coerceIn(0, 100)
                            onProgress(downloaded, total, pct)
                        }
                        read = input.read(buffer)
                    }
                }
            }
            true
        } catch (e: Exception) {
            ElysiaLog.w(tag, "stream interrupted: ${e.message}")
            false
        }
    }
}
