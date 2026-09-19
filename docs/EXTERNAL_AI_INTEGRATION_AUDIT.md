# Elysia External AI + Web Workspace Integration Audit

**Audit Date:** 2026-09-19  
**Scope:** `elysia/core/providers.py`, `elysia/core/browser_login.py`, `elysia/core/tools.py`, `elysia/core/toolkit.py`, `elysia/core/computer.py`, `elysia/core/skills.py`, `elysia/config.json`, `elysia/cli.py`, `orchestrator/`, `legacy/workspace/tools/`

---

## Executive Summary

**Current State:** Elysia has a **complete canonical provider abstraction** (`ProviderManager`) supporting local models (llama.cpp/Ollama), cloud OpenAI-compatible APIs (OpenRouter, Groq, Together, DeepSeek, Mistral, xAI, NVIDIA NIM, GitHub Models, Cerebras, Gemini, HuggingFace, Freebuff gateways), and **CLI coding agents** (Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw) that activate when their binary is on PATH. A **browser login flow** (`elysia login <provider>`) opens provider consoles and stores keys in `config/providers.env` (0600, git-ignored). **However, external AI systems are only exposed as *providers* (chat/completion) — not as *external agents* that can inspect repos, edit files, run commands, and iterate.** No `ExternalAgentManager`, no workspace isolation for delegated tasks, no result normalization, no verification gate.

**Critical Gaps:**
1. **Provider vs External Agent conflation** — OpenCode/Codex/Claude Code are treated as chat providers; they cannot act as autonomous agents on a workspace
2. **No ExternalAgentManager** — No `inspect/start_task/send_instruction/observe/cancel/collect_result` abstraction
3. **No workspace isolation** — Delegated tasks would write to shared workspace without ownership control
4. **No result normalization** — Each external agent returns different formats; no canonical schema
5. **No verification gate** — External agent "done" ≠ task verified (tests, QA, diff review)
6. **Browser/Computer control exists but not integrated with external agents** — `ToolLayer` has `desktop.*` tools but no delegation path

**Bottom Line:** Elysia can **call** external APIs; it cannot **delegate** to external agents.

---

## 1. Provider System: Complete (Providers Only)

### 1.1 `elysia/core/providers.py` — Verified Inventory

| Provider Kind | Activation | Capabilities | Status |
|---------------|------------|--------------|--------|
| `openai` (local llama.cpp/Ollama) | Always (default) | `chat`, `coding`, `reasoning`, `tool_calling`, `structured_output`, `streaming` | ✅ Working |
| `openai` (OpenRouter, Groq, Together, DeepSeek, Mistral, xAI, Cerebras, GitHub Models, Freebuff) | `*_API_KEY` env var set | Same as above | ✅ Credential-gated |
| `nim` (NVIDIA NIM) | `NIM_API_KEY` + `nim_model` | `chat`, `coding`, `reasoning` | ✅ Credential-gated |
| `cli` (Claude Code) | `claude` binary on PATH | `chat`, `coding`, `tool_calling`, `file_access` | ✅ Binary-gated |
| `cli` (Codex) | `codex` binary on PATH | `chat`, `coding`, `tool_calling`, `file_access` | ✅ Binary-gated |
| `cli` (Gemini CLI) | `gemini` binary on PATH | `chat`, `coding`, `tool_calling`, `file_access` | ✅ Binary-gated |
| `cli` (OpenCode) | `opencode` binary on PATH | `chat`, `coding`, `tool_calling`, `file_access` | ✅ Binary-gated |
| `cli` (OpenClaw) | `openclaw` binary on PATH | `chat`, `coding`, `tool_calling`, `file_access` | ✅ Binary-gated |
| `hf` (HuggingFace Inference) | `HF_TOKEN` env var | `chat`, `coding`, `reasoning` | ✅ Credential-gated |

**All providers route through `ProviderManager.select(capabilities)` → `execute()` with circuit breaker, budget enforcement, atomic reservation, fallback chain.**

### 1.2 What Providers CANNOT Do (Prompt §4)

| External Agent Capability | Provider Support |
|---------------------------|------------------|
| Inspect repository (read files, analyze structure) | ❌ Only prompt context |
| Edit files in workspace | ❌ Only text response |
| Run commands (tests, build, lint) | ❌ Only text response |
| Iterate on failures (retry with context) | ❌ Single call |
| Monitor execution progress | ❌ Fire-and-forget |
| Cancel mid-execution | ❌ No control |
| Return structured result (files changed, tests, errors) | ❌ Raw text only |

---

## 2. External Agent Adapters: Missing

### 2.1 Required by Prompt (§4, §5, §12, §16, §17, §19)

| Component | Prompt Ref | Implemented? |
|-----------|------------|--------------|
| `elysia/core/integrations/base.py` — ExternalAgent abstract base | §4, §12 | ❌ |
| `elysia/core/integrations/registry.py` — IntegrationRegistry | §13 | ❌ |
| `elysia/core/integrations/freebuff.py` | §5 | ❌ |
| `elysia/core/integrations/opencode.py` | §6 | ❌ |
| `elysia/core/integrations/codex.py` | §7 | ❌ |
| `elysia/core/integrations/openai.py` (API vs ChatGPT web) | §8 | ❌ |
| `elysia/core/integrations/browser.py` | §9 | ❌ |
| `elysia/core/integrations/computer.py` | §10 | ❌ (computer.py exists but not as integration) |
| `elysia/core/integrations/__init__.py` | §12 | ❌ |

### 2.2 Required ExternalAgent Interface (Prompt §4)

```python
class ExternalAgent:
    def inspect(self, workspace: str) -> dict: ...           # repo analysis
    def start_task(self, task: dict, workspace: str) -> str: ...  # returns execution_id
    def send_instruction(self, execution_id: str, instruction: str) -> dict: ...
    def observe(self, execution_id: str) -> dict: ...         # progress, logs, state
    def cancel(self, execution_id: str) -> bool: ...
    def get_status(self, execution_id: str) -> dict: ...
    def collect_result(self, execution_id: str) -> dict: ...  # normalized result
    def capabilities(self) -> list[str]: ...                  # coding, repo, terminal, file_edit
    def health(self) -> dict: ...                             # available, authenticated, version
```

**None of this exists.** Current `Provider` interface only has `chat(messages)`, `capabilities()`, `health()`.

---

## 3. Browser + Computer Control: Exists But Not Integrated

### 3.1 `elysia/core/toolkit.py` — ToolLayer (Verified)

| Tool | Permissions | Risk | Backend | Status |
|------|-------------|------|---------|--------|
| `browser.open_url` | `net:http`, `browser:control` | MODERATE | `urllib` + SSRF guard | ✅ Works |
| `desktop.screenshot` | `desktop:control` | HIGH | `CommandLineDesktop` (xdotool/import) | ✅ If display |
| `desktop.windows` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `desktop.focus` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `desktop.mouse` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `desktop.click` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `desktop.type` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `desktop.key` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `desktop.launch` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `clipboard.read` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |
| `clipboard.write` | `desktop:control` | HIGH | `CommandLineDesktop` | ✅ If display |

**Gap:** These are **tools for Elysia's own agents** — not an integration surface for external agents. No delegation path: `ExternalAgent → ToolManager → ComputerController`.

### 3.2 `elysia/core/browser_login.py` — Verified

```bash
./bin/elysia login groq --no-browser        # Prints console URL + export line
./bin/elysia login groq --paste <KEY>       # Stores in config/providers.env (0600)
./bin/elysia login status                   # Shows stored keys (redacted)
./bin/elysia login load                     # Loads keys into env
./bin/elysia login logout groq              # Removes stored key
./bin/elysia login claude-code              # Reports CLI agent reuse
```

**Works for provider credentials. Does not support browser automation login for ChatGPT web (prompt §8: "DO NOT bypass CAPTCHA, DO NOT steal cookies").**

---

## 4. Legacy Workspace Tools: External Agent Candidates (Unsafe)

### 4.1 `legacy/workspace/tools/` — 80+ Scripts (Audit Required)

| Category | Examples | Safety | Canonical? |
|----------|----------|--------|------------|
| YouTube | `composio_youtube.py`, `youtube_direct.py`, `youtube_oauth.py` | Composio v3.1 verified; direct needs API key; OAuth placeholder | ❌ Legacy |
| Web Research | `web_research.py`, `browser.py` | DDG search; browser automation | ❌ Legacy |
| Finance/Trading | `crypto_tracker.py`, `trading_bot.py`, 10+ more | API keys; real money risk | ❌ Legacy |
| Security | `security_scanner.py`, `port_scanner.py`, `vuln_scanner.py` | **Offensive capabilities**; skill gate blocks | ❌ Legacy |
| Git | `git_auto.py` | Auto-commit/push | ❌ Legacy |
| Android | 7+ scripts | Device automation | ❌ Legacy |
| **External AI** | `agent_commander.py` (opencode wrapper) | **Hardcoded paths, unsafe** | ❌ Legacy |

**All legacy tools are explicitly quarantined** (`legacy/README.md`: "unsafe operations... must never be reachable through the Elysia agent pipeline"). They demonstrate **what external agents could do** but are not integrated.

---

## 5. Integration Registry: Missing

### 5.1 Required CLI (Prompt §31)

| Command | Implemented? |
|---------|--------------|
| `elysia integrations` | ❌ (only `elysia providers --catalog`) |
| `elysia integrations doctor` | ❌ |
| `elysia integrations test` | ❌ |
| `elysia integrations status` | ❌ |
| `elysia integrations run <integration>` | ❌ |

### 5.2 Required Doctor Checks (Prompt §32)

| Check | Current ProviderDoctor | Missing for External Agents |
|-------|------------------------|----------------------------|
| Executable exists | ✅ (binary on PATH) | OpenCode/Codex/Claude workspace access |
| Version | ✅ | Agent protocol version |
| Authentication | ✅ (env var / binary login) | Workspace permissions, token scope |
| Configuration | ✅ | Isolation config, resource limits |
| Permissions | ✅ | Workspace isolation, file ownership |
| Provider health | ✅ | Agent responsiveness, task queue |
| Browser availability | ✅ | Browser automation backend |
| Computer backend | ✅ | Display server, input permissions |
| API connectivity | ✅ | Agent WebSocket/HTTP endpoint |

---

## 6. Security Audit

| Threat | Current Mitigation | Missing |
|--------|-------------------|---------|
| Arbitrary command execution via external agent | ProviderManager only does chat | **ExternalAgent adapter must sandbox** |
| Workspace escape | `Workspace` path validation | **Isolation per delegated task** |
| Credential leakage | `config/providers.env` 0600, redacted in logs | **Agent tokens not stored** |
| Unrestricted browser control | SSRF guard + permission tokens | **Agent browser actions need same guard** |
| Secret logging | Central redaction in `git.py` | **Agent output redaction** |
| CAPTCHA bypass | Not attempted | **Explicitly forbidden (prompt §8)** |

---

## 7. Resource Awareness (Prompt §24)

| Resource Class | Provider | External Agent (Missing) |
|----------------|----------|--------------------------|
| `LOCAL_LLM` | ✅ Budgeted (1 slot) | Would need local agent CPU budget |
| `REMOTE_LLM` | ✅ Budgeted (spend cap) | Agent API spend tracking |
| `CPU_HEAVY` | ✅ Scheduler budget | Local agent (OpenCode) CPU |
| `NETWORK` | ✅ Provider calls | Agent WebSocket/HTTP |
| `BROWSER` | ✅ Tool permission | Agent browser automation |
| `COMPUTER` | ✅ Tool permission | Agent desktop control |
| `LIGHT` | ✅ Unlimited | Agent status polling |

---

## 8. Findings Summary

| Category | Count | Criticality |
|----------|-------|-------------|
| Provider system complete | 9/9 providers | ✅ |
| ExternalAgent abstraction | 0/8 adapters | 🔴 |
| IntegrationRegistry | 0/1 | 🔴 |
| Workspace isolation for delegation | 0/1 | 🔴 |
| Result normalization | 0/1 | 🔴 |
| Verification gate | 0/1 | 🔴 |
| Browser/Computer tools exist | 11/11 tools | ✅ (but not for delegation) |
| Browser login flow | ✅ Complete | ✅ |
| Legacy tools quarantined | 80+ scripts | ✅ (correct) |
| CLI integration commands | 0/5 | 🟡 |
| Integration doctor | 0/9 checks | 🟡 |

---

## 9. Remediation Plan (Sequential, After Intelligence Fabric)

1. **`elysia/core/integrations/base.py`** — `ExternalAgent` ABC with `inspect/start_task/observe/cancel/collect_result`
2. **`elysia/core/integrations/registry.py`** — `IntegrationRegistry` with capability detection, health, auth status
3. **`elysia/core/integrations/opencode.py`** — OpenCode adapter:
   - Detect install (`which opencode`), version (`opencode --version`)
   - Launch with workspace dir, task instruction via CLI/stdin
   - Monitor process, capture stdout/stderr, parse structured output
   - Workspace isolation: copy repo to `workspace/tasks/task-<id>/` or Git worktree
4. **`elysia/core/integrations/codex.py`** — Codex adapter (similar; official CLI if available)
5. **`elysia/core/integrations/freebuff.py`** — Freebuff adapter (API-based per their docs)
6. **`elysia/core/integrations/openai.py`** — OpenAI API provider (already exists) + ChatGPT web **explicitly not automated** (prompt §8)
7. **`elysia/core/integrations/browser.py`** — Playwright/CDP backend for `BrowserController` (separate from `urllib` tool)
8. **Wire into `MasterController`/`Scheduler`** — External agent tasks enter canonical scheduler; `TaskExecutor` calls `ExternalAgent.start_task()` → monitors → `collect_result()` → `ToolLayer` verification (tests, QA, diff)
9. **CLI** — `elysia integrations`, `elysia integrations doctor`, `elysia integrations run`
10. **Tests** — Fake adapters for unit tests; opt-in smoke tests with real agents

---

## 10. Verification Commands (Post-Implementation)

```bash
# Discovery
./bin/elysia integrations
# Freebuff       AVAILABLE
# OpenCode       AVAILABLE (v0.3.1)
# Codex          NOT CONFIGURED (no auth)
# OpenAI API     AVAILABLE
# Browser        AVAILABLE (Playwright)
# Computer       AVAILABLE (xdotool)

# Doctor
./bin/elysia integrations doctor
# OpenCode: installed ✓, version ✓, workspace access ✓, usable ✓
# Codex: installed ✓, authenticated ✗, usable ✗

# Delegation test
./bin/elysia master run "Use OpenCode to add tests to utils.py"
# → creates task, selects OpenCode, launches in isolated workspace,
#   monitors, collects result, runs tests, verifies diff, reports

# Multi-agent delegation
./bin/elysia master run "OpenCode implements, Codex reviews, local tests verify"
# → scheduler queues 3 tasks with deps; each runs on appropriate integration
```

---

## 11. Conclusion

Elysia's **provider system is production-complete** for model inference. **External agent delegation is the missing layer** — treating OpenCode/Codex/Claude Code as *agents* (not providers) requires: `ExternalAgent` abstraction, `IntegrationRegistry`, workspace isolation, result normalization, and verification gate. All **canonical integration points exist** (`MasterController → Scheduler → TaskExecutor → ToolManager → Workspace → QA`). The work is building the adapter layer and wiring it into the scheduler, not creating parallel execution paths.

**Next step (after Intelligence Fabric):** Implement `elysia/core/integrations/base.py` + `registry.py` + `opencode.py` as the foundation.