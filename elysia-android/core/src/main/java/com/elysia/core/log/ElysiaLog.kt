package com.elysia.core.log

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ConcurrentLinkedDeque

enum class LogSeverity {
    DEBUG, INFO, WARNING, ERROR
}

data class LogEntry(
    val timestamp: Long,
    val component: String,
    val severity: LogSeverity,
    val message: String
) {
    val formatted: String
        get() {
            val time = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.US).format(Date(timestamp))
            return "$time [$severity] ($component) $message"
        }
}

object ElysiaLog {
    private const val MAX_ENTRIES = 1000
    private val ring = ConcurrentLinkedDeque<LogEntry>()

    fun d(component: String, message: String) = push(component, LogSeverity.DEBUG, message)
    fun i(component: String, message: String) = push(component, LogSeverity.INFO, message)
    fun w(component: String, message: String) = push(component, LogSeverity.WARNING, message)
    fun e(component: String, message: String) = push(component, LogSeverity.ERROR, message)

    private fun push(component: String, severity: LogSeverity, message: String) {
        val entry = LogEntry(System.currentTimeMillis(), component, severity, message)
        ring.addLast(entry)
        while (ring.size > MAX_ENTRIES) ring.pollFirst()
        val tag = "Elysia/$component"
        when (severity) {
            LogSeverity.DEBUG -> android.util.Log.d(tag, message)
            LogSeverity.INFO -> android.util.Log.i(tag, message)
            LogSeverity.WARNING -> android.util.Log.w(tag, message)
            LogSeverity.ERROR -> android.util.Log.e(tag, message)
        }
    }

    fun snapshot(): List<LogEntry> = ring.toList()

    fun clear() = ring.clear()

    /** Render a full diagnostic report, scrubbing nothing that should not be exposed. */
    fun renderReport(): String {
        return buildString {
            appendLine("===== ELYSIA LOG REPORT =====")
            appendLine("Generated: ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())}")
            appendLine("Entries: ${ring.size}")
            appendLine("========================================")
            ring.forEach { appendLine(it.formatted) }
        }
    }
}
