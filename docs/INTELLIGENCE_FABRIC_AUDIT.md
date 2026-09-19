# Elysia Intelligence Fabric Audit — Complete System Analysis

**Audit Date:** 2026-09-19  
**Scope:** `elysia/core/` — `master.py`, `scheduler.py`, `executor.py`, `agents.py`, `providers.py`, `tasks.py`, `workspace.py`, `toolkit.py`, `skills.py`, `memory.py`, `context.py`, `graph.py`, `healing.py`, `knowledge.py`, `config.py`, `prompts.py`, `project.py`, `resources.py`, `health.py`, `events.py`, `telemetry.py`, `fileblocks.py`, `qa.py`, `git.py`, `paths.py`, `browser_login.py`, `hf.py`, `plugins.py`, `autonomy.py`, `openreacher.py`, `server_api.py`, `jarvis.py`, `briefing.py`

---

## Executive Summary

**Current State:** Elysia has a **complete canonical execution pipeline** (`MasterController → Scheduler → TaskExecutor → AgentPipeline → ProviderManager → ToolLayer → Workspace → QA`) with real durability, provider failover, lease/heartbeat recovery, resource-aware scheduling, and structured events. **However, the "Intelligence Fabric" (knowledge retrieval, dataset ingestion, adapter registry, RAG, embeddings, provenance, distillation) is entirely absent.** The system operates as: **goal → plan → execute → verify** with **zero external knowledge retrieval**, **zero dataset support**, **zero adapter system**, and **no provenance tracking**.

**Critical Gaps:**
1. **No Knowledge Fabric** — `elysia/core/knowledge.py` only indexes vendored Kali-tool docs (10 files); no document ingestion, chunking, embedding, hybrid retrieval, reranking
2. **No Dataset System** — No dataset registry, ingestion pipeline, catalog, or compatibility checks
3. **No Adapter System** — No LoRA/PEFT registry, router, loader, stacking, or compatibility checks
4. **No RAG Pipeline** — No query analysis, lexical/semantic retrieval, hybrid merge, compression, citation
5. **No Provenance** — Knowledge items lack source, version, transform history, license, trust level
6. **No Distillation/Synthetic Data** — No teacher→dataset→adapter pipeline
7. **No Intelligence Router** — Skills/knowledge/adapters not unified; `AgentPipeline` uses hardcoded roles only
7. **Context = only task files + memory** — No retrieved knowledge, no skill instructions, no adapter context

**Bottom Line:** The **execution engine is production-ready**; the **intelligence layer is missing entirely**.

---

## 1. Current Architecture: Canonical Pipeline (Working)

### 1.1 Execution Flow (Verified in Code)

```
User Goal
    ↓
MasterController.submit(goal)           # elysia/core/master.py:302
    ↓
MasterController.plan(goal)             # → AgentPipeline.plan_task() (planner role)
    ↓
persist_goal() → TaskStore (SQLite)     # Durable task graph with deps, owned_files
    ↓
MasterController.start()                # Scheduler + TaskExecutor threads
    ↓
Scheduler.dispatch_once()               # Claims ready tasks; atomic provider reservation
    ↓
TaskExecutor._run_one(task)             # In-process, parallel threads, lease heartbeats
    ↓
AgentPipeline.solve_task()              # elysia/core/agents.py:234
    ├── implementer_messages()          # ContextPlanner builds prompt (budget=6000 tokens)
    │   ├── task + owned files content
    │   ├── failure memories + classification
    │   ├── test results
    │   ├── solution/decision memory
    │   └── provider routing explanation
    ├── _call(implementer)              # ProviderManager.execute() with fallback
    ├── parse_file_blocks()             # Fenced code blocks → file writes
    ├── Workspace.write_owned()         # Path-validated (no traversal)
    ├── QA validate_file()              # py_compile, gofmt, tsc, shellcheck, json
    ├── _run_tests()                    # Discovered test runner (pytest/go/cargo/npm)
    ├── git_diff_text()                 # Real diff for code_reviewer
    └── review()                        # code_reviewer role on diff
    ↓
TaskStore.complete()                    # Status: completed/failed + result
    ↓
Memory.remember_solution()              # Persistent layered memory
Memory.remember_task_context()          # Context report stored
```

### 1.2 Verified Capabilities (Tests Pass)

| Capability | Module | Test Coverage |
|------------|--------|---------------|
| Durable task graph with deps | `tasks.py`, `scheduler.py` | `tests/test_master_control.py`, `test_runtime_wiring.py` |
| Lease/heartbeat + crash recovery | `scheduler.py:131-163` | `test_runtime_wiring.py` (lease expiry → ready) |
| Provider failover (circuit breaker) | `providers.py:182-280` | `test_providers_plus.py::ProviderHealthCircuitTests` |
| Resource-aware scheduling | `scheduler.py:292-300`, `resources.py` | `test_runtime_wiring.py` (budget gate) |
| Atomic provider reservation | `providers.py:770-812` | `test_master_control.py` (provider failover mid-task) |
| Permissioned tool layer | `toolkit.py`, `tools.py` | `test_tool_layer.py` (deny-by-default, reviewers read-only) |
| Workspace path security | `paths.py`, `workspace.py` | `test_paths.py`, `test_worker_security.py` |
| Language-aware QA | `qa.py` | `test_core.py` (py_compile, gofmt, tsc, json) |
| Self-healing (classify→recover→verify) | `healing.py`, `agents.py:422-458` | `test_memory_context_healing.py` |
| Structured events | `events.py`, `master.py` | All integration tests emit events |
| Git safety (checkpoint, redact) | `git.py` | `test_git_redact.py` |
| Multi-agent pipeline stages | `agents.py` | `test_master_control.py` (planner→impl→test→review) |

---

## 2. Intelligence Fabric: What Exists vs Required

### 2.1 Required by Prompt (§2-§107) vs Implemented

| Intelligence Fabric Component | Prompt Ref | Implemented? | Location |
|-------------------------------|------------|--------------|----------|
| `fabric.py` — high-level interface | §3, §4 | ❌ | — |
| `router.py` — unified IntelligenceRouter | §25 | ❌ | — |
| `knowledge.py` — unified knowledge system | §5 | ⚠️ Partial | `elysia/core/knowledge.py` (vendored Kali docs only) |
| `datasets.py` — dataset ingestion/registry | §7, §8 | ❌ | — |
| `adapters.py` — LoRA/PEFT registry/router | §17, §18, §19 | ❌ | — |
| `embeddings.py` — embedding abstraction | §12, §13 | ❌ | — |
| `retrieval.py` — hybrid RAG pipeline | §10, §11 | ❌ | — |
| `reranking.py` | §10 | ❌ | — |
| `context.py` — ContextPlanner (exists) | §41, §42 | ✅ | `elysia/core/context.py` |
| `provenance.py` — source tracing | §6 | ❌ | — |
| `sources.py` — source registration/refresh | §76, §77 | ❌ | — |
| `loaders.py` — document/PDF/web loaders | §7 | ❌ | — |
| `ingestion.py` — normalize/dedup/quality | §7 | ❌ | — |
| `chunking.py` | §7 | ❌ | — |
| `indexing.py` — vector/lexical index | §10, §11 | ❌ | — |
| `compression.py` — context compression | §14 | ❌ | — |
| `distillation.py` — teacher→adapter | §30 | ❌ | — |
| `evaluation.py` / `benchmarks.py` | §63, §64 | ❌ | — |
| `cache.py` — retrieval/embedding cache | §20, §44 | ❌ | — |
| `policies.py` — security/trust/license | §54, §55, §56 | ❌ | — |
| `resource.py` — resource declarations | §57-§60 | ❌ | — |

### 2.2 Existing `elysia/core/knowledge.py` Analysis

```python
# CURRENT: Only 10 vendored Kali-tool markdown files
load_all() → [
    KnowledgeEntry(name="nmap", category="recon", ...),
    KnowledgeEntry(name="wireshark", category="analysis", ...),
    KnowledgeEntry(name="burpsuite", category="web", ...),
    KnowledgeEntry(name="sqlmap", category="web", ...),
    KnowledgeEntry(name="metasploit", category="exploitation", ...),
    KnowledgeEntry(name="ghidra", category="reverse-engineering", ...),
    KnowledgeEntry(name="john", category="passwords", ...),
    KnowledgeEntry(name="hydra", category="passwords", ...),
    KnowledgeEntry(name="aircrack-ng", category="wireless", ...),
    KnowledgeEntry(name="feroxbuster", category="web", ...),
]
```

**Missing for Intelligence Fabric:**
- No document ingestion (PDF, web, Git, YouTube, datasets)
- No chunking, embedding, vector index
- No hybrid retrieval (BM25 + semantic)
- No reranking, compression, citation
- No provenance (source, version, license, transform history)
- No trust levels (only `risk: low/moderate/high`)
- No freshness policies, conflict detection, claim extraction
- No project-specific namespaces, snapshots, temporal knowledge

### 2.3 Existing `elysia/core/memory.py` — Layered Memory (Working)

```python
# Namespaces: session, conversation, task, workflow, project, repo,
# user_prefs, agents, providers, failure, solution, decision,
# architecture, research, tools, history
# Per-record: importance, confidence, provenance, TTL, recall_count, content_hash
# Dedup: identical content merged
# Compaction: expired dropped; oldest compressed into summary (keys preserved)
# Backup/restore: round-trip; refuses corrupt
# Recall: explainable score (keyword × importance × recency + recall boost)
```

**This IS the Memory subsystem** — works correctly. **But it's not Knowledge** (prompt §15: "MEMORY = user/task history; KNOWLEDGE = external info").

---

## 3. Provider System: Complete (With Circuit Breaker)

### 3.1 `elysia/core/providers.py` — Verified Capabilities

| Feature | Status | Details |
|---------|--------|---------|
| OpenAI-compatible (local llama.cpp, Ollama, OpenRouter, Groq, etc.) | ✅ | `_chat_openai` |
| NVIDIA NIM | ✅ | Configurable |
| CLI providers (Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw) | ✅ | `_chat_cli` — activates when binary on PATH |
| Capability-based routing | ✅ | `select(capabilities)`, `explain(capabilities)` |
| Strict → soft capability fallback | ✅ | `SOFT_CAPABILITIES = {REASONING, LONG_CONTEXT, VISION}` |
| Circuit breaker (closed/open/half-open) | ✅ | `FAILURE_THRESHOLD=3`, doubling cooldown (30s→900s) |
| Budget enforcement (estimated spend) | ✅ | `set_budget()`, `_spend_gate()` drops paid providers |
| Health reporting + probe | ✅ | `health_report(probe=True)` |
| One-slot atomic reservation | ✅ | `ProviderReservation` context manager |
| Structured events on transitions | ✅ | `provider.quarantined`, `half_open`, `recovered` |

**No Intelligence Fabric integration** — providers don't declare adapter compatibility, dataset awareness, or knowledge source requirements.

---

## 4. Context Management: Working (ContextPlanner)

### 4.1 `elysia/core/context.py` — Verified

| Feature | Status |
|---------|--------|
| Layers: system, task, files, failures, tests, memory, review, provider, capabilities | ✅ |
| Per-role priority tables | ✅ (implementer: failures > provider; reviewer: diff > memory) |
| Token budget enforcement | ✅ (implementer: 6000 tokens) |
| Long layer → recent TAIL truncation | ✅ |
| Dropped layers reported with reason | ✅ |
| Plan cached until inputs change | ✅ |
| `ContextBuilder` simple assembler also exists | ✅ |

**Gap:** ContextPlanner only sees **task files + memory + provider routing**. No retrieved knowledge, no skill instructions, no adapter context.

---

## 5. Critical Missing: Intelligence Fabric Integration Points

### 5.1 Where Intelligence Fabric Must Plug In (Prompt §0, §4, §10, §16, §25)

| Integration Point | Current | Required |
|-------------------|---------|----------|
| `MasterController.plan()` | Planner only | → `KnowledgeRouter` → relevant sources → `SkillRouter` → relevant skills → `AdapterRouter` |
| `AgentPipeline.implementer_messages()` | Task files + memory | + Retrieved knowledge chunks + Skill instructions + Adapter context |
| `AgentPipeline.solve_task()` | Fixed roles | Dynamic role selection based on skill/adapters |
| `ProviderManager.select()` | Capabilities only | + Adapter compatibility + Knowledge source requirements |
| `Scheduler.dispatch_once()` | Resource budget | + Intelligence budget (model calls, retrieval, embedding CPU) |
| `ToolLayer` | Static tools | + Skill-declared tools dynamically registered |

### 5.2 Required New Types (Prompt §4)

```python
# IntelligencePlan — produced by IntelligenceFabric
IntelligencePlan:
    objective: str
    knowledge_sources: list[KnowledgeSource]
    retrieved_context: list[RetrievedChunk]
    skills: list[Skill]
    adapters: list[Adapter]
    memory: MemoryContext
    provider: ProviderRequirement
    model: ModelRequirement
    tools: list[Tool]
    permissions: Permissions
    resource_budget: ResourceBudget
    verification_plan: VerificationPlan
    provenance: ProvenanceRecord
```

---

## 6. Security Audit: Intelligence Fabric Surface

| Threat | Current Mitigation | Missing |
|--------|-------------------|---------|
| Prompt injection via retrieved docs | None (no retrieval) | Provenance + trust boundaries (§55) |
| Malicious dataset payloads | None (no datasets) | Safe ingestion pipeline (§54) |
| Unsafe adapter loading | None (no adapters) | Verify repo, hash, metadata (§56) |
| Credential leakage in knowledge | None (no knowledge) | Central redaction (§55) |
| License violation | None (no ingestion) | License tracking + policy (§34, §98) |
| Path traversal in loaders | None (no loaders) | Path validation reuse (§54) |

---

## 7. Resource Audit

| Resource | Current | Intelligence Fabric Adds |
|----------|---------|--------------------------|
| RAM | 1 local model (1-3 GB) + TaskExecutor | Embedding model(s), vector index, knowledge cache, adapter weights |
| CPU | 1-2 inference threads | Embedding batch, indexing, reranking, distillation |
| Disk | SQLite + workspace | Vector DB, dataset files, adapter files, knowledge chunks |
| Network | Provider APIs | Web research, dataset download, model/adapter fetch |
| Model slots | 1 local (`LOCAL_LLM_CONCURRENCY=1`) | Same — adapters share base model |

**Must implement:** Lazy loading, streaming, chunked processing, cache eviction, adapter unloading, background indexing (§58).

---

## 8. Findings Summary

| Component | Status | Criticality |
|-----------|--------|-------------|
| Knowledge Fabric | ❌ Missing | 🔴 |
| Dataset System | ❌ Missing | 🔴 |
| Adapter System | ❌ Missing | 🔴 |
| RAG Pipeline | ❌ Missing | 🔴 |
| Provenance System | ❌ Missing | 🔴 |
| Intelligence Router | ❌ Missing | 🔴 |
| Distillation/Synthetic Data | ❌ Missing | 🟡 |
| Evaluation/Benchmarks | ❌ Missing | 🟡 |
| ContextPlanner | ✅ Complete | — |
| ProviderManager + Circuit Breaker | ✅ Complete | — |
| Layered Memory | ✅ Complete | — |
| Task Graph + Scheduler | ✅ Complete | — |
| Permissioned Tool Layer | ✅ Complete | — |
| Workspace Security | ✅ Complete | — |
| Self-Healing | ✅ Complete | — |

---

## 9. Remediation Plan (Sequential)

1. **`elysia/core/intelligence/fabric.py`** — `IntelligenceFabric` class; `plan(task, agent, context)` → `IntelligencePlan`
2. **`elysia/core/intelligence/knowledge.py`** — Replace/extend vendored `knowledge.py` with:
   - `KnowledgeRegistry` (SQLite: source, chunks, embeddings, provenance, trust, license)
   - `DocumentLoader` (PDF, MD, web, Git, YouTube transcript)
   - `Chunker` (semantic, size-bounded)
   - `EmbeddingManager` (local/remote, batch, cache, LRU)
   - `VectorIndex` (SQLite-vec or FAISS-lite; metadata filter)
   - `HybridRetriever` (BM25 + semantic + metadata filter + rerank)
   - `ContextCompressor` (extractive → summary → claims)
   - `ProvenanceTracker` (source → raw → norm → chunk → embed → index → retrieve)
3. **`elysia/core/intelligence/datasets.py`** — `DatasetRegistry`, ingestion pipeline, catalog CLI
4. **`elysia/core/intelligence/adapters.py`** — `AdapterRegistry`, `AdapterRouter`, compatibility checks, LRU load/unload
5. **`elysia/core/intelligence/router.py`** — `IntelligenceRouter` unifying Knowledge/Skill/Adapter routers → `ProviderManager`
6. **Wire into `MasterController.plan()`** — `IntelligenceFabric.plan()` → `IntelligencePlan` → `AgentPipeline` context
7. **Wire into `AgentPipeline.implementer_messages()`** — Inject retrieved chunks, skill instructions, adapter context
8. **CLI** — `elysia intelligence status|plan|search|sources`, `elysia datasets ...`, `elysia adapters ...`
9. **Tests** — Retrieval precision/recall, citation correctness, adapter compat, resource limits, offline mode

---

## 10. Verification Commands (Post-Implementation)

```bash
# Intelligence Fabric
./bin/elysia intelligence status              # sources, embeddings, adapters, loaded model
./bin/elysia intelligence plan "Analyze PDF"  # dry-run: skills, sources, adapters, provider, budget
./bin/elysia intelligence search "port scan"  # hybrid retrieval with citations
./bin/elysia intelligence explain "task"      # why this model/skill/adapter/source

# Knowledge
./bin/elysia knowledge search "nmap"          # existing vendored
./bin/elysia knowledge ingest ./docs          # PDF/MD/web ingestion
./bin/elysia knowledge rebuild                # re-index

# Datasets
./bin/elysia datasets list
./bin/elysia datasets search "code"
./bin/elysia datasets ingest ./data.csv

# Adapters
./bin/elysia adapters list
./bin/elysia adapters load coding-lora
./bin/elysia adapters benchmark

# Integration test
./bin/elysia master run "Research X, write report with citations"
# → should show: knowledge sources retrieved, skills selected, provider chosen, citations in output
```

---

## 11. Conclusion

Elysia's **canonical execution pipeline is complete and tested**. The **Intelligence Fabric is the only major missing subsystem**. All required integration points exist (`MasterController.plan`, `AgentPipeline.implementer_messages`, `ProviderManager.select`, `Scheduler.dispatch_once`, `ContextPlanner`, `ToolLayer`, `Memory`, `EventBus`). The work is **building the fabric modules and wiring them into these existing hooks** — not creating parallel architectures.

**Next step:** Implement `elysia/core/intelligence/fabric.py` + `knowledge.py` (registry, loader, chunker, embedder, index, retriever) as the foundation.