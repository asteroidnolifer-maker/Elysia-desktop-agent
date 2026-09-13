# Elysia System State

**Last Updated:** 2026-09-13 (13:00 UTC, continued by new agent)
**Status:** ACTIVE - HUD live, LOCAL LLM RESTORED (Qwen 1.5B serving :11434), youtube_search bug FIXED, pool WS_DIR FIXED + stale claims released (pool still stopped, awaiting go-ahead)

## Structure (Unified /data/elysia/)
```
/data/elysia/
├── orchestrator/          # Core system
│   ├── taskboard.py       # SQLite task board
│   ├── taskboard.sqlite   # 1,010,665 tasks (40 done)
│   ├── worker_local.py    # Worker loop
│   ├── brain.py           # LLM integration
│   ├── adaptive.sh        # Pool management
│   ├── monitor.py         # System monitor
│   ├── server.py          # HUD server :8087 (UPDATED - has /api/agent endpoint)
│   ├── airllm.py          # AirLLM model selector + keepalive
│   └── hud.html           # Dashboard UI
├── workspace/
│   ├── tools/
│   │   ├── web_research.py        # Web search via DuckDuckGo (WORKING - uses ddgs library)
│   │   ├── elysia_agent.py        # MASTER AGENT - classifies tasks, executes them (WORKING)
│   │   ├── crypto_tracker.py      # Live crypto prices via CoinGecko (WORKING)
│   │   ├── news_aggregator.py     # News via DDG News (WORKING)
│   │   ├── youtube_research.py    # YouTube trend scraper (WORKING)
│   │   ├── youtube_direct.py      # YouTube Data API v3 (NEEDS API KEY)
│   │   ├── composio_youtube.py    # Composio integration (FIXED 2026-09-13: v3.1 snake_case endpoints, search WORKS, 2-step S3 upload implemented)
│   │   ├── browser.py             # Web browser/search tool
│   │   ├── git_auto.py            # Git automation
│   │   └── [50+ task tools]       # Stock, dropshipping, finance, etc. tools
│   ├── agents/
│   ├── cache/
│   ├── videos/
│   ├── repos/             # Auto-generated git repos
│   ├── docs/
│   │   └── STATE.md       # This file
│   ├── elysia_master.db   # Master agent task/log database
│   └── agent_result.json  # Latest agent result
├── runtime/
│   ├── models/ -> REAL DIR, contains qwen15b-q4.gguf (1.1GB, downloaded 2026-09-13 from HF Qwen/Qwen2.5-1.5B-Instruct-GGUF)
│   ├── llama/ -> REAL DIR, contains llama-server build 10937 (ggml-org release, CPU ubuntu-x64) + libs, log at runtime/llama/server.log
│   └── restore-model.sh     # WORKS (fixed: ggml-org org, pinned b10937 tarball, correct HF filename)
├── agent-core/            # Go source (only Windows .exe, no Linux binary)
├── config/
│   └── composio.env       # Composio API key
├── logs/
├── scripts/               # Task generators
└── TASKS.md               # Master task list (1,010,665 tasks)
```

## Services
- **HUD Server**: Port 8087 (RUNNING - restarted 2026-09-13 11:03 UTC via setsid, reports model=True)
- **llama-server**: Port 11434 (RUNNING since 2026-09-13 ~11:10 UTC - llama.cpp b10937 CPU, Qwen2.5-1.5B-Instruct Q4_K_M, ctx 8192, brain.health=True, `brain.chat` verified)
- **LearmServer**: Was at /data/Elysia - DELETED, models lost (superceded: fresh binary+model downloaded, no longer needed)

## CRITICAL ISSUES TO FIX
1. **Models lost**: FIXED 2026-09-13. `/data/Elysia` still gone, but runtime/ has fresh llama-server + 1.1GB Qwen model. Full loop verified: /api/ask divided a goal into task #1329816, pool started, worker ad-1-0 online and claiming tasks. NOTE: llama.cpp moved orgs (ggerganov -> ggml-org); 'latest' has no stable binary assets - use pinned builds (b10937). Server must start WITHOUT --mlock (invalid in this build).
2. **No agent-core Linux binary**: Only Windows .exe exists (unchanged, low priority - Python agent + workers cover functionality; stack_up=False only due to :8085)
3. **Composio YouTube upload**: FIXED 2026-09-13 - root cause was outdated camelCase endpoints (404). Now uses v3.1 snake_case. Upload = 2-step flow (presigned S3 PUT then YOUTUBE_MULTIPART_UPLOAD_VIDEO), implemented in `youtube_upload_file()`. PROVEN 2026-09-13: minted presigned URL + PUT 100KB probe.mp4 -> PUT_OK True, s3key returned. Final execute step untested (would post to user's channel - needs explicit go-ahead + real video). Tokens are REDACTED by Composio API so direct googleapis upload with extracted token is NOT possible - must use Composio execute path.

## What's WORKING Right Now
| Feature | Status | How |
|---------|--------|-----|
| HUD Dashboard | Live | http://localhost:8087 |
| Local LLM | UP (restored 2026-09-13) | llama.cpp b10937 + Qwen2.5-1.5B Q4 on :11434, /api/ask verified |
| Agent Chat | Live | POST /api/chat with {"message": "..."} |
| Master Agent | Live | POST /api/agent with {"task": "..."} |
| Web Search | Live | DuckDuckGo via `ddgs` library |
| Crypto Prices | Live | CoinGecko API (BTC: $77K, ETH: $2.5K) |
| Stock Research | Live | Yahoo Finance, MarketBeat, Reuters |
| YouTube Trends | Live | Real YouTube scraping |
| News | Live | DDG News (Forbes, Motley Fool) |
| Product Research | Live | Amazon, AliExpress data |
| Composio Connection | ACTIVE (v3.1 verified 2026-09-13) | 3 YouTube conns (1 ACTIVE main + 1 ACTIVE spare + 1 EXPIRED), search via API works |
| Task Board | Live | 1,010,666 tasks (49 done, 0 claimed - 11 stale released 2026-09-13, 0 failed) |

## Composio Setup
- **API Key**: `ak_FIwmCfHE8vjHlYW8zY_F` (in config/composio.env)
- **YouTube Auth Config**: `ac_V9z363xdny0d`
- **Connected Accounts** (verified live 2026-09-13 via GET /api/v3.1/connected_accounts):
  - `ca_sWrT8cHrT-ek` = youtube, ACTIVE, user elysia_user, scopes include youtube.upload (MAIN - default in code)
  - `ca_GMKyLU1N5SV4` = youtube, ACTIVE (spare)
  - `ca_sas_LvLOB9kB` = youtube, EXPIRED (needs re-auth)
  - plus canva, googlecalendar, gmail, github accounts ACTIVE
- **Correct endpoints (v3.1, snake_case)** - old camelCase code 404'd, fixed in composio_youtube.py:
  - `GET /api/v3.1/connected_accounts` (was `connectedAccounts`)
  - `GET /api/v3.1/tools?toolkit_slug=youtube`
  - `POST /api/v3.1/tools/execute/{slug}` with `{arguments, connected_account_id, user_id}`
  - Search slug = `YOUTUBE_SEARCH_YOU_TUBE` with param `q` (not `query`)
- **Upload flow (PROVEN END-TO-END 2026-09-13 via master agent task #18)**:
  1. `POST /api/v3.1/files/upload/request` {toolkit_slug, tool_slug, filename, mimetype, md5} -> {key, new_presigned_url}
  2. `PUT` file bytes to presigned URL
  3. Execute `YOUTUBE_MULTIPART_UPLOAD_VIDEO` with `videoFile: {name, mimetype, s3key: key}`
  - Use `youtube_upload_file(path, title, desc, ...)` in composio_youtube.py
  - Master agent auto-uploads: `elysia_agent.try_agent_upload()` triggers on "upload" in youtube tasks, picks named/newest mp4 from workspace/videos/, privacy parsed from text (default unlisted)
  - LIVE RESULT: task #18 uploaded workspace/videos/elysia_test_shorts.mp4 (15s Short) as PRIVATE -> video id `nLhkcNeH35U` (https://youtube.com/watch?v=nLhkcNeH35U), uploadStatus=uploaded

## How to Use the Agent

### Through HUD Chat (http://localhost:8087):
```bash
# Status check
curl -X POST http://localhost:8087/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"what is the status?"}'

# Ask Elysia to research anything
curl -X POST http://localhost:8087/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"what is Bitcoin price right now"}'

# YouTube research
curl -X POST http://localhost:8087/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"find trending YouTube shorts ideas for tech channel"}'
```

### Through Agent API directly:
```bash
curl -X POST http://localhost:8087/api/agent \
  -H "Content-Type: application/json" \
  -d '{"task":"analyze Tesla stock and tell me if I should buy"}'
```

### Task Types Supported:
- `youtube` - YouTube trend research, video ideas, scripts
- `stock` - Stock analysis, price checks, news
- `crypto` - Live crypto prices, trend analysis
- `research` - General web research
- `ecommerce` - Product/supplier research
- `meme` - Meme ideas and content
- `content` - Blog/article writing
- `code` - Code generation
- `automation` - Workflow automation

## Next Steps for New Agent

### Priority 1: Fix Models — DONE 2026-09-13
- [x] Replace broken symlinks with real dirs
- [x] Download llama-server b10937 + Qwen2.5-1.5B Q4_K_M (1.1GB) - serving on :11434
- [x] Verify brain.health + brain.chat + HUD model=True + /api/ask division (task #1329816) + pool/worker live
- Optional: bigger model (`restore-model.sh qwen3b`) or external API keys in agent_commander.py for harder tasks

### Priority 2: YouTube Upload — DONE END-TO-END 2026-09-13
- [x] Fix v3.1 endpoints + search (verified live)
- [x] Implement 2-step S3 upload in `youtube_upload_file()`
- [x] Prove S3 leg with 100KB probe (PUT_OK True)
- [x] LIVE UPLOAD via master agent task #18: elysia_test_shorts.mp4 -> PRIVATE video `nLhkcNeH35U`
- Note: youtube_direct.py still NEEDS a YouTube Data API key; youtube_oauth.py still has placeholder CLIENT_ID/SECRET. Composio path is the working one.

### Priority 3: Keep Building — IN PROGRESS
- [x] 2026-09-13: Fixed elysia_agent.youtube_search() ignoring its query arg. Now Composio YOUTUBE_SEARCH_YOU_TUBE primary (honors query+num, parses v3 shape id.videoId/snippet.title/channelTitle/publishedAt via _normalize_composio_search) with scraping fallback (category inferred via _infer_youtube_category). Verified live: "viral tech gadgets 2026" -> 3 real results (composio), /api/agent task #20 done with real titles/channels.
- [x] 2026-09-13 ~13:00 UTC: machine rebooted (or services died) - restarted llama-server (b10937, Qwen1.5B Q4, :11434, brain.health UP, brain.chat "OK" verified) + HUD :8087 (model=True). /api/chat status + /api/agent verified.
- [x] 2026-09-13: Pool WS_DIR FIXED - adaptive.sh default was /data/elysia-run/workspace (old layout), now /data/elysia/workspace; server.py start_pool() pins ELYSIA_WS=WS_DIR in worker env (both syntax/compile verified). Released 11 stale claimed tasks (10x elysia-main + 1x ad-59-0, no live workers) via taskboard.release_stale -> open=1,010,617. Pool NOT started (needs explicit go-ahead - 1M open backlog would burn CPU on 1.5B model).
- NOTE: monitor.py still references old paths (/data/elysia-run/workspace, /home/myusername/elysia/elysia-run.sh) - fix when monitor is re-enabled.

## Key Files to Know
- `/data/elysia/workspace/tools/elysia_agent.py` - Master agent (start here)
- `/data/elysia/orchestrator/server.py` - HUD server (has /api/agent + /api/chat endpoints)
- `/data/elysia/workspace/tools/web_research.py` - Web search engine
- `/data/elysia/workspace/tools/crypto_tracker.py` - Crypto prices
- `/data/elysia/workspace/tools/composio_youtube.py` - YouTube via Composio (FIXED v3.1 - use this, not youtube_direct)
- `/data/elysia/workspace/elysia_master.db` - Agent task database (16 tasks, all done)
- `/data/elysia/config/composio.env` - Composio API key
- `/data/elysia/runtime/restore-model.sh` - NEW: restores local LLM
- `/data/elysia/orchestrator/logs/server.log` - HUD log (check on any failure)

## Quick Commands
```bash
# HUD server already RUNNING (started 2026-09-13 via setsid). If down, restart:
setsid bash -c 'exec python3 /data/elysia/orchestrator/server.py --port 8087 --host 0.0.0.0 </dev/null >>/data/elysia/orchestrator/logs/server.log 2>&1' & disown

# Health check (no model needed)
curl --max-time 5 -s http://localhost:8087/api/state | head -c 500

# Test agent
cd /data/elysia/workspace/tools && python3 -c "
import sys; sys.path.insert(0, '.')
from elysia_agent import process_request
r = process_request('YOUR TASK HERE')
print(r)
"

# Check crypto prices
python3 /data/elysia/workspace/tools/crypto_tracker.py

# Search web
python3 /data/elysia/workspace/tools/web_research.py
```
