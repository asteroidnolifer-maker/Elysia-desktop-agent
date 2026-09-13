package com.elysia.core.memory

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import com.elysia.core.log.ElysiaLog
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Persistent memory for the assistant.
 *
 * Facts the user shares ("my name is X", "I like Y") and notes are stored
 * locally and recalled across sessions, so Elysia behaves like it remembers
 * the user. Everything stays on-device; nothing is synced anywhere.
 */
class MemoryStore(private val dataStore: DataStore<Preferences>) {

    @Serializable
    data class Memory(
        val facts: Map<String, String> = emptyMap(),
        val notes: List<String> = emptyList(),
        val lastSeenName: String = ""
    )

    companion object {
        private const val KEY = "elysia_memory"
        private val json = Json { ignoreUnknownKeys = true }

        /** Production instance backed by the app's memory preferences file. */
        fun create(context: Context): MemoryStore =
            MemoryStore(
                PreferenceDataStoreFactory.create(
                    produceFile = { context.preferencesDataStoreFile("elysia_memory") }
                )
            )
    }

    private val memory: Flow<Memory> = dataStore.data.map { prefs ->
        val raw = prefs[stringPreferencesKey(KEY)] ?: return@map Memory()
        try {
            json.decodeFromString<Memory>(raw)
        } catch (e: Exception) {
            ElysiaLog.e("MemoryStore", "decode failed: ${e.message}")
            Memory()
        }
    }

    suspend fun snapshot(): Memory = memory.first()

    /** Remember a fact, e.g. ("name", "Alex"). Overwrites existing key. */
    suspend fun remember(key: String, value: String) {
        val k = key.trim().lowercase()
        if (k.isEmpty()) return
        dataStore.edit { prefs ->
            val m = current(prefs)
            prefs[stringPreferencesKey(KEY)] = json.encodeToString(Memory.serializer(), m.copy(facts = m.facts + (k to value.trim())))
        }
    }

    suspend fun forget(key: String) {
        val k = key.trim().lowercase()
        dataStore.edit { prefs ->
            val m = current(prefs)
            prefs[stringPreferencesKey(KEY)] = json.encodeToString(Memory.serializer(), m.copy(facts = m.facts - k))
        }
    }

    suspend fun addNote(note: String) {
        val n = note.trim()
        if (n.isEmpty()) return
        dataStore.edit { prefs ->
            val m = current(prefs)
            val notes = (listOf(n) + m.notes).take(200)
            prefs[stringPreferencesKey(KEY)] = json.encodeToString(Memory.serializer(), m.copy(notes = notes))
        }
    }

    suspend fun setName(name: String) {
        if (name.isBlank()) return
        remember("name", name)
        dataStore.edit { prefs ->
            val m = current(prefs)
            prefs[stringPreferencesKey(KEY)] = json.encodeToString(Memory.serializer(), m.copy(lastSeenName = name.trim()))
        }
    }

    suspend fun lookup(key: String): String? {
        val k = key.trim().lowercase()
        return snapshot().facts[k]
    }

    private fun current(prefs: Preferences): Memory {
        val raw = prefs[stringPreferencesKey(KEY)] ?: return Memory()
        return try {
            json.decodeFromString<Memory>(raw)
        } catch (e: Exception) {
            Memory()
        }
    }
}
