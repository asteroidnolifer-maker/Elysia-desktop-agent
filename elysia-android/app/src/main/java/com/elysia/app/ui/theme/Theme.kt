package com.elysia.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DarkColors = darkColorScheme(
    primary = Color(0xFF8AB4FF),
    onPrimary = Color(0xFF003061),
    secondary = Color(0xFF7C5CFF),
    background = Color(0xFF0B0B12),
    surface = Color(0xFF14141E),
    surfaceVariant = Color(0xFF1E1E2C),
    onSurface = Color(0xFFE4E4EF),
    onSurfaceVariant = Color(0xFFB8B8C6),
    error = Color(0xFFFF6B6B)
)

@Composable
fun ElysiaTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColors,
        content = content
    )
}
