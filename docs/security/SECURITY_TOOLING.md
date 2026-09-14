# Security tooling policy (Elysia)

This repository integrates security-tooling **knowledge**, not attack
tooling. The policy below explains why, and how to add real tooling safely.

## Why knowledge-first

Elysia's architecture already treats dangerous operations as first-class
risks:

- `elysia/core/skills.py` — intent-based risk gate; offensive skills
  (`pentest`, `password-cracker`, `exploit-development`, …) are
  `BLOCKED_SKILL_NAMES` and stay quarantined unless explicitly enabled.
- `elysia/core/tools.py` — every tool has a risk level; high-risk tools are
  denied by policy and destructive actions get dry-run previews.
- `elysia/core/paths.py` + `workspace.py` — the model can only read/write
  inside the workspace; traversal/symlink escape is rejected.
- `scripts/import_skills.py` — vendor imports go through the same gate.

Vendoring live pentest binaries or attack playbooks into the repo would
circumvent these gates and poison every agent context with offensive
content. It would also make the repo un-distributable for many users.

## What IS in the repo

- `docs/knowledge/kali-tools/*.md` — curated, defensive-first docs
  (purpose, authorized use, install hint, risk class) indexed by
  `elysia.core.knowledge` and searchable via `elysia knowledge …`.
  Agents consult these when a user asks "how would I test X on my own
  machine?" — the answer cites the doc and its authorization limits.

## What the agent will NOT do

- execute discovery/exploitation against systems without explicit
  authorization (the prompts in `elysia/core/prompts.py` carry the
  forbidden-scope rule: workspace-only, authorized-only),
- import or generate attack walkthroughs, payloads, or cracking recipes,
- auto-install Kali packages into the user's system.

## Installing real tooling (operator action, authorized machines)

If you want the actual tools on your own machine (Kali/Debian/Ubuntu):

```bash
# examples — each tool's doc lists its package
sudo apt install nmap wireshark ghidra feroxbuster john hydra aircrack-ng
```

CLI/agent providers (Claude Code, OpenCode, OpenClaw, …) follow the same
rule: install per their docs, log in once with the tool itself, and Elysia
reuses that login through `elysia providers` — it never stores those
credentials.

## Skills

To extend the vendored set, add a skill through the normal gated path:

```bash
./bin/elysia skills import <path-or-url>
```

Anything the risk gate marks `high` is listed but quarantined; it never
auto-loads into agent contexts.
