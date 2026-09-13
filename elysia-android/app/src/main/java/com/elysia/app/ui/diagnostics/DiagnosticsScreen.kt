package com.elysia.app.ui.diagnostics

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.elysia.app.link.HotUpdateManager
import com.elysia.app.ui.ElysiaViewModel

@Composable
fun DiagnosticsScreen(vm: ElysiaViewModel) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("Diagnostics", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(12.dp))

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { vm.runDiagnostics() }, modifier = Modifier.weight(1f)) {
                Text("Run diagnostics")
            }
            Button(onClick = { vm.runAiTest() }, modifier = Modifier.weight(1f)) {
                Text("Run AI test")
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { vm.runBenchmark() }, modifier = Modifier.weight(1f)) {
                Text("Benchmark")
            }
            Button(onClick = { vm.clearCache() }, modifier = Modifier.weight(1f)) {
                Text("Clear cache")
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { vm.exportDiagnostics() }, modifier = Modifier.weight(1f)) {
                Text("Export logs")
            }
            Button(onClick = { vm.resetElysia() }, modifier = Modifier.weight(1f)) {
                Text("Reset Elysia")
            }
        }
        val context = LocalContext.current
        val bundleVersion = remember { HotUpdateManager(context).cachedVersion() }
        Text(
            "Live bundle: ${if (bundleVersion >= 0) "v$bundleVersion" else "not fetched"} · /api/app/bundle",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(Modifier.height(8.dp))

        if (vm.benchmarkText.isNotEmpty()) {
            Card(Modifier.fillMaxWidth()) {
                Text(vm.benchmarkText, Modifier.padding(12.dp), fontSize = 12.sp, fontFamily = FontFamily.Monospace)
            }
            Spacer(Modifier.height(12.dp))
        }

        Text(
            vm.diagnosticsText.ifEmpty { "Tap \"Run diagnostics\" to inspect this device." },
            modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()),
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}
