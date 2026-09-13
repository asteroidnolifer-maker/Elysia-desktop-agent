package com.elysia.app

import android.app.Application
import com.elysia.core.memory.MemoryStore
import com.elysia.core.settings.SettingsStore
import com.elysia.device.DeviceDetector
import com.elysia.app.link.HotUpdateManager
import com.elysia.diagnostics.DiagnosticsManager
import com.elysia.installer.Installer
import com.elysia.models.ModelManager
import com.elysia.permissions.PermissionManager
import com.elysia.runtime.RuntimeManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Application-level dependency container.
 * Simple manual DI: small, zero annotation processing, fast on low-end devices.
 */
class ElysiaApplication : Application() {

    lateinit var settingsStore: SettingsStore
        private set
    lateinit var deviceDetector: DeviceDetector
        private set
    lateinit var runtimeManager: RuntimeManager
        private set
    lateinit var modelManager: ModelManager
        private set
    lateinit var installer: Installer
        private set
    lateinit var diagnosticsManager: DiagnosticsManager
        private set
    lateinit var memoryStore: MemoryStore
        private set

    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()
        settingsStore = SettingsStore(this)
        deviceDetector = DeviceDetector(this)
        runtimeManager = RuntimeManager(this, settingsStore, deviceDetector)
        modelManager = ModelManager(this, settingsStore, deviceDetector)
        installer = Installer(this, settingsStore, deviceDetector)
        diagnosticsManager = DiagnosticsManager(
            this, deviceDetector, runtimeManager, modelManager, settingsStore
        )
        memoryStore = MemoryStore.create(this)
        runtimeManager.refreshDevice()
        applicationScope.launch {
            try {
                HotUpdateManager(this@ElysiaApplication).refresh()
            } catch (_: Exception) {
            }
        }
    }

    fun permissionAudit(): String = PermissionManager.auditReport(this)
}
