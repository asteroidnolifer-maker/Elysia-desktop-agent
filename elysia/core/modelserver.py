"""The ONE place that starts or stops a local model server.

Elysia must never end up with several copies of the same model competing for a
2-core CPU. Every other path — the resource layer's warm-model lifecycle, the
legacy ``orchestrator/airllm.py`` helper, desktop launchers — delegates here
instead of calling ``subprocess`` itself.

Guarantees:

  - at most ONE managed model process (tracked in a pid file under the runtime
    directory), so a second start is a no-op rather than a second model
  - the server's parallel-slot setting follows ``resources.local_llm_concurrency``
    (default 1 on the target laptop), and thread count follows the core count
  - a start is refused when free RAM is below the configured floor, quoting the
    real number instead of guessing
  - nothing is started unless the binary and the model file genuinely exist —
    a missing model is reported as missing, never as "starting"
  - ``stop()`` is graceful (SIGTERM) and verifies the process really went away

It is deliberately small: the router/pool decide *whether* a model is needed;
this module only owns the process.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time

DEFAULT_PORT = 11434
PID_FILE = "model-server.pid"
STATE_FILE = "model-server.json"


def _runtime_dir(cfg=None) -> str:
    rc = getattr(cfg, "workspace", None)
    root = getattr(rc, "root", None) if rc is not None else None
    base = os.environ.get("ELYSIA_RUNTIME")
    if base:
        return base
    if root:
        return os.path.join(root, "..", "runtime")
    return "runtime"


def port_from_url(url: str, default: int = DEFAULT_PORT) -> int:
    """Port of a local provider base_url (``http://127.0.0.1:11434/v1``)."""
    try:
        tail = (url or "").split("//", 1)[-1].split("/", 1)[0]
        if ":" in tail:
            return int(tail.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        pass
    return default


class ModelServer:
    """Owns the local model process (start/stop/status). Never guesses."""

    def __init__(self, binary: str = "", model_path: str = "", port: int = DEFAULT_PORT,
                 runtime_dir: str = "runtime", threads: int = 0, parallel: int = 1,
                 ctx_size: int = 8192, ram_floor_mb: int = 1024,
                 host: str = "127.0.0.1", extra_args: list | None = None):
        self.binary = binary
        self.model_path = model_path
        self.port = int(port)
        self.runtime_dir = runtime_dir
        self.threads = int(threads) if threads else self._default_threads()
        self.parallel = max(1, int(parallel))
        self.ctx_size = int(ctx_size)
        self.ram_floor_mb = int(ram_floor_mb)
        self.host = host
        self.extra_args = list(extra_args or [])

    # -- construction --------------------------------------------------------
    @staticmethod
    def _default_threads() -> int:
        try:
            cores = os.cpu_count() or 2
        except (ValueError, OSError):
            cores = 2
        # never saturate every core: the desktop stays usable
        return max(1, min(cores, max(1, cores // 2)))

    @classmethod
    def from_config(cls, cfg=None, providers=None) -> "ModelServer":
        """Build from config + the configured local provider (no side effects)."""
        rc = getattr(cfg, "resources", cfg) or None

        def g(name, default):
            return getattr(rc, name, default) if rc is not None else default
        binary, model, port = "", "", DEFAULT_PORT
        try:
            locals_ = (providers.local_providers() if providers is not None
                       else [])
        except AttributeError:
            locals_ = []
        if locals_:
            p = locals_[0]
            url = p.cfg.base_url or ""
            port = port_from_url(url)
            model = p.cfg.model or ""
        binary = (os.environ.get("ELYSIA_LLAMA_BIN")
                  or os.environ.get("ELYSIA_MODEL_BIN")
                  or shutil.which("llama-server") or "")
        if not model:
            model = os.environ.get("ELYSIA_MODEL", "")
        if model and not os.path.isabs(model) and not model.endswith(".gguf"):
            model = os.environ.get("ELYSIA_MODEL", "")
        return cls(binary=binary, model_path=model, port=port,
                   runtime_dir=_runtime_dir(cfg),
                   threads=int(g("model_threads", 0) or 0),
                   parallel=int(g("local_llm_concurrency", 1) or 1),
                   ctx_size=int(g("model_ctx_size", 8192) or 8192),
                   ram_floor_mb=int(g("ram_block_infer_mb", 1024) or 1024))

    # -- introspection -------------------------------------------------------
    @property
    def pid_path(self) -> str:
        return os.path.join(self.runtime_dir, PID_FILE)

    @property
    def state_path(self) -> str:
        return os.path.join(self.runtime_dir, STATE_FILE)

    def model_file(self) -> str:
        """Resolve the model path (a real .gguf file, or "" when unknown)."""
        if self.model_path and os.path.isfile(self.model_path):
            return self.model_path
        if self.model_path and not os.path.isabs(self.model_path):
            cand = os.path.join(self.runtime_dir, "models", self.model_path)
            if os.path.isfile(cand):
                return cand
        try:
            models_dir = os.path.join(self.runtime_dir, "models")
            for name in sorted(os.listdir(models_dir)):
                if name.endswith(".gguf"):
                    return os.path.join(models_dir, name)
        except OSError:
            pass
        return ""

    def command(self) -> list:
        """The exact argv a start would use (empty list = cannot start)."""
        model = self.model_file()
        if not self.binary or not model:
            return []
        cmd = [self.binary, "--host", self.host, "--port", str(self.port),
               "--model", model, "--ctx-size", str(self.ctx_size),
               "--parallel", str(self.parallel), "--threads", str(self.threads)]
        return cmd + self.extra_args

    def plan(self, check_ram: bool = True) -> dict:
        """What a start WOULD do, and whether it is possible right now."""
        cmd = self.command()
        problems = []
        if not self.binary:
            problems.append("no llama-server binary found (set ELYSIA_LLAMA_BIN "
                            "or install it)")
        if not self.model_file():
            problems.append("no *.gguf model file found (set ELYSIA_MODEL_DIR / "
                            "ELYSIA_MODEL)")
        free_mb = None
        if check_ram:
            from .resources import available_memory_mb
            free_mb = available_memory_mb()
            if free_mb and 0 < free_mb < self.ram_floor_mb:
                problems.append(f"free RAM {free_mb} MB < {self.ram_floor_mb} MB "
                                "floor: refusing to load another model")
        return {"ok": not problems, "problems": problems, "command": cmd,
                "port": self.port, "parallel": self.parallel,
                "threads": self.threads, "model": self.model_file(),
                "binary": self.binary, "free_ram_mb": free_mb,
                "already_running": self.is_running()}

    def is_running(self) -> bool:
        """True when the managed pid is alive AND accepting connections."""
        pid = self._read_pid()
        if pid and self._pid_alive(pid):
            return True
        return self.port_open()

    def port_open(self) -> bool:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(1.5)
            s.connect((self.host, self.port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    # -- lifecycle -----------------------------------------------------------
    def start(self, wait_s: float = 8.0) -> dict:
        """Start the model server. One process, never a second copy."""
        plan = self.plan()
        if self.port_open() and not self._read_pid():
            return {"ok": True, "status": "external",
                    "detail": f"a model server is already listening on port "
                              f"{self.port} (not started by Elysia)",
                    "plan": plan}
        if self.is_running():
            return {"ok": True, "status": "already_running",
                    "detail": f"model server already up on port {self.port}",
                    "plan": plan}
        if not plan["ok"]:
            return {"ok": False, "status": "refused",
                    "detail": "; ".join(plan["problems"]), "plan": plan}
        os.makedirs(self.runtime_dir, exist_ok=True)
        try:
            proc = subprocess.Popen(
                plan["command"], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        except OSError as e:
            return {"ok": False, "status": "failed",
                    "detail": f"cannot start {self.binary}: {e}", "plan": plan}
        with open(self.pid_path, "w") as f:
            f.write(str(proc.pid))
        deadline = time.time() + max(0.5, wait_s)
        while time.time() < deadline:
            if self.port_open():
                break
            if proc.poll() is not None:
                # the process died: report the exit code, do not claim success
                with open(self.state_path, "w") as f:
                    json.dump({"pid": proc.pid, "ok": False,
                               "exit_code": proc.returncode}, f)
                return {"ok": False, "status": "crashed",
                        "detail": f"model server exited with code "
                                  f"{proc.returncode}", "plan": plan}
            time.sleep(0.25)
        ready = self.port_open()
        with open(self.state_path, "w") as f:
            json.dump({"pid": proc.pid, "ok": ready, "port": self.port,
                       "parallel": self.parallel, "model": plan["model"],
                       "threads": self.threads, "started_at": time.time()}, f)
        return {"ok": ready, "status": "started" if ready else "unconfirmed",
                "detail": (f"model server pid {proc.pid} on port {self.port} "
                           f"(parallel={self.parallel}, threads={self.threads})"
                           if ready else
                           f"pid {proc.pid} started but port {self.port} is not "
                           "accepting connections yet"),
                "pid": proc.pid, "plan": plan}

    def stop(self, timeout_s: float = 8.0) -> dict:
        pid = self._read_pid()
        if not pid:
            return {"ok": True, "status": "not_managed",
                    "detail": "no model server started by Elysia is recorded"}
        if not self._pid_alive(pid):
            self._clear_pid()
            return {"ok": True, "status": "already_stopped",
                    "detail": f"recorded pid {pid} is no longer running"}
        try:
            if os.name == "nt":                       # Windows: no SIGTERM
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
        except OSError as e:
            return {"ok": False, "status": "failed",
                    "detail": f"cannot signal pid {pid}: {e}"}
        deadline = time.time() + max(0.5, timeout_s)
        while time.time() < deadline and self._pid_alive(pid):
            time.sleep(0.25)
        alive = self._pid_alive(pid)
        self._clear_pid()
        return {"ok": not alive,
                "status": "stopped" if not alive else "still_running",
                "detail": (f"model server pid {pid} stopped" if not alive
                           else f"pid {pid} did not exit within {timeout_s:.0f}s")}

    def status(self) -> dict:
        plan = self.plan(check_ram=False)
        pid = self._read_pid()
        return {"managed_pid": pid if pid and self._pid_alive(pid) else None,
                "running": self.is_running(), "port": self.port,
                "port_open": self.port_open(), "binary": self.binary,
                "model": self.model_file(), "parallel": self.parallel,
                "threads": self.threads, "can_start": plan["ok"],
                "problems": plan["problems"]}

    # -- helpers -------------------------------------------------------------
    def unload_command(self) -> list:
        """argv the warm-model registry can run to unload this server.

        Self-invocation (no shell, no PATH assumptions) so the unload path works
        on Windows and inside the packaged runtime. ``--require-managed`` makes
        the command fail when Elysia does not own the running server, so the
        caller reports "not ours to unload" instead of claiming an unload that
        never happened.
        """
        return [sys.executable, os.path.abspath(__file__), "stop",
                "--runtime", self.runtime_dir, "--port", str(self.port),
                "--require-managed"]

    def _read_pid(self) -> int | None:
        try:
            with open(self.pid_path) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    def _clear_pid(self) -> None:
        try:
            os.remove(self.pid_path)
        except OSError:
            pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                 capture_output=True, text=True)
            return str(pid) in (out.stdout or "")
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="modelserver",
                                 description="Elysia local model server "
                                             "(canonical launcher)")
    ap.add_argument("action", choices=["start", "stop", "status", "plan"])
    ap.add_argument("--runtime", default=None)
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--model", default="")
    ap.add_argument("--binary", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-managed", action="store_true",
                    help="stop: fail when the running server was not started "
                         "by Elysia (used by the warm-model unload path)")
    args = ap.parse_args(argv)
    srv = ModelServer(binary=args.binary, model_path=args.model, port=args.port,
                      runtime_dir=args.runtime or "runtime")
    out = {"plan": srv.plan, "start": srv.start, "stop": srv.stop,
           "status": srv.status}[args.action]()
    if (args.require_managed and args.action == "stop"
            and out.get("status") == "not_managed"):
        out["ok"] = False
    print(json.dumps(out, indent=1, default=str))
    return 0 if out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
