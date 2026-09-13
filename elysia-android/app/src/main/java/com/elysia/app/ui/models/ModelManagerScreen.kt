package com.elysia.app.ui.models

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.elysia.app.ui.ElysiaViewModel
import com.elysia.models.ModelEntry

@Composable
fun ModelManagerScreen(vm: ElysiaViewModel) {
    val manifest = vm.manifest

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Text("Model", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(12.dp))

        vm.downloadMessage.let { if (it.isNotEmpty()) Text(it, fontSize = 12.sp) }
        vm.downloadProgress?.let { (id, pct) ->
            Spacer(Modifier.height(8.dp))
            Text("$id: $pct%")
            LinearProgressIndicator(progress = { pct / 100f }, modifier = Modifier.fillMaxWidth())
        }
        Spacer(Modifier.height(8.dp))

        val models = manifest?.models ?: emptyList()
        Column(Modifier.verticalScroll(rememberScrollState())) {
            models.forEach { entry ->
                ModelCard(
                    entry = entry,
                    isInstalled = vm.modelManager.isInstalled(entry.id)
                )
                Spacer(Modifier.height(8.dp))
            }
            if (models.isEmpty()) {
                Text("No model found.", fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun ModelCard(
    entry: ModelEntry,
    isInstalled: Boolean
) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp)) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(entry.name, fontWeight = FontWeight.SemiBold)
                Text(
                    if (isInstalled) "INSTALLED" else "NOT INSTALLED",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.primary
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "Profile: ${entry.profile} | Quant: ${entry.quantization} | " +
                    "${entry.sizeBytes / (1024 * 1024)} MB\n" +
                    "RAM: ${entry.ramRequirementMb} MB | Version: ${entry.version}",
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
