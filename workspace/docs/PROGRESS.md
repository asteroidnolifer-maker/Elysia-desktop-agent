# Elysia Agent Progress Tracker

> Live todo list for the current work. Updated as steps complete.
> Source of truth for architecture: `STATE.md`. Last updated: 2026-09-08

## HARD CONSTRAINTS (do not violate)

- **NO opencode / NO third-party AI calls.** Credits exhausted. All inference goes
  through the local stack: llama-server (:11434) + agent-core (:8085).
- **PROTECT THE MACHINE ("blackbox must not crash")**: 4 cores, 16GB RAM.
  Max 2 workers, each worker = 1 lightweight python process (HTTP calls only).
  If MemAvailable < 2GB, adaptive pool pauses spawning.
- Workers only edit `/home/myusername/elysia/workspace` (writable copy).

## Phase 0 — Cleanup & diagnosis ✅

- [x] Diagnosed old failures: opencode hung awaiting permission approval
      (missing `--auto`) → rc=124; empty replies → tasks burned as failed.
- [x] Local model verified directly: `POST :8085/chat` → `PONG_OK`.
- [x] Old opencode pool + stray workers killed.

## Phase 1 — opencode-free agent runtime ✅

- [x] `brain.py` — local-LLM runtime: chat via :11434, file-block parser,
      auto-QA (JSON parse / py compile / brace balance / md checks).
- [x] `worker_local.py` — worker loop: claim → local model → write files →
      QA → done/failed. Max 2 model calls per task.
- [x] `adaptive.sh` rewired: spawns `worker_local.py`, cap 2, RAM guard,
      correct `down`.
- [x] `ask.sh` — direct prompts to the local model (one-shot or interactive).
- [x] Smoke test PASSED: worker claimed #14, wrote `src/VulnScanner.ts`, DONE.
- [x] Pool launched (cap 2): board draining 59 → 53 open; done 208 → 214.
      Verified completions: #19 src/elysia.ts, #43 mobile link test, #51 in progress.

## Phase 2 — Task board expansion (NEXT)

- [ ] Add fresh tasks tied to real workspace files: Android integration docs,
      mobile UI implementation, agent-core docs, config validation, test notes.
- [ ] Retry policy for failed tasks (e.g. #53 failed: model answered prose
      instead of file blocks).

## Phase 3 — Monitoring agent (mistake watcher)

- [ ] `monitor.py` — requeue failed tasks (max 2 retries), check model health,
      kill zombie workers, log anomalies here.

## Phase 4 — JARVIS UI ✅ (implemented 2026-09-09)

- [x] `server.py` — stdlib HTTP server on **:8087**. Endpoints:
      `GET /` (HUD page) · `GET /jarvis.jpg` (theme image) ·
      `GET /api/state` (health+counts+recent+agents) ·
      `GET /api/tasks?status=&n=&id=` · `GET /api/agents` ·
      `GET /api/agent-log?worker=` · `POST /api/ask` (goal → local-model
      division → board → auto pool) · `POST /api/pool {start|stop}` ·
      `POST /api/task` (manual add).
- [x] HUD web UI (`hud.html`) themed after `~/Downloads/jarvis.jpg`
      (extracted palette: dark slate #292a32, teal #269395/#2fb8bf,
      steel #7ca8b8): stat tiles, board drain meter, live task table,
      agent cards, tail-able console, ASK JARVIS box, pool controls.
- [x] Full automatic loop smoke-tested end-to-end: `/api/ask` → division
      (model) → board → adaptive pool worker claimed → wrote file → done.
- [x] Fixed bug found in smoke test: `/api/ask` + `/api/task` success paths
      returned their payload instead of sending it (empty reply) — now `_send`s.

## Phase 5 — Quality hardening (2026-09-09, in progress)

- [x] `INSTRUCTIONS.md` — binding rules injected into EVERY worker prompt and
      every division call: ground work in the attached real file contents,
      never invent, write complete files, never paste raw dumps into .md, no
      filler lines, output format.
- [x] Worker context attach: prompts include real content of owned files that
      exist + every existing file named in the task (verbatim when small /
      markdown; structural surface for big code). Fixes the old blind
      hallucination (workers previously saw file NAMES only).
- [x] Grounding QA: produced `.md` must reuse ≥2 distinctive tokens from the
      attached reference files, else attempt is rejected and retried.
- [x] Markdown QA hardening (`brain.qa_check`): raw JSON dumps and files
      without a leading `#` heading are rejected.
- [x] Division safety: prompt tells the splitter a subtask owns files it
      CREATES/REWRITES only; `apply_output_target()` guard re-owns a doc goal
      with the user's named new `.md` (never hands an existing config/source
      to a worker as a write target).
- [x] JARVIS chat (`POST /api/chat`): intent detection → live status | pool
      control | build-split | general model answer. HUD chat panel with
      history, typing indicator, task chips.
- [x] Adaptive pool: always reserves ≥1.5 GB free RAM (`mem_avail -
      want*600MB >= 1536`); never kills mid-task.
- [x] Verified end-to-end: #1319 grounded config guide (exact values), #1320 bad
      (JSON dump) caught by review → archived, #1321 regenerate passed all QA
      (headings, real values, no dump/filler). Board has 2 done + 1 archived
      for this pass.

  Known model limit (recorded honestly): qwen 1.5B hallucinates when
  ungrounded, truncates, and occasionally disobeys instructions (attempted to
  paste a JSON dump as a doc). The QA/grounding layers above catch and reject
  these so junk never lands as `done` — bad attempts are requeued with the
  rules re-injected.

  Launch: `setsid nohup python3 orchestrator/server.py --port 8087`
  `</dev/null >>orchestrator/logs/server.log 2>&1 &`
  Desktop: `~/Desktop/open-jarvis-hud.sh` / `open-jarvis-hud.desktop`

## Verification log

| Time | Check | Result |
|------|-------|--------|
| 09-08 | model chat :8085 | PONG_OK |
| 09-08 | opencode run (baseline) | broken: rc=124 / empty output → abandoned |
| 09-08 | worker_local smoke test | DONE: wrote src/VulnScanner.ts |
| 09-08 | pool cycle 1-3 | 2 workers, RAM 11.7GB free, board draining |
| 09-09 | HUD server + /api/ask | division → board #1315 → worker claimed → file written (loop OK; content hallucinated by 1.5B) |
| 09-09 | HUD endpoints | /api/state, /tasks, /agent-log, /pool, /task, /jarvis.jpg all 200 |
| 09-09 | chat status/#NNN | deterministic live summaries accurate |
| 09-09 | chat general Q | local model answered (taskboard lock) |
| 09-09 | chat build → #1319 | grounded config guide written (values match agent_config.json exactly); filler lines flagged |
| 09-09 | review loop | #1320 bad pass (JSON dump in .md) caught by review → archived; QA + INSTRUCTIONS hardened |
| 09-09 | #1321 regenerate | proper-markdown pass running (see board) |
| 09-09 | #1321 done | clean md guide: `#` per-key sections, real values, no dump/filler — review loop closed |
