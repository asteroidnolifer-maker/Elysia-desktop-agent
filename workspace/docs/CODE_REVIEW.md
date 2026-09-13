# Elysia Project - Code Review Summary

## Overview
- **Files reviewed**: 83 TypeScript source files (~10,900 lines) + 41 test suites
- **Test coverage**: 41 test suites, 282 tests (all passing)
- **TypeCheck**: ✅ Passes
- **Lint**: ✅ Passes

## Architecture Strengths

### 1. Clean Separation of Concerns
- **AirLLM stack** (`src/common/airllm/`): Model routing, runtime management, task queue, embeddings
- **Agent core** (`src/common/agent/`): Agent loop, tools, memory, preferences, orchestrator
- **IPC layer** (`src/electron/ipc/`): Electron main/renderer communication
- **Skills/Plugins**: Extensible via `SkillRegistry` and `PluginLoader`

### 2. Innovative Multi-Model Orchestration
- **AirRouter**: Task-type → tier mapping (fast/reason/deep) with warm-model preference
- **AsteroidMode**: Fleet debate with parallel models + judge synthesis
- **WorkSplitter**: Planner → parallel workers → merger (true separation of labor). `parseWorkItems` is robust to loose planner output formats.
- **OnlineRouting**: Privacy-first cloud routing with per-category consent

### 3. Robust Runtime Management
- `LlmRuntimeManager`: Spawns `llama-server` processes, health-checks, idle sweeper
- Warm model pinning for instant interactive responses (skipped by the idle sweeper)
- External backend support (Ollama) without process management; syncs locally installed Ollama models via `ModelRegistry.syncOllama`

### 4. Memory & Preferences
- `MemoryStore`: JSONL-backed with token + vector search hybrid, retention policy (1000 entries, 30-day cutoff, importance-weighted eviction)
- `Preferences`: Category-based, deduped, injected into system prompt
- Context compaction in `Agent.compactHistory`: older turns are summarized into memory so long conversations stay bounded

### 5. Tool Ecosystem (25+ tools)
Files (read/write/list), shell, web search/fetch (multi-engine fallback with TTL caches), memory, preferences, game, VM, nightcrawler, WSL, storage, knowledge, claw, opencode, finance, departments, devtools, composio, agentreach, MCP

### 6. Security & Approval Gates
- `ScopeEngine`: CIDR/IP/subdomain allowlists backed by `store/scope.txt`
- `ApprovalEngine`: once/tool/target/task/session/preapprove rules with persisted grants; deterministic scope check runs first — an AI promise is never the authorization
- `CommandHistory`: Pattern analysis for repeated/risky commands
- Safe mode blocks dangerous commands
- Config schema validation (hand-rolled JSON-Schema subset in `src/common/config/ConfigSchema.ts`) now covers `models.json`, `preferences.json`, `online-routing.json`, `profile.json`, `skills-state.json`

## Code Quality Observations

### ✅ Good Practices
- Comprehensive JSDoc comments on public APIs
- Defensive error handling (try/catch with graceful degradation; asteroid/work splitter degrade to "strongest member" or best-effort merge instead of dying)
- Event-driven architecture via `EventEmitter`
- Dependency injection for testability (e.g., `ResearchAgent` takes search/fetch fns, `AsteroidMode`/`WorkSplitter` take an injectable runtime)
- TypeScript strict mode, no `any` abuse
- Singleton globals for cross-module access (e.g., `GlobalLlmRuntime`, `GlobalAgentMemory`)

### ⚠️ Areas for Improvement

1. **Error Handling Consistency**
   - Some catch blocks swallow errors silently (`/* memory must never break tasks */`)
   - Error paths favor string matching on `e.message`; consider structured error types (e.g. `ModelLoadError`, `ToolExecutionError`)

2. **Magic Numbers/Strings**
   - `COMPACT_TOKEN_THRESHOLD = 12000` (env-configurable but hardcoded default)
   - `REQUEST_TIMEOUT_MS = 30 * 60 * 1000` duplicated in `AsteroidMode.ts:41` and `WorkSplitter.ts:50`
   - Port numbers hardcoded: `8080` (`RuntimeManager.ts:30`, and `nightcrawler.ts:16` assumes the warm model is on 8080), `8095` (`Embeddings.ts:9`, `HealthCheck.ts:95`)

3. **Test Gaps**
   - No integration tests for `ElysiaOrchestrator.executeTask()` (core coordination logic; `runTask`/`executeTask` are the center of the system)
   - `LlmRuntimeManager` tests are mock-heavy — no real `llama-server` process tests
   - Electron IPC handlers untested

4. **TypeScript Config**
   - Multiple tsconfig files (common, electron, root) — could consolidate
   - `strictNullChecks` not explicitly verified

5. **Performance Considerations**
   - `MemoryStore.search()` loads and scores all entries in memory — unbounded cost as the store grows (retention cap is 1000 entries by default; the 30-day "recent" branch can keep far more)
   - `EmbeddingService.hashEmbed()` is O(n*dims) per token — acceptable fallback, not primary
   - Regex-based HTML parsing in `tools/web.ts` is fragile; `</nav>`/`<script>` stripping in `htmlToText` misses non-closing tags and lazy lists never re-check orphaned markup

6. **Configuration Management**
   - Config files scattered (`models.json`, `skills.json`, `preferences.json`, `online-routing.json`) — schema validation now exists but there is no single unified, validated entry point for all configs

7. **Async Patterns**
   - Some `async` functions don't need to be (e.g., `MemoryStore.recent()`, `MemoryStore.all()`)
   - `Promise.all` without concurrency limits in fleet spawning (asteroid members, work-split workers)

## Verified Issues Found During This Review

1. **OnlineRouting cold-start key cache bug** (`src/common/airllm/OnlineRouting.ts:131`): `route()` gates on `getKeySync()`, which only checks the in-memory `keyCache`. `keyCache` is populated only by `setKey`/`setKeyCache`/`getKey`, and `getKey` is only ever called from `executeOnline` — *after* a route has already been approved. Nothing warms the cache at `init()`. After an app restart with a previously saved provider key, the first `route()` call sees an empty cache and returns `no online provider key configured`, so consented non-private tasks silently stay local. The bug is permanently latent unless a UI action calls `getKey` (or `setKey`) first. The unit tests mask it by calling `setKeyCache` explicitly.

2. **Mixed-dimension vector cache after embedder switch** (`src/common/agent/MemoryStore.ts:23`): hash fallback produces 256-dim vectors while the LLM backend (bge-small) produces 384-dim. `ensureVectors()` only embeds *missing* ids, so cached 256-dim vectors survive a switch to the llama backend; `cosine()` returns 0 on dimension mismatch (`Embeddings.ts:60`). `stopEmbeddings()` invalidates, but `startEmbeddings()` does not — leaving stale medium-quality vectors that score 0 alongside fresh ones.

3. **Scope semantics inconsistency** (`src/common/approval/ScopeEngine.ts:78`): `isInScope()` returns `true` when no scope entries are configured (open gate), while `ScopeEngine.check()` (`:52`) returns `allowed: false` with "no scope configured". Two callers of `isInScope` therefore get opposite default behavior depending on which entry point they use — a foot-gun for new network tools.

4. **Idle sweeper never evicts failed/starting models** (`src/common/airllm/RuntimeManager.ts:59`): eviction only targets entries with `status === 'ready'`. A server stuck in `starting` (e.g., after `waitForHealth` timeout) stays in the map indefinitely and its port stays reserved.

## Recommendations

### High Priority
1. Warm the online-routing key cache at `OnlineRouting.init()` (call `getKey` for the configured provider) or make `route()` async / fall back to a lazy key load — currently consent-eligible tasks silently stay local after restart
2. Add integration test for `ElysiaOrchestrator.executeTask()` covering all task types
3. Extract timeout/port constants to a shared config module
4. Add structured error classes (e.g., `ModelLoadError`, `ToolExecutionError`) and stop relying on `e.message` string matching

### Medium Priority
1. Invalidate the `MemoryStore` vector cache when the embedder changes (and normalize dimensions across backends)
2. Reconcile `ScopeEngine.check()` vs. `isInScope()` empty-scope semantics; add a regression test
3. Implement config schema validation with a real library (Zod or JSON Schema) instead of the hand-rolled subset in `ConfigSchema.ts`
4. Add pagination/streaming to `MemoryStore.all()` for large stores
5. Replace regex HTML parsing in `tools/web.ts` with a proper parser (e.g., `parse5` or `cheerio`)

### Low Priority
1. Consolidate tsconfig files
2. Add benchmark tests for memory/vector search at scale
3. Document plugin/skill development API

## Verdict
**Strong codebase** with novel multi-model orchestration, clean architecture, defensive degradation, and comprehensive tests (41 suites / 282 tests, all green; typecheck and lint pass). One behavior-level bug (online-routing key cache never warming after restart) and one data-consistency bug (mixed-dimension vector cache on embedder switch) should be fixed before production. Ready for production with the above improvements tracked.