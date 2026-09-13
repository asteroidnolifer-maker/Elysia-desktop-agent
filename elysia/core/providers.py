"""Provider abstraction — Elysia talks to many AI backends through one
interface. Local llama.cpp/Ollama is just one provider among many.

Each provider reports:
  - capabilities (chat/coding/reasoning/tool_calling/vision/long_context/
    structured_output/streaming/background/file_access)
  - health & rate-limit state
  - concurrency slots (in_flight)
  - estimated cost, latency

The scheduler picks a healthy provider whose capabilities match the work.
A provider failure NEVER crashes the scheduler: ProviderManager.execute() tries
providers in a configured priority order (fallback routing) and reports the
failure as an event instead of raising.

Model routing is capability-driven and configurable: tasks advertise the
capabilities they need (e.g. an architect task wants reasoning; a doc task only
needs chat); the manager selects accordingly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.request
from urllib.error import HTTPError, URLError

from .config import ProviderConfig

# Capability vocabulary
CHAT = "chat"
CODING = "coding"
REASONING = "reasoning"
TOOL_CALLING = "tool_calling"
VISION = "vision"
LONG_CONTEXT = "long_context"
STRUCTURED_OUTPUT = "structured_output"
STREAMING = "streaming"
BACKGROUND = "background"
FILE_ACCESS = "file_access"
ALL_CAPABILITIES = {CHAT, CODING, REASONING, TOOL_CALLING, VISION,
                    LONG_CONTEXT, STRUCTURED_OUTPUT, STREAMING, BACKGROUND,
                    FILE_ACCESS}


class ProviderError(Exception):
    pass


class ProviderUnavailable(ProviderError):
    pass


class Provider:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"

    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg
        self.status = self.HEALTHY
        self.last_error = ""
        self.in_flight = 0
        self._mu = threading.Lock()
        self.requests = 0
        self.failures = 0
        self.total_latency_s = 0.0
        self.tokens_in = 0
        self.tokens_out = 0

    # -- identity ---------------------------------------------------------
    @property
    def name(self) -> str:
        return self.cfg.label or f"{self.cfg.kind}:{self.cfg.model}"

    def has_capability(self, cap: str) -> bool:
        return cap in (self.cfg.capabilities or [])

    def has_all(self, caps) -> bool:
        if not caps:
            return True
        return all(self.has_capability(c) for c in caps)

    # -- concurrency accounting ------------------------------------------
    def acquire(self) -> bool:
        """Try to reserve a concurrency slot. True if available."""
        with self._mu:
            if self.in_flight >= self.cfg.concurrency:
                return False
            self.in_flight += 1
            return True

    def release(self) -> None:
        with self._mu:
            if self.in_flight > 0:
                self.in_flight -= 1

    # -- health ------------------------------------------------------------
    def check_health(self) -> str:
        try:
            base = self.cfg.base_url.rstrip("/")
            with urllib.request.urlopen(base + "/models", timeout=5) as r:
                if r.status == 200:
                    self.status = self.HEALTHY
                    self.last_error = ""
                else:
                    self.status = self.DEGRADED
            return self.status
        except HTTPError as e:
            self.status = self.RATE_LIMITED if e.code == 429 else self.DEGRADED
            self.last_error = f"http {e.code}"
        except Exception as e:
            self.status = self.UNAVAILABLE
            self.last_error = str(e)[:200]
        return self.status

    def mark_error(self, msg: str) -> None:
        self.failures += 1
        self.last_error = msg[:300]
        if "429" in msg or "rate" in msg.lower() or "quota" in msg.lower():
            self.status = self.RATE_LIMITED
        else:
            self.status = self.DEGRADED

    # -- entry point -------------------------------------------------------
    def chat(self, messages, max_tokens: int | None = None,
             temperature: float | None = None, timeout: int | None = None):
        """One chat call. Returns (text, error)."""
        if not self.acquire():
            return "", "provider busy (concurrency limit)"
        self.requests += 1
        t0 = time.time()
        try:
            if self.cfg.kind == "cli":
                text, err = self._chat_cli(messages)
            else:
                text, err = self._chat_openai(messages, max_tokens,
                                              temperature, timeout)
            if err:
                self.mark_error(err)
            else:
                self.status = self.HEALTHY
                self.total_latency_s += time.time() - t0
            return text, err
        finally:
            self.release()

    # -- backends ----------------------------------------------------------
    def _chat_openai(self, messages, max_tokens, temperature, timeout):
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "stream": False,
        }
        temp = self.cfg.temperature if temperature is None else temperature
        if temp > 0:
            payload["temperature"] = temp
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        if self.cfg.api_key and self.cfg.api_key not in ("", "none"):
            req.add_header("Authorization", f"Bearer {self.cfg.api_key}")
        try:
            with urllib.request.urlopen(req,
                                        timeout=timeout or self.cfg.timeout_s) as r:
                data = json.loads(r.read().decode())
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage") or {}
            self.tokens_in += int(usage.get("prompt_tokens") or 0)
            self.tokens_out += int(usage.get("completion_tokens") or 0)
            return text, ""
        except HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            self.status = self.RATE_LIMITED if e.code == 429 else self.DEGRADED
            return "", f"http {e.code}: {body}"
        except (URLError, TimeoutError, OSError) as e:
            self.status = self.UNAVAILABLE
            return "", f"{type(e).__name__}: {str(e)[:200]}"
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            self.status = self.DEGRADED
            return "", f"bad response: {e}"

    def _chat_cli(self, messages):
        """CLI provider: pipe a rendered prompt into a subprocess command."""
        prompt = "\n\n".join(f"{m.get('role','user')}: {m.get('content','')}"
                             for m in messages)
        cmd = self.cfg.base_url.split()
        if not cmd:
            return "", "cli provider needs base_url set to a command"
        cmd.append(prompt)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=self.cfg.timeout_s)
            out = (r.stdout or r.stderr or "").strip()
            if r.returncode != 0:
                return "", out[:300]
            return out, ""
        except subprocess.TimeoutExpired:
            return "", "cli provider timed out"
        except OSError as e:
            return "", f"cli provider not found: {e}"

    # -- provider capacity model -------------------------------------------
    def capacity(self) -> dict:
        return {
            "name": self.name,
            "kind": self.cfg.kind,
            "model": self.cfg.model,
            "capabilities": self.cfg.capabilities or [],
            "status": self.status,
            "last_error": self.last_error,
            "max_concurrency": self.cfg.concurrency,
            "current_concurrency": self.in_flight,
            "requests": self.requests,
            "failures": self.failures,
            "avg_latency_s": round(self.total_latency_s / max(1, self.requests), 3),
            "estimated_cost_usd": round(getattr(self.cfg, "estimated_cost_usd", 0.0),
                                        6),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
        }


class ProviderManager:
    def __init__(self, ordering: list[tuple] | None = None):
        self._providers: dict[str, Provider] = {}
        self._mu = threading.Lock()
        # ordering: list of (kind, label) priority — first matched best
        self._ordering = ordering or []

    def register(self, cfg: ProviderConfig) -> Provider:
        p = Provider(cfg)
        name = p.name
        with self._mu:
            self._providers[name] = p
        if cfg.kind and cfg.label and (cfg.kind, cfg.label) not in self._ordering:
            self._ordering.append((cfg.kind, cfg.label))
        return p

    def register_many(self, cfgs) -> None:
        for cfg in cfgs:
            self.register(cfg)

    def list(self, healthy_only: bool = False) -> list[Provider]:
        with self._mu:
            ps = list(self._providers.values())
        if healthy_only:
            ps = [p for p in ps if p.status == Provider.HEALTHY]
        return ps

    def get(self, name: str) -> Provider | None:
        with self._mu:
            return self._providers.get(name)

    def _ordered(self) -> list[Provider]:
        ps = self.list()
        order = {k: i for i, k in enumerate(self._ordering)}
        return sorted(ps, key=lambda p: order.get((p.cfg.kind, p.cfg.label), 999))

    def select(self, capabilities=None, avoid_models=None) -> Provider | None:
        """Pick a healthy provider matching capabilities with a free slot.

        Uses configured priority order (fallback-friendly). Returns None if
        nothing suitable is available (caller queues the task instead).
        """
        caps = set(capabilities or [])
        avoid = set(avoid_models or [])
        for p in self._ordered():
            if p.status != Provider.HEALTHY:
                continue
            if p.cfg.model in avoid:
                continue
            if caps and not p.has_all(caps):
                continue
            if p.acquire():
                p.release()  # sample; actual acquire during use
                return p
        return None

    def execute(self, messages, capabilities=None, max_tokens=None,
                temperature=None, timeout=None, preferred=None) -> tuple:
        """Try providers in priority order until one succeeds.

        Returns (text, error). If all providers fail, returns (None, summary of
        errors) — never raises for a provider failure.
        """
        caps = set(capabilities or [])
        candidates = self._ordered()
        if preferred:
            p = self.get(preferred)
            if p:
                candidates = [p] + [x for x in candidates if x.name != preferred]
        errors = []
        for p in candidates:
            if p.status == Provider.UNAVAILABLE and not preferred:
                continue
            if caps and not p.has_all(caps):
                continue
            if not p.acquire():
                continue
            try:
                text, err = p.chat(messages, max_tokens=max_tokens,
                                   temperature=temperature, timeout=timeout)
                if not err:
                    return text, ""
                errors.append(f"{p.name}: {err[:120]}")
            finally:
                p.release()
            if p.status == Provider.RATE_LIMITED:
                # rate limited—try next provider rather than hammering
                continue
        summary = "; ".join(errors) if errors else "no provider available"
        return None, summary

    def health_report(self) -> list[dict]:
        return [p.capacity() for p in self.list()]

    def usage_totals(self) -> dict:
        totals = {"requests": 0, "failures": 0, "tokens_in": 0, "tokens_out": 0,
                  "latency_s": 0.0, "estimated_cost_usd": 0.0}
        for p in self.list():
            totals["requests"] += p.requests
            totals["failures"] += p.failures
            totals["tokens_in"] += p.tokens_in
            totals["tokens_out"] += p.tokens_out
            totals["latency_s"] += p.total_latency_s
            totals["estimated_cost_usd"] += p.capacity()["estimated_cost_usd"]
        return totals
