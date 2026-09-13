package com.elysia.app.ui.setup

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.elysia.app.ui.ElysiaViewModel
import com.elysia.core.model.InstallPhase
import com.elysia.permissions.PermissionManager
import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat

/**
 * First-run setup wizard.
 * Screens:
 *  0 Welcome
 *  1 Device compatibility check
 *  2 Permissions
 *  3 Runtime selection
 *  4 Model selection
 *  5 Installation (real progress)
 *  6 Verification
 *  7 Finished
 */
@Composable
fun SetupWizard(vm: ElysiaViewModel, context: Context, onDone: () -> Unit) {
    var step by remember { mutableStateOf(0) }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* state re-audited on screen render */ }

    Column(Modifier.fillMaxSize().padding(20.dp)) {
        when (step) {
            0 -> WelcomeStep { step = 1 }
            1 -> DeviceCheckStep(vm) { step = 2 }
            2 -> PermissionsStep(context, permissionLauncher) { step = 3 }
            3 -> RuntimeStep { step = 4 }
            4 -> ModelStep(vm) { step = 5 }
            5 -> InstallStep(vm) {
                if (vm.installError == null) step = 6 else step = 5
            }
            6 -> VerifyStep(vm) { step = 7 }
            7 -> FinishedStep(vm) {
                vm.completeSetup()
                onDone()
            }
        }
    }
}

@Composable
private fun WizardButton(
    text: String,
    enabled: Boolean = true,
    onClick: () -> Unit
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp)
    ) {
        Text(text)
    }
}

@Composable
private fun StepTitle(title: String, subtitle: String) {
    Text(title, fontSize = 26.sp, fontWeight = FontWeight.Bold)
    Spacer(Modifier.height(4.dp))
    Text(subtitle, fontSize = 14.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
    Spacer(Modifier.height(20.dp))
}

@Composable
private fun WelcomeStep(onNext: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Spacer(Modifier.weight(1f))
        Text("ELYSIA", fontSize = 40.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.height(8.dp))
        Text(
            "Your local-first AI assistant for this phone.\n" +
                "Runs on-device. Works offline. No cloud required.",
            fontSize = 16.sp
        )
        Spacer(Modifier.height(24.dp))
        Text(
            "This wizard will check your device, set up the local runtime, and install a model sized for your hardware.",
            fontSize = 14.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.weight(1f))
        WizardButton("Get Started") { onNext() }
    }
}

@Composable
private fun DeviceCheckStep(vm: ElysiaViewModel, onNext: () -> Unit) {
    val device = vm.deviceInfo
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        StepTitle("Device compatibility", "Real hardware check")
        if (device != null) {
            InfoRow("Device", "${device.manufacturer} ${device.model}")
            InfoRow("Android", "${device.androidVersion} (API ${device.sdkInt})")
            InfoRow("CPU", "${device.cpuArchitecture} / ${device.cpuCores} cores")
            InfoRow("ABI", device.abi)
            InfoRow("RAM", "${device.ramTotalMb} MB (${device.ramAvailableMb} MB free)")
            InfoRow("Storage", "${device.storageAvailableMb} MB free")
            InfoRow("Class", device.deviceClass.name)
            InfoRow("Root", if (device.isRooted) "Detected (not required)" else "No")
        } else {
            Text("Reading device information...")
        }
        Spacer(Modifier.height(12.dp))
        WizardButton("Continue", enabled = device != null) { onNext() }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Text(label, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    }
    HorizontalDivider(Modifier.padding(vertical = 4.dp), color = MaterialTheme.colorScheme.surfaceVariant)
}

@Composable
private fun PermissionsStep(
    context: Context,
    launcher: androidx.activity.compose.ManagedActivityResultLauncher<Array<String>, Map<String, Boolean>>,
    onNext: () -> Unit
) {
    val perms = remember { PermissionManager.requiredPermissions() }
    val granted = rememberUpdatedState(
        perms.filter { ContextCompat.checkSelfPermission(context, it.permission) == PackageManager.PERMISSION_GRANTED }.size
    )

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        StepTitle("Permissions", "Only what Elysia actually needs")
        perms.forEach { p ->
            val isGranted = ContextCompat.checkSelfPermission(context, p.permission) == PackageManager.PERMISSION_GRANTED
            Card(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                Column(Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(p.label, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        Text(if (isGranted) "GRANTED" else if (p.optional) "OPTIONAL" else "REQUIRED",
                            fontSize = 11.sp,
                            color = if (isGranted) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.error)
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(p.reason, fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        WizardButton("Request required permissions") {
            val needed = perms.filter { !it.optional && !isGranted(context, it.permission) }.map { it.permission }
            if (needed.isNotEmpty()) {
                launcher.launch(needed.toTypedArray())
            }
        }
        WizardButton("Continue", enabled = true) { onNext() }
    }
}

private fun isGranted(context: Context, permission: String): Boolean =
    ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

@Composable
private fun RuntimeStep(onNext: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        StepTitle("Runtime selection", "Picked for your hardware")
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text("Recommended: Lightweight local CPU runtime", fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                Text(
                    "ONNX Runtime for Android — runs fully on-device with no cloud. " +
                        "Backend auto-selects CPU/NNAPI based on what this phone supports.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        Spacer(Modifier.height(12.dp))
        WizardButton("Use recommended runtime") { onNext() }
    }
}

@Composable
private fun ModelStep(vm: ElysiaViewModel, onNext: () -> Unit) {
    val recommended = vm.recommendModel()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        StepTitle("Model selection", "Auto-recommended for your device")
        if (recommended != null) {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text(recommended.name, fontWeight = FontWeight.SemiBold, fontSize = 17.sp)
                    Spacer(Modifier.height(4.dp))
                    Text(
                        "Profile: ${recommended.profile} | Quant: ${recommended.quantization} | " +
                            "${recommended.sizeBytes / (1024 * 1024)} MB\n" +
                            "RAM requirement: ${recommended.ramRequirementMb} MB",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        } else {
            Text("No compatible model found in manifest.")
        }
        Spacer(Modifier.height(12.dp))
        WizardButton("Install model") {
            vm.chooseInstallModel(true)
            onNext()
        }
    }
}

@Composable
private fun InstallStep(vm: ElysiaViewModel, onNext: () -> Unit) {
    val progress = vm.installProgress
    LaunchedEffect(Unit) {
        if (vm.installError == null && progress?.phase != InstallPhase.DONE) {
            vm.runInstallation()
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        StepTitle("Installation", "Installing the ONNX model")
        vm.downloadMessage.let { if (it.isNotEmpty()) Text(it, fontSize = 13.sp) }
        Spacer(Modifier.height(8.dp))
        progress?.let { p ->
            Text("${p.percent}% — ${p.message}", fontSize = 14.sp, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(
                progress = { p.percent / 100f },
                modifier = Modifier.fillMaxWidth()
            )
        }
        Spacer(Modifier.height(16.dp))
        vm.installError?.let {
            Text("ERROR: $it", color = MaterialTheme.colorScheme.error)
        }
        Spacer(Modifier.height(12.dp))
        WizardButton("Continue", enabled = !vm.isInstalling && vm.installError == null) { onNext() }
        if (vm.installError != null) {
            WizardButton("Retry") { vm.retryInstallation() }
        }
    }
}

@Composable
private fun VerifyStep(vm: ElysiaViewModel, onNext: () -> Unit) {
    var testResult by remember { mutableStateOf<String?>(null) }
    var runtimeInstalled by remember { mutableStateOf<Boolean?>(null) }
    var modelInstalled by remember { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(Unit) {
        if (testResult == null) {
            testResult = vm.runtimeManager.selfTest()
            runtimeInstalled = vm.settings.runtimeInstalledNow()
            modelInstalled = vm.settings.modelInstalledNow()
        }
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        StepTitle("Verification", "Self-tests")
        testResult?.let { Text(it, fontSize = 14.sp) }
        Spacer(Modifier.height(8.dp))
        runtimeInstalled?.let { Text("Runtime installed: $it") }
        modelInstalled?.let { Text("Model installed: $it") }
        Spacer(Modifier.height(16.dp))
        WizardButton("Continue", enabled = testResult != null) { onNext() }
    }
}

@Composable
private fun FinishedStep(vm: ElysiaViewModel, onDone: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        Spacer(Modifier.weight(1f))
        Text("ELYSIA IS READY", fontSize = 30.sp, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.height(8.dp))
        Text(
            "Your assistant is set up and running locally.\n" +
                "You can change models, run diagnostics, and tune settings from the main screen.",
            fontSize = 15.sp
        )
        Spacer(Modifier.weight(1f))
        WizardButton("Start chatting") { onDone() }
    }
}
