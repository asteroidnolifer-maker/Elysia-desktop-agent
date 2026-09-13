package com.elysia.core.chat

/**
 * Spelling-tolerant intent matching for the ready-made responses.
 *
 * The user may type "helo", "who r u", "hw r u doin", "wht can do"
 * etc. This normalizes common texting shorthand and then fuzzy-matches
 * against known phrases using Levenshtein distance, so a typo still
 * lands on the right canned reply instead of falling through to the
 * (small) neural model.
 */
object SpellIntents {

    private val shorthand = mapOf(
        "r" to "are",
        "u" to "you",
        "ur" to "your",
        "ya" to "you",
        "hw" to "how",
        "wht" to "what",
        "wat" to "what",
        "wut" to "what",
        "waht" to "what",
        "doin" to "doing",
        "gud" to "good",
        "thx" to "thanks",
        "thanx" to "thanks",
        "ty" to "thank you",
        "pls" to "please",
        "plz" to "please",
        "k" to "okay",
        "im" to "i am",
        "ive" to "i have",
        "dont" to "do not",
        "cant" to "cannot",
        "wont" to "will not",
        "wat's" to "what is",
        "whats" to "what is",
        "wats" to "what is",
        "who's" to "who is",
        "whos" to "who is",
        "whr" to "where",
        "wher" to "where",
        "cud" to "could",
        "wud" to "would",
        "shud" to "should",
        "bcz" to "because",
        "cos" to "because",
        "cuz" to "because",
        "n" to "and",
        "abt" to "about",
        "btw" to "by the way",
        "idk" to "i do not know",
        "rn" to "right now",
        "tbh" to "to be honest",
        "hru" to "how are you",
        "hows it going" to "how are you doing",
        "sup" to "what is up",
        "cya" to "see you",
        "gtg" to "got to go",
        "brb" to "be right back",
        "2" to "to",
        "4" to "for"
    )

    private val fuzzyTargets = listOf(
        "hi", "hello", "hey", "hi there", "hello there",
        "good morning", "good afternoon", "good evening",
        "how are you", "how are you doing", "what is up",
        "who are you", "what are you", "your name", "what is your name",
        "what can you do", "help", "help me", "commands",
        "what time is it", "what is the time", "time",
        "what is the date", "date", "today",
        "thank you", "thanks", "bye", "goodbye", "see you",
        "tell me a joke", "joke", "fun fact",
        "what is my name", "do you know my name", "do you remember my name",
        "where am i", "about my device", "device info", "phone specs",
        "are you real", "who made you", "are you a robot",
        "i love you", "tell me more", "another one"
    )

    private val greetingWords = setOf("hi", "hello", "hey")

    /** Lowercase, strip punctuation (keep letters/digits/apostrophes), collapse whitespace. */
    fun normalize(raw: String): String {
        val lower = raw.lowercase().trim()
        val cleaned = lower.map { if (it.isLetterOrDigit() || it == '\'' || it.isWhitespace()) it else ' ' }.joinToString("")
        return cleaned.replace(Regex("\\s+"), " ").trim()
    }

    /** Expand common texting shorthand AFTER normalization ("hw r u" -> "how are you"). */
    fun expandShorthand(normalized: String): String {
        if (normalized.isEmpty()) return normalized
        val words = normalized.split(" ")
        val expanded = words.joinToString(" ") { shorthand[it] ?: it }
        return collapse(expanded)
    }

    private fun collapse(s: String): String {
        var changed: String
        var cur = s
        do {
            changed = cur
            cur = changed.replace(Regex("\\bhow are you are\\b"), "how are you")
        } while (cur != changed)
        return cur.replace(Regex("\\s+"), " ").trim()
    }

    /**
     * Best-effort fuzzy match: returns the closest known phrase if its
     * Levenshtein distance is within tolerance, else null.
     *
     * Matching tiers:
     *  1. exact phrase
     *  2. whole-phrase Levenshtein (a couple of typos)
     *  3. token-level (same word count, each word tolerates a typo):
     *     "how are yu doing" -> "how are you doing"
     *  4. greeting prefix: "hello elysia" / "hey bot" -> greeting
     */
    fun match(input: String): String? {
        val key = normalize(expandShorthand(input))
        if (key.isEmpty()) return null

        val exact = fuzzyTargets.firstOrNull { it == key }
        if (exact != null) return exact

        // Greeting prefix: "hello elysia", "hey bot" -> greeting.
        // Checked before whole-phrase fuzzy so "hey you" isn't matched
        // against "see you".
        val keyWords = key.split(" ")
        if (keyWords.isNotEmpty() && key.length <= 24) {
            val first = keyWords[0]
            if (first in greetingWords) {
                return when (first) {
                    "hi" -> "hi"
                    "hey" -> "hey"
                    else -> "hello"
                }
            }
        }

        var best: String? = null
        var bestScore = Int.MAX_VALUE
        for (target in fuzzyTargets) {
            val dist = levenshtein(key, target)
            val limit = if (target.length <= 3) 1 else maxOf(2, target.length / 3)
            if (dist <= limit && dist < bestScore && key.length <= target.length + 3) {
                best = target
                bestScore = dist
            }
        }
        if (best != null) return best

        // Token-level: identical word count, each word within typo tolerance.
        if (keyWords.size >= 2) {
            for (target in fuzzyTargets) {
                val targetWords = target.split(" ")
                if (keyWords.size != targetWords.size) continue
                var cost = 0
                var ok = true
                for (i in keyWords.indices) {
                    val d = levenshtein(keyWords[i], targetWords[i])
                    val lim = if (targetWords[i].length <= 3) 1 else maxOf(1, targetWords[i].length / 3)
                    if (d > lim) {
                        ok = false
                        break
                    }
                    cost += d
                }
                if (ok && cost <= maxOf(1, targetWords.size / 2)) return target
            }
        }

        return null
    }

    /** Standard Levenshtein distance between two strings. */
    fun levenshtein(a: String, b: String): Int {
        if (a == b) return 0
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length
        val dp = Array(a.length + 1) { IntArray(b.length + 1) }
        for (i in 0..a.length) dp[i][0] = i
        for (j in 0..b.length) dp[0][j] = j
        for (i in 1..a.length) {
            for (j in 1..b.length) {
                val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                dp[i][j] = minOf(
                    dp[i - 1][j] + 1,
                    dp[i][j - 1] + 1,
                    dp[i - 1][j - 1] + cost
                )
            }
        }
        return dp[a.length][b.length]
    }
}