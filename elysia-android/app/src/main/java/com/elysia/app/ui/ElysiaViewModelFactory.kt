package com.elysia.app.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.elysia.app.ElysiaApplication
import android.content.Context

class ElysiaViewModelFactory(
    private val app: ElysiaApplication,
    private val context: Context
) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return ElysiaViewModel(app, context) as T
    }
}
