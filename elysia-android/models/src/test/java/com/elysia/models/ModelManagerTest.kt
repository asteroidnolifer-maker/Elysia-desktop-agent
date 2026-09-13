package com.elysia.models

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.emptyPreferences
import com.elysia.core.settings.SettingsStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import java.io.File

@RunWith(RobolectricTestRunner::class)
class ModelManagerTest {

    private val context: Context = RuntimeEnvironment.getApplication()

    private fun settingsStore(): SettingsStore = SettingsStore(InMemoryDataStore())

    /** In-memory DataStore avoids platform file locking issues on Windows. */
    private class InMemoryDataStore : DataStore<Preferences> {
        private val state = MutableStateFlow<Preferences>(emptyPreferences())
        override val data: Flow<Preferences> = state
        override suspend fun updateData(transform: suspend (t: Preferences) -> Preferences): Preferences {
            val updated = transform(state.value)
            state.value = updated
            return updated
        }
    }

    private fun sampleManifest(): ModelManifest = ModelManifest(
        schemaVersion = 1,
        models = listOf(
            ModelEntry(
                id = "ultra.onnx",
                name = "Ultra",
                version = "1",
                sizeBytes = 100,
                sha256 = "",
                url = "file:///asset",
                quantization = "float32",
                ramRequirementMb = 256,
                deviceClassMin = "VERY_LOW",
                profile = "ULTRA_LIGHT"
            ),
            ModelEntry(
                id = "heavy.onnx",
                name = "Heavy",
                version = "1",
                sizeBytes = 1_000_000,
                sha256 = "",
                url = "https://example.com/heavy.onnx",
                quantization = "float32",
                ramRequirementMb = 6000,
                deviceClassMin = "HIGH",
                profile = "QUALITY"
            )
        )
    )

    @Test
    fun `recommend picks the lightest compatible model`() {
        val mgr = ModelManager(context, settingsStore())
        val entry = mgr.recommend(sampleManifest())
        assertNotNull(entry)
        assertEquals("ultra.onnx", entry?.id)
    }

    @Test
    fun `recommend returns null for empty manifest`() {
        val mgr = ModelManager(context, settingsStore())
        val entry = mgr.recommend(ModelManifest())
        assertTrue(entry == null)
    }

    @Test
    fun `installed and removal lifecycle`() = runBlocking {
        val mgr = ModelManager(context, settingsStore())
        val modelFile = File(mgr.modelsDir(), "testmodel.onnx")
        modelFile.parentFile?.mkdirs()
        modelFile.writeText("fake-model-bytes")
        assertTrue(mgr.isInstalled("testmodel.onnx"))
        assertTrue(mgr.installedModels().any { it.id == "testmodel.onnx" })
        assertTrue(mgr.removeModel("testmodel.onnx"))
        assertFalse(mgr.isInstalled("testmodel.onnx"))
    }

    @Test
    fun `manifest parses from file`() {
        val f = File.createTempFile("manifest", ".json")
        f.writeText(
            """{"schemaVersion":1,"models":[{"id":"m","name":"M","version":"1","sizeBytes":1,
               "sha256":"","url":"","quantization":"f32","ramRequirementMb":1,
               "deviceClassMin":"LOW","profile":"LIGHT"}]}"""
        )
        val manifest = ModelManager(context, settingsStore()).manifestFromFile(f.absolutePath)
        assertEquals(1, manifest.models.size)
        assertEquals("m", manifest.models[0].id)
    }

    @Test
    fun `storageFreeMb returns a non-negative value`() {
        val mgr = ModelManager(context, settingsStore())
        assertTrue(mgr.storageFreeMb() >= 0)
    }
}
