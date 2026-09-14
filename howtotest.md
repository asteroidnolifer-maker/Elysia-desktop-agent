# How to test Elysia — provider ecosystem, login, knowledge, prompt styles

Everything below is **offline-safe**: no test needs an API key, a GPU, or a
running model. Optional connected checks are marked.

---

## 1. The full unit suite (must stay green)

```bash
cd Elysia-desktop-agent          # repo root
python3 -m unittest discover -s tests -v
```

Expected: **all tests pass** — the original 88 plus the new
`tests/test_providers_plus.py` bundle (provider presets, config integration,
prompt styles, browser login store, knowledge base, HuggingFace catalog) and
the `tests/test_runtime_wiring.py` bundle (scheduler-in-server crash recovery,
worker lease heartbeat, provider failover on timeout/429/unavailable/crash,
concurrency=1 isolation, resource-queue budget gate, symlink-escape and
invalid-tool-argument rejection). No key, no network, no model required.

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
