# Elysia JARVIS (Windows Desktop)

A self-contained AI assistant on your own computer. Runs as a tiny local HTTP
service (Go, ~10 MB, idles near 0% CPU) so it works fine on 4 GB RAM.

## Quick start
1. Double-click `start.bat` (or run `elysia-desktop.exe`).
2. Open http://127.0.0.1:8085 in your browser for the control page.
3. POST JSON to the endpoints (curl / PowerShell) or use `/chat` to talk to it.

`stop.bat` shuts it down. Generated projects and downloads live in the local
`workspace\` folder and never leave it.

## Configuration (agent_config.json)
Created automatically on first run. Edit it and restart.

| Field | Meaning |
|---|---|
| `api_key` | When set, every mutating request needs `Authorization: Bearer <key>`. When empty, mutating calls are only allowed from this PC (127.0.0.1). Set a key to safely access it remotely. |
| `bind_addr` | Listen address. Keep `127.0.0.1:8085` for local-only use. |
| `llm.backend` | `llama` (bundled local model), `openai` (any OpenAI-compatible API), or `nim` (NVIDIA NIM). |
| `llm.openai_base_url` / `openai_api_key` / `openai_model` | OpenAI-compatible endpoint. Works with Ollama (http://127.0.0.1:11434/v1), LM Studio, AnythingLLM, OpenAI, etc. |
| `llm.nim_api_key` / `nim_model` | NVIDIA NIM: get a free API key at https://build.nvidia.com and put it in `nim_api_key`. |
| `llm.llama_model` | Registered local model name for the llama.cpp backend (default `tiny`). |
| `google_api_key` / `google_cx` | Enable web search (Google Programmable Search Engine). |
| `workspace_dir` | Sandbox root. The agent can only write here. |
| `sandbox_allow_commands` | Whitelist of executables the sandbox may run. |
| `sandbox_timeout_sec` / `rate_limit_per_min` | Command timeout and per-IP rate limit. |

## What it can do
- **Chat (`POST /chat`)** â€“ `{"message":"write a python calculator"}`
  It plans, uses tools, runs things, and answers: web search, sandboxed shell,
  read/write files (inside the workspace), macros, games, project generation.
- **Projects (`POST /projects/new`)** â€“ generate a complete project, then
  `POST /projects/test` auto-tests it in the sandbox (go/python/node/rust)
  and reports pass/fail.
- **Tools (`POST /tools/run`)** â€“ `{"command":"npm install"}` downloads and
  builds inside the workspace.
- **Games (`/games`)** â€“ tic-tac-toe (with a minimax bot), rock-paper-scissors,
  hangman, number-guess, blackjack.
- **Research (`POST /research`)** â€“ web + vulnerability search.
- **System** â€“ `/sysinfo`, `/thermal`, `/power`, `/optimize`, `/macros`.

## Safety ("it won't destroy my computer")
- All agent activity is jailed to `workspace_dir`.
- Sandboxed commands must be in `sandbox_allow_commands`; shell metacharacters
  (`;`, `&&`, `|`, backticks) and destructive patterns (`rm -rf`, `format`,
  `shutdown`, registry edits, disk tools) are blocked outright.
- Every mutating request is rate-limited per IP and written to the audit log.
- No `api_key` set = loopback-only for mutating calls.

## NVIDIA NIM example
```
llm: {
  "backend": "nim",
  "nim_api_key": "nvapi-...",
  "nim_model": "meta/llama-3.1-8b-instruct"
}
```

## OpenAI-compatible example (Ollama on this PC)
```
llm: {
  "backend": "openai",
  "openai_base_url": "http://127.0.0.1:11434/v1",
  "openai_model": "qwen2.5-coder:1.5b"
}
```
