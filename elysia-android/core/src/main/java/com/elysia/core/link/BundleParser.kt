package com.elysia.core.link

import org.json.JSONArray
import org.json.JSONObject

data class ParsedBundle(
    val version: Long,
    val config: JSONObject,
    val scripts: JSONArray,
    val raw: String,
)

fun parseBundle(json: String): ParsedBundle {
    val obj = try {
        JSONObject(json)
    } catch (e: Exception) {
        throw IllegalArgumentException("malformed JSON: ${e.message}", e)
    }
    if (!obj.has("version")) throw IllegalArgumentException("missing version")
    val version = obj.optLong("version", -1L)
    if (version < 0) throw IllegalArgumentException("version must be >= 0")
    val config = obj.optJSONObject("config") ?: JSONObject()
    val scripts = obj.optJSONArray("scripts") ?: JSONArray()
    return ParsedBundle(version, config, scripts, json)
}

fun isNewer(cachedVersion: Long, fetchedVersion: Long): Boolean = fetchedVersion > cachedVersion
