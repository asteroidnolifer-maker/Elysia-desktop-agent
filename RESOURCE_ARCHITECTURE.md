# Elysia Resource Architecture

> The rule everything else follows:
>
> **LOGICAL AGENT ≠ MODEL PROCESS ≠ OS PROCESS ≠ PROVIDER REQUEST**

Many agents. Few expensive processes. One local model slot. Remote work in
parallel. Deterministic tools wherever a model would be guessing. A responsive
laptop.

This document describes the resource-aware execution layer: what each unit of
work actually is, how admission is decided, where the numbers come from, and
what was measured on the low-end profile.

Target machine: **Intel i5-6300U — 2 cores / 4 threads, 16 GB RAM, no useful
GPU.** Everything below is designed around that reality and configurable for
better hardware.

---

## 1. The four different things people usually confuse

| Unit | What it is | Cost | How many |
|---|---|---|---|
| **Logical agent** | A role with a prompt, context, memory and tool permissions (`planner`, `implementer`, `code_reviewer`, …). It is a *stage in a pipeline*, executed inside the worker process. | ~0 (a function call between model uses) | dozens–hundreds |
| **Worker (OS process)** | `TaskExecutor` runs tasks in threads **inside the master process**. The legacy `worker_local.py` OS processes are a deprecated compatibility path. | 1 process per runtime | 1 (recommended), N possible |
| **Model process** | `llama-server` (or Ollama) serving the local model. Owned exclusively by `elysia.core.modelserver.ModelServer`. | GBs of RAM, whole cores while generating | **1** |
| **Provider request** | One HTTP/CLI call to any provider, local or remote, bounded by `ProviderConfig.concurrency`. | seconds of latency | concurrency-limited per provider |

So: 40 logical agents can be "active" — holding tasks, building context, writing
files, running tests — while **one** model process serves their inference
requests through a queue, and remote providers handle the overflow in parallel.

## 2. Canonical execution path (one path, no forks)

```
USER GOAL
  └─ MasterController.submit()
       └─ durable TaskStore rows (goal milestone + subtasks, priority_class,
          resource_class, privacy)
  └─ Scheduler.dispatch_plan()          ← decides WHO may start NOW, and WHY NOT
       ├─ ordered_ready()               priority class + aging + numeric priority
       ├─ ResourcePolicy.decide()       live CPU/RAM/swap/thermal ladder
       ├─ ResourceLedger.reserve()      heavy/build/io/network slot reservation
       └─ _reserve_for()                provider slot BEFORE the task starts
            ├─ local_only task → shared local slot (waits, never leaks)
            └─ else             → ModelRouter.decide(): local vs remote
  └─ TaskExecutor._run_one()            one thread per in-flight task
       └─ AgentPipeline.solve_task()
            ├─ deterministic_checks()   REAL tests/compile/JSON — zero model calls
            ├─ implementer → Workspace (permissioned writes) → QA
            ├─ router.call() → LocalModelPool (queued, 1 slot)
            │                 or remote provider (parallel)
            ├─ tester → real test runner
            └─ code_reviewer → real git diff
  └─ store.complete() / fail → healing → retry/failover/replan
```

Every piece reports the *same* verdicts the runtime enforces —
`elysia queue` prints what `dispatch_plan` actually decided, not a parallel
opinion.

## 3. Resource classes

`elysia/core/resources.py`:

| Class | Meaning | Slot cap (default) |
|---|---|---|
| `light` | cheap in-process work | unbounded |
| `io` | disk-bound | 4 |
| `network` | waiting on remote endpoints | 8 |
| `cpu` | moderate CPU | # cores |
| `cpu_heavy` | saturates cores | **1 (heavy slot)** |
| `memory_heavy` | GB-scale RAM | **1 (heavy slot)** |
| `local_llm` | inference on THIS machine | **1 (heavy slot ∧ local slot)** |
| `remote_llm` | inference elsewhere | 8 (provider concurrency also applies) |
| `build` | compile/test/bundle | **1 (heavy slot)** |

`heavy_exclusive: true` makes all heavy classes share **one** slot — this is the
enforcement of "do not run a local 7B model and a large build concurrently on a
2-core CPU".

Every task declares or is estimated a class (`task_resource_needs()`,
`estimate_resource_class()`): declared `resource_class` wins; otherwise role
(model roles → `local_llm`/`remote_llm`), build verbs in the title/description
→ `build`, heavy verbs → `cpu`, else `light`.

## 4. Priorities and fairness

Classes (lower rank runs first): `critical → interactive → normal →
background → idle`.

* **Elysia's own self-improvement defaults to `background`** — user work is never
  queued behind it (`self_improvement_priority()`).
* **Aging:** every `dispatch_aging_s` (default 30) of waiting lifts a task one
  priority rank. A background refactor can never starve behind a stream of
  newer `normal` tasks, and an interactive request still outranks everything
  that has not waited.
* **Interactive preemption:** while an `interactive`/`critical` task waits,
  `background` tasks are *not admitted* — the verdict says exactly that:
  `interactive request is waiting (background work deferred)`.
* The local model pool queue sorts by the same ranks with the same aging, so a
  long coding agent cannot block a short interactive question even inside the
  slot's queue.

## 5. Admission ladder (all configurable in `resources.*`)

| Condition (measured live) | Heavy work (`local_llm`, `build`, `cpu_heavy`, `memory_heavy`) | Light/network/remote |
|---|---|---|
| CPU < 50 % (`cpu_busy_pct`) | normal scheduling | normal |
| CPU 50–75 % (`cpu_high_pct`) | CPU-heavy jobs deferred | normal |
| CPU 75–90 % | heavy **and background** deferred | normal |
| CPU ≥ 90 % (`cpu_critical_pct`) | **blocked** | allowed (labelled `critical`) |
| Free RAM < 2 GB (`ram_min_free_mb`) | no new model/heavy job | allowed |
| Free RAM < 1 GB (`ram_block_infer_mb`) | **local inference blocked** ("memory recovery pending") | allowed |
| Swap used > 1 GB (`swap_max_used_mb`) | `memory_heavy`/`local_llm` deferred | allowed |
| Temperature ≥ `temp_max_c` | heavy deferred (thermal) | allowed |

Unknown metrics are never treated as healthy-by-assumption: when the platform
cannot read a value it is `None`/`-1` and the reason strings say so.

## 6. Local model sharing (`elysia/core/inference.py`)

`LocalModelPool` is the single queue in front of the single local slot:

* `local_llm_concurrency: 1` — one request in flight; verified by tests, not
  asserted in comments.
* Every request carries its **own** messages/context/memory — the model is
  shared, the state is not (context isolation).
* Priorities, aging, cancellation, per-request timeout, task/agent ownership.
* Requests the ledger refuses are **deferred, not failed** — they keep their
  place and `why_waiting` records the reason for `elysia resources`.
* A provider exception cannot kill a slot thread or leak the heavy slot; a
  release that raises is recorded, not propagated.

**Batching** is honest: it is only enabled when the backend declares
`batch: true`; otherwise `elysia models` says plainly that grouping chat
requests would only add latency on this hardware.

### Warm state and idle unloading (`WarmModelRegistry`)

* Every use touches the provider's warm timestamp.
* Under **sustained** memory pressure (persisting ≥ `pressure_hold_s`), models
  idle longer than `model_idle_ttl_s` are unloaded via the configured
  `model_unload_command`.
* Hysteresis: a model is never unloaded before `model_warm_min_s` of warm time,
  so a burst of requests cannot thrash load/unload cycles.
* Without a configured unload command the registry reports `unsupported` —
  it never pretends to unload.

## 7. Provider resource scoring (`Provider.resource_profile()`)

Each provider exposes: `local` (runs on this machine?), `spawns_process`
(CLI providers start a short-lived local process), `resource_class`,
`cpu_cost` (relative), `ram_cost_mb` (resident estimate, derived from the
model's size tag when not configured), `concurrency`, `in_flight`,
`availability` (last-20-outcomes success rate), `circuit` state,
`observed_latency_s` (real measurements when available), `estimated_cost_usd`,
`privacy` (`local_only`/`remote_allowed`), `batch`.

Routing consequences:

* **CLI/cloud providers never consume the local model slot.** `claude -p` runs
  one short local process but is classified remote for slot purposes.
* **When local compute is saturated and a healthy remote provider exists, work
  overflows there** (`prefer_remote_when_saturated`), including at dispatch
  time (the scheduler books the remote slot before the task starts).
* **Privacy is structural:** a `local_only` task — or every task when
  `privacy.local_only: true` — can *only* be served by the local slot. If the
  slot is busy the request queues or fails honestly; it is never sent to a
  remote provider. Sensitive-file globs are configurable in `privacy.*`.
* Scoring is transparent: `elysia master route` shows the per-provider trace
  with the rejection reason for every candidate.

## 8. Model-call minimization (deterministic first)

Before any model call:

1. `deterministic_checks()` answers pure-verification tasks with the real
   compiler, test runner and strict JSON parser — **zero model calls** — and
   records `deterministic_checks` on the task.
2. The `AnalysisCache` caches model-independent analysis keyed by a hash of
   its inputs; changed inputs can never return stale results, TTL bounds
   memory, and eviction is bounded.
3. Memory recall (`memory.rec_about`) reuses prior solutions/failures before
   re-deriving them.
4. Per-task cap `max_model_calls_per_task` (0 = unbounded) is available in
   config.

## 9. Accounting and efficiency report

Every model call is attributed to its task row: calls, tokens (labelled
estimates), duration, provider/model, failures, retries, deterministic checks.

```
$ elysia master efficiency
task     class        prio         AI checks   tokens    ai_s retries fail
#42      local_llm    interactive   3     14     5200    42.0       0    0
#43      build        normal        0     14        0    13.0       1    1
totals: AI calls=3 deterministic checks=28 tokens=5200 ai_time=55.0s
token counts are estimates; checks are real tool runs
```

`elysia resources` prints the live system picture (CPU, RAM, swap, temperature
when readable, top processes by CPU), every held slot with its owner, and the
**exact reason** every queued task is waiting:

```
coder-7      WAITING   reason: interactive request is waiting (background work deferred)
build-14     WAITING   reason: CPU pressure 87% >= 75% — heavy work deferred
research-3   RUNNING   provider: cloud
```

## 10. CLI surface

| Command | Shows |
|---|---|
| `elysia resources [--watch] [--json]` | live system + slots + waiting reasons |
| `elysia queue` | same waiting view, task-centric |
| `elysia models` | local slots, warm state, batching policy, per-provider profiles |
| `elysia providers` | per-provider class/cost/privacy/circuit + fleet summary |
| `elysia master queue` | running + waiting from the live controller |
| `elysia master efficiency [task_id]` | AI calls vs deterministic checks per task |

## 11. Model server lifecycle (`elysia/core/modelserver.py`)

The ONE place that starts/stops the local model:

* pid-tracked: a second start is a no-op, never a second model process.
* `--parallel` follows `local_llm_concurrency`; `--threads` follows the real
  core count (never saturate all cores).
* Refuses to load when free RAM is under `ram_block_infer_mb` (quotes the real
  number), and reports missing binary/model as missing instead of "starting".
* `stop` is graceful and verified; `unload_command` fails honestly when the
  running server was not started by Elysia (`--require-managed`).

Legacy paths were migrated, not removed: `orchestrator/airllm.py` is a wrapper
over this module (its own `subprocess` use is gone, enforced by test), the HUD's
`start_pool` no longer spawns OS worker processes, and `monitor.py` starts the
stack only through the canonical launcher.

## 12. Measured behavior (low-end profile)

Tests: `tests/test_resource_execution.py` (44 tests). All numbers below come
from real subsystems — real ledger, real policy ladder, real pool threads, real
scheduler + SQLite board; only the model transport is faked.

| Property | Result |
|---|---|
| 20 logical agents, 1 local slot | 20/20 requests completed, **max simultaneous local inferences = 1**, slot released after every request |
| Slot survival | provider exception fails the request, slot stays usable; cancelled request never reaches the model; timed-out queued request is removed |
| Fairness | interactive queued behind 3 background requests ran first; a 2-minute-old background request outranks a fresh one; interactive admission defers background tasks |
| CPU ladder | 60 % → build deferred; 80 % → heavy/background deferred; 95 % → local blocked but remote allowed (`critical`) |
| RAM ladder | 1.5 GB free → no new model; 0.8 GB → inference blocked; remote still serves |
| Heavy exclusivity | model running → build refused ("one heavy job at a time") |
| Warm models | no pressure → no unload; fresh model → keep (hysteresis); old+idle without unload command → honest `unsupported`; with command → unloaded |
| Privacy | `local_only` task stays local while the slot is busy; global `privacy.local_only` locks all routing; saturated local slot overflows to remote for normal tasks |
| Reservations | model task claims its provider slot before starting; finish/cancel releases it exactly once; a build task takes the build slot, **not** the model slot |
| Determinism | verification tasks complete with 0 model calls; the checks really ran (`tests: rc=…`) |
| Model server | duplicate start refused; RAM floor refusal quotes real free MB; missing model reported as missing; `--require-managed` unload fails when the process is not ours |
| Bypass audit | `start_pool` spawns nothing (OS pool is gone); `airllm` has no `subprocess` at all (AST-checked); `worker_local.py` reaches models only through the `brain` wrapper |
| Accounting | calls/tokens/duration/failures/retries/checks land on the owning task rows |

**Live end-to-end proof** (real `MasterController`, real board, fake transport):
8 sub-tasks submitted for one goal, executed by the canonical scheduler with 3
executor threads and `local_llm_concurrency=1`:
**8/8 sub-tasks completed, peak concurrent model calls = 1, all files written
through the Workspace layer.**

## 13. Configuration (`elysia/config.json`)

```jsonc
{
  "resources": {
    "heavy_slots": 1,               // one expensive thing at a time
    "local_llm_concurrency": 1,     // THE local model slot
    "remote_slots": 8,              // cloud/CLI run in parallel
    "heavy_exclusive": true,        // no model + build together
    "cpu_busy_pct": 50, "cpu_high_pct": 75, "cpu_critical_pct": 90,
    "ram_min_free_mb": 2048, "ram_block_infer_mb": 1024,
    "swap_max_used_mb": 1024, "temp_max_c": 90,
    "prefer_remote_when_saturated": true,
    "inference_timeout_s": 900,
    "model_idle_ttl_s": 900, "model_warm_min_s": 300, "pressure_hold_s": 20
  },
  "scheduler": { "dispatch_aging_s": 30, "interactive_preempt": true },
  "privacy": { "local_only": false, "sensitive_globs": ["*.env", "*.key", "..."] }
}
```

Profiles only change these numbers; there is no second code path behind them.

## 14. Limitations (honest)

* Provider health history is in-process; it does not survive restarts.
* Per-process CPU sampling needs two samples one window apart, so the first
  snapshot reports `per_process: []` rather than a guess.
* Temperature requires a readable thermal zone; on machines without one the
  thermal rung is inert (and reported as unknown, never as cool).
* Batching stays off unless a backend declares support — on this hardware that
  is the correct default, not a missing feature.
* The legacy `worker_local.py` compatibility path still exists for old boards;
  it reaches models only through the `brain` wrapper and is not part of the
  canonical execution path.
