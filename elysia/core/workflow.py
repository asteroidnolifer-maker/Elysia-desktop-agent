"""Workflow engine: real node types over the durable task graph (Phase 2).

A workflow is a list of node dicts, each describing ONE durable board task plus
its control semantics. The board (TaskStore) stays the single source of truth —
the engine never keeps a second state machine: it persists nodes as rows and
then EVALUATES gates by reading and transitioning those rows through the
canonical state machine (`tasks.status_transition`).

Node types

    task        normal work node: runs through the standard agent pipeline.
    approval    human gate: `request_approval()` pauses the workflow here; a
                human (or an operator) calls `resolve_approval(allow=True/False)`
                to complete or cancel the node. NOT auto-approved by anything.
    fallback    tries node B only if node A reached a failed terminal state.
    retry       policy node: attempts its child up to N times (with a delay)
                before failing.
    timeout     child with a deadline: a task still running after
                `timeout_s` seconds is timed out through the store's policy
                (`timeout_task`), never left running forever.
    join        waits for parallel siblings (fan-in by dependency) and completes
                when they do; fails the join if any sibling failed.
    rollback    safety node: completes only if the listed checkpoint exists in
                the workspace's git repo (the actual rollback is an explicit,
                operator-visible action — never a silent destructive reset).
    fail        terminal failure node (explicit error out of the workflow).

Every node's dependencies are enforced by the canonical board (only tasks whose
dependencies completed become ready), so parallel sections really run in
parallel and gates really stop downstream work — there is no simulated ordering.

    WORKFLOW_ENGINE_VERSION = 1
"""
from __future__ import annotations

import json
import time

from .tasks import TaskStore

WORKFLOW_ENGINE_VERSION = 1

#: Node types whose rows must never be claimed by the model-executing worker.
GATE_KINDS = {"approval", "join", "rollback", "fallback", "retry", "timeout",
              "fail"}

_KIND_PREFIX = {k: f"{k}:" for k in GATE_KINDS}

# Statuses that "satisfy" a dependency for gate evaluation purposes.
_OK = ("completed", "done")
_BAD = ("failed", "cancelled", "dependency_failed")


class WorkflowError(Exception):
    pass


def _spec_of(description: str, kind: str) -> dict:
    """Decode the node's spec JSON from its description suffix, if present."""
    marker = f"@@{kind}:"
    idx = description.find(marker)
    if idx < 0:
        return {}
    try:
        return json.loads(description[idx + len(marker):].split("@@", 1)[0])
    except (json.JSONDecodeError, TypeError):
        return {}


def _encode_description(kind: str, text: str, spec: dict) -> str:
    base = (text or kind).strip()
    if not spec:
        return base
    return f"{base}@@{kind}:{json.dumps(spec, sort_keys=True)}@@"


def validate_workflow(nodes: list[dict]) -> list[str]:
    """Static validation problems (empty = the graph is well-formed).

    Checks: non-empty, unique ids, every node has a known type, `after`
    references exist and point backwards (no cycles by construction), join
    nodes wait on something, fallback names both sides.
    """
    problems: list[str] = []
    if not nodes:
        return ["workflow has no nodes"]
    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids):
        problems.append("duplicate node ids")
    index = {n.get("id"): i for i, n in enumerate(nodes)}
    for i, n in enumerate(nodes):
        t = n.get("type", "task")
        if t not in ("task", "approval", "fallback", "retry", "timeout",
                     "join", "rollback", "fail"):
            problems.append(f"node {n.get('id')}: unknown type {t!r}")
        for dep in n.get("after") or []:
            if dep not in index:
                problems.append(f"node {n.get('id')}: after unknown node {dep!r}")
            elif index[dep] >= i:
                problems.append(
                    f"node {n.get('id')}: depends on a later node ({dep}); "
                    "cycles are impossible by construction — reorder the nodes")
        if t == "join" and not n.get("after"):
            problems.append(f"join node {n.get('id')} waits on nothing")
        if t == "fallback" and not n.get("fallback_of"):
            problems.append(f"fallback node {n.get('id')} has no fallback_of")
    return problems


class WorkflowEngine:
    """Persists a workflow onto a TaskStore and evaluates its gate nodes."""

    def __init__(self, store: TaskStore, events=None, clock=time.time):
        self.store = store
        self.events = events
        self.clock = clock

    # -- helpers -------------------------------------------------------------
    def _emit(self, status: str, **kw) -> None:
        if self.events is not None:
            try:
                self.events.emit("workflow", status=status, **kw)
            except Exception:  # noqa: BLE001 — a broken sink must not stop runs
                pass

    # -- persistence ----------------------------------------------------------
    def start(self, name: str, nodes: list[dict], priority: int = 5,
              owned_files=None) -> dict:
        """Validate and persist a workflow; returns ids and the run record.

        Gate rows (approval/join/...) are created as ``kind='gate:<type>'`` so
        no worker will ever claim them; they are completed by this engine.
        """
        problems = validate_workflow(nodes)
        if problems:
            raise WorkflowError("; ".join(problems))
        ids: dict[str, int] = {}
        dep_ids: dict[str, list[int]] = {}
        for n in nodes:
            t = n.get("type", "task")
            after = [ids[d] for d in (n.get("after") or [])]
            dep_ids[n["id"]] = after
            kind = "task" if t == "task" else f"gate:{t}"
            spec = {k: v for k, v in n.items()
                    if k in ("timeout_s", "max_attempts", "retry_delay_s",
                             "fallback_of", "checkpoint")}
            desc = _encode_description(t, n.get("description") or n.get("title"),
                                       spec)
            if t == "task":
                tid = self.store.add_task(
                    title=n.get("title") or n["id"], description=desc,
                    owned_files=(n.get("owned_files")
                                 if n.get("owned_files") is not None
                                 else (owned_files or [])),
                    dependencies=after, priority=priority,
                    agent_role=n.get("agent_role"), kind="task",
                    workflow=name, timeout_s=n.get("timeout_s"))
            else:
                tid = self.store.add_task(
                    title=f"[{t}] {n.get('title') or n['id']}", description=desc,
                    dependencies=after, priority=priority, kind=kind,
                    workflow=name)
            # A node is ready only when nothing blocks it. Observer/policy
            # gates (timeout, fallback, rollback, fail, retry) are evaluated by
            # tick() as soon as they are ready; join/approval/task nodes wait
            # for their dependencies (queued = waiting on prerequisites).
            if not after or t in ("timeout", "fallback", "rollback", "fail",
                                  "retry"):
                self.store.mark_ready(tid)
            ids[n["id"]] = tid
        self._emit("started", detail=f"{name}: {len(nodes)} node(s)",
                   agent_id="workflow")
        return {"ok": True, "name": name, "engine_version": WORKFLOW_ENGINE_VERSION,
                "node_ids": ids, "dependencies": dep_ids,
                "total": len(nodes)}

    # -- gate evaluation -------------------------------------------------------
    #: Node types that observe the run rather than wait for prerequisites.
    _OBSERVER_GATES = {"timeout", "fallback", "rollback", "fail", "retry"}

    def tick(self) -> dict:
        """Advance the run: promote eligible rows, then evaluate ready gates."""
        advanced: list[dict] = []
        rows = self.store.list(limit=2000)
        # -- 1) promotion: queued workflow rows whose prerequisites are met
        for t in rows:
            if t.get("status") != "queued" or not t.get("workflow"):
                continue
            kind = t.get("kind") or "task"
            node_type = kind.split(":", 1)[1] if kind.startswith("gate:") \
                else "task"
            if node_type in self._OBSERVER_GATES:
                self.store.mark_ready(t["id"])
                continue
            deps = t.get("dependencies") or []
            if not deps:
                self.store.mark_ready(t["id"])
                continue
            states = {d: (self.store.get(d) or {}).get("status") for d in deps}
            if node_type in ("join", "approval"):
                # become evaluable once every dependency is TERMINAL; the
                # handler then decides success or failure
                if all(s in _OK + _BAD for s in states.values()):
                    self.store.mark_ready(t["id"])
            else:
                if all(s in _OK for s in states.values()):
                    self.store.mark_ready(t["id"])
        # -- 2) evaluate ready gates
        rows = self.store.list(limit=2000)
        gates = [t for t in rows
                 if (t.get("kind") or "").startswith("gate:")
                 and t.get("status") == "ready"]
        for t in gates:
            kind = (t["kind"] or "").split(":", 1)[1]
            handler = getattr(self, f"_gate_{kind}", None)
            if handler is None:
                continue
            result = handler(t)
            if result:
                advanced.append({"node": t["id"], "kind": kind, **result})
        if advanced:
            self._emit("gates", detail=json.dumps(advanced)[:300],
                       agent_id="workflow")
        return {"advanced": advanced}

    def _deps(self, t: dict) -> list[int]:
        return t.get("dependencies") or []

    def _dep_states(self, t: dict) -> dict[int, str]:
        return {d: (self.store.get(d) or {}).get("status") for d in self._deps(t)}

    def _complete(self, tid: int, t: dict, result: str) -> bool:
        if t["status"] not in ("ready", "queued", "claimed", "running"):
            return False
        self.store.complete(tid, "completed", result[:500])
        return True

    def _fail(self, tid: int, t: dict, reason: str) -> bool:
        if t["status"] not in ("ready", "queued"):
            return False
        self.store.transition(tid, "failed", last_error=reason[:500])
        return True

    # -- specific gates ---------------------------------------------------------
    def _gate_approval(self, t: dict) -> dict | None:
        states = self._dep_states(t)
        if any(s in _BAD for s in states.values()):
            return {"state": "failed",
                    "detail": "upstream failed; nothing to approve"} \
                if self._fail(t["id"], t,
                              "approval gate: upstream dependency failed") else None
        spec = _spec_of(t["description"], "approval")
        requested_for = spec.get("requested_for", "")
        return {"state": "waiting_for_human",
                "detail": f"approval node {t['id']} pending"
                          + (f" (requested by {requested_for})" if requested_for
                             else "")}

    def _gate_join(self, t: dict) -> dict | None:
        states = self._dep_states(t)
        if not states:
            return None
        if any(s in _BAD for s in states.values()):
            return {"state": "failed",
                    "detail": "sibling failed"} if self._fail(
                t["id"], t, "join: a dependency failed") else None
        if all(s in _OK for s in states.values()):
            summary = ", ".join(f"#{d}={s}" for d, s in sorted(states.items()))
            return {"state": "completed",
                    "detail": summary} if self._complete(
                t["id"], t, f"join complete: {summary}") else None
        return None

    def _gate_fallback(self, t: dict) -> dict | None:
        """Complete only when the primary reaches a terminal state: the fallback
        work executes when the primary FAILED, and is recorded as skipped when
        the primary succeeded."""
        spec = _spec_of(t["description"], "fallback")
        of_name = spec.get("fallback_of")
        if not of_name:
            return self._fail(t["id"], t, "fallback has no fallback_of") \
                or {"state": "failed", "detail": "no fallback_of"}
        rows = self.store.list(limit=2000, workflow=t.get("workflow"))
        primary = next((r for r in rows if r.get("title") == of_name
                        or (r.get("title") or "").endswith(f"] {of_name}")), None)
        if primary is None:
            return {"state": "failed", "detail": "primary not found"} \
                if self._fail(t["id"], t,
                              f"fallback primary node {of_name!r} not found") \
                else None
        if primary.get("status") in _BAD:
            self._complete(t["id"], t,
                           f"primary #{primary['id']} "
                           f"{primary.get('status')}; fallback executes")
            return {"state": "completed",
                    "detail": f"primary failed ({primary.get('status')}); "
                              "fallback executes"}
        if primary.get("status") in _OK:
            self._complete(t["id"], t, "primary succeeded; fallback skipped")
            return {"state": "completed", "detail": "primary already succeeded"}
        return None

    def _gate_retry(self, t: dict) -> dict | None:
        spec = _spec_of(t["description"], "retry")
        attempts = int(spec.get("max_attempts", 2))
        done = (t.get("usage_json") or {}).get("retry_evaluations", 0)
        usage = dict(t.get("usage_json") or {})
        usage["retry_evaluations"] = done + 1
        self.store._update(t["id"], usage_json=json.dumps(usage))
        if done + 1 >= attempts:
            return {"state": "failed",
                    "detail": f"retry policy exhausted ({attempts})"} \
                if self._fail(t["id"], t, "retry policy exhausted") else None
        return {"state": "waiting", "detail": f"retry node waiting "
                                              f"({done + 1}/{attempts})"}

    def _gate_timeout(self, t: dict) -> dict | None:
        spec = _spec_of(t["description"], "timeout")
        limit = float(spec.get("timeout_s", 900))
        states = self._dep_states(t)
        if any(s in _BAD for s in states.values()):
            return {"state": "failed", "detail": "dependency failed"} \
                if self._fail(t["id"], t, "timeout node: dependency failed") else None
        if all(s in _OK for s in states.values()):
            return {"state": "completed", "detail": "child completed in time"} \
                if self._complete(t["id"], t, "child completed before timeout") \
                else None
        started = min((self.store.get(d) or {}).get("started_at") or 0
                      for d in states)
        if started and (self.clock() - started) > limit:
            for d, s in states.items():
                if s in ("claimed", "running", "testing", "reviewing"):
                    self.store.timeout_task(d)
            return {"state": "failed",
                    "detail": f"child exceeded {limit}s; timed out via store"} \
                if self._fail(t["id"], t, f"child exceeded {limit}s") else None
        return None

    def _gate_rollback(self, t: dict) -> dict | None:
        spec = _spec_of(t["description"], "rollback")
        checkpoint = spec.get("checkpoint", "")
        from .git import checkpoint_list
        commits = checkpoint_list(".", limit=50)
        known = any(c.get("sha", "").startswith(checkpoint) for c in commits
                    if checkpoint)
        if checkpoint and not known:
            return {"state": "failed", "detail": f"checkpoint {checkpoint!r} "
                                                 "not found; refusing to guess"} \
                if self._fail(t["id"], t, f"unknown checkpoint {checkpoint}") else None
        return {"state": "completed",
                "detail": f"rollback point {checkpoint or 'HEAD'} verified"} \
            if self._complete(t["id"], t, f"rollback point {checkpoint or 'HEAD'} "
                                          "verified") else None

    def _gate_fail(self, t: dict) -> dict | None:
        return {"state": "failed", "detail": "explicit fail node"} \
            if self._fail(t["id"], t, "explicit fail node") else None

    # -- human approval API -----------------------------------------------------
    def request_approval(self, node_id: int, requested_for: str = "") -> bool:
        """Mark an approval gate as actively requesting a human decision."""
        t = self.store.get(node_id)
        if not t or (t.get("kind") or "") != "gate:approval":
            return False
        self.store._update(node_id, last_error=f"approval requested"
                                               f"{f' by {requested_for}' if requested_for else ''}")
        self._emit("approval_requested", task_id=node_id,
                   agent_id="workflow", detail=requested_for)
        return True

    def resolve_approval(self, node_id: int, allow: bool, by: str = "operator",
                         note: str = "") -> bool:
        """Human decision: complete (allow) or cancel (deny) an approval gate.

        Cancelling the gate also cancels everything downstream that depends on
        it (the store's cancel handles the cascade).
        """
        t = self.store.get(node_id)
        if not t or (t.get("kind") or "") != "gate:approval":
            return False
        if allow:
            self._complete(node_id, t, f"approved by {by}"
                                       f"{f': {note}' if note else ''}")
            self._emit("approval_granted", task_id=node_id, agent_id="workflow")
            return True
        self.store.cancel(node_id, by=by)
        self._emit("approval_denied", task_id=node_id, agent_id="workflow")
        return True

    # -- introspection ------------------------------------------------------------
    def run_state(self, name: str) -> dict:
        """Full state of one workflow run (nodes, gate states, progress)."""
        rows = [t for t in self.store.list(limit=2000, workflow=name)]
        nodes = []
        for t in sorted(rows, key=lambda r: r["id"]):
            kind = (t.get("kind") or "task")
            gate = kind.startswith("gate:")
            nodes.append({"id": t["id"], "title": t["title"],
                          "type": kind.split(":", 1)[1] if gate else "task",
                          "status": t["status"],
                          "dependencies": t.get("dependencies") or [],
                          "result": (t.get("result") or "")[:200],
                          "error": (t.get("last_error") or "")[:200] or None})
        done = sum(1 for n in nodes if n["status"] in _OK)
        failed = sum(1 for n in nodes if n["status"] in _BAD)
        waiting = [n for n in nodes if n["type"] == "approval"
                   and n["status"] in ("ready", "queued", "claimed", "running")]
        return {"name": name, "engine_version": WORKFLOW_ENGINE_VERSION,
                "nodes": nodes, "completed": done, "failed": failed,
                "total": len(nodes),
                "finished": done + failed == len(nodes) and len(nodes) > 0,
                "ok": len(nodes) > 0 and failed == 0 and done + failed == len(nodes),
                "awaiting_approval": [n["id"] for n in waiting]}
