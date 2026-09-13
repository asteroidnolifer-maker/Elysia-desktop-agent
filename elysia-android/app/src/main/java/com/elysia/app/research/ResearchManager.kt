package com.elysia.app.research

import com.elysia.core.log.ElysiaLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Lightweight research helper. Only used when online mode is enabled.
 * Queries text search engines and returns a small set of results that the
 * assistant can surface. Results are always cached into memory as notes so
 * they stay available offline afterwards.
 */
class ResearchManager {

    private val tag = "ResearchManager"

    data class SearchResult(
        val title: String,
        val url: String,
        val snippet: String
    )

    /**
     * Search using DuckDuckGo's instant-answer + web results. Returns up to [limit] results.
     * Falls back gracefully to an empty list on any error (local-only mode stays quiet).
     */
    suspend fun search(query: String, limit: Int = 5): List<SearchResult> = withContext(Dispatchers.IO) {
        if (query.isBlank()) return@withContext emptyList()
        val results = mutableListOf<SearchResult>()
        try {
            // Instant answers first (structured, fast).
            val enc = URLEncoder.encode(query, "UTF-8")
            val conn = URL("https://api.duckduckgo.com/?q=$enc&format=json&no_html=1&skip_disambig=1")
                .openConnection() as HttpURLConnection
            conn.connectTimeout = 8000
            conn.readTimeout = 8000
            conn.requestMethod = "GET"

            if (conn.responseCode == 200) {
                val body = conn.inputStream.bufferedReader().use { it.readText() }
                conn.disconnect()
                val json = JSONObject(body)
                val abstractText = json.optString("AbstractText")
                val abstractUrl = json.optString("AbstractURL")
                val heading = json.optString("Heading")
                if (abstractText.isNotBlank()) {
                    results.add(
                        SearchResult(
                            title = if (heading.isNotBlank()) heading else query,
                            url = abstractUrl,
                            snippet = abstractText.take(300)
                        )
                    )
                }
                val related = json.optJSONObject("RelatedTopics") ?: JSONObject()
                val topics = related.optJSONArray("Top") ?: JSONArray()
                for (i in 0 until topics.length().coerceAtMost(limit + 2)) {
                    val t = topics.optJSONObject(i) ?: continue
                    val text = t.optString("Text")
                    val url = t.optString("FirstURL")
                    if (text.isNotBlank() && url.isNotBlank()) {
                        results.add(SearchResult(t.optString("Name", text.take(60)), url, text.take(300)))
                    }
                }
                ElysiaLog.i(tag, "ddg instant answers: ${results.size}")
            } else {
                conn.disconnect()
            }
        } catch (e: Exception) {
            ElysiaLog.w(tag, "research error: ${e.message}")
        }
        results.take(limit)
    }
}