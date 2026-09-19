# Elysia Skill Ecosystem Audit — Complete System Analysis

**Audit Date:** 2026-09-19  
**Scope:** 34 curated vendor skills + 9 Elysia-native skills, `elysia/core/skills.py`, `elysia/core/toolkit.py`, `elysia/core/agents.py`, CLI (`elysia/cli.py`), `elysia/config.json`

---

## Executive Summary

**Current State:** Elysia has a **functional but partial skill ecosystem** — curated vendor skills exist on disk, a tolerant parser and risk assessor are implemented in `elysia/core/skills.py`, and 9 native skills are present in `elysia/skills/elysia/`. However, **no registry/index/router/composer is wired into the live `MasterController` pipeline**. Skills are discoverable but not activatable through the canonical architecture.

**Critical Gaps:**
1. **No canonical skill registry** — `elysia/core/skills.py` discovers/parses/assesses but does not register, index, or make skills available to `AgentPipeline`
2. **No skill router** — tasks never select skills; `AgentPipeline` has hardcoded roles only
3. **No progressive disclosure** — all skills would load into context (violates prompt §4)
4. **No dependency resolution** — skills declare no deps; vendor skills assume external tooling (`npm`, `gh`, `coderabbit`)
5. **No trust/activation gating** — risk assessment exists but doesn't gate execution
6. **No CLI integration** — `elysia skills list` shows skills but `install/search/validate/enable` not implemented

**Bottom Line:** Skills are **passive files on disk**, not **active capabilities** in the canonical loop.

---

## 1. Existing Skill Systems Inventory

### 1.1 Core Implementation: `elysia/core/skills.py`

| Component | Status | Notes |
|-----------|--------|-------|
| Front-matter parser (`_read_frontmatter`) | ✅ Implemented | Tolerant YAML-ish parser; handles bool, lists, strings |
| Discovery (`discover_skills`) | ✅ Implemented | Walks `skill_root` up to `max_depth=3`, finds `SKILL.md` |
| Risk assessment (`assess_risk`) | ✅ Implemented | Intent-based; `BLOCKED_SKILL_NAMES` (16), `HIGH_RISK_MARKERS` (37), destructive intent detection |
| Curated allow-list (`curated_allow_list`) | ✅ Implemented | 19 names/groups; used for default agent |
| Skill object (`Skill` class) | ✅ Implemented | `path, name, description, risk, meta, invocable, allowed_tools` |
| Full load (`load_skill`) | ✅ Implemented | Returns `body` + `supporting_files` |
| **Registry / Index** | ❌ Missing | No persistent index, no SQLite/JSON store |
| **Router / Selector** | ❌ Missing | No task→skill matching |
| **Composer / Planner integration** | ❌ Missing | `AgentPipeline.plan_task` does not consult skills |
| **Dependency resolver** | ❌ Missing | Skills don't declare deps; no resolution |
| **Trust levels** | ⚠️ Partial | `RISK_SAFE/LOW/MODERATE/HIGH` but no `TRUSTED/VERIFIED/COMMUNITY/UNVERIFIED/BLOCKED` |
| **Versioning / rollback** | ❌ Missing | No version tracking, content hash, install date |

### 1.2 Vendor Skills on Disk: `elysia/skills/curated/` (34 files)

| Source | Skills | Risk | Notes |
|--------|--------|------|-------|
| `superpowers/systematic-debugging` | 1 (SKILL + 7 refs) | SAFE | 4-phase debugging; defensive; **no external deps** |
| `claude-bootstrap/code-review` | 1 (SKILL + adr-gate) | SAFE | Mandatory `/code-review`; ADR gate; **needs `gh`/`npm` for Codex/Gemini** |
| `claude-bootstrap/commit-hygiene` | 1 | SAFE | Atomic commits; PR size limits; **no external deps** |
| `claude-bootstrap/existing-repo` | 1 | SAFE | Analyze-before-modify; gradual rollout; **no external deps** |
| `claude-bootstrap/python` | 1 | SAFE | Ruff+mypy+pytest TDD; **no external deps** |
| `coderabbit-skills/autofix` | 1 (+ github.md) | MODERATE | **Needs `gh` auth + `coderabbit` CLI** |
| `coderabbit-skills/code-review` | 1 | MODERATE | **Needs `coderabbit` CLI v0.4.0+** |
| `dev-agent-skills/git-commit` | 1 | SAFE | Conventional commits; **no external deps** |
| `dev-agent-skills/github-pr-creation` | 1 | MODERATE | **Needs `gh` CLI + task files** |
| `dev-agent-skills/github-pr-review` | 1 | MODERATE | **Needs `gh` CLI + GraphQL** |
| `dev-agent-skills/github-pr-merge` | 1 | MODERATE | **Needs `gh` CLI + CHANGELOG** |
| `mattpocock-skills/code-review` | 1 | SAFE | Dual-agent diff review; **no external deps** |
| `vibe-skills/.../systematic-debugging` | 1 (SKILL + 7 refs) | SAFE | **Duplicate of superpowers** (same content, different path) |
| `marketing-and-advertising/dev-gtm/senior-architect` | 2 | SAFE | **Duplicate** (two folders, identical content) |
| `mcollina-skills/documentation` | 1 | SAFE | Diátaxis framework; **no external deps** |

**Total unique vendor skills: ~16** (after dedupe). **Duplicates found:** senior-architect (x2), systematic-debugging (x2 via vibe-skills mirror).

### 1.3 Elysia-Native Skills: `elysia/skills/elysia/` (9 skills)

| Skill | Description | Invocable | Risk |
|-------|-------------|-----------|------|
| planner | Goal → ordered task graph | ✅ | SAFE |
| architect | Plan → architecture (modules, data flow, risks) | ✅ | SAFE |
| senior-architect | Hard review with simplification focus | ✅ | SAFE |
| research | Plan queries, gather sources, cited report | ✅ | SAFE |
| security-review | Trace data flow, check sinks, gate tools | ✅ | SAFE |
| test-driven | RED→GREEN→REFACTOR cycle | ✅ | SAFE |
| debug-fix | Reproduce → root-cause → minimal fix | ✅ | SAFE |
| docs | Accurate documentation for changes | ✅ | SAFE |
| git-hygiene | Clean commits, secrets-free, safe checkpoints | ✅ | SAFE |

**All 9 are SAFE, invocable, stdlib-compatible, no external deps.**

### 1.4 Integration Points (Current)

| Integration | Status | Problem |
|-------------|--------|---------|
| `elysia/cli.py` → `skills list` | ✅ Works | Lists curated + native; shows risk |
| `elysia/cli.py` → `skills import` | ❌ Stub | Imports from `agent-skills-collection` but no registry write |
| `AgentPipeline` → skills | ❌ None | Hardcoded roles only; skills never consulted |
| `MasterController` → skills | ❌ None | No skill selection in `plan()` or `submit()` |
| `ToolManager` → skill tools | ❌ None | Skills declare `allowed-tools` but tools not exposed |

---

## 2. Architecture Audit: Canonical vs Required

### 2.1 Required by Prompt (§3, §4, §5, §9, §12, §14, §16, §19)

| Required Component | Prompt Ref | Implemented? |
|--------------------|------------|--------------|
| `skill_registry.py` — canonical store | §3 | ❌ |
| `skill_loader.py` — load full SKILL.md on demand | §3, §4 | ⚠️ `load_skill` exists but not wired |
| `skill_parser.py` — tolerant front-matter parser | §2 | ✅ `_read_frontmatter` |
| `skill_router.py` — task → candidate skills | §5, §10 | ❌ |
| `skill_index.py` — metadata-only startup index | §4, §20 | ❌ |
| `skill_installer.py` — Git/ZIP/local install | §5 | ❌ |
| `skill_updater.py` — safe updates with rollback | §21 | ❌ |
| `skill_validator.py` — structure + security scan | §2, §12 | ⚠️ `assess_risk` only |
| `skill_security.py` — sandbox, permissions, credentials | §12, §13 | ❌ |
| `skill_composer.py` — multi-skill SkillPlan | §9 | ❌ |
| `skill_evaluator.py` — evals, success rate, quarantine | §16 | ❌ |
| `skill_manifest.py` — content hash, deps, credentials | §15 | ❌ |
| `skill_cache.py` — parsed metadata, embeddings, validation | §20 | ❌ |

### 2.2 Registry Fields Required (§3) vs Actual

| Required Field | In `Skill` class? | In Registry? |
|----------------|-------------------|--------------|
| id | ❌ (path only) | N/A |
| name | ✅ | N/A |
| description | ✅ | N/A |
| version | ⚠️ meta only | N/A |
| author | ⚠️ meta only | N/A |
| license | ⚠️ meta only | N/A |
| source | ❌ | N/A |
| source_repo | ❌ | N/A |
| homepage | ❌ | N/A |
| local_path | ✅ (path) | N/A |
| tags | ❌ | N/A |
| domains | ❌ | N/A |
| dependencies | ❌ | N/A |
| required_tools | ⚠️ `allowed_tools` meta | N/A |
| required_credentials | ❌ | N/A |
| risk_level | ✅ | N/A |
| resource_cost | ❌ | N/A |
| compatibility | ❌ | N/A |
| last_updated | ❌ | N/A |
| content_hash | ❌ | N/A |
| trust_status | ❌ | N/A |
| enabled | ❌ | N/A |
| health | ❌ | N/A |
| usage_count | ❌ | N/A |
| success_rate | ❌ | N/A |

---

## 3. Security Audit

| Check | Status | Finding |
|-------|--------|---------|
| Malformed SKILL.md handling | ✅ | Parser tolerant; missing front-matter → empty meta |
| Arbitrary script execution | ✅ Blocked | `assess_risk` detects destructive intent; `BLOCKED_SKILL_NAMES` quarantines 16 offensive names |
| Credential exposure | ✅ | Skills declare `allowed-tools`; no credentials in SKILL.md |
| Path traversal in skill load | ✅ | `os.path.realpath` + `os.path.relpath` in `discover_skills` |
| Duplicate detection | ⚠️ Partial | No content-hash dedupe; senior-architect & systematic-debugging duplicated on disk |
| License tracking | ⚠️ Meta only | `license` in front-matter but not enforced/checked |
| Sandbox for skill scripts | ❌ | Vendor skills assume `npm`/`gh`/`coderabbit` CLI — no sandbox |

---

## 4. Resource Awareness Audit (Prompt §11)

| Requirement | Status |
|-------------|--------|
| Skill metadata includes CPU/RAM/network/disk/LLM calls/latency estimates | ❌ No |
| Skills loaded progressively (metadata at startup, full body on selection) | ❌ All loaded at discovery |
| `LOCAL_LLM_CONCURRENCY = 1` respected by skill execution | N/A (skills not executed) |
| ResourceManager integration | ❌ Skills not in scheduler budget |

---

## 5. CLI Audit: `elysia skills ...`

| Command | Implemented? | Notes |
|---------|--------------|-------|
| `elysia skills list` | ✅ | Shows curated + native; risk column |
| `elysia skills search <query>` | ❌ | Not implemented |
| `elysia skills info <skill>` | ❌ | Not implemented |
| `elysia skills install <repo>` | ❌ | Stub in `cli.py` calls `scripts/import_skills.py` |
| `elysia skills update` | ❌ | Not implemented |
| `elysia skills remove <skill>` | ❌ | Not implemented |
| `elysia skills validate <skill>` | ❌ | Not implemented |
| `elysia skills audit <skill>` | ❌ | Not implemented |
| `elysia skills enable <skill>` | ❌ | Not implemented |
| `elysia skills disable <skill>` | ❌ | Not implemented |
| `elysia skills health` | ❌ | Not implemented |
| `elysia skills stats` | ❌ | Not implemented |
| `elysia skills sources` | ❌ | Not implemented |
| `elysia skills refresh` | ❌ | Not implemented |

---

## 6. Vendor Skill Compatibility Matrix

| Skill | External Deps | Compatible with Elysia Canonical? | Action |
|-------|---------------|-----------------------------------|--------|
| systematic-debugging | None | ✅ Yes | Adopt as-is |
| code-review (claude-bootstrap) | `gh`, `npm` (Codex/Gemini) | ⚠️ Conditional | Make CLI tools optional; fallback to local provider |
| commit-hygiene | None | ✅ Yes | Adopt |
| existing-repo | None | ✅ Yes | Adopt |
| python | None | ✅ Yes | Adopt |
| coderabbit autofix | `gh`, `coderabbit` CLI | ❌ No | Requires external SaaS; wrap behind adapter |
| coderabbit code-review | `coderabbit` CLI | ❌ No | Same |
| github-pr-* (3) | `gh` CLI | ⚠️ Conditional | `gh` is common; make optional |
| mattpocock code-review | None | ✅ Yes | Adopt |
| documentation (Diátaxis) | None | ✅ Yes | Adopt |
| senior-architect (marketing) | None | ✅ Yes | Adopt (dedupe) |

---

## 7. Findings Summary

| Category | Count | Critical |
|----------|-------|----------|
| Missing core registry components | 11/14 | 🔴 |
| Skills not wired into `MasterController`/`AgentPipeline` | 2/2 | 🔴 |
| No progressive disclosure / metadata-only startup | 1/1 | 🔴 |
| No skill router / selector | 1/1 | 🔴 |
| No dependency resolution | 1/1 | 🟡 |
| No trust/activation gating | 1/1 | 🟡 |
| No eval/quarantine system | 1/1 | 🟡 |
| CLI commands missing | 12/14 | 🟡 |
| Duplicate skills on disk | 3 pairs | 🟢 |
| Vendor skills needing external SaaS | 4 | 🟡 |

---

## 8. Remediation Plan (Sequential, Per Prompt)

1. **Create `elysia/core/skill_registry.py`** — SQLite-backed store with all required fields; content-hash dedupe; trust status
2. **Create `elysia/core/skill_index.py`** — Startup metadata index (name, desc, tags, risk, caps); no full bodies
3. **Create `elysia/core/skill_loader.py`** — On-demand full SKILL.md + refs load; cache with content hash
4. **Create `elysia/core/skill_router.py`** — Task classification → candidate skills → rank → select → load
4. **Wire into `AgentPipeline.plan_task`** — Planner consults router; selected skills injected into context
5. **Create `elysia/core/skill_composer.py`** — SkillPlan with deps, tools, providers, permissions
6. **Implement CLI commands** — `install`, `search`, `info`, `validate`, `enable`, `disable`, `health`, `stats`
7. **Add eval framework** — Per-skill test cases; success rate tracking; quarantine on repeated failure
8. **Dedupe vendor skills** — Remove senior-architect x2, systematic-debugging x2 (keep one canonical)
9. **Wrap external-dep skills** — `coderabbit`/`gh` skills behind adapters; optional activation

---

## 9. Verification Commands (Post-Implementation)

```bash
# Registry
./bin/elysia skills list                    # all skills with risk/trust/status
./bin/elysia skills search "debug"          # tag/semantic search
./bin/elysia skills info systematic-debugging

# Installation
./bin/elysia skills install https://github.com/.../skill-repo
./bin/elysia skills validate systematic-debugging

# Runtime
./bin/elysia master simulate "debug this"   # shows skills selected
./bin/elysia master run "debug this"        # skills actually execute

# Health
./bin/elysia skills health                  # evals, success rates, quarantined
./bin/elysia doctor                         # includes skill registry check
```

---

## 10. Conclusion

Elysia has **excellent skill content** (16 unique vendor + 9 native = 25 high-quality skills) but **zero active skill infrastructure** in the canonical runtime. The parser and risk assessor are production-ready; everything else (registry, index, router, composer, CLI, evals) must be built and wired into `MasterController → Scheduler → Executor → AgentPipeline → ProviderManager → ToolManager → Workspace → QA`.

**Next step:** Implement `elysia/core/skill_registry.py` + `skill_index.py` + `skill_loader.py` as the foundation.