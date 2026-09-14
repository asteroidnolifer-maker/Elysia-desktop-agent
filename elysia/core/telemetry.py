"""Structured logging, cost & usage tracking, and correlation IDs.

Elysia records behavior as structured events, not scattered prints. Telemetry
provides:

  - a JSONL log sink (append, crash-safe)
  - cost/usage aggregation per task, run, provider, model
  - correlation id propagation (task -> agent -> tool)
  - an execution history summary (what happened, in order)
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import defaultdict


def _now() -> float:
    return time.time()


class Correlation:
    def __init__(self, task_id=None, run_id=None):
        self.task_id = task_id
        self.run_id = run_id
        self.agent_role = None
        self.cancelled = False

    def child(self, **kw) -> "Correlation":
        c = Correlation(task_id=self.task_id, run_id=self.run_id)
        c.agent_role = kw.get("agent_role", self.agent_role)
        return c

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "run_id": self.run_id,
                "agent_role": self.agent_role}


class CostTracker:
    """Per-provider/model cost & token aggregation."""

    PROVIDER_COST_PER_1K_IN = {"openai": 0.0005, "claude": 0.0005,
                               "local": 0.0, "llama": 0.0}
    PROVIDER_COST_PER_1K_OUT = {"openai": 0.0015, "claude": 0.003,
                                "local": 0.0, "llama": 0.0}

    def __init__(self):
        self._mu = threading.Lock()
        self._totals = defaultdict(lambda: {"requests": 0, "tokens_in": 0,
                                            "tokens_out": 0, "cost_usd": 0.0,
                                            "latency_s": 0.0, "failures": 0})

    def record(self, provider=None, model=None, tokens_in=0, tokens_out=0,
               cost_usd=None, latency_s=0.0, failures=0):
        key = f"{provider or 'unknown'}:{model or 'unknown'}"
        with self._mu:
            t = self._totals[key]
            t["requests"] += 1
            t["tokens_in"] += int(tokens_in)
            t["tokens_out"] += int(tokens_out)
            t["latency_s"] += float(latency_s)
            t["failures"] += int(failures)
            if cost_usd is None:
                cost_usd = self._estimate(provider, tokens_in, tokens_out)
            t["cost_usd"] += float(cost_usd)
        return self._totals[key]

    @classmethod
    def _estimate(cls, provider, tin, tout) -> float:
        p = (provider or "").lower()
        in_rate = cls.PROVIDER_COST_PER_1K_IN.get(p, 0.0)
        out_rate = cls.PROVIDER_COST_PER_1K_OUT.get(p, 0.0)
        return (tin / 1000) * in_rate + (tout / 1000) * out_rate

    def totals(self) -> dict:
        with self._mu:
            return {k: dict(v) for k, v in sorted(self._totals.items())}

    def grand_total(self) -> dict:
        with self._mu:
            req = sum(v["requests"] for v in self._totals.values())
            cost = sum(v["cost_usd"] for v in self._totals.values())
            tin = sum(v["tokens_in"] for v in self._totals.values())
            tout = sum(v["tokens_out"] for v in self._totals.values())
            fail = sum(v["failures"] for v in self._totals.values())
            lat = sum(v["latency_s"] for v in self._totals.values())
        return {"requests": req, "tokens_in": tin, "tokens_out": tout,
                "cost_usd": round(cost, 6), "failures": fail,
                "latency_s": round(lat, 3)}


class Journal:
    """Append-only structured log to a JSONL file (crash-safe)."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._mu = threading.Lock()

    def record(self, event: dict) -> None:
        ev = {"ts": _now(), **event}
        try:
            with self._mu:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev, default=str) + "\n")
        except OSError:
            pass


class ExecutionHistory:
    """Ordered, bounded summary of events for a task/run."""

    def __init__(self, max_entries: int = 1000):
        self._mu = threading.Lock()
        self._entries: list[dict] = []
        self.max_entries = max_entries

    def log(self, entry: dict) -> None:
        with self._mu:
            self._entries.append(entry)
            if len(self._entries) > self.max_entries:
                self._entries = self._entries[-self.max_entries:]

    def entries(self, n: int | None = None) -> list[dict]:
        with self._mu:
            if n is None:
                return list(self._entries)
            return list(self._entries[-n:])

    def summary(self) -> list[str]:
        out = []
        for e in self.entries(50):
            kind = e.get("type", "?")
            detail = e.get("detail", "")
            if kind == "tool":
                out.append(f"tool {e.get('name')} -> {e.get('status')}"
                           + (f" ({detail})" if detail else ""))
            elif kind == "task":
                out.append(f"task {e.get('task_id')} -> {e.get('status')}")
            else:
                out.append(f"{kind}: {detail or e.get('status', '')}")
        return out