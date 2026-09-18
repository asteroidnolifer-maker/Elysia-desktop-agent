"""Task-graph intelligence (Phase 3) and intelligent replanning (Phase 50).

A plan is data, so it can be checked BEFORE anything runs. This module answers,
for a planner output or an explicit sub-task list:

  structure   unknown dependency indices, circular dependencies, tasks that
              nothing can execute (no capability match), impossible graphs
  files       two tasks owning the same file, files named by a task but owned
              by nobody, tasks touching files that already exist (regression
              risk) versus brand-new files
  shape       oversized tasks (split candidates) and trivial tasks (merge
              candidates), with a complexity score rather than a vibe
  estimates   per-task and totals for duration, model calls, tokens and local
              memory, plus the capability each task needs

``replan()`` then applies the repairs that are safe and mechanical — dropping
unknown dependencies, breaking dependency cycles, giving a file exactly one
owner, splitting oversized tasks and merging trivial ones — and reports every
change it made. Anything it cannot safely repair is left as a blocker so the
caller can escalate instead of guessing.

Nothing here calls a model or touches the board: it is pure analysis over the
plan plus (optionally) the real provider fleet and the real workspace.
"""
from __future__ import annotations

import os
import re

#: severity order used for reporting/escalation
SEVERITY_ORDER = {"blocker": 3, "major": 2, "minor": 1}

_FILE_RE = re.compile(
    r"[\w./-]+\.(?:py|md|rs|go|js|ts|tsx|jsx|sh|yaml|yml|json|toml|sql|css|html|"
    r"kt|java|rb|c|h|cpp|hpp|cs|php|swift|vue|svelte)",
    re.I)

#: Above this many owned files (or this much detail) a task is a split candidate.
OVERSIZED_FILES = 4
OVERSIZED_DETAIL_CHARS = 900
#: Below this, a task is a merge candidate (single tiny file, short detail).
TRIVIAL_FILES = 1
TRIVIAL_DETAIL_CHARS = 40


def files_in(text: str | None, limit: int = 12) -> list[str]:
    """File paths named in free text (traversal and absolute paths dropped)."""
    out = [p for p in _FILE_RE.findall(text or "")
           if ".." not in p and not p.startswith("/")]
    return list(dict.fromkeys(out))[:limit]


def _plan_nodes(plan: list) -> list[dict]:
    """Normalise plan items into {title, detail, files, after, role}."""
    nodes = []
    for i, raw in enumerate(plan or []):
        if isinstance(raw, str):
            raw = {"title": raw}
        raw = dict(raw)
        detail = (raw.get("detail") or raw.get("description") or "")
        files = list(raw.get("owned_files") or raw.get("files") or [])
        if not files:
            files = files_in(f"{raw.get('title') or ''} {detail}")
        after = raw.get("after") or raw.get("dependencies") or []
        nodes.append({
            "index": i,
            "title": (raw.get("title") or f"task {i}").strip(),
            "detail": detail,
            "files": files,
            "after": [a for a in after if isinstance(a, int)],
            "role": raw.get("agent_role") or raw.get("role") or "implementer",
        })
    return nodes


def _issue(kind: str, severity: str, detail: str, nodes: list[int],
           fix: str = "", **extra) -> dict:
    out = {"kind": kind, "severity": severity, "detail": detail,
           "nodes": sorted(nodes), "fix": fix}
    out.update(extra)
    return out


def find_cycles(nodes: list[dict]) -> list[list[int]]:
    """Dependency cycles as index paths (DFS with an explicit stack)."""
    edges = {n["index"]: [a for a in n["after"] if 0 <= a < len(nodes)]
             for n in nodes}
    cycles, state, stack = [], {}, []

    def visit(i: int) -> None:
        state[i] = 1
        stack.append(i)
        for nxt in edges.get(i, []):
            if state.get(nxt, 0) == 1:
                cycles.append(stack[stack.index(nxt):] + [nxt])
            elif state.get(nxt, 0) == 0:
                visit(nxt)
        stack.pop()
        state[i] = 2

    for n in nodes:
        if state.get(n["index"], 0) == 0:
            visit(n["index"])
    return cycles


def analyze(plan: list, root: str = "", providers=None,
            role_caps: dict | None = None,
            role_of=lambda n: n["role"]) -> dict:
    """Statically analyse a plan; returns issues, estimates and the graph."""
    nodes = _plan_nodes(plan)
    issues: list[dict] = []
    n = len(nodes)
    if n == 0:
        return {"ok": False, "nodes": 0, "issues": [
            _issue("empty_plan", "blocker", "the plan has no tasks", [],
                   "ask the planner for at least one task")],
            "blockers": 1, "estimates": {}, "graph": {"edges": {}}}

    # -- structure ---------------------------------------------------------
    for node in nodes:
        bad = [a for a in node["after"] if not 0 <= a < n]
        if bad:
            issues.append(_issue(
                "unknown_dependency", "major",
                f"task {node['index']} ({node['title']}) waits on "
                f"non-existent task index(es) {bad}", [node["index"]],
                "drop the unknown dependency"))
        if node["index"] in node["after"]:
            issues.append(_issue(
                "self_dependency", "major",
                f"task {node['index']} depends on itself", [node["index"]],
                "drop the self edge"))
    for cycle in find_cycles(nodes):
        issues.append(_issue(
            "circular_dependency", "blocker",
            "dependency cycle: " + " -> ".join(f"task {i}" for i in cycle),
            cycle[:-1], "break the cycle by removing one back-edge",
            tasks=list(cycle[:-1])))

    # -- file ownership ----------------------------------------------------
    owners: dict[str, list[int]] = {}
    for node in nodes:
        for f in node["files"]:
            owners.setdefault(f, []).append(node["index"])
    for f, ids in sorted(owners.items()):
        if len(ids) > 1:
            issues.append(_issue(
                "duplicate_file_ownership", "blocker",
                f"{f} is owned by tasks {ids}; two writers would race",
                ids, "give the file exactly one owner (or sequence them)",
                file=f, tasks=list(ids)))

    # a file named in a task's text but owned by a DIFFERENT task only
    for node in nodes:
        mentioned = set(files_in(f"{node['title']} {node['detail']}"))
        for f in sorted(mentioned - set(node["files"])):
            others = owners.get(f, [])
            if others and node["index"] not in others and \
                    not any(o in node["after"] or node["index"] in
                            nodes[o]["after"] for o in others):
                issues.append(_issue(
                    "overlapping_modification", "major",
                    f"task {node['index']} mentions {f} but task {others} owns "
                    "it without a dependency", [node["index"]] + others,
                    "add a dependency so the owner runs first"))

    # -- workspace awareness ----------------------------------------------
    existing, new_files = [], []
    for node in nodes:
        for f in node["files"]:
            path = os.path.join(root, f) if root else ""
            if root and path and os.path.isfile(path):
                existing.append((node["index"], f))
            else:
                new_files.append((node["index"], f))
    if root and existing:
        for idx, f in existing:
            if not nodes[idx]["detail"]:
                issues.append(_issue(
                    "existing_file_without_detail", "minor",
                    f"task {idx} overwrites existing {f} with no detail "
                    "about how it must change", [idx],
                    "add what must change in that file"))

    # -- executors / capabilities -----------------------------------------
    caps_by_role = dict(role_caps or {})
    for node in nodes:
        role = role_of(node)
        caps = caps_by_role.get(role)
        if providers is None or caps is None:
            continue
        try:
            trace = providers.explain(capabilities=caps)
        except Exception:  # noqa: BLE001 — analysis must never raise
            continue
        if not trace.get("selected"):
            issues.append(_issue(
                "no_executor", "blocker",
                f"no provider can serve role '{role}' (needs {caps})",
                [node["index"]],
                "install/enable a provider with those capabilities"))

    # -- shape -------------------------------------------------------------
    for node in nodes:
        if len(node["files"]) > OVERSIZED_FILES or \
                len(node["detail"]) > OVERSIZED_DETAIL_CHARS:
            issues.append(_issue(
                "oversized_task", "major",
                f"task {node['index']} is large ({len(node['files'])} file(s), "
                f"{len(node['detail'])} chars of detail)", [node["index"]],
                "split it into one task per file"))
        elif len(node["files"]) <= TRIVIAL_FILES and \
                len(node["detail"]) < TRIVIAL_DETAIL_CHARS:
            issues.append(_issue(
                "trivial_task", "minor",
                f"task {node['index']} looks trivial", [node["index"]],
                "merge it with a sibling if they are independent"))

    blockers = sum(1 for i in issues if i["severity"] == "blocker")
    return {
        "ok": blockers == 0,
        "nodes": n,
        "issues": issues,
        "blockers": blockers,
        "majors": sum(1 for i in issues if i["severity"] == "major"),
        "minors": sum(1 for i in issues if i["severity"] == "minor"),
        "estimates": estimate(nodes, root, caps_by_role, role_of),
        "graph": {
            "edges": {no["index"]: sorted(set(no["after"])) for no in nodes},
            "owners": owners,
            "existing_files": [f for _, f in existing],
            "new_files": [f for _, f in new_files],
        },
    }


def complexity(node: dict, root: str = "") -> float:
    """0..1 heuristic: breadth (files), depth (detail), and edit risk."""
    score = min(0.4, 0.1 * len(node["files"]))
    score += min(0.35, len(node["detail"]) / 2500.0)
    if root:
        hits = sum(1 for f in node["files"]
                   if os.path.isfile(os.path.join(root, f)))
        score += min(0.25, 0.08 * hits)
    if node["after"]:
        score += 0.05
    return round(min(1.0, score), 3)


def estimate(nodes: list[dict], root: str = "", role_caps: dict | None = None,
             role_of=lambda n: n["role"]) -> dict:
    """Duration/model-call/token estimates per task and in total.

    Accepts EITHER raw plan items or already-normalised nodes. These are
    ESTIMATES from plan shape, not measurements: the report says so (``basis``)
    so nobody mistakes them for telemetry.
    """
    nodes = _plan_nodes(nodes)
    caps_by_role = dict(role_caps or {})
    per_task = []
    total_s = 0.0
    total_tokens = 0
    for node in nodes:
        c = complexity(node, root)
        role = node["role"]
        caps = caps_by_role.get(role, [])
        # one model call per stage the role implies, plus a retry allowance
        calls = 1 + (1 if "coding" in caps else 0)
        calls += 1 if "reasoning" in caps else 0
        attempts = 1.35                      # expected attempts incl. retries
        per_call_s = 12 + 40 * c
        seconds = round(per_call_s * calls * attempts, 1)
        tokens = int((900 + 2200 * c) * calls)
        total_s += seconds
        total_tokens += tokens
        per_task.append({
            "index": node["index"], "title": node["title"],
            "role": role, "capabilities": caps,
            "files": node["files"], "complexity": c,
            "model_calls": calls, "duration_s": seconds,
            "tokens_est": tokens,
            "provider_requirement": caps or ["chat"],
        })
    return {
        "per_task": per_task,
        "total_duration_s": round(total_s, 1),
        "total_tokens_est": total_tokens,
        "basis": "heuristic from plan shape (files, detail length, role "
                 "capabilities) — not measured telemetry",
    }


# ---------------------------------------------------------------------------
# replanning
# ---------------------------------------------------------------------------
def _absorb(base: dict, other: dict) -> dict:
    """Merge ``other`` into ``base`` (one task, one writer per file)."""
    merged = dict(base)
    merged["title"] = (base["title"] + " + " + other["title"])[:120]
    merged["detail"] = (base["detail"] + " " + other["detail"]).strip()
    merged["files"] = list(dict.fromkeys(base["files"] + other["files"]))
    merged["merged_from"] = sorted(set(base.get("merged_from", []) +
                                      other.get("merged_from", []) +
                                      [other["index"]]))
    return merged


def _split_node(node: dict) -> list[dict]:
    """One task per owned file (deterministic, keeps the role and deps)."""
    return [{
        "index": node["index"],
        "title": f"{node['title']} [{f}]"[:120],
        "detail": f"{node['detail']} (this task only writes {f})".strip(),
        "files": [f],
        "after": list(node["after"]),
        "role": node["role"],
        "split_from": node["index"],
    } for f in node["files"]]


def _groups_as_map(nodes: list[dict], groups: list[list[int]]) -> dict:
    """old index -> group id (unchanged nodes map to themselves).

    Overlapping groups are unioned (a file owned by three tasks where one of
    them is already grouped must end up in ONE group, never two).
    """
    parent: dict[int, int] = {n["index"]: n["index"] for n in nodes}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for group in groups:
        members = [i for i in group if i in parent]
        for other in members[1:]:
            parent[find(other)] = find(members[0])
    # every member of a multi-member group (INCLUDING the root) must map to
    # the same key, or the root would be treated as its own group.
    counts: dict[int, int] = {}
    for n in nodes:
        r = find(n["index"])
        counts[r] = counts.get(r, 0) + 1
    return {n["index"]: (f"g{find(n['index'])}"
                         if counts[find(n["index"])] > 1 else n["index"])
            for n in nodes}


def replan(plan: list, issues: list[dict] | None = None, root: str = "",
           merge_trivial: bool = False,
           providers=None, role_caps: dict | None = None) -> dict:
    """Apply safe, mechanical repairs; report every change.

    Dependencies are remapped through an explicit old->new table, so splitting
    or merging tasks can never leave a stale index or a self/cyclic edge.

    Repairs applied unconditionally (they only remove ambiguity):
      unknown/self dependencies dropped, cycles broken, duplicate file owners
      merged, oversized tasks split.
    ``merge_trivial`` additionally merges trivial independent tasks.
    """
    nodes = _plan_nodes(plan)
    if issues is None:
        issues = analyze(plan, root=root, providers=providers,
                         role_caps=role_caps)["issues"]
    changes: list[str] = []
    original_n = len(nodes)

    # 1) drop unknown / self dependencies
    for node in nodes:
        keep = [a for a in node["after"] if 0 <= a < original_n
                and a != node["index"]]
        if keep != node["after"]:
            dropped = sorted(set(node["after"]) - set(keep))
            changes.append(f"task {node['index']}: dropped invalid "
                           f"dependencies {dropped}")
            node["after"] = keep

    # 2) break cycles (drop the back-edge that closes each cycle)
    for cycle in find_cycles(nodes):
        a, b = cycle[-2], cycle[-1]
        if b in nodes[a]["after"]:
            nodes[a]["after"].remove(b)
            changes.append(f"task {a}: dropped dependency on {b} to break a cycle")

    # 3) merge groups: duplicate file ownership, plus optional trivial pairs
    groups: list[list[int]] = []
    owners: dict[str, list[int]] = {}
    for node in nodes:
        for f in node["files"]:
            owners.setdefault(f, []).append(node["index"])
    for f, ids in sorted(owners.items()):
        if len(ids) > 1:
            groups.append(sorted(set(ids)))
            changes.append(f"merged tasks {sorted(set(ids))} into one owner: "
                           f"{f} had two writers")
    if merge_trivial:
        claimed = {i for g in groups for i in g}
        for a, b in zip(nodes, nodes[1:]):
            if a["index"] in claimed or b["index"] in claimed:
                continue
            independent = (b["index"] not in a["after"] and
                           a["index"] not in b["after"])
            trivial = all(
                len(x["files"]) <= TRIVIAL_FILES and
                len(x["detail"]) < TRIVIAL_DETAIL_CHARS for x in (a, b))
            if independent and trivial:
                groups.append([a["index"], b["index"]])
                changes.append(f"merged trivial independent tasks "
                               f"{a['index']} and {b['index']}")

    # which old indices are split
    splits = {n["index"] for n in nodes if len(n["files"]) > OVERSIZED_FILES}
    for idx in sorted(splits):
        node = next(n for n in nodes if n["index"] == idx)
        changes.append(f"split task {idx} into {len(node['files'])} per-file tasks")

    gmap = _groups_as_map(nodes, groups)
    merged: dict[object, dict] = {}
    for node in nodes:
        gid = gmap[node["index"]]
        if gid in merged:
            merged[gid] = _absorb(merged[gid], node)
        else:
            merged[gid] = dict(node)

    # 4) build the new list, recording old-index -> new positions
    old_to_new: dict[int, list[int]] = {}
    out_nodes: list[dict] = []
    for gid, base in merged.items():
        members = sorted(i for i, g in gmap.items() if g == gid)
        for member in members:
            old_to_new[member] = []
        if base["index"] in splits and len(members) == 1:
            parts = _split_node(base)
        else:
            parts = [base]
        for part in parts:
            pos = len(out_nodes)
            part = dict(part)
            part["index"] = pos
            out_nodes.append(part)
            for member in members:
                old_to_new[member].append(pos)

    # 5) remap dependencies through the table
    for node in out_nodes:
        deps: set[int] = set()
        for old in node["after"]:
            deps.update(old_to_new.get(old, []))
        deps.discard(node["index"])
        node["after"] = sorted(deps)

    out = [{"title": nd["title"], "detail": nd["detail"],
            "owned_files": nd["files"], "agent_role": nd["role"],
            "after": nd["after"]} for nd in out_nodes]
    return {"plan": out, "changes": changes, "before": original_n,
            "after": len(out),
            "mapping": {str(k): v for k, v in old_to_new.items()}}


def summary(analysis: dict) -> str:
    """One-line human summary of an analysis."""
    return (f"{analysis.get('nodes', 0)} task(s): "
            f"{analysis.get('blockers', 0)} blocker(s), "
            f"{analysis.get('majors', 0)} major, {analysis.get('minors', 0)} minor")
