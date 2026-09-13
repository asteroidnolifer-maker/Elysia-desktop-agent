"""Provider abstraction — Elysia talks to many AI backends through one
interface. Local llama.cpp/Ollama is just one provider among many.

Each provider reports capabilities, health, rate-limit state and concurrency.
The scheduler picks a healthy provider whose capabilities match the task.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.request
from urllib.error import HTTPError, URLError

from .config import ProviderConfig


class ProviderError(Exception):
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

    # -- identity ---------------------------------------------------------
    @property
    def name(self) -> str:
        return self.cfg.label or f"{self.cfg.kind}:{self.cfg.model}"

    def has_capability(self, cap: str) -> bool:
        return cap in (self.cfg.capabilities or [])

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

    # -- entry point -------------------------------------------------------
    def chat(self, messages, max_tokens: int | None = None,
             temperature: float | None = None, timeout: int | None = None):
        """One chat call. Returns (text, error)."""
        if not self.acquire():
            return "", "provider busy (concurrency limit)"
        try:
            if self.cfg.kind == "cli":
                return self._chat_cli(messages)
            return self._chat_openai(messages, max_tokens, temperature, timeout)
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
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.cfg.timeout_s) as r:
                data = json.loads(r.read().decode())
            text = data["choices"][0]["message"]["content"]
            self.status = self.HEALTHY
            self.last_error = ""
            return text, ""
        except HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            self.status = self.RATE_LIMITED if e.code == 429 else self.DEGRADED
            self.last_error = f"http {e.code}: {body}"
            return "", self.last_error
        except (URLError, TimeoutError, OSError) as e:
            self.status = self.UNAVAILABLE
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            return "", self.last_error
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            self.status = self.DEGRADED
            self.last_error = f"bad response: {e}"
            return "", self.last_error
        finally:
            self._last_call_s = time.time() - t0

    def _chat_cli(self, messages):
        """CLI provider: pipe a rendered prompt into a subprocess command.

        The command is split naively; this is a starting point for
        opencode/codex/claude CLIs — configure exact argv per provider.
        """
        prompt = "\n\n".join(f"{m.get('role','user')}: {m.get('content','')}"
                             for m in messages)
        cmd = self.cfg.base_url.split()  # base_url holds argv for cli kind
        if not cmd:
            return "", "cli provider needs base_url set to a command"
        cmd.append(prompt)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.cfg.timeout_s)
            out = (r.stdout or r.stderr or "").strip()
            if r.returncode != 0:
                self.status = self.DEGRADED
                self.last_error = out[:300]
                return "", self.last_error
            self.status = self.HEALTHY
            return out, ""
        except subprocess.TimeoutExpired:
            self.status = self.DEGRADED
            return "", "cli provider timed out"
        except OSError as e:
            self.status = self.UNAVAILABLE
            return "", f"cli provider not found: {e}"


class ProviderManager:
    def __init__(self):
        self._providers: dict[str, Provider] = {}
        self._mu = threading.Lock()

    def register(self, cfg: ProviderConfig) -> Provider:
        p = Provider(cfg)
        name = p.name
        # de-dupe: same name replaces
        with self._mu:
            self._providers[name] = p
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

    def select(self, capabilities=None) -> Provider | None:
        """Pick a healthy provider matching capabilities with a free slot."""
        caps = set(capabilities or [])
        for p in self.list(healthy_only=False):
            if p.status != Provider.HEALTHY:
                continue
            if caps and not all(p.has_capability(c) for c in caps):
                continue
            if p.acquire():
                p.release()  # sample; actual acquire happens during use
                return p
        return None

    def health_report(self) -> list[dict]:
        return [{
            "name": p.name,
            "kind": p.cfg.kind,
            "model": p.cfg.model,
            "status": p.status,
            "last_error": p.last_error,
            "concurrency": p.cfg.concurrency,
            "in_flight": p.in_flight,
        } for p in self.list()]