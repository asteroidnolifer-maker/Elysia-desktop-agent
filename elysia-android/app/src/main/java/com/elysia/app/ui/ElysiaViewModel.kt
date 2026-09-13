package com.elysia.app.ui

import android.app.ActivityManager
import android.content.Context
import android.os.Build
import android.os.PowerManager
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.elysia.app.ElysiaApplication
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import com.elysia.app.otp.OtpOverlayController
import com.elysia.app.otp.OtpPrefs
import com.elysia.app.research.ResearchManager
import com.elysia.core.chat.SpellIntents
import com.elysia.core.memory.MemoryStore
import com.elysia.core.model.DeviceSummary
import com.elysia.core.model.InferenceResult
import com.elysia.core.model.InstallProgress
import com.elysia.core.settings.SettingsStore
import com.elysia.device.DeviceDetector
import com.elysia.diagnostics.DiagnosticsManager
import com.elysia.installer.Installer
import com.elysia.models.ModelEntry
import com.elysia.models.ModelManifest
import com.elysia.models.ModelManager
import com.elysia.permissions.PermissionManager
import com.elysia.runtime.CharTokenizer
import com.elysia.runtime.InferenceChunk
import com.elysia.runtime.RuntimeManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

data class ChatMessage(
    val role: String, // "user" or "assistant"
    val text: String,
    val timestamp: Long = System.currentTimeMillis()
)

class ElysiaViewModel(
    private val app: ElysiaApplication,
    private val context: Context
) : ViewModel() {

    val settings: SettingsStore get() = app.settingsStore
    val deviceDetector: DeviceDetector get() = app.deviceDetector
    val runtimeManager: RuntimeManager get() = app.runtimeManager
    val modelManager: ModelManager get() = app.modelManager
    val installer: Installer get() = app.installer
    val diagnosticsManager: DiagnosticsManager get() = app.diagnosticsManager
    val memoryStore: MemoryStore get() = app.memoryStore
    val researchManager: ResearchManager = ResearchManager()

    var setupComplete by mutableStateOf(false)
        private set
    var deviceInfo by mutableStateOf<DeviceSummary?>(null)
        private set
    var isInstalling by mutableStateOf(false)
        private set
    var installProgress by mutableStateOf<InstallProgress?>(null)
        private set
    var installError by mutableStateOf<String?>(null)
        private set
    var installMessage by mutableStateOf("")
        private set
    var installModel by mutableStateOf(true)
        private set

    var chatMessages by mutableStateOf<List<ChatMessage>>(emptyList())
        private set
    var isGenerating by mutableStateOf(false)
        private set
    var modelLabel by mutableStateOf("ONNX")
        private set

    var manifest by mutableStateOf<ModelManifest?>(null)
        private set
    var downloadProgress by mutableStateOf<Pair<String, Int>?>(null) // modelId to percent
        private set
    var downloadMessage by mutableStateOf("")
        private set

    var diagnosticsText by mutableStateOf("")
        private set
    var isRunningDiagnostics by mutableStateOf(false)
        private set
    var benchmarkText by mutableStateOf("")
        private set
    var localOnly by mutableStateOf(true)
        private set
    var permissionReport by mutableStateOf("")
        private set
    var otpEnabled by mutableStateOf(false)
        private set

    init {
        viewModelScope.launch {
            setupComplete = settings.isSetupCompleteNow()
            deviceInfo = deviceDetector.detect()
            localOnly = settings.localOnlyNow()
            permissionReport = PermissionManager.auditReport(context)
            manifest = modelManager.bundledManifest()
            otpEnabled = OtpPrefs.enabled(context)
            refreshModelLabel()
        }
    }

    fun refreshDevice() {
        viewModelScope.launch {
            deviceInfo = deviceDetector.detect()
        }
    }

    fun refreshModelLabel() {
        viewModelScope.launch {
            modelLabel = if (settings.modelInstalledNow()) {
                val id = settings.selectedModelIdNow()
                "ONNX: ${if (id.isEmpty()) "installed" else id}"
            } else {
                "ONNX: not installed"
            }
        }
    }

    // ---------- Setup / Install ----------

    fun setSetupStep(step: Int) {
        viewModelScope.launch { settings.setSetupStep(step) }
    }

    fun completeSetup() {
        viewModelScope.launch {
            settings.setSetupComplete(true)
            setupComplete = true
        }
    }

    fun chooseInstallModel(include: Boolean) {
        installModel = include
    }

    fun runInstallation() {
        if (isInstalling) return
        viewModelScope.launch {
            isInstalling = true
            installError = null
            installMessage = "Starting installation..."
            val progressJob = viewModelScope.launch {
                installer.progress.collectLatest { p ->
                    installProgress = p
                    installMessage = p.message
                }
            }
            val result = installer.run(includeModel = installModel)
            progressJob.cancel()
            isInstalling = false
            if (!result.success) {
                installError = result.error
            } else {
                installMessage = "Installation complete"
                refreshModelLabel()
            }
        }
    }

    fun retryInstallation() = runInstallation()

    // ---------- Chat ----------

    fun sendMessage(text: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty() || isGenerating) return
        chatMessages = chatMessages + ChatMessage("user", trimmed)
        isGenerating = true
        viewModelScope.launch(Dispatchers.Default) {
            val reply = StringBuilder()
            val corrected = SpellIntents.expandShorthand(SpellIntents.normalize(trimmed))
            var memoryReply = handleMemoryIntent(trimmed)
            if (memoryReply == null && corrected != trimmed) memoryReply = handleMemoryIntent(corrected)
            if (memoryReply != null) {
                isGenerating = false
                chatMessages = chatMessages + ChatMessage("assistant", memoryReply)
                return@launch
            }
            val readyReply = handleReadyResponse(trimmed)
            if (readyReply != null) {
                isGenerating = false
                chatMessages = chatMessages + ChatMessage("assistant", readyReply)
                return@launch
            }
            if (!settings.localOnlyNow()) {
                val researchReply = handleResearchIntent(trimmed)
                if (researchReply != null) {
                    isGenerating = false
                    chatMessages = chatMessages + ChatMessage("assistant", researchReply)
                    return@launch
                }
            }
            if (shouldOffload(trimmed) && tryOffload(trimmed)) {
                isGenerating = false
                chatMessages = chatMessages + ChatMessage("assistant", "Offloaded to laptop — thermal/RAM pressure detected. Your prompt was queued on the host via /api/task/offload (Work Separation fleet); results will appear in host memory & agent log.")
                return@launch
            }
            runtimeManager.loadSelectedModel()
            val modelPrompt = buildModelPrompt(trimmed)
            try {
                runtimeManager.generate(modelPrompt, maxTokens = 120, temperature = 0.15f, topP = 0.95f).collect { chunk ->
                    when (chunk) {
                        is InferenceChunk.Token -> reply.append(chunk.text)
                        is InferenceChunk.Done -> {
                            isGenerating = false
                            // Stop at any echoed "user:" turn so only the assistant's reply shows.
                            val finalText = reply.toString().substringBefore("\nuser:").trim()
                            chatMessages = chatMessages + ChatMessage("assistant", finalText)
                            settings.setLastInference(chunk.result.durationMs, settings.lastInference().second + 1)
                            refreshModelLabel()
                        }
                        is InferenceChunk.Error -> {
                            isGenerating = false
                            chatMessages = chatMessages + ChatMessage("assistant", "Error: ${chunk.message}")
                        }
                    }
                }
            } finally {
                // If the stream ended without Done/Error (e.g. cancelled or process
                // pressure), still surface whatever the model managed to produce.
                if (isGenerating) {
                    isGenerating = false
                    val partial = reply.toString().substringBefore("\nuser:").trim()
                    if (partial.isNotEmpty()) {
                        chatMessages = chatMessages + ChatMessage("assistant", partial)
                    }
                }
            }
        }
    }

    /**
     * Build the prompt for the char-level neural model.
     * The model is trained on "user: <msg>\nassistant: <reply>\n..." turns, so recent
     * history is included to give the model conversation context. The whole prompt is
     * trimmed to fit the model's fixed context window, always keeping the latest
     * user message intact so it can answer the right turn.
     */
    private fun buildModelPrompt(message: String): String {
        val latest = "user: ${message.replace('\n', ' ').trim()}\nassistant: "
        var budget = (CharTokenizer.CTX_WINDOW - latest.length - 4).coerceAtLeast(0)
        val picked = mutableListOf<String>()
        // chatMessages already contains the current user message; exclude it here.
        // Newest turns first: the most recent context matters most for follow-ups
        // like "another one", so the latest assistant reply is never dropped.
        for (m in chatMessages.dropLast(1).takeLast(6).asReversed()) {
            if (budget <= 0) break
            val turn = (if (m.role == "user") "user: " else "assistant: ") + m.text.replace('\n', ' ').trim() + "\n"
            if (turn.length > budget) {
                // Keep a truncated slice of the newest turn so some context survives.
                if (picked.isEmpty() && turn.length > 10) {
                    val kept = turn.take(budget.coerceAtLeast(10))
                    picked.add(kept)
                    budget -= kept.length
                }
                continue
            }
            picked.add(turn)
            budget -= turn.length
        }
        return picked.asReversed().joinToString("") + latest
    }

    /**
     * Handle memory commands without using the neural model:
     *  - "remember X is Y" / "my name is X" -> store a fact
     *  - "what is my X" / "do you remember my X" -> recall a fact
     *  - "forget X" -> delete a fact
     *  - "what do you remember" -> list stored facts
     */
    private suspend fun handleMemoryIntent(message: String): String? {
        val m = message.lowercase().trim()
        if (m.length > 120) return null

        val forget = Regex("^(forget|forgot|delete)\\s+(?:that\\s+)?(.+)$").find(m)
        if (forget != null) {
            memoryStore.forget(forget.groupValues[2])
            return "Forgot \"${forget.groupValues[2]}\"."
        }

        val remember = Regex("^(remember|note)\\s+(?:that\\s+)?my\\s+(.+?)\\s+is\\s+(.+)$").find(m)
        if (remember != null) {
            memoryStore.remember(remember.groupValues[2], remember.groupValues[3])
            return "Got it — I'll remember your ${remember.groupValues[2]}."
        }
        val rememberPlain = Regex("^(remember|note)\\s+(?:that\\s+)?(.+?)\\s+is\\s+(.+)$").find(m)
        if (rememberPlain != null) {
            memoryStore.remember(rememberPlain.groupValues[2], rememberPlain.groupValues[3])
            return "Got it — I'll remember that ${rememberPlain.groupValues[2]} is ${rememberPlain.groupValues[3]}."
        }

        val myIs = Regex("my\\s+(.+?)\\s+is\\s+(.+)$", RegexOption.IGNORE_CASE).find(message.trim())
        if (myIs != null && m.length <= 120) {
            memoryStore.remember(myIs.groupValues[1], myIs.groupValues[2])
            if (myIs.groupValues[1].contains("name", ignoreCase = true)) memoryStore.setName(myIs.groupValues[2])
            return "Noted — your ${myIs.groupValues[1]} is ${myIs.groupValues[2]}."
        }

        val recall = Regex("^(what is|what's|do you remember|do you know)\\s+(?:my\\s+)?(.+?)\\??$").find(m)
        if (recall != null) {
            val key = recall.groupValues[2].trim()
            val fact = memoryStore.lookup(key)
            return if (fact != null) "Yes — your $key is $fact."
            else "I don't remember that yet. Tell me \"remember my $key is ...\" to save it."
        }

        if (m.contains("what do you remember")) {
            val mem = memoryStore.snapshot()
            if (mem.facts.isEmpty()) return "You haven't told me anything to remember yet."
            return buildString {
                appendLine("Here's what I remember about you:")
                mem.facts.forEach { (k, v) -> appendLine("  - $k: $v") }
            }
        }

        // Fuzzy fallback: "wat my name" / "do u remember my name" still recall.
        val fuzzy = SpellIntents.match(message)
        if (fuzzy == "what is my name" || fuzzy == "do you know my name" || fuzzy == "do you remember my name") {
            val name = memoryStore.snapshot().lastSeenName
            return if (name.isNotBlank()) "Your name is $name — I remembered!"
            else "I don't know your name yet. Tell me \"my name is ...\" and I'll remember it."
        }
        return null
    }

    /**
     * Ready-made curated responses for common words/questions.
     * These give a clean, useful reply instantly without burning the neural
     * model — great for basic chat and demos. Returns null if the message
     * should go to the neural model instead.
     */
    private suspend fun handleReadyResponse(message: String): String? {
        // Spelling-tolerant path: expand shorthand, then if the raw text
        // didn't hit a ready reply, try the fuzzy-corrected one.
        val m = message.lowercase().trim()
        val corrected = SpellIntents.expandShorthand(SpellIntents.normalize(message)).ifBlank { m }

        val direct = readyReply(m)
        if (direct != null) return direct
        if (corrected != m) {
            val viaCorrected = readyReply(corrected)
            if (viaCorrected != null) return viaCorrected
        }
        // Last hope: fuzzy match a typo'd phrase to a known intent.
        val target = SpellIntents.match(message) ?: return null
        return readyReply(target)
    }

    /**
     * The set of things we can answer instantly without the neural model.
     * Matching already happened (raw or spelling-corrected); this just
     * produces the reply.
     */
    private suspend fun readyReply(message: String): String? {
        val m = message.lowercase().trim()
        val name = memoryStore.snapshot().lastSeenName
        val nameRef = if (name.isNotBlank()) name else "there"

        return when {
            m.length > 160 -> null // long message -> neural model

            // Greetings
            m in setOf("hi", "hello", "hey", "hi there", "hello there", "good morning", "good afternoon", "good evening") -> {
                memoryStore.addNote("greeted at ${System.currentTimeMillis()}")
                val time = java.text.SimpleDateFormat("h:mm a", java.util.Locale.getDefault()).format(java.util.Date())
                if (m.contains("morning")) "Good morning, $nameRef! It's $time. What can I help you with today?"
                else if (m.contains("afternoon")) "Good afternoon, $nameRef! It's $time. What can I help you with?"
                else if (m.contains("evening")) "Good evening, $nameRef! It's $time. What can I help you with?"
                else "Hello $nameRef! It's $time. How can I help you today?"
            }

            // How are you
            m.contains("how are you") -> "I'm running great on this device — fully local, fully offline. How are you doing?"
            m.contains("what's up") || m.contains("sup") -> "Not much — just processing locally on your phone. What about you?"

            // Identity
            m.contains("who are you") || m == "what are you" || m.contains("are you a robot") || m.contains("are you real") || m.contains("who made you") -> {
                val engine = if (settings.modelInstalledNow()) "ONNX neural model (${settings.selectedModelIdNow()})" else "ONNX neural model"
                "I'm Elysia — a local-first AI assistant that runs entirely on your device. " +
                    "No cloud, no account. Right now I'm using the $engine."
            }
            m.contains("your name") || m.contains("who are you called") -> "I'm Elysia. Nice to meet you, $nameRef!"

            // Warm replies
            m.contains("i love you") -> "Aww, thank you! I'm just a small local model, but I'm here for you, $nameRef."
            m.contains("tell me more") -> "I'd love to! What topic should we dive into — I can chat, remember things about you, do quick math, or tell jokes."

            // Capabilities
            m.contains("what can you do") || m == "help" || m.contains("help me") || m.contains("commands") ->
                "Here's what I can do:\n" +
                    "  \u2022 Chat — basic conversation, all on-device\n" +
                    "  \u2022 Memory — tell me \"my name is ...\" and I'll remember\n" +
                    "  \u2022 Research — say \"research <topic>\" in online mode\n" +
                    "  \u2022 OTP — incoming SMS codes get a one-tap autofill bubble\n" +
                    "  \u2022 Math — try \"what is 2+3*4?\"\n" +
                    "  \u2022 Device info — ask \"about my device\""

            // Time & date
            m.contains("time") -> "It's ${java.text.SimpleDateFormat("h:mm a", java.util.Locale.getDefault()).format(java.util.Date())}."
            m.contains("date") || m.contains("today is") -> "Today is ${java.text.SimpleDateFormat("EEEE, MMMM d", java.util.Locale.getDefault()).format(java.util.Date())}."

            // Thanks / bye
            m.contains("thank") -> "You're welcome, $nameRef! Anything else I can help with?"
            m.contains("bye") || m.contains("goodbye") || m.contains("see you") -> "Goodbye $nameRef! I'll be right here whenever you need me."

            // Jokes
            m.contains("joke") -> "Why did the phone go to therapy? It had too many unresolved tabs!"
            m.contains("fun fact") -> "This app's entire AI model is about 1 MB and runs on your phone's CPU — no internet required."

            // Name handling
            m.matches(Regex("my name is .+")) -> null // handled by memory intent above; safety net
            m.contains("what is my name") || m.contains("do you know my name") || m.contains("do you remember my name") ->
                if (name.isNotBlank()) "Your name is $name — I remembered!"
                else "I don't know your name yet. Tell me \"my name is ...\" and I'll remember it."

            // Location / device
            m.contains("where am i") -> "You're on a ${deviceInfo?.model ?: "device"} running this local assistant. Beyond that, I stay private — no location tracking."
            m.contains("about my device") || m.contains("device info") || m.contains("phone specs") ->
                deviceInfo?.let { d ->
                    "Your device:\n  ${d.manufacturer} ${d.model}\n  Android ${d.androidVersion} (API ${d.sdkInt})\n  " +
                        "${d.cpuCores} cores, ${d.ramTotalMb} MB RAM\n  Class: ${d.deviceClass.name}"
                } ?: "Reading device info..."

            // Math: "what is ...?" wrappers
            m.startsWith("what is") || m.startsWith("what's") -> {
                val expr = m.replace("what is", "").replace("what's", "").replace("?", "").trim()
                if (expr.isNotEmpty() && expr.all { it.isDigit() || it in "+-*/(). x" }) {
                    try {
                        val result = com.elysia.runtime.LightRuleEngine { deviceInfo }.evaluatePublic(expr)
                        "$expr = $result"
                    } catch (e: Exception) {
                        null
                    }
                } else null
            }

            else -> null
        }
    }

    /** Research intent: "research <topic>" — only in online mode. Saves findings to memory. */
    private suspend fun handleResearchIntent(message: String): String? {
        val match = Regex("^(research|search)\\s+(.+)$", RegexOption.IGNORE_CASE).find(message)
        if (match == null) return null
        val query = match.groupValues[2].trim()
        val results = researchManager.search(query, limit = 4)
        if (results.isEmpty()) return "Research couldn't fetch results for \"$query\". Check network, or stay in local-only mode."
        val reply = buildString {
            appendLine("Research: $query")
            results.forEachIndexed { i, r ->
                appendLine("${i + 1}. ${r.title}")
                appendLine("   ${r.url}")
                r.snippet.take(120).let { if (it.isNotEmpty()) appendLine("   $it") }
            }
        }
        memoryStore.addNote("research:$query => ${results.joinToString(" | ") { it.title + " " + it.url }}")
        return reply
    }

    fun stopGeneration() {
        isGenerating = false
    }

    fun clearConversation() {
        chatMessages = emptyList()
    }

    fun setLocalOnlyMode(value: Boolean) {
        localOnly = value
        viewModelScope.launch { settings.setLocalOnly(value) }
    }

    fun setOtpAutofill(value: Boolean) {
        otpEnabled = value
        OtpPrefs.setEnabled(context, value)
        if (!value) OtpOverlayController.hide(context)
    }

    // ---------- Models ----------

    fun recommendModel(): ModelEntry? = manifest?.let { modelManager.recommend(it) }

    fun downloadModel(entry: ModelEntry) {
        if (entry.url.isEmpty()) return
        viewModelScope.launch {
            downloadMessage = "Downloading ${entry.name}..."
            downloadProgress = entry.id to 0
            modelManager.downloadModel(entry).collect { p ->
                downloadProgress = entry.id to p.percent
                downloadMessage = "Downloading ${entry.name}... ${p.percent}%"
            }
            downloadProgress = null
            downloadMessage = "Model installed: ${entry.name}"
            refreshModelLabel()
        }
    }

    fun removeModel(entry: ModelEntry) {
        viewModelScope.launch {
            modelManager.removeModel(entry.id)
            downloadMessage = "Model removed: ${entry.name}"
            refreshModelLabel()
        }
    }

    // ---------- Diagnostics ----------

    fun runDiagnostics() {
        if (isRunningDiagnostics) return
        viewModelScope.launch {
            isRunningDiagnostics = true
            val result = diagnosticsManager.run()
            diagnosticsText = buildString {
                appendLine("===== ELYSIA DIAGNOSTICS =====")
                result.device.toReportLines().forEach { appendLine(it) }
                appendLine("Backend: ${result.backend}")
                appendLine("Local-only: ${result.localOnly}")
                appendLine("Model installed: ${result.modelInstalled} (${result.modelId})")
                appendLine("Runtime installed: ${result.runtimeInstalled}")
                appendLine("Last inference: ${result.lastInferenceMs} ms (count ${result.inferenceCount})")
                appendLine("Thermal: ${result.thermal}")
                appendLine("Root: ${result.root}")
                appendLine("ROM: ${result.romBrand}")
            }
            isRunningDiagnostics = false
        }
    }

    fun runAiTest() {
        viewModelScope.launch {
            diagnosticsText = "Running AI test..."
            diagnosticsText = diagnosticsManager.runAiTest()
        }
    }

    fun runBenchmark() {
        viewModelScope.launch {
            benchmarkText = "Running benchmark..."
            val b = diagnosticsManager.benchmark()
            benchmarkText = buildString {
                appendLine("Benchmark (${b.iterations} iterations)")
                appendLine("Engine: ${b.engine}")
                appendLine("Avg latency: ${b.avgLatencyMs} ms")
                appendLine("Tokens/sec: ${"%.2f".format(b.tokensPerSec)}")
                appendLine("Process RAM: ${b.ramUsedMb} MB")
            }
        }
    }

    fun exportDiagnostics() {
        viewModelScope.launch {
            diagnosticsText = "Exporting..."
            diagnosticsText = diagnosticsManager.run().let { result ->
                diagnosticsManager.exportReport(result)?.let { "Exported to: ${it.absolutePath}" } ?: "Export failed"
            }
        }
    }

    fun clearCache() {
        viewModelScope.launch(Dispatchers.IO) {
            app.cacheDir.listFiles()?.forEach { it.deleteRecursively() }
            diagnosticsText = "Cache cleared"
        }
    }

    fun resetElysia() {
        viewModelScope.launch(Dispatchers.IO) {
            settings.reset()
            runtimeManager.unloadModel()
            chatMessages = emptyList()
            setupComplete = false
            installMessage = "Elysia reset"
        }
    }

    private fun shouldOffload(prompt: String): Boolean {
        if (prompt.length < 300) {
            val heavyKeywords = listOf("research", "code", "analyze", "summarize", "generate", "write", "explain", "translate", "build", "create app")
            if (heavyKeywords.none { prompt.contains(it, ignoreCase = true) }) return false
        }
        return isUnderPressure()
    }

    private fun isUnderPressure(): Boolean {
        try {
            val am = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
            val memInfo = ActivityManager.MemoryInfo()
            am?.getMemoryInfo(memInfo)
            val availMB = memInfo.availMem / (1024 * 1024)
            if (availMB < 1024) return true
            if (memInfo.lowMemory) return true
        } catch (_: Exception) {}
        try {
            val pm = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
            if (pm?.isPowerSaveMode == true) return true
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                val status = pm?.currentThermalStatus
                if (status != null && status >= PowerManager.THERMAL_STATUS_MODERATE) return true
            }
        } catch (_: Exception) {}
        return false
    }

    private suspend fun tryOffload(prompt: String): Boolean = kotlinx.coroutines.withContext(Dispatchers.IO) {
        try {
            val link = context.getSharedPreferences("elysia_link", Context.MODE_PRIVATE)
            val host = link.getString("host", "")?.takeIf { it.isNotEmpty() } ?: return@withContext false
            val token = link.getString("token", "")?.takeIf { it.isNotEmpty() } ?: return@withContext false
            val body = JSONObject().apply { put("prompt", prompt) }.toString()
            val conn = URL("http://$host/api/task/offload").openConnection() as HttpURLConnection
            conn.connectTimeout = 4000
            conn.readTimeout = 8000
            conn.requestMethod = "POST"
            conn.setRequestProperty("Authorization", "Bearer $token")
            conn.setRequestProperty("Content-Type", "application/json")
            conn.doOutput = true
            conn.outputStream.use { it.write(body.toByteArray()) }
            val code = conn.responseCode
            conn.disconnect()
            code in 200..299
        } catch (_: Exception) {
            false
        }
    }
}
