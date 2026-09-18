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


# Estimated spend rates (USD per 1K tokens) by provider kind. Estimates are
# computed at call time from prompt/completion size when a backend does not
# report usage — they are labelled estimates everywhere they surface.
SPEND_PER_1K_IN = {"openai": 0.0005, "claude": 0.0005, "hf": 0.0003}
SPEND_PER_1K_OUT = {"openai": 0.0015, "claude": 0.003, "hf": 0.0008}


def estimate_tokens(text: str) -> int:
    """~4 characters per token — an honest estimate, never a fake exact count."""
    return max(1, len(text or "") // 4)


class Provider:
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"

    #: Circuit breaker (Phase 7). Consecutive failures trip it; the cooldown
    #: doubles per trip (capped), and after the cooldown ONE half-open probe is
    #: allowed — success closes the circuit, failure re-opens it longer.
    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"
    FAILURE_THRESHOLD = 3
    OPEN_BASE_S = 30.0
    OPEN_MAX_S = 900.0
    INCIDENT_HISTORY = 20
    OUTCOME_WINDOW = 20

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
        # -- health history / circuit breaker -------------------------------
        self.consecutive_failures = 0
        self.circuit = self.CLOSED
        self.opened_at = 0.0
        self.open_seconds = 0.0
        self.trips = 0
        self.recovered_at = 0.0
        self.incidents: list[dict] = []
        self.outcomes: list[bool] = []
        self.PROBE_TIMEOUT_S = 120.0
        self._half_open_taken = False
        self._half_open_at = 0.0

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
        """Record a failed call and feed the circuit breaker."""
        from .healing import classify
        self.failures += 1
        self.last_error = msg[:300]
        if "429" in msg or "rate" in msg.lower() or "quota" in msg.lower():
            self.status = self.RATE_LIMITED
        else:
            self.status = self.DEGRADED
        kind = classify(msg).get("kind") or "provider_http_error"
        self.record_failure(msg, kind=kind)

    def mark_success(self) -> None:
        """Record a successful call (closes a half-open circuit)."""
        self.status = self.HEALTHY
        self.last_error = ""
        self.record_success()

    # -- circuit breaker / availability history ---------------------------
    def _release_half_open(self) -> None:
        """Hand a half-open probe ticket back (no slot was actually taken)."""
        with self._mu:
            self._half_open_taken = False

    def _publish_state(self) -> None:
        """Tell the manager about a circuit transition (never raises)."""
        mgr = getattr(self, "_manager", None)
        note = getattr(mgr, "_note_circuit", None)
        if note is None:
            return
        try:
            note(self)
        except Exception:  # noqa: BLE001 — observability must never break a call
            pass

    def record_success(self) -> None:
        with self._mu:
            self.consecutive_failures = 0
            self.outcomes.append(True)
            del self.outcomes[:-self.OUTCOME_WINDOW]
            if self.circuit != self.CLOSED:
                self.circuit = self.CLOSED
                self.recovered_at = time.time()
                self._half_open_taken = False
                self.incidents.append({
                    "at": self.recovered_at, "kind": "provider_recovered",
                    "detail": "circuit closed after a successful call"})
                del self.incidents[:-self.INCIDENT_HISTORY]
        self._publish_state()

    def record_failure(self, msg: str, kind: str = "provider_http_error") -> None:
        now = time.time()
        # HALF_OPEN is derived from the clock, so the EFFECTIVE state decides
        # whether this failure was a failed probe (re-quarantine, longer) or
        # another ordinary failure.
        effective = self.circuit_state()
        with self._mu:
            self.consecutive_failures += 1
            self.outcomes.append(False)
            del self.outcomes[:-self.OUTCOME_WINDOW]
            self.incidents.append({"at": now, "kind": kind,
                                   "detail": str(msg)[:200],
                                   "consecutive": self.consecutive_failures})
            del self.incidents[:-self.INCIDENT_HISTORY]
            if effective == self.HALF_OPEN or self.circuit == self.HALF_OPEN:
                # the probe failed: quarantine again, LONGER this time
                self.trips += 1
                self.open_seconds = min(self.OPEN_BASE_S * (2 ** (self.trips - 1)),
                                        self.OPEN_MAX_S)
                self.opened_at = now
                self.circuit = self.OPEN
                self._half_open_taken = False
            elif effective == self.CLOSED \
                    and self.consecutive_failures >= self.FAILURE_THRESHOLD:
                self.trips += 1
                self.open_seconds = min(self.OPEN_BASE_S * (2 ** (self.trips - 1)),
                                        self.OPEN_MAX_S)
                self.opened_at = now
                self.circuit = self.OPEN
            # already OPEN: the failure is recorded as an incident, but a trip is
            # a TRANSITION — it must not be inflated by every extra failure.
        self._publish_state()

    def cooldown_remaining(self) -> float:
        if self.circuit != self.OPEN:
            return 0.0
        return max(0.0, (self.opened_at + self.open_seconds) - time.time())

    def circuit_state(self) -> str:
        """``closed`` / ``open`` / ``half_open`` right now."""
        if self.circuit == self.OPEN and self.cooldown_remaining() <= 0:
            return self.HALF_OPEN
        return self.circuit

    def circuit_blocked(self) -> bool:
        """True when this provider must not be selected at all.

        Open-with-cooldown-left blocks. Open-with-cooldown-elapsed becomes a
        HALF-OPEN probe: exactly one request may go through, so a recovered
        provider is discovered without stampeding it. A probe ticket that was
        never resolved (abandoned reservation) expires, so the provider can
        never be locked out permanently by a lost ticket.
        """
        state = self.circuit_state()
        if state == self.OPEN:
            return True
        if state == self.HALF_OPEN:
            now = time.time()
            with self._mu:
                if (self._half_open_taken
                        and (now - self._half_open_at) < self.PROBE_TIMEOUT_S):
                    return True
                self._half_open_taken = True
                self._half_open_at = now
            return False
        return False

    def success_rate(self) -> float | None:
        with self._mu:
            window = list(self.outcomes)
        if not window:
            return None
        return round(sum(1 for ok in window if ok) / len(window), 3)

    def availability_history(self) -> dict:
        """Bounded, honest health history (no invented samples)."""
        return {
            "circuit": self.circuit_state(),
            "consecutive_failures": self.consecutive_failures,
            "trips": self.trips,
            "cooldown_remaining_s": round(self.cooldown_remaining(), 1),
            "open_seconds": self.open_seconds,
            "success_rate": self.success_rate(),
            "last_recovered_at": self.recovered_at or None,
            "incidents": list(self.incidents[-5:]),
        }

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
            self.mark_success()
            self.total_latency_s += time.time() - t0
            self._record_spend(messages, text)
        return text, err

    def _record_spend(self, messages, text) -> None:
        """Accumulate an estimated spend for this call (budget enforcement)."""
        mgr = getattr(self, "_manager", None)
        if mgr is None:
            return
        tin = estimate_tokens("\n".join(str(m.get("content", ""))
                                        for m in (messages or [])))
        tout = estimate_tokens(text or "")
        kind = (self.cfg.kind or "").lower()
        cost = ((tin / 1000) * SPEND_PER_1K_IN.get(kind, 0.0)
                + (tout / 1000) * SPEND_PER_1K_OUT.get(kind, 0.0))
        mgr.add_spend(cost, provider=self.name, tokens_in=tin,
                      tokens_out=tout)

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
            # health history (Phase 7): circuit state, success rate, incidents
            **self.availability_history(),
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
        # Budget state (Phase 27). spend_estimated_usd accumulates every
        # successful provider call through this manager (labelled estimates).
        self.spend_estimated_usd = 0.0
        self.budget_max_usd = None   # None = unbounded
        self.budget_warn_usd = None
        self._budget_warned = False
        self._budget_dropped: set[str] = set()
        self.spend_lock = threading.Lock()
        self._spend_by_provider: dict[str, float] = {}
        self._tokens_by_provider: dict[str, dict] = {}
        # Provider health events (Phase 7). Optional: when a bus is attached,
        # circuit transitions are published as provider.quarantined /
        # provider.recovered so the run timeline shows WHY a provider vanished.
        self.events = None
        self._circuit_seen: dict[str, str] = {}

    def set_events(self, events) -> "ProviderManager":
        self.events = events
        return self

    def _note_circuit(self, provider) -> None:
        """Publish a circuit transition once per change (never per call)."""
        state = provider.circuit_state()
        prev = self._circuit_seen.get(provider.name)
        if prev == state:
            return
        self._circuit_seen[provider.name] = state
        if self.events is None:
            return
        if state == Provider.OPEN:
            self.events.emit(
                "provider.quarantined", status="open",
                provider=provider.name, model=provider.cfg.model,
                detail=f"circuit opened after {provider.trips} trip(s) "
                       f"({provider.consecutive_failures} consecutive "
                       f"failures); {provider.open_seconds:.0f}s cooldown",
                error=(provider.last_error or "")[:200])
        elif state == Provider.CLOSED and prev is not None:
            self.events.emit(
                "provider.recovered", status="closed",
                provider=provider.name, model=provider.cfg.model,
                detail="circuit closed after a successful call")
        elif state == Provider.HALF_OPEN:
            self.events.emit(
                "provider.half_open", status="half_open",
                provider=provider.name, model=provider.cfg.model,
                detail="cooldown elapsed: one probe request is allowed")

    def register(self, cfg: ProviderConfig) -> Provider:
        p = Provider(cfg)
        p._manager = self          # spend accounting hook (budget enforcement)
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

    def _eligible(self, capabilities=None, avoid_models=None):
        """Yield ``(required, provider, rejection_reason)`` for capacity probes.

        ONE source of truth for the capability/health/avoid/budget criteria that
        ``select()`` and ``explain()`` share — strict capability match first,
        then the relaxed (soft-capability) pass. ``rejection_reason`` is None
        for a provider the policy would accept.
        """
        caps = set(capabilities or [])
        avoid = set(avoid_models or [])
        for required in self._requirement_passes(caps):
            for p in self._ordered():
                if self._over_budget() and self._is_paid_kind(p.cfg):
                    yield required, p, "over budget: paid provider dropped " \
                                       "(local/zero-cost providers still serve)"
                    continue
                # quarantine is checked BEFORE the coarse status so the trace
                # says "circuit open after N failures", not just "degraded"
                if p.circuit_state() == Provider.OPEN:
                    yield required, p, (
                        f"circuit open after {p.trips} trip(s)/"
                        f"{p.consecutive_failures} failures, "
                        f"{p.cooldown_remaining():.0f}s cooldown left")
                    continue
                if p.status != Provider.HEALTHY:
                    yield required, p, f"health={p.status}"
                    continue
                if p.cfg.model in avoid:
                    yield required, p, "model is avoided"
                    continue
                if required and not p.has_all(required):
                    missing = sorted(set(required) - set(p.cfg.capabilities or []))
                    yield required, p, f"missing capabilities {missing}"
                    continue
                yield required, p, None

    def select(self, capabilities=None, avoid_models=None) -> Provider | None:
        """Pick a healthy provider matching capabilities with a free slot.

        Uses configured priority order (fallback-friendly). Returns None if
        nothing suitable is available (caller queues the task instead).

        NOTE: this is a capacity *probe*. For atomic, held reservations use
        ``reserve()`` — the slot is then guaranteed for the whole call.
        """
        for required, p, reason in self._eligible(capabilities, avoid_models):
            if reason is not None:
                continue
            if p.acquire():
                p.release()  # probe; actual reservation via reserve()
                return p
        return None

    def availability_report(self) -> list[dict]:
        """Per-provider availability history (circuit, success rate, incidents)."""
        return [{"name": p.name, "status": p.status,
                 **p.availability_history()} for p in self.list()]

    def explain(self, capabilities=None, avoid_models=None) -> dict:
        """READ-ONLY routing decision trace: why this provider/model was chosen.

        Never acquires a slot (``select()`` is the acquiring probe). Reports the
        candidates considered, what each was rejected for, the requirement passes
        tried (strict, then soft-capability), the configured priority order and
        the health evidence behind it — so model routing is explainable rather
        than an opaque chooser.
        """
        caps = set(capabilities or [])
        trace: list[dict] = []
        selected = None
        seen_eligible: list[str] = []
        budget = self.budget_status()
        for required, p, reason in self._eligible(capabilities, avoid_models):
            strict = required == caps
            free = max(0, int(p.cfg.concurrency) - p.in_flight)
            row = {"provider": p.name, "model": p.cfg.model,
                   "status": p.status, "probed": bool(getattr(p, "probed", False)),
                   "last_error": p.last_error[:120],
                   "capabilities": sorted(p.cfg.capabilities or []),
                   "requirement_pass": "strict" if strict else "soft-fallback",
                   "required": sorted(required), "slots_free": free}
            if reason is not None:
                row["reason"] = reason
            elif free <= 0:
                row["reason"] = "no free concurrency slot"
            else:
                row["reason"] = None
                if p.name not in seen_eligible:
                    seen_eligible.append(p.name)
                if selected is None:
                    selected = p
                    row["selected"] = True
            trace.append(row)
        if selected is None:
            why = ("no healthy provider matched " + (f"{sorted(caps)} " if caps else "")
                   + "with a free slot — the task will queue instead of failing")
        else:
            strict_row = next((r for r in trace if r.get("selected")), {})
            pass_kind = strict_row.get("requirement_pass", "strict")
            why = (f"{selected.name} ({selected.cfg.model}) chosen for "
                   f"{sorted(caps) or ['chat']}: {pass_kind} capability match, "
                   f"health={selected.status}"
                   f"{' (unprobed)' if not getattr(selected, 'probed', False) else ''}"
                   f", {max(0, int(selected.cfg.concurrency) - selected.in_flight)} "
                   f"free slot(s), priority rank "
                   f"{self._priority_rank(selected)}")
        return {"selected": selected.name if selected else None,
                "model": selected.cfg.model if selected else None,
                "reason": why,
                "requirements": sorted(caps),
                "priority_order": [p.name for p in self._ordered()],
                "fallback_order": seen_eligible,
                "trace": trace,
                "budget": budget,
                "slots": {p.name: {"concurrency": p.cfg.concurrency,
                                   "in_flight": p.in_flight}
                          for p in self.list()}}

    def _priority_rank(self, provider) -> int:
        order = {k: i for i, k in enumerate(self._ordering)}
        return order.get((provider.cfg.kind, provider.cfg.label), 999)

    # -- budget enforcement (Phase 27) ---------------------------------------
    def set_budget(self, max_usd: float | None = None,
                   warn_usd: float | None = None) -> None:
        """Set the estimated-spend ceiling (and optional warning threshold).

        ``max_usd=None`` removes the ceiling. The budget applies to ESTIMATED
        spend accumulated through this manager since process start.
        """
        with self.spend_lock:
            self.budget_max_usd = max_usd
            self.budget_warn_usd = warn_usd
            self._budget_warned = False

    def add_spend(self, cost_usd: float, provider: str = "",
                  tokens_in: int = 0, tokens_out: int = 0) -> None:
        with self.spend_lock:
            self.spend_estimated_usd += float(cost_usd)
            if provider:
                self._spend_by_provider[provider] = \
                    self._spend_by_provider.get(provider, 0.0) + float(cost_usd)
                tk = self._tokens_by_provider.setdefault(
                    provider, {"tokens_in": 0, "tokens_out": 0})
                tk["tokens_in"] += int(tokens_in)
                tk["tokens_out"] += int(tokens_out)

    def _over_budget(self) -> bool:
        with self.spend_lock:
            return (self.budget_max_usd is not None
                    and self.spend_estimated_usd >= self.budget_max_usd)

    def _maybe_warn(self) -> None:
        with self.spend_lock:
            if (self.budget_warn_usd is not None and not self._budget_warned
                    and self.spend_estimated_usd >= self.budget_warn_usd):
                self._budget_warned = True
                return True
        return False

    def budget_status(self) -> dict:
        with self.spend_lock:
            return {
                "estimated_spend_usd": round(self.spend_estimated_usd, 6),
                "max_usd": self.budget_max_usd,
                "warn_usd": self.budget_warn_usd,
                "over_budget": (self.budget_max_usd is not None
                                and self.spend_estimated_usd >= self.budget_max_usd),
                "warned": self._budget_warned,
                "by_provider": {k: round(v, 6)
                                for k, v in sorted(self._spend_by_provider.items())},
                "tokens": dict(self._tokens_by_provider),
                "note": "spend values are estimates (chars/4), not billing data",
            }

    def _spend_gate(self, providers: list) -> list:
        """Zero-cost providers that may still run when the budget is exhausted.

        ONE source of truth for the paid-kind test used by ``_eligible()`` and
        ``reserve()`` — local/zero-cost providers always stay available.
        """
        if not self._over_budget():
            return list(providers)
        return [p for p in providers
                if (SPEND_PER_1K_IN.get((p.cfg.kind or "").lower(), 0.0) == 0.0
                    and SPEND_PER_1K_OUT.get((p.cfg.kind or "").lower(), 0.0) == 0.0)]

    @staticmethod
    def _is_paid_kind(cfg) -> bool:
        return (SPEND_PER_1K_IN.get((cfg.kind or "").lower(), 0.0) > 0.0
                or SPEND_PER_1K_OUT.get((cfg.kind or "").lower(), 0.0) > 0.0)

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
        # budget gate: when the estimated-spend ceiling is exhausted, only
        # zero-cost (local) providers may be reserved — same rule as _eligible.
        candidates = self._spend_gate(candidates)
        for required in self._requirement_passes(caps):
            for p in candidates:
                if p.status == Provider.UNAVAILABLE and not preferred:
                    continue
                if p.cfg.model in avoid:
                    continue
                if required and not p.has_all(required):
                    continue
                # quarantine gate: skip a provider whose circuit is open, and
                # allow exactly ONE half-open probe through. The gate is taken
                # before the slot so a failed probe cannot leak a slot.
                if p.circuit_blocked():
                    continue
                if p.acquire():  # slot held until release()
                    self._note_circuit(p)
                    return ProviderReservation(self, p)
                p._release_half_open()
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
