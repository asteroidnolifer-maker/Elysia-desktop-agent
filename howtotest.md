# How to test Elysia — provider ecosystem, login, knowledge, prompt styles

Everything below is **offline-safe**: no test needs an API key, a GPU, or a
running model. Optional connected checks are marked.

---

## 1. The full unit suite (must stay green)

```bash
cd Elysia-desktop-agent          # repo root
python3 -m unittest discover -s tests -v
```

Expected: **all 402 tests pass** — the original 88 plus the new
`tests/test_providers_plus.py` bundle (provider presets, config integration,
prompt styles, browser login store, knowledge base, HuggingFace catalog),
the `tests/test_runtime_wiring.py` bundle (scheduler-in-server crash recovery,
worker lease heartbeat, provider failover on timeout/429/unavailable/crash,
concurrency=1 isolation, resource-queue budget gate, symlink-escape and
invalid-tool-argument rejection), and the `tests/test_master_control.py`
bundle (see §1c), the `tests/test_boot_scripts.py` bundle (install/launch
script contract; see §7b), the `tests/test_tool_layer.py` bundle (see §1d),
the `tests/test_db_budget_workflow.py` bundle (DB hardening, budget
enforcement, workflow gates — see §1e), the `tests/test_memory_context_healing.py`
bundle (see §1f), the `tests/test_task_graph.py` bundle (see §1g) andthe `tests/test_front_door.py` bundle (see §1i) and the
`tests/test_resource_execution.py` bundle (see §1j). No key, no network, no model
required.

### 1i. Front door: grounded environment and progress answers

The Jarvis chat used to hand machine/repo questions and goal follow-ups to the
small local model, which answered with invented refusals ("I don't have access
to your GitHub repositories", "I can't check the progress of a workflow"). The
front door now routes those deterministically and answers from real state.

- **environment route** (`elysia.core.environment`) — `what github repos do i
ow` inspects this checkout's git remotes, the `gh` CLI and the workspace. When
  `gh` is unavailable it says exactly that (`run gh auth login`) instead of
  guessing. Never fabricates a repository list.
- **progress route** (`elysia.core.briefing.goal_progress`) — `is it done`,
  `any progress?`, `did it finish` read durable board state and report the
  latest goal: `DONE`, `still running — 1/2 sub-task(s) completed`, or
  `stopped — N failed`, plus each sub-task's status and last error.
- **goal milestones carry a result** — a goal row is a milestone, not worker
  output, but it is no longer empty, so the HUD shows a summary instead of
  "(no result yet)".
- **HUD counters map both vocabularies** — the DONE tile now counts canonical
  `completed` tasks (it previously read 0 while dozens were finished).

```bash
./bin/elysia jarvis "what github repos do i own"   # -> environment
./bin/elysia jarvis "is it done"                    # -> progress
python3 -m unittest tests.test_front_door -v
```

### 1j. Resource-aware execution: many agents, one local model slot

`tests/test_resource_execution.py` proves the core rule
**LOGICAL AGENT ≠ MODEL PROCESS ≠ OS PROCESS ≠ PROVIDER REQUEST** on a
simulated Intel i5-6300U (2 cores / 4 threads / 16 GB, no GPU). Full design,
admission ladder and measured numbers: `RESOURCE_ARCHITECTURE.md`.

```bash
python3 -m unittest tests.test_resource_execution -v
./bin/elysia resources          # live CPU/RAM/swap + held slots + waiting reasons
./bin/elysia resources watch    # 2s refresh loop
./bin/elysia queue              # task-centric waiting view
./bin/elysia models             # local slots, warm state, batching honesty
./bin/elysia master efficiency  # AI calls vs deterministic checks per task
```

Key guarantees exercised by the bundle: 20 logical agents complete through ONE
local model slot (peak concurrency = 1); the slot survives provider exceptions,
cancellation and timeouts; interactive requests outrank background work with
aging so nothing starves; the CPU/RAM admission ladder defers heavy work with
an exact reason; heavy classes are exclusive (no model + build at once);
warm models unload only under sustained pressure with hysteresis;
`local_only` privacy is structural (never sent remote); provider slots are
reserved before a task starts; verification tasks finish with zero model calls;
the model server refuses duplicate starts and RAM-floor violations.

### 1f. Layered memory, context planner, self-healing

`tests/test_memory_context_healing.py` exercises the three subsystems that sit
behind every model call, with real objects (real on-disk memory store, real
SQLite board, real pipeline over a scripted transport):

- **memory** — importance/confidence/provenance are stored and returned by
  retrieval; identical content is deduplicated; recall scores are explainable
  (`why: keyword=… importance=… recency=…`) and recall counts are bumped; TTL
  expiry; invalidation and correction keep an audit trail; compaction reports
  the expired count and compresses the oldest records into a summary that keeps
  the keys it replaced; backup/restore round-trips and *refuses* missing or
  corrupt files instead of wiping live memory.
- **context planner** — the token budget is honoured, priorities decide which
  layers make it, truncation keeps the recent tail and states how much was
  omitted, dropped layers carry a reason, the plan is cached until an input
  changes, and roles get different priorities.
- **healing** — 23 documented failure texts and 3 exception types classify with
  their evidence; retries are bounded per class (`give_up` at the cap, no
  infinite loop); backoff grows and is deterministic under jitter; recovery
  routines really run (a stale lease is released on a real board, disk pressure
  really compacts memory and vacuums the DB) and report honestly when nothing
  is attached; `git_conflict` escalates and leaves the task untouched.
- **live path** — a QA failure is classified, recorded in failure memory and
  emitted as a `task.healing` event, and the retry prompt then contains the
  classified failure plus the "DO THIS DIFFERENTLY" hint from the classifier;
  a success lands in solution memory together with its context report; an
  implementer that returns no parseable file block is a real failure, never a
  silent "wrote 0 files".

### 1g. Task graph intelligence and replanning

`tests/test_task_graph.py` proves the analyser and the repair pass over real
plans, the real workspace and the real provider fleet: unknown/self deps and
cycles are found with their path; two writers of one file are a blocker; a task
that mentions another task's file without depending on it is flagged (and the
warning disappears once the dependency exists); existing and new files are told
apart; a role no provider can serve is a blocker and one that can is not;
oversized/trivial tasks are identified; estimates are per task and labelled
heuristics. Then `replan()`: invalid edges dropped, cycles broken, duplicate
owners merged with dependents rewired, an oversized task split into one task
per file with dependents pointed at **every** part, trivial merges opt-in only,
no repair can introduce a structural problem, and replanning a repaired plan
changes nothing (idempotent). Finally the master: `plan()` returns the analysis
and the repairs it applied, `simulate()` stays a dry run while reporting the raw
conflicts, the repairs available for an explicit plan and the estimates, and a
read-only role is a blocking `no_write_permission`.

### 1e. DB hardening, budget enforcement, workflow engine

`tests/test_db_budget_workflow.py` uses real subsystems only: the SQLite
TaskStore (WAL, versioned migrations, integrity check, online backup/restore,
vacuum), a real ProviderManager over a scripted transport (over budget → paid
providers dropped, local still serves, all-paid honestly refuses), and the
workflow engine persisting gate nodes onto the real board: approvals block
downstream work until a human resolves them and denial cascades; joins wait for
all siblings and fail on any failure; fallback runs only when its primary
failed; timeout fails a stuck child through the store; rollback refuses unknown
checkpoints; gate rows can never be claimed by a worker; static validation
rejects cycles and orphan refs.

### 1d. Runtime tool layer, simulation, routing, health

`tests/test_tool_layer.py` proves the permissioned tool layer that the live
pipeline now writes through: deny-by-default for unknown tools and roles,
reviewers that can never write even when config asks, traversal/absolute-path/
symlink-escape refusal, dry-run previews that change nothing on disk, the
desktop two-key gate (policy AND permission) with an honest "backend
unavailable" on headless hosts, the SSRF guard (loopback/link-local/private/
bad scheme), planning simulation that writes nothing, routing explanations with
rejection reasons, and the ten independent health dimensions. Its live test
drives the real MasterController: the file appears on disk **and** a
`file.changed`/`tool.invoke` audit event with `fs.write` proves the write went
through the registry — and with a read-only permission ceiling the same task
fails loudly and writes nothing.

### 1h. Provider health: circuit breaker, quarantine, half-open recovery

`tests/test_providers_plus.py::ProviderHealthCircuitTests` (Phase 7) drives real
`Provider`/`ProviderManager` objects with scripted outcomes:

- consecutive failures trip the circuit at the threshold, and a quarantined
  provider is **not** reserved — `explain()` says
  `circuit open after N trip(s)/M failures, Xs cooldown left` instead of the
  vaguer `health=degraded` (quarantine is checked before the coarse status);
- after the cooldown exactly ONE half-open probe is let through, and a second
  reserve waits for that probe's outcome;
- a successful probe closes the circuit (and publishes `provider.recovered`),
  a failed probe re-quarantines **longer** (each trip doubles, capped);
- an abandoned probe ticket expires, so a lost reservation can never lock a
  provider out permanently;
- the success rate is a real window of the last 20 outcomes (`None` before any
  call — never an invented number) and the incident timeline is bounded;
- a run-time boundary: with one broken and one healthy provider the healthy
  peer serves, `provider.quarantined` appears once on the event timeline, and
  the health dimension reports `N quarantined (circuit open)`.

### 1c. Master control plane (goal -> agents -> files -> review)

`tests/test_master_control.py` drives the REAL runtime with a scripted model
transport: TaskStore, Scheduler, TaskExecutor, AgentPipeline, Workspace, QA and
the git-diff reviewer are all the shipped code. It proves the master control
plane end to end: the planner produced the durable task graph, the implementer
wrote real files, QA compiled them, the tester and code reviewer ran (the
reviewer sees a real `git diff`), provider A failing hands the task to B,
independent sub-tasks overlap, a dependent sub-task waits for its prerequisite,
a fresh controller over the same SQLite board recovers and finishes the work,
cancellation is honest, and a QA failure rolls the bad file back instead of
leaving invalid code in the workspace.

```bash
python3 -m unittest tests.test_master_control -v
```

Live inspection of the same machinery:

```bash
./bin/elysia master agents     # which provider serves each logical role
./bin/elysia master status     # board, inflight, stages seen, provider health
./bin/elysia master run "add a subtract() helper to calc.py"
# -> per-task status, files changed, agent order, provider req/fail counts
```

### 1b. Runtime failure-mode checks (spot-check the wiring)

```bash
# In-process executor (live execution without external workers). With a
# healthy provider configured it starts with the server; control it via HTTP:
curl -s -X POST localhost:8087/api/executor -d '{"action":"status"}'
curl -s -X POST localhost:8087/api/executor -d '{"action":"start"}'   # or stop
curl -s localhost:8087/api/scheduler   # shows executor: {running, inflight, stats}

# End-to-end execution tests (goal -> dispatch -> failover -> real file ->
# QA -> completion; retry/exhaustion; dependency ordering; parallelism):
python3 -m unittest tests.test_e2e_executor -v

# The canonical scheduler runs inside the HUD server; ask it for state:
python3 orchestrator/server.py &            # start HUD
sleep 1
curl -s localhost:8087/api/scheduler        # {"ok":true,"running":true,...}

# A crashed worker's task is recovered (lease expiry -> ready, not stuck):
python3 orchestrator/taskboard.py add demo "crash demo" demo.md
python3 orchestrator/taskboard.py claim ghost-worker
python3 - <<'EOF'
import sqlite3, time
c = sqlite3.connect('orchestrator/taskboard.sqlite')
c.execute("UPDATE tasks SET lease_expires_at=? WHERE status='claimed'",
          (time.time()-1,)); c.commit()
EOF
python3 orchestrator/taskboard.py list   # after a scheduler pass: back to ready
curl -s -X POST localhost:8087/api/task/cancel -d '{"id":1}'
kill %1
```

---

## 2. New CLI surfaces (each is read-only)

```bash
./bin/elysia providers --catalog   # full provider catalog + what each needs
./bin/elysia providers             # active runtime providers (local at minimum)
./bin/elysia prompt                # prompt styles; '*' marks the active one
./bin/elysia prompt claude-code    # print one style's system prompt
./bin/elysia hf models             # curated top open models (GGUF candidates)
./bin/elysia hf datasets           # curated fine-tune/eval datasets
./bin/elysia hf recommend 4000     # best local model for ~4GB free RAM
./bin/elysia knowledge list        # vendored security-tooling knowledge stats
./bin/elysia knowledge search "port scanner"
./bin/elysia knowledge show nmap
./bin/elysia tools                 # machine tool catalog: what's installed
./bin/elysia tools --missing       # gap report: what's NOT installed
./bin/elysia tools --check nmap    # probe one tool + its knowledge doc
./bin/elysia brief                 # Jarvis-style briefing (caps+board+providers)
./bin/elysia brief "memory forensics"   # briefing + focused knowledge digest
./bin/elysia prompt jarvis         # the briefing-officer system prompt
./bin/elysia jarvis "what's running?"    # natural-language front door
./bin/elysia jarvis "how do I scan my own server"   # -> knowledge route
./bin/elysia jarvis "what github repos do i own"    # -> environment route
./bin/elysia jarvis "is it done"                    # -> progress route (board state)
./bin/elysia jarvis --deep "latest llama.cpp features"  # -> deep research
./bin/elysia jarvis "add retry to the exporter"         # -> master control plane
./bin/elysia master agents | status | run "<goal>"
./bin/elysia master route --caps chat,coding      # provider decision trace
./bin/elysia master simulate "<goal>"             # dry run: plan + graph + estimates
./bin/elysia master simulate "x" --file plan.json # analyse a plan offline
./bin/elysia memory stats | timeline [--ns NS] | recall "<query>"
./bin/elysia memory backup [PATH] | compact | invalidate --ns NS --key K
./bin/elysia healing policies | report | classify "<error text>"
./bin/elysia tools --registry                     # runtime tools + permissions
./bin/elysia tools --registry --role implementer  # allow/deny per role + reason
./bin/elysia health                               # ten independent dimensions
./bin/elysia db health | backup DIR | restore F | vacuum
./bin/elysia workflow start --file nodes.json --name demo | tick | state demo
./bin/elysia workflow approve --node ID           # or deny (cascades)
```

All of these must exit 0 with no traceback even with zero credentials and no
network (the `hf model <repo>` subcommand is the only one that wants network;
offline it prints a clean "could not resolve" line and exits 1).

---

## 3. Provider activation (no real keys needed)

Prove presets are credential-gated:

```bash
ELYSIA_DISABLE_PRESETS=1 ./bin/elysia providers
# → only "local"

GROQ_API_KEY=dummy ./bin/elysia providers
# → "local" first, then "groq" (groq appears because the key var is set;
#   no request is made by this command)

OPENROUTER_API_KEY=dummy ./bin/elysia prompt >/dev/null
ELYSIA_PROMPT_STYLE=claude-code ./bin/elysia prompt
# → '*' on claude-code
```

CLI agents (Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw) activate when
their binary is on PATH — the catalog shows exactly that condition.

---

## 4. Login flow (desktop browser + local store)

```bash
./bin/elysia login groq --no-browser
# prints the console URL + the export line; exits 1 (no key yet)

./bin/elysia login groq --paste gsk_your_real_key --no-browser
# stores it in config/providers.env (0600, git-ignored) — real key only

./bin/elysia login status
./bin/elysia login load          # loads stored keys into the environment
./bin/elysia login logout groq   # removes the stored key
./bin/elysia login claude-code   # CLI agent: reports install/login reuse
```

Verify nothing leaks:

```bash
git status --porcelain           # config/providers.env must NOT appear
stat -c '%a' config/providers.env   # 600
grep -c gsk_your_real_key config/providers.env >/dev/null && echo present
git check-ignore config/providers.env && echo "ignored OK"
```

`elysia providers` never prints key values — only names, status, and errors.

---

## 5. Style-routed chat (needs a reachable provider — optional)

With the local model up (`bash runtime/restore-model.sh qwen1.5b`) or any
activated cloud/CLI provider:

```bash
python3 orchestrator/brain.py ask "say hi in one line"
python3 orchestrator/brain.py ask --style claude-code "refactor plan for a CLI tool, 3 bullets"
ELYSIA_PROMPT_STYLE=hermes python3 orchestrator/brain.py ask "what tools would you use to add a route to agent-core?"
```

Offline (no provider) these print `[error] ...` and exit 1 — that is the
correct graceful degradation, not a failure.

---

## 6. Security-knowledge behavior (no tools installed needed)

```bash
./bin/elysia knowledge show "how do I scan my own machine for open ports"
# → nmap doc digest with the authorized-use framing

./bin/elysia skills list
# → curated vendor + native skills; offensive names stay quarantined/absent
```

The briefing also prints the **Control plane** section: which provider/model
serves each logical agent role, and which roles are unserved (no provider
matches their capabilities). Providers are labelled *unverified* until
something actually contacts them (`elysia master status` probes).

Agent-context wiring (unit-covered): a task mentioning "nmap"/"pentest" gets
the defensive digest in its prompt; a normal coding task does not. See
`tests/test_providers_plus.py::KnowledgeTests` and
`elysia/core/agents_context.py`. Policy: `docs/security/SECURITY_TOOLING.md`.

---

## 7. HuggingFace connected checks (optional, network)

```bash
./bin/elysia hf model Qwen/Qwen2.5-Coder-7B-Instruct-GGUF
# → downloads/likes/last-modified + first files (exit 0)

HF_TOKEN=hf_xxx ./bin/elysia providers
# → hf-inference appears in the active provider list
```

Model/dataset downloads stay manual (`hf.co/<repo>` links are printed by
`elysia hf models`); nothing auto-fetches weights.

---

## 7b. Universal install + launch scripts (offline-safe)

`scripts/elysia_boot.py` is the one implementation for Linux, macOS and
Windows; `install.sh`/`start.sh`, `install.ps1`/`start.ps1` and the `.cmd`
wrappers only locate a Python interpreter. Everything below needs no network,
no model and no credentials.

```bash
# syntax / wiring
sh -n install.sh && bash -n start.sh
python3 -m py_compile scripts/elysia_boot.py
python3 scripts/elysia_boot.py --help
./install.sh --help

# a full dry run: prints every action, changes nothing
./install.sh --dry-run
./install.sh --dry-run --deps        # shows the exact package-manager command
./start.sh --dry-run                 # shows the exact service commands

# real (read-only) state
./start.sh status                    # ports/pids/binaries; add --json for machines
./start.sh doctor
./start.sh stop                      # safe no-op when nothing is running
```

Expected: `--dry-run` performs no writes and prints "dry run: nothing was
changed"; `status` reports `down` for every port when nothing is running (it
never claims a service is up without the port answering); `stop` with no pid
files prints `stopped: nothing` and exits 0; with no Go toolchain the build
step reports SKIP plus the exact `go build` command instead of a fake success.

Lifecycle check (spawns a harmless sleeper, verifies stop really kills it):

```bash
python3 - <<'EOF'
import sys, argparse
sys.path.insert(0, "scripts")
import elysia_boot as eb
ui, args = eb.Ui(), argparse.Namespace(dry_run=False, json=False, yes=True)
assert eb._spawn(ui, "hud", [sys.executable, "-c", "import time; time.sleep(60)"],
                 eb.ROOT, None)
pid = eb._read_pid("hud")
assert pid and eb._alive(pid)
eb.cmd_stop(ui, args)
assert not eb._alive(pid) and not eb._pid_file("hud").exists()
assert eb.cmd_stop(ui, args) == 0          # idempotent
print("launcher lifecycle OK")
EOF
```

## 8. Pre-existing regression envelope (unchanged, still binding)

```bash
python3 -m py_compile orchestrator/server.py elysia/cli.py elysia/core/*.py tests/*.py
./bin/elysia doctor
./bin/elysia audit
./bin/elysia skills list
./bin/elysia research "question" --deep --breadth 2 --depth 1   # offline-degradable
```

Full background: `checks.md`. If anything above fails, the fastest bisect is
`ELYSIA_DISABLE_PRESETS=1` — if the symptom disappears, the cause is an env
credential activating a preset on your machine (which is by design).
