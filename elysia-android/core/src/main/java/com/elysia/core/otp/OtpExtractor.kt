package com.elysia.core.otp

/**
 * Extracts one-time passwords from SMS text.
 *
 * Targets the common shapes of verification messages:
 *  - "Your code is 123456"
 *  - "OTP: 123456"
 *  - "Do not share 123456"
 *  4-8 digit codes are treated as OTP when they appear with a hint word
 *  (otp, code, verification, verify, one-time, pin, auth, security) or alone.
 */
object OtpExtractor {

    private val HINTS = listOf(
        "otp", "one-time", "one time", "verification", "verify", "verif",
        "code", "pin", "auth", "authentication", "security", "login", "sign-in", "sign in"
    )

    private val CODE_PATTERN = Regex("\\b(\\d{4,8})\\b")
    private val APP_PATTERN = Regex(
        "(?:from|at|for)\\s+([A-Za-z][A-Za-z0-9 ._-]{0,23}?)(?=\\s*:(?!\\d)|\\s+is\\b|\\s+code\\b|\\s+otp\\b|\\s+\\d|\\s*$)",
        RegexOption.IGNORE_CASE
    )

    /** Return the detected OTP, or null if none found. */
    fun extract(body: String): String? {
        val text = body.trim()
        if (text.isEmpty()) return null
        val lower = text.lowercase()

        val hasHint = HINTS.any { lower.contains(it) }
        // If the message claims it is not a code-sharing situation, ignore.
        if (lower.contains("refund") || lower.contains("payment") && !hasHint) return null

        val candidates = CODE_PATTERN.findAll(text).map { it.groupValues[1] }.toList()
        if (candidates.isEmpty()) return null

        // Prefer a code adjacent to a hint word.
        if (hasHint) {
            val hintIndexes = HINTS.mapNotNull { h ->
                lower.indexOf(h).takeIf { it >= 0 }
            }
            val hintStart = hintIndexes.minOrNull() ?: -1
            var best: String? = null
            var bestDist = Int.MAX_VALUE
            candidates.forEach { code ->
                val idx = text.indexOf(code)
                val dist = kotlin.math.abs(idx - hintStart)
                if (dist < bestDist) {
                    bestDist = dist
                    best = code
                }
            }
            return best
        }

        // Otherwise: return the longest code (most likely the OTP).
        return candidates.maxByOrNull { it.length }
    }

    /** Best-effort sender/app name from the message, if mentioned. */
    fun appName(body: String): String? =
        APP_PATTERN.find(body)?.groupValues?.get(1)?.trim()?.takeIf { it.length in 2..25 }
}