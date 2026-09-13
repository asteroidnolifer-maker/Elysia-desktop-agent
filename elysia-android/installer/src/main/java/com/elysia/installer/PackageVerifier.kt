package com.elysia.installer

import java.io.File
import java.io.InputStream
import java.security.MessageDigest

/**
 * Cryptographic package integrity verification.
 * Every downloaded component must be verified before it is used.
 */
object PackageVerifier {

    /** Compute the SHA-256 hex digest of a file. */
    fun sha256(file: File): String? {
        return try {
            file.inputStream().use { sha256(it) }
        } catch (e: Exception) {
            null
        }
    }

    fun sha256(stream: InputStream): String? {
        return try {
            val md = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            var read = stream.read(buffer)
            while (read != -1) {
                md.update(buffer, 0, read)
                read = stream.read(buffer)
            }
            md.digest().joinToString("") { "%02x".format(it) }
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Verify a file against an expected SHA-256 and size.
     * Returns true only if both match (when provided). Empty strings are
     * treated as "no check" so a manifest can ship without a hash.
     */
    fun verify(file: File, expectedSha256: String?, expectedSizeBytes: Long?): Boolean {
        if (!file.exists()) return false
        if (expectedSizeBytes != null && file.length() != expectedSizeBytes) return false
        val sha = expectedSha256?.trim()?.lowercase()
        if (!sha.isNullOrEmpty()) {
            val actual = sha256(file) ?: return false
            if (!actual.equals(sha, ignoreCase = true)) return false
        }
        return true
    }

    /** Verify a file, deleting it immediately on failure. */
    fun verifyOrDelete(file: File, expectedSha256: String?, expectedSizeBytes: Long?): Boolean {
        val ok = verify(file, expectedSha256, expectedSizeBytes)
        if (!ok) file.delete()
        return ok
    }
}
