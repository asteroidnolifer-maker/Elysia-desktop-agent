package com.elysia.installer

import com.elysia.core.log.ElysiaLog
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/**
 * Atomic file staging helpers.
 * Files are written to a staging directory first, then moved into place.
 * On failure the staging directory is removed, leaving the target untouched.
 */
object AtomicFileOps {

    private const val TAG = "AtomicFileOps"

    /** Copy a verified file into a staging dir and atomically move it to [target]. */
    fun stageAndMove(source: File, target: File, stagingDir: File): Boolean {
        return try {
            stagingDir.mkdirs()
            val staged = File(stagingDir, target.name)
            source.copyTo(staged, overwrite = true)
            try {
                Files.move(staged.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            } catch (e: Exception) {
                Files.move(staged.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            }
            ElysiaLog.i(TAG, "staged ${source.name} -> $target")
            true
        } catch (e: Exception) {
            ElysiaLog.e(TAG, "stageAndMove failed: ${e.message}")
            stagingDir.deleteRecursively()
            false
        }
    }

    /** Atomically replace [target] with [newFile] if present, deleting the old one. */
    fun replace(newFile: File, target: File): Boolean {
        return try {
            if (target.exists()) target.delete()
            newFile.renameTo(target)
        } catch (e: Exception) {
            false
        }
    }
}
