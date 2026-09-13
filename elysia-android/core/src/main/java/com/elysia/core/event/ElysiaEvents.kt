package com.elysia.core.event

import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow

sealed interface ElysiaEvent {
    data class InstallProgress(val phase: String, val percent: Int, val message: String) : ElysiaEvent
    data class StatusChanged(val component: String, val status: String) : ElysiaEvent
    data class Error(val component: String, val message: String) : ElysiaEvent
    object ModelLoaded : ElysiaEvent
    object ModelUnloaded : ElysiaEvent
}

object ElysiaEvents {
    private val _events = MutableSharedFlow<ElysiaEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<ElysiaEvent> = _events

    suspend fun emit(event: ElysiaEvent) {
        _events.emit(event)
    }

    fun tryEmit(event: ElysiaEvent) {
        _events.tryEmit(event)
    }
}
