package com.elysia.core.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.elysiaDataStore by preferencesDataStore(name = "elysia_settings")
/**
 * Central settings repository backed by DataStore.
 * All persisted Elysia settings live here.
 *
 * Construct with [Context] for the app, or with an explicit [DataStore]
 * instance (e.g. tests).
 */
class SettingsStore(
    private val dataStore: DataStore<Preferences>
) {

    /** Production instance backed by the app's preferences file. */
    constructor(context: Context) : this(
        PreferenceDataStoreFactory.create(
            produceFile = { context.preferencesDataStoreFile("elysia_settings") }
        )
    )


    object Keys {
        val SETUP_COMPLETE = booleanPreferencesKey("setup_complete")
        val SETUP_STEP = intPreferencesKey("setup_step")
        val LOCAL_ONLY = booleanPreferencesKey("local_only")
        val TELEMETRY_ENABLED = booleanPreferencesKey("telemetry_enabled")
        val SELECTED_BACKEND = stringPreferencesKey("selected_backend")
        val SELECTED_MODEL_ID = stringPreferencesKey("selected_model_id")
        val RUNTIME_INSTALLED = booleanPreferencesKey("runtime_installed")
        val MODEL_INSTALLED = booleanPreferencesKey("model_installed")
        val LOG_LEVEL = stringPreferencesKey("log_level")
        val LAST_INFERENCE_MS = longPreferencesKey("last_inference_ms")
        val INFERENCE_COUNT = longPreferencesKey("inference_count")
        val MODEL_UNLOAD_SECONDS = intPreferencesKey("model_unload_seconds")
        val CONVERSATION_HISTORY = stringPreferencesKey("conversation_history")
        val DEVICE_CLASS = stringPreferencesKey("device_class")
        val INSTALL_ERROR = stringPreferencesKey("install_error")
    }

    val isSetupComplete: Flow<Boolean> = dataStore.data.map { it[Keys.SETUP_COMPLETE] ?: false }
    val setupStep: Flow<Int> = dataStore.data.map { it[Keys.SETUP_STEP] ?: 0 }
    val localOnly: Flow<Boolean> = dataStore.data.map { it[Keys.LOCAL_ONLY] ?: true }
    val selectedBackend: Flow<String> = dataStore.data.map { it[Keys.SELECTED_BACKEND] ?: "auto" }
    val selectedModelId: Flow<String> = dataStore.data.map { it[Keys.SELECTED_MODEL_ID] ?: "" }
    val runtimeInstalled: Flow<Boolean> = dataStore.data.map { it[Keys.RUNTIME_INSTALLED] ?: false }
    val modelInstalled: Flow<Boolean> = dataStore.data.map { it[Keys.MODEL_INSTALLED] ?: false }

    suspend fun isSetupCompleteNow(): Boolean = isSetupComplete.first()
    suspend fun localOnlyNow(): Boolean = localOnly.first()
    suspend fun selectedModelIdNow(): String = selectedModelId.first()
    suspend fun selectedBackendNow(): String = selectedBackend.first()
    suspend fun runtimeInstalledNow(): Boolean = runtimeInstalled.first()
    suspend fun modelInstalledNow(): Boolean = modelInstalled.first()

    suspend fun setSetupComplete(value: Boolean) = dataStore.edit { it[Keys.SETUP_COMPLETE] = value }
    suspend fun setSetupStep(value: Int) = dataStore.edit { it[Keys.SETUP_STEP] = value }
    suspend fun setLocalOnly(value: Boolean) = dataStore.edit { it[Keys.LOCAL_ONLY] = value }
    suspend fun setTelemetryEnabled(value: Boolean) = dataStore.edit { it[Keys.TELEMETRY_ENABLED] = value }
    suspend fun setSelectedBackend(value: String) = dataStore.edit { it[Keys.SELECTED_BACKEND] = value }
    suspend fun setSelectedModelId(value: String) = dataStore.edit { it[Keys.SELECTED_MODEL_ID] = value }
    suspend fun setRuntimeInstalled(value: Boolean) = dataStore.edit { it[Keys.RUNTIME_INSTALLED] = value }
    suspend fun setModelInstalled(value: Boolean) = dataStore.edit { it[Keys.MODEL_INSTALLED] = value }
    suspend fun setLastInference(ms: Long, count: Long) =
        dataStore.edit {
            it[Keys.LAST_INFERENCE_MS] = ms
            it[Keys.INFERENCE_COUNT] = count
        }
    suspend fun setModelUnloadSeconds(value: Int) = dataStore.edit { it[Keys.MODEL_UNLOAD_SECONDS] = value }
    suspend fun setDeviceClass(value: String) = dataStore.edit { it[Keys.DEVICE_CLASS] = value }
    suspend fun setInstallError(value: String) = dataStore.edit { it[Keys.INSTALL_ERROR] = value }

    suspend fun lastInference(): Pair<Long, Long> {
        val prefs = dataStore.data.first()
        return (prefs[Keys.LAST_INFERENCE_MS] ?: 0L) to (prefs[Keys.INFERENCE_COUNT] ?: 0L)
    }

    /** Factory-like clear for "Reset Elysia". Keeps nothing user-critical by default. */
    suspend fun reset() {
        dataStore.edit { it.clear() }
    }
}
