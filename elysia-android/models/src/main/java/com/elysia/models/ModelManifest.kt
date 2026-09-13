package com.elysia.models

import kotlinx.serialization.Serializable

/** A downloadable model entry. */
@Serializable
data class ModelEntry(
    val id: String,
    val name: String,
    val version: String,
    val sizeBytes: Long,
    val sha256: String,
    val url: String,
    val quantization: String,
    val ramRequirementMb: Long,
    val deviceClassMin: String,
    val profile: String,
    val description: String = ""
)

/** A remote or local model manifest. */
@Serializable
data class ModelManifest(
    val schemaVersion: Int = 1,
    val models: List<ModelEntry> = emptyList()
)
