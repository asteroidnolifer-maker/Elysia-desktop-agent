package com.elysia.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.elysia.app.ui.ElysiaViewModel
import com.elysia.app.ui.ElysiaViewModelFactory
import com.elysia.app.ui.chat.ChatScreen
import com.elysia.app.ui.diagnostics.DiagnosticsScreen
import com.elysia.app.ui.models.ModelManagerScreen
import com.elysia.app.ui.settings.SettingsScreen
import com.elysia.app.ui.setup.SetupWizard
import com.elysia.app.ui.integration.IntegrationScreen
import com.elysia.app.ui.link.DeviceLinkScreen
import com.elysia.app.ui.theme.ElysiaTheme
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val app = application as ElysiaApplication
        setContent {
            ElysiaTheme {
                val vm: ElysiaViewModel = viewModel(
                    factory = ElysiaViewModelFactory(app, applicationContext)
                )
                MainRoot(vm)
            }
        }
    }
}

@Composable
fun MainRoot(vm: ElysiaViewModel) {
    var tab by remember { mutableStateOf(0) }

    if (!vm.setupComplete) {
        SetupWizard(vm, context = androidx.compose.ui.platform.LocalContext.current) {
            vm.completeSetup()
            tab = 0
        }
        return
    }

    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = tab == 0,
                    onClick = { tab = 0 },
                    icon = { Icon(Icons.Filled.Chat, contentDescription = null) },
                    label = { Text("Chat") }
                )
                NavigationBarItem(
                    selected = tab == 1,
                    onClick = { tab = 1 },
                    icon = { Icon(Icons.Filled.Memory, contentDescription = null) },
                    label = { Text("Models") }
                )
                NavigationBarItem(
                    selected = tab == 2,
                    onClick = { tab = 2 },
                    icon = { Icon(Icons.Filled.MonitorHeart, contentDescription = null) },
                    label = { Text("Diagnostics") }
                )
                NavigationBarItem(
                    selected = tab == 3,
                    onClick = { tab = 3 },
                    icon = { Icon(Icons.Filled.Settings, contentDescription = null) },
                    label = { Text("Settings") }
                )
                NavigationBarItem(
                    selected = tab == 4,
                    onClick = { tab = 4 },
                    icon = { Icon(Icons.Filled.Link, contentDescription = null) },
                    label = { Text("Link") }
                )
                NavigationBarItem(
                    selected = tab == 5,
                    onClick = { tab = 5 },
                    icon = { Icon(Icons.Filled.IntegrationInstructions, contentDescription = null) },
                    label = { Text("Integrations") }
                )
            }
        }
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            when (tab) {
                0 -> ChatScreen(vm)
                1 -> ModelManagerScreen(vm)
                2 -> DiagnosticsScreen(vm)
                3 -> SettingsScreen(vm)
                4 -> DeviceLinkScreen()
                5 -> IntegrationScreen()
            }
        }
    }
}
