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
    }

    def __init__(self, budget_chars: int = 60000, layer_order=None):
        self.budget = budget_chars
        self.layers: dict[str, str] = dict(self.DEFAULTS)
        self.order = layer_order or ["system", "project", "task", "memory",
                                     "history", "scratch"]
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