"""Layered context management for Elysia agents.

Context is assembled from distinct layers so the pipeline stays grounded and
bounded:

  L0  system (roles, tool schemas, safety rules)
  L1  project intelligence (languages, deps, test/build commands)
  L2  task context (description, files, deps, prior failures)
  L3  memory (user prefs, long-term project notes, agent memory)
  L4  execution history (recent events for this task/run)
  L5  scratch (agent-produced notes)

Each layer can be compressed/replaced independently; the builder keeps the
total within a character budget by trimming older entries first, then falling
back to summarised placeholders.
"""
from __future__ import annotations

import json


class ContextError(Exception):
    pass


class ContextBuilder:
    DEFAULTS = {
        "system": "",
        "project": "",
        "task": "",
        "memory": "",
        "history": "",
        "scratch": "",
        "capabilities": "",
    }

    def __init__(self, budget_chars: int = 60000, layer_order=None):
        self.budget = budget_chars
        self.layers: dict[str, str] = dict(self.DEFAULTS)
        self.order = layer_order or ["system", "project", "task", "memory",
                                     "history", "scratch", "capabilities"]
        # immutable layers are never compressed (system first)
        self.protected = {"system"}

    def set(self, layer: str, text: str) -> None:
        if layer not in self.layers:
            raise ContextError(f"unknown context layer {layer}")
        self.layers[layer] = text or ""

    def add(self, layer: str, text: str, sep: str = "\n") -> None:
        if layer not in self.layers:
            raise ContextError(f"unknown context layer {layer}")
        if self.layers[layer]:
            self.layers[layer] = self.layers[layer] + sep + text
        else:
            self.layers[layer] = text

    def get(self, layer: str) -> str:
        return self.layers.get(layer, "")

    MIN_TAIL = 120  # smallest useful trimmed slice

    def to_prompt(self) -> str:
        """Assemble layers, trimming to fit budget (protected layers kept)."""
        parts = []
        used = 0
        for layer in self.order:
            text = self.layers[layer].strip()
            if not text:
                continue
            if layer in self.protected:
                parts.append(text)
                used += len(text)
                continue
            if used + len(text) > self.budget:
                remaining = max(0, self.budget - used)
                if remaining >= self.MIN_TAIL:
                    text = text[:remaining - 3] + "..."
                    parts.append(text)
                    used += len(text)
                    break
                # not enough room for a useful slice — drop this and later layers
                break
            parts.append(text)
            used += len(text)
        return "\n\n".join(parts)

    def compress_history(self, entries: list[str], keep: int = 40) -> str:
        """Compress execution history: keep the newest N entries, append a
        summary line for the older ones. Cheap deterministic compression."""
        if len(entries) <= keep:
            return "\n".join(entries)
        dropped = len(entries) - keep
        kept = entries[-keep:]
        summary = f"[... {dropped} older events omitted ...]"
        return "\n".join([summary] + kept)

    def describe(self) -> dict:
        total = sum(len(v) for v in self.layers.values())
        return {
            "layers": {k: len(v) for k, v in self.layers.items()},
            "total_chars": total,
            "budget": self.budget,
        }

    @staticmethod
    def from_config(config_dict: dict) -> "ContextBuilder":
        cb = ContextBuilder(budget_chars=int(config_dict.get("budget_chars",
                                                            60000)))
        return cb


# ---------------------------------------------------------------------------
# Context planner (Phase 10)
#
# The builder above assembles layers and trims them. The planner decides WHICH
# material an agent actually needs for one call: it takes candidate layer texts
# with priorities + provenance, spends a token budget in priority order, keeps
# the tail of truncated layers (the most recent, most relevant part), and
# reports exactly what it included, trimmed or dropped and why.
# ---------------------------------------------------------------------------

#: Per-role layer priorities. Higher wins when the budget is tight. Roles not
#: listed fall back to DEFAULT_PRIORITY.
ROLE_CONTEXT_PRIORITY: dict[str, dict[str, int]] = {
    "planner": {"system": 100, "project": 60, "architecture": 55,
                "memory": 50, "task": 50, "capabilities": 40},
    "architect": {"system": 100, "project": 70, "architecture": 60,
                  "task": 55, "memory": 45},
    "implementer": {"system": 100, "task": 90, "failures": 80,
                    "files": 75, "tests": 60, "memory": 55, "review": 50,
                    "provider": 30, "capabilities": 25},
    "debugger": {"system": 100, "task": 90, "failures": 85, "tests": 80,
                 "files": 70, "memory": 55},
    "tester": {"system": 100, "task": 80, "tests": 75, "files": 60,
               "failures": 55},
    "code_reviewer": {"system": 100, "diff": 95, "review": 60,
                      "task": 55, "tests": 45, "memory": 35},
    "security_reviewer": {"system": 100, "diff": 95, "files": 60,
                          "task": 55, "capabilities": 40},
    "documentation_agent": {"system": 100, "task": 70, "diff": 60,
                            "project": 50},
    "research_agent": {"system": 100, "task": 70, "memory": 55,
                       "capabilities": 40},
}

DEFAULT_PRIORITY: dict[str, int] = {
    "system": 100, "task": 70, "project": 60, "files": 55, "diff": 55,
    "failures": 55, "tests": 45, "memory": 45, "review": 40,
    "architecture": 40, "capabilities": 35, "provider": 25,
}


class ContextPlanner:
    """Budgeted, explainable prompt assembly for one agent call."""

    CHARS_PER_TOKEN = 4
    MIN_SLICE_CHARS = 160

    def __init__(self, budget_tokens: int = 6000, role: str | None = None,
                 priority: dict | None = None):
        self.budget_tokens = max(200, int(budget_tokens))
        self.role = role
        table = dict(DEFAULT_PRIORITY)
        table.update(ROLE_CONTEXT_PRIORITY.get(role or "", {}))
        if priority:
            table.update(priority)
        self.priority = table
        self._layers: dict[str, dict] = {}
        self._cache: tuple | None = None

    # -- inputs -------------------------------------------------------------
    def add(self, layer: str, text, source: str = "", required: bool = False,
            priority: int | None = None) -> "ContextPlanner":
        if not text:
            return self
        text = text if isinstance(text, str) else json.dumps(
            text, ensure_ascii=False, indent=1, default=str)
        entry = self._layers.get(layer)
        if entry:
            entry["text"] = entry["text"] + "\n" + text
        else:
            self._layers[layer] = {
                "text": text, "source": source or layer,
                "required": bool(required),
                "priority": self.priority.get(layer, 30)
                            if priority is None else priority,
            }
        self._cache = None
        return self

    def invalidate(self, layer: str | None = None) -> None:
        """Drop cached output (all of it, or one layer's content)."""
        self._cache = None
        if layer is not None:
            self._layers.pop(layer, None)

    # -- planning -----------------------------------------------------------
    def plan(self, cache_key: str | None = None, header: str = "") -> dict:
        """Spend the budget in priority order and report what happened."""
        fingerprint = self._fingerprint()
        # The cache key includes the fingerprint, and add()/invalidate() clear
        # it, so a stale plan can never be served after the inputs changed.
        key = (cache_key, self.role, fingerprint)
        if self._cache and self._cache[0] == key:
            cached = dict(self._cache[1])
            cached["cached"] = True
            return cached
        budget_chars = self.budget_tokens * self.CHARS_PER_TOKEN
        ordered = sorted(self._layers.items(),
                         key=lambda kv: (not kv[1]["required"],
                                         -kv[1]["priority"]))
        parts, report, used = [], [], 0
        dropped = []
        for layer, entry in ordered:
            text = entry["text"].strip()
            if not text:
                continue
            remaining = budget_chars - used
            if remaining <= 0:
                dropped.append({"layer": layer, "chars": len(text),
                                "reason": "budget exhausted"})
                continue
            if len(text) <= remaining:
                parts.append((layer, text))
                used += len(text)
                report.append({"layer": layer, "chars": len(text),
                               "tokens_est": len(text) // self.CHARS_PER_TOKEN,
                               "included": True, "truncated": False,
                               "source": entry["source"],
                               "priority": entry["priority"]})
                continue
            if entry["required"] or remaining >= self.MIN_SLICE_CHARS:
                # keep the TAIL: recent attempts/results matter more than the
                # start of a long layer, and say the head was cut.
                cut = len(text) - remaining + 40
                slice_text = (f"[... {cut} chars omitted ...]\n"
                              + text[-(remaining - 40):])
                parts.append((layer, slice_text))
                used += len(slice_text)
                report.append({"layer": layer, "chars": len(slice_text),
                               "tokens_est": len(slice_text) // self.CHARS_PER_TOKEN,
                               "included": True, "truncated": True,
                               "omitted_chars": cut,
                               "source": entry["source"],
                               "priority": entry["priority"]})
            else:
                dropped.append({"layer": layer, "chars": len(text),
                                "reason": "no useful slice fits the budget"})
        body = "\n\n".join(f"## {layer}\n{t}" for layer, t in parts)
        prompt = (header + "\n\n" + body) if header else body
        out = {
            "prompt": prompt,
            "report": {
                "role": self.role,
                "budget_tokens": self.budget_tokens,
                "used_tokens_est": used // self.CHARS_PER_TOKEN,
                "used_chars": used,
                "layers": report,
                "dropped": dropped,
                "fingerprint": fingerprint,
            },
            "cached": False,
        }
        self._cache = (key, out)
        return out

    def explain(self) -> dict:
        """Why each candidate layer would/wouldn't fit (no model call)."""
        return self.plan()["report"]

    def _fingerprint(self) -> str:
        blob = "|".join(f"{k}:{len(v['text'])}" for k, v in sorted(self._layers.items()))
        return f"{hash(blob) & 0xFFFFFFFF:08x}:{len(self._layers)}"

    # -- layer builders (kept here so every caller formats them the same) ----
    @staticmethod
    def task_layer(task: dict) -> str:
        lines = [f"title: {task.get('title') or ''}",
                 f"detail: {task.get('description') or ''}",
                 f"role: {task.get('agent_role') or 'implementer'}",
                 f"status: {task.get('status') or ''}",
                 f"attempt: {task.get('attempts') or 0}/"
                 f"{task.get('max_attempts') or 3}",
                 f"owned files: {task.get('owned_files') or []}"]
        if task.get("dependencies"):
            lines.append(f"depends on task ids: {task.get('dependencies')}")
        if task.get("last_error"):
            lines.append(f"last error: {str(task['last_error'])[:400]}")
        return "\n".join(lines)

    @staticmethod
    def failure_layer(memories: list, classification: dict | None = None) -> str:
        lines = []
        if classification:
            lines.append(
                f"classified: {classification.get('kind')} "
                f"(retryable={classification.get('retryable')}, "
                f"action={classification.get('action')}, "
                f"hint={classification.get('hint')})")
        for m in memories or []:
            lines.append(f"- [{m.get('namespace')}/{m.get('kind') or ''}] "
                         f"{str(m.get('value'))[:280]}")
        return "\n".join(lines)

    @staticmethod
    def file_layer(files: dict) -> str:
        """Current content of the files this task owns (bounded per file)."""
        out = []
        for path, content in (files or {}).items():
            body = content if isinstance(content, str) else str(content)
            out.append(f"### {path} ({len(body)} chars)\n{body}")
        return "\n\n".join(out)

    @staticmethod
    def test_layer(test_result) -> str:
        if not test_result:
            return ""
        if isinstance(test_result, dict):
            return json.dumps(test_result, ensure_ascii=False)[:2000]
        return str(test_result)[:2000]

    @staticmethod
    def memory_layer(memories: list) -> str:
        return "\n".join(
            f"- ({m.get('namespace')}, score={m.get('score')}, "
            f"confidence={m.get('confidence')}) {str(m.get('value'))[:300]}"
            for m in memories or [])

    @staticmethod
    def provider_layer(explain: dict) -> str:
        """Provider constraints for this call (cost/health, not a secret)."""
        if not explain:
            return ""
        lines = []
        if explain.get("selected"):
            lines.append(f"selected provider: {explain['selected']}")
        for r in (explain.get("rejected") or [])[:6]:
            lines.append(f"rejected {r.get('name')}: {r.get('reason')}")
        return "\n".join(lines)