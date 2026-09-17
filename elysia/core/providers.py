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

# Capabilities that improve quality but are not required to serve a role.
# A provider missing only these may still be used as a FALLBACK, so a plain
# local coder model can plan/review when nothing better is configured — while a
# strictly matching provider is always preferred.
SOFT_CAPABILITIES = {REASONING, LONG_CONTEXT, VISION}


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
        # A freshly registered provider has never been contacted: "healthy" is
        # the optimistic default, not evidence. Reports must say so.
        self.probed = False
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
        self.probed = True
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
        """One chat call with its own concurrency slot. Returns (text, error)."""
        if not self.acquire():
            return "", "provider busy (concurrency limit)"
        try:
            return self._chat_unaccounted(messages, max_tokens=max_tokens,
                                          temperature=temperature, timeout=timeout)
        finally:
            self.release()

    def _chat_unaccounted(self, messages, max_tokens: int | None = None,
                          temperature: float | None = None,
                          timeout: int | None = None):
        """Transport + stats without touching the concurrency slot.

        Callers that already hold a slot (e.g. ProviderManager.execute or a
        ProviderReservation) MUST go through this method so a request acquires
        EXACTLY one slot, never two.
        """
        self.requests += 1
        t0 = time.time()
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
            "probed": self.probed,
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


class ProviderReservation:
    """A held provider slot. Guarantees exactly one acquire-release pair.

    Usable as a context manager; the slot is released on exit even if the
    underlying call raises.
    """

    def __init__(self, manager: "ProviderManager", provider: Provider):
        self.manager = manager
        self.provider = provider

    def call(self, messages, max_tokens: int | None = None,
             temperature: float | None = None, timeout: int | None = None):
        if self.provider is None:
            return None, "reservation released"
        return self.provider._chat_unaccounted(
            messages, max_tokens=max_tokens, temperature=temperature,
            timeout=timeout)

    def call_failover(self, messages, capabilities=None, max_tokens=None,
                      temperature=None, timeout=None):
        """Call via the held slot; if it errors, return the slot and let the
        manager fail over to the next provider.

        Exactly one slot is ever held (ours first, then the next provider's);
        the reservation is marked released so the scheduler's later
        ``release_reserved`` stays idempotent.
        """
        if self.provider is None:
            return self.manager.execute(messages, capabilities=capabilities,
                                        max_tokens=max_tokens,
                                        temperature=temperature, timeout=timeout)
        text, err = self.provider._chat_unaccounted(
            messages, max_tokens=max_tokens, temperature=temperature,
            timeout=timeout)
        if err:
            self.release()
            text, err = self.manager.execute(
                messages, capabilities=capabilities, max_tokens=max_tokens,
                temperature=temperature, timeout=timeout)
        return text, err

    def release(self) -> None:
        if self.provider is None:
            return
        self.provider.release()
        self.provider = None

    def __enter__(self) -> "ProviderReservation":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


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

    @staticmethod
    def _requirement_passes(caps: set) -> list[set]:
        """Strict capability set first, then the relaxed (soft-optional) one."""
        if not caps:
            return [set()]
        relaxed = {c for c in caps if c not in SOFT_CAPABILITIES}
        return [caps] if relaxed == caps else [caps, relaxed]

    def select(self, capabilities=None, avoid_models=None) -> Provider | None:
        """Pick a healthy provider matching capabilities with a free slot.

        Uses configured priority order (fallback-friendly). Returns None if
        nothing suitable is available (caller queues the task instead).

        NOTE: this is a capacity *probe*. For atomic, held reservations use
        ``reserve()`` — the slot is then guaranteed for the whole call.
        """
        caps = set(capabilities or [])
        avoid = set(avoid_models or [])
        for required in self._requirement_passes(caps):
            for p in self._ordered():
                if p.status != Provider.HEALTHY:
                    continue
                if p.cfg.model in avoid:
                    continue
                if required and not p.has_all(required):
                    continue
                if p.acquire():
                    p.release()  # probe; actual reservation via reserve()
                    return p
        return None

    def reserve(self, capabilities=None, avoid_models=None,
                preferred=None, exclude=()) -> "ProviderReservation | None":
        """Atomically select AND hold a provider slot (lease).

        Race-safe: two schedulers cannot both hold the final slot of a provider.
        The caller must call ``.release()`` (or use it as a context manager)
        exactly once when the work is done. ``exclude`` skips provider names
        already tried in this fallback chain.
        """
        caps = set(capabilities or [])
        avoid = set(avoid_models or [])
        skip = set(exclude or ())
        candidates = self._ordered()
        if preferred:
            p = self.get(preferred)
            if p and p.name not in skip:
                candidates = [p] + [x for x in candidates
                                    if x.name != preferred]
            else:
                candidates = list(candidates)
        # always honor the exclude set (fallback chain never re-tries)
        candidates = [x for x in candidates if x.name not in skip]
        for required in self._requirement_passes(caps):
            for p in candidates:
                if p.status == Provider.UNAVAILABLE and not preferred:
                    continue
                if p.cfg.model in avoid:
                    continue
                if required and not p.has_all(required):
                    continue
                if p.acquire():  # slot held until release()
                    return ProviderReservation(self, p)
        return None

    def execute(self, messages, capabilities=None, max_tokens=None,
                temperature=None, timeout=None, preferred=None) -> tuple:
        """Try providers in priority order until one succeeds.

        Each attempt acquires EXACTLY one slot (never two), so
        ``concurrency=1`` providers work correctly. Providers that error,
        crash (raise) or rate-limit are skipped, and the next provider takes
        over. Never raises for a provider failure.
        """
        caps = set(capabilities or [])
        tried: set[str] = set()
        errors: list[str] = []
        while len(tried) < len(self.list()):
            res = self.reserve(capabilities=caps or None,
                               avoid_models=None, preferred=preferred,
                               exclude=tried)
            if res is None:
                break
            provider = res.provider
            name = provider.name
            tried.add(name)
            rate_limited = False
            try:
                text, err = res.call(messages, max_tokens=max_tokens,
                                     temperature=temperature, timeout=timeout)
                if not err:
                    return text, ""
                errors.append(f"{name}: {err[:120]}")
            except Exception as e:  # noqa: BLE001 — provider crash must not kill the caller
                provider.mark_error(f"exception: {type(e).__name__}: {str(e)[:120]}")
                errors.append(f"{name}: exception {type(e).__name__}: {str(e)[:120]}")
            finally:
                rate_limited = provider.status == Provider.RATE_LIMITED
                res.release()
            if rate_limited:
                continue  # try next provider rather than hammering
        summary = "; ".join(errors) if errors else "no provider available"
        return None, summary

    def health_report(self, probe: bool = False) -> list[dict]:
        """Capacity rows for every provider.

        ``probe=True`` actively calls each provider first so the report never
        claims "healthy" for a backend nobody has contacted (the cached status
        of a freshly registered provider starts at healthy).
        """
        if probe:
            for p in self.list():
                try:
                    p.check_health()
                except Exception as e:  # noqa: BLE001 — a probe must not crash
                    p.status = Provider.UNAVAILABLE
                    p.last_error = str(e)[:200]
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
