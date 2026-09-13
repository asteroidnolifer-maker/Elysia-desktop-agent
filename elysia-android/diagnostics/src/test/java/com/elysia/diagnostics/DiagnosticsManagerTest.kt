package com.elysia.diagnostics

import android.content.Context
import com.elysia.core.settings.SettingsStore
import com.elysia.device.DeviceDetector
import com.elysia.models.ModelManager
import com.elysia.runtime.RuntimeManager
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

@RunWith(RobolectricTestRunner::class)
class DiagnosticsManagerTest {

    private val context: Context = RuntimeEnvironment.getApplication()

    private fun manager(): DiagnosticsManager {
        val settings = SettingsStore(context)
        val detector = DeviceDetector(context)
        val runtime = RuntimeManager(context, settings, detector)
        val models = ModelManager(context, settings, detector)
        return DiagnosticsManager(context, detector, runtime, models, settings)
    }

    @Test
    fun `run produces a populated result`() = runBlocking {
        val result = manager().run()
        assertNotNull(result)
        assertTrue(result.device.manufacturer.isNotBlank())
        assertNotNull(result.backend)
        assertTrue(result.logCount >= 0)
    }

    @Test
    fun `ai test runs without crashing`() = runBlocking {
        val text = manager().runAiTest()
        assertNotNull(text)
        assertTrue(text.contains("Done."))
    }

    @Test
    fun `benchmark returns a result`() = runBlocking {
        val b = manager().benchmark(iterations = 1)
        assertNotNull(b)
        assertTrue(b.avgLatencyMs >= 0)
        assertTrue(b.iterations == 1)
    }

    @Test
    fun `export report writes a file`() = runBlocking {
        val result = manager().run()
        val file = manager().exportReport(result)
        assertNotNull(file)
        assertTrue(file!!.exists())
        assertTrue(file.length() > 0)
        assertTrue(file.readText().contains("ELYSIA DIAGNOSTIC REPORT"))
    }
}
