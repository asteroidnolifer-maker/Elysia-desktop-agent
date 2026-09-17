#!/usr/bin/env python3
"""Elysia universal installer + launcher — Linux, macOS, Windows.

One implementation for all three platforms; the thin wrappers
(``install.sh``/``start.sh``, ``install.ps1``/``start.ps1``, ``*.cmd``) only
locate a Python 3 interpreter and call this file.

    python3 scripts/elysia_boot.py install [--deps] [--build] [--with-model]
    python3 scripts/elysia_boot.py start   [--no-model|--no-agent|--no-hud]
    python3 scripts/elysia_boot.py stop | restart | status | doctor

Design rules:
  * stdlib only, Python 3.8+ (the runtime itself is stdlib-only Python).
  * never destructive: install adds files and normalizes config paths; it
    never deletes user data, never overwrites API keys, never edits secrets.
  * honest reporting: a step that cannot run is reported SKIP/FAIL with the
    exact command to run by hand — never a fake success.
  * ``--dry-run`` prints every action without performing it.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

STATE_DIR = ROOT / "state"
PID_DIR = STATE_DIR / "pids"
LOG_DIR = ROOT / "logs"
WORKSPACE = ROOT / "workspace"
RUNTIME_DIR = ROOT / "runtime"
MODEL_DIR = RUNTIME_DIR / "models"
LLAMA_DIR = RUNTIME_DIR / "llama"

PY = sys.executable or ("python" if IS_WIN else "python3")

OK, SKIP, FAIL, INFO = "ok", "skip", "fail", "info"

# Ports: model API, agent-core HTTP, HUD/orchestrator HTTP.
PORT_MODEL = int(os.environ.get("ELYSIA_MODEL_PORT", "11434"))
PORT_AGENT = int(os.environ.get("ELYSIA_AGENT_PORT", "8085"))
PORT_HUD = int(os.environ.get("ELYSIA_API_PORT", "8087"))


# --------------------------------------------------------------------------- #
# output helpers
# --------------------------------------------------------------------------- #
class Ui:
    def __init__(self, dry_run=False, yes=False, quiet=False, as_json=False):
        self.dry_run = dry_run
        self.yes = yes
        self.quiet = quiet
        self.as_json = as_json
        self.records = []

    def line(self, msg=""):
        if not self.quiet and not self.as_json:
            print(msg)

    def step(self, name, status, detail=""):
        self.records.append({"step": name, "status": status, "detail": detail})
        if self.as_json:
            return
        mark = {OK: "ok  ", SKIP: "skip", FAIL: "FAIL", INFO: "    "}[status]
        pad = "" if status == INFO else f"[{mark}] "
        self.line(f"{pad}{name}" + (f": {detail}" if detail else ""))

    def cmd(self, argv, cwd=None):
        """Print (and, unless --dry-run, run) a command. Returns rc."""
        pretty = " ".join(str(a) for a in argv)
        if cwd:
            pretty = f"(cd {cwd} && {pretty})"
        self.line(f"    $ {pretty}")
        if self.dry_run:
            return 0
        try:
            return subprocess.call([str(a) for a in argv],
                                   cwd=str(cwd) if cwd else None)
        except FileNotFoundError:
            self.line(f"    ! command not found: {argv[0]}")
            return 127
        except OSError as e:  # noqa: BLE001 — report, never traceback
            self.line(f"    ! {type(e).__name__}: {e}")
            return 1


# --------------------------------------------------------------------------- #
# small utilities
# --------------------------------------------------------------------------- #
def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(port: int, seconds: float = 30.0, host: str = "127.0.0.1") -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port, host):
            return True
        time.sleep(0.5)
    return port_open(port, host)


def read_json(path: Path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# --------------------------------------------------------------------------- #
# install
# --------------------------------------------------------------------------- #
def _pkg_manager() -> tuple:
    """(install-cmd-prefix, name) for this platform, or (None, reason)."""
    if IS_WIN:
        for tool, prefix in (("winget", ["winget", "install", "-e", "--id"]),
                             ("choco", ["choco", "install", "-y"]),
                             ("scoop", ["scoop", "install"])):
            if have(tool):
                return prefix, tool
        return None, "no winget/choco/scoop on PATH"
    if IS_MAC:
        return (["brew", "install"], "brew") if have("brew") else \
            (None, "Homebrew not installed (https://brew.sh)")
    if have("apt-get"):
        return ["sudo", "apt-get", "install", "-y"], "apt-get"
    if have("dnf"):
        return ["sudo", "dnf", "install", "-y"], "dnf"
    if have("pacman"):
        return ["sudo", "pacman", "-S", "--noconfirm"], "pacman"
    if have("zypper"):
        return ["sudo", "zypper", "install", "-y"], "zypper"
    if have("apk"):
        return ["sudo", "apk", "add"], "apk"
    return None, "no supported package manager found"


# tool -> per-platform package names
PKG_NAMES = {
    "git": {"linux": "git", "mac": "git", "win": "Git.Git"},
    "go": {"linux": "golang-go", "mac": "go", "win": "GoLang.Go"},
    "curl": {"linux": "curl", "mac": "curl", "win": "curl.curl"},
}


def _pkg_key() -> str:
    return "win" if IS_WIN else ("mac" if IS_MAC else "linux")


def cmd_install(ui: Ui, args) -> int:
    ui.line(f"Elysia install — {platform_label()}")
    ui.line(f"repository: {ROOT}")
    ui.line("")

    # 1) Python (hard requirement: the whole runtime is stdlib Python)
    ver = ".".join(str(v) for v in sys.version_info[:3])
    if sys.version_info < (3, 8):
        ui.step("python", FAIL, f"{ver} is too old — need 3.8+")
        return 1
    ui.step("python", OK, ver)
    ui.step("platform", INFO, platform_label())

    # 2) command-line prerequisites
    missing = []
    for tool, why in (("git", "repository + checkpoints"),
                      ("curl", "downloads"),
                      ("go", "build agent-core (optional)")):
        if have(tool):
            ui.step(f"tool: {tool}", OK, why)
        elif tool == "go":
            ui.step(f"tool: {tool}", SKIP, f"not found — {why}")
            missing.append(tool)
        else:
            ui.step(f"tool: {tool}", FAIL, f"not found — {why}")
            missing.append(tool)

    if missing and args.deps:
        prefix, mgr = _pkg_manager()
        if prefix is None:
            ui.step("dependencies", FAIL, mgr)
        else:
            for tool in missing:
                pkg = PKG_NAMES.get(tool, {}).get(_pkg_key(), tool)
                if ui.dry_run:
                    ui.cmd(prefix + [pkg])
                    ui.step(f"install {tool}", INFO, f"would install via {mgr}")
                    continue
                if not ui.yes and sys.stdin.isatty():
                    reply = input(f"    install {tool} via {mgr}? [y/N] ")
                    if reply.strip().lower() not in ("y", "yes"):
                        ui.step(f"install {tool}", SKIP, "declined")
                        continue
                ui.cmd(prefix + [pkg])
                ui.step(f"install {tool}",
                        OK if have(tool) else FAIL,
                        "now on PATH" if have(tool) else "check the output above")
    elif missing:
        prefix, mgr = _pkg_manager()
        hint = " ".join(prefix + [PKG_NAMES.get(t, {}).get(_pkg_key(), t)
                                  for t in missing])
        ui.step("dependencies", SKIP,
                "re-run with --deps to install automatically"
                + (f" ({mgr}: {hint})" if prefix else f" ({mgr})"))

    # 3) directories the runtime needs (all git-ignored)
    dirs = (WORKSPACE, MODEL_DIR, LLAMA_DIR, STATE_DIR, PID_DIR, LOG_DIR,
            ROOT / "config")
    if not ui.dry_run:
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    ui.step("directories",
            INFO if ui.dry_run else OK,
            "would create workspace, runtime, state, logs, config"
            if ui.dry_run else "workspace, runtime, state, logs, config")

    # 4) config bootstrap (never touches keys/secrets)
    rc = _bootstrap_config(ui)
    if rc:
        return rc

    # 5) build agent-core
    if args.build:
        _build_agent_core(ui)
    else:
        ui.step("agent-core", SKIP, "build skipped (pass --build)")

    # 6) local model runtime (opt-in: weights are large)
    if args.with_model:
        _install_model(ui, args.with_model)
    else:
        have_model, have_llama = _find_model(), _find_llama_server()
        ui.step("local model", SKIP,
                "pass --with-model to fetch llama-server + GGUF" if not
                (have_model and have_llama) else
                f"already present: {have_llama} + {have_model}")

    # 7) verify (compile + doctor), then record the manifest
    if not args.no_verify:
        _verify(ui)

    manifest = STATE_DIR / "install.json"
    if ui.dry_run:
        ui.step("manifest", INFO, f"would write {manifest}")
    else:
        write_json(manifest, {
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "platform": platform_label(),
            "python": ver,
            "root": str(ROOT),
            "agent_bin": str(_agent_bin()) if _agent_bin() else None,
            "llama_bin": str(_find_llama_server() or ""),
            "model": str(_find_model() or ""),
            "ports": {"model": PORT_MODEL, "agent": PORT_AGENT,
                      "hud": PORT_HUD},
        })
        ui.step("manifest", OK, str(manifest))

    failed = [r for r in ui.records if r["status"] == FAIL]
    ui.line("")
    if failed:
        ui.line(f"install finished with {len(failed)} problem(s); see above.")
        return 1
    if ui.dry_run:
        ui.line("dry run: nothing was changed.")
        return 0
    ui.line("install complete. Next:")
    ui.line("    python3 scripts/elysia_boot.py start     # model + agent + HUD")
    ui.line("    ./bin/elysia doctor                      # health check")
    return 0


def platform_label() -> str:
    bits = "64" if sys.maxsize > 2 ** 32 else "32"
    if IS_WIN:
        return f"Windows ({bits}-bit, {os.environ.get('PROCESSOR_ARCHITECTURE', '')})".strip()
    name = "macOS" if IS_MAC else ("Linux" if IS_LINUX else sys.platform)
    machine = os.uname().machine if hasattr(os, "uname") else ""
    return f"{name} ({machine})"


def _bootstrap_config(ui: Ui) -> int:
    """Write elysia/config.json if absent; normalize workspace paths.

    The shipped ``agent-core/agent_config.json`` uses a RELATIVE
    ``workspace_dir``, which the Go runtime resolves against the executable's
    directory — so the sandbox would silently land in ``agent-core/workspace``.
    Installing normalizes it to this checkout's absolute ``workspace/``.
    """
    cfg_path = ROOT / "elysia" / "config.json"
    if cfg_path.exists():
        ui.step("config: elysia/config.json", OK, "kept (existing file)")
    else:
        data = None
        try:
            sys.path.insert(0, str(ROOT))
            from elysia.core.config import default_config, to_dict
            data = to_dict(default_config())
        except Exception as e:  # noqa: BLE001 — fall back to a minimal config
            ui.step("config: elysia/config.json", INFO,
                    f"using minimal defaults ({type(e).__name__})")
        if data is None:
            data = {"workspace": {"root": str(WORKSPACE)},
                    "providers": [{"kind": "openai", "label": "local",
                                   "base_url": f"http://127.0.0.1:{PORT_MODEL}/v1",
                                   "api_key": "none",
                                   "model": os.environ.get("ELYSIA_MODEL",
                                                           "qwen2.5-coder:7b"),
                                   "capabilities": ["chat", "coding"],
                                   "concurrency": 2, "timeout_s": 900}]}
        if ui.dry_run:
            ui.step("config: elysia/config.json", INFO, "would be created")
        else:
            write_json(cfg_path, data)
            ui.step("config: elysia/config.json", OK, "created")

    agent_cfg = ROOT / "agent-core" / "agent_config.json"
    data = read_json(agent_cfg)
    if data is None:
        ui.step("config: agent-core/agent_config.json", SKIP,
                "not found (build agent-core first)")
        return 0
    current = str(data.get("workspace_dir") or "")
    if current and os.path.isabs(current):
        ui.step("config: agent-core/agent_config.json", OK,
                f"workspace_dir={current}")
        return 0
    if ui.dry_run:
        ui.step("config: agent-core/agent_config.json", INFO,
                f"would set workspace_dir -> {WORKSPACE}")
        return 0
    data["workspace_dir"] = str(WORKSPACE)
    write_json(agent_cfg, data)
    ui.step("config: agent-core/agent_config.json", OK,
            f"workspace_dir {current or '(empty)'} -> {WORKSPACE}")
    return 0


def _agent_bin() -> Path | None:
    name = "elysia-agent.exe" if IS_WIN else "elysia-agent"
    for candidate in (ROOT / "agent-core" / name, ROOT / "bin" / name):
        if candidate.is_file():
            return candidate
    return None


def _build_agent_core(ui: Ui) -> None:
    if not have("go"):
        ui.step("agent-core", SKIP,
                "Go toolchain not found — install Go, then re-run "
                "`install --build`")
        return
    out = _agent_bin() or (ROOT / "agent-core" /
                           ("elysia-agent.exe" if IS_WIN else "elysia-agent"))
    rc = ui.cmd(["go", "build", "-o", out.name, "./"],
                cwd=ROOT / "agent-core")
    ui.step("agent-core", OK if rc == 0 else FAIL,
            f"built {out.name}" if rc == 0 else f"go build failed (rc={rc})")


def _find_llama_server() -> str | None:
    env = os.environ.get("ELYSIA_LLAMA_BIN")
    if env and Path(env).is_file():
        return env
    name = "llama-server.exe" if IS_WIN else "llama-server"
    for candidate in (LLAMA_DIR / name, ROOT / "bin" / name):
        if candidate.is_file():
            return str(candidate)
    which = shutil.which("llama-server")
    return which


def _find_model() -> str | None:
    env = os.environ.get("ELYSIA_MODEL")
    if env and Path(env).is_file():
        return env
    if MODEL_DIR.is_dir():
        ggufs = sorted(MODEL_DIR.glob("*.gguf"))
        if ggufs:
            return str(ggufs[0])
    return None


def _install_model(ui: Ui, name: str) -> None:
    """Delegate to the repo's model fetcher when present; never guess URLs."""
    if name in ("1", "yes", "true", "default"):
        name = "qwen1.5b"
    existing = _find_model()
    if existing and _find_llama_server():
        ui.step("local model", OK, f"already installed: {existing}")
        return
    fetcher = RUNTIME_DIR / "restore-model.sh"
    if fetcher.is_file():
        ui.step("local model", INFO, f"{fetcher.name} {name}")
        rc = ui.cmd(["bash", fetcher, name])
        ui.step("local model", OK if rc == 0 else FAIL,
                f"{fetcher} rc={rc}")
        return
    # No fetcher in this checkout (runtime/ is git-ignored). Give real steps.
    ui.step("local model", SKIP,
            "no runtime/restore-model.sh in this checkout")
    ui.line("    fetch a runtime by hand:")
    ui.line(f"      - llama-server  -> {LLAMA_DIR}  "
            f"(https://github.com/ggml-org/llama.cpp/releases)")
    ui.line(f"      - a *.gguf      -> {MODEL_DIR}  (e.g. hf.co/Qwen/"
            f"Qwen2.5-Coder-1.5B-Instruct-GGUF)")
    ui.line("      - then re-run: scripts/elysia_boot.py start")
    ui.line("    …or point at an existing setup:")
    ui.line("      ELYSIA_LLAMA_BIN=/path/to/llama-server \\")
    ui.line("      ELYSIA_MODEL=/path/to/model.gguf scripts/elysia_boot.py start")


def _verify(ui: Ui) -> None:
    ui.line("")
    ui.line("verifying:")
    py_files = sorted((ROOT / "elysia").rglob("*.py"))
    rc = ui.cmd([PY, "-m", "py_compile", *[str(f) for f in py_files]]) \
        if py_files else 1
    ui.step("compile check", OK if rc == 0 else FAIL,
            f"{len(py_files)} files" if rc == 0 else "py_compile failed")
    rc = ui.cmd([PY, str(ROOT / "elysia" / "cli.py"), "doctor"])
    ui.step("doctor", OK if rc == 0 else FAIL, f"rc={rc}")


# --------------------------------------------------------------------------- #
# launch
# --------------------------------------------------------------------------- #
SERVICES = ("model", "agent", "hud")


# Children we started in THIS process (kept referenced so we own the handle
# and can reap them; a dropped Popen also emits a ResourceWarning).
_CHILDREN: dict = {}


def _pid_file(name: str) -> Path:
    return PID_DIR / f"{name}.pid"


def _reap(name: str, timeout: float = 3.0) -> None:
    """Reap a child we started (no-op when it was started elsewhere)."""
    proc = _CHILDREN.pop(name, None)
    if proc is None:
        return
    try:
        proc.wait(timeout=timeout)
    except Exception:  # noqa: BLE001 — reaping is best effort
        pass


def _read_pid(name: str):
    try:
        return int(_pid_file(name).read_text().strip())
    except (OSError, ValueError):
        return None


def _alive(pid) -> bool:
    """True only if the process is actually RUNNING (a zombie is not)."""
    if not pid:
        return False
    if IS_WIN:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    # os.kill(0) also succeeds for a terminated-but-unreaped child, so ask the
    # OS for the process's real state. No output / non-zero exit means the pid
    # is gone; `Z` means zombie (defunct) — neither is "running".
    try:
        out = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return True  # no ps available: fall back to the kill(0) answer
    stat = out.stdout.strip().upper()
    if out.returncode != 0 or not stat or stat.startswith("Z"):
        return False
    return True


def _spawn(ui: Ui, name: str, argv, cwd, env) -> bool:
    log = LOG_DIR / f"{name}.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pretty = " ".join(str(a) for a in argv)
    ui.line(f"    $ {pretty}   (log: {log})")
    if ui.dry_run:
        return True
    try:
        with open(log, "ab") as fh:
            kwargs = dict(cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                          stdout=fh, stderr=subprocess.STDOUT, close_fds=True)
            if IS_WIN:
                kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                           | subprocess.DETACHED_PROCESS)
            else:
                kwargs["start_new_session"] = True
            proc = subprocess.Popen([str(a) for a in argv], **kwargs)
    except OSError as e:  # noqa: BLE001
        ui.step(f"start {name}", FAIL, f"{type(e).__name__}: {e}")
        return False
    PID_DIR.mkdir(parents=True, exist_ok=True)
    _pid_file(name).write_text(str(proc.pid))
    _CHILDREN[name] = proc
    return True


def _launch(ui: Ui, args, key: str, display: str, argv, cwd, env,
            port: int, port_desc: str, started: list) -> None:
    """Start one service and report its REAL state (never assumed)."""
    if port_open(port):
        ui.step(display, OK, f"already up on {port_desc}")
        return
    if not _spawn(ui, key, argv, cwd, env):
        return
    if ui.dry_run:
        ui.step(display, INFO, f"would start ({port_desc})")
        return
    if wait_port(port, args.timeout):
        ui.step(display, OK, f"up on {port_desc}")
        started.append(display)
    else:
        ui.step(display, FAIL,
                f"did not answer within {args.timeout:.0f}s "
                f"(see {LOG_DIR / (key + '.log')})")


def cmd_start(ui: Ui, args) -> int:
    env = dict(os.environ)
    env["ELYSIA_WS"] = str(WORKSPACE)
    env.setdefault("PYTHONUNBUFFERED", "1")

    ui.line(f"starting Elysia ({platform_label()})")
    started = []

    # 1) model API (llama.cpp / Ollama-compatible endpoint)
    if not args.no_model:
        llama, model = _find_llama_server(), _find_model()
        if not llama or not model:
            ui.step("model", SKIP,
                    "no llama-server/model found — an external "
                    "OpenAI-compatible endpoint works too "
                    "(set one in elysia/config.json)")
        else:
            _launch(ui, args, "model", "model", [
                llama, "--host", "127.0.0.1", "--port", str(PORT_MODEL),
                "--model", model,
                "--alias", env.get("ELYSIA_MODEL_ALIAS", "qwen2.5-coder:7b"),
                "--ctx-size", env.get("ELYSIA_CTX", "8192"),
                "--parallel", env.get("ELYSIA_PARALLEL", "2"),
            ], ROOT, dict(env, ELYSIA_MODEL=model), PORT_MODEL,
                f":{PORT_MODEL}", started)

    # 2) agent-core (sandboxed local tool server)
    if not args.no_agent:
        agent = _agent_bin()
        if agent is None:
            ui.step("agent-core", SKIP,
                    "not built — run `install --build` (needs Go)")
        else:
            _launch(ui, args, "agent", "agent-core", [agent],
                    ROOT / "agent-core",
                    dict(env, ELYSIA_HTTP_ADDR=f":{PORT_AGENT}"), PORT_AGENT,
                    f":{PORT_AGENT}", started)

    # 3) HUD / orchestrator: canonical scheduler + in-process executor
    port = args.port or PORT_HUD
    if not args.no_hud:
        _launch(ui, args, "hud", "hud", [
            PY, ROOT / "orchestrator" / "server.py",
            "--host", args.host, "--port", str(port),
        ], ROOT, env, port, f"http://{args.host}:{port}", started)

    ui.line("")
    if ui.dry_run:
        ui.line("dry run: nothing was started.")
        return 0
    if started:
        ui.line("ready: " + ", ".join(started))
    ui.line(f"    HUD        http://{args.host}:{port}")
    ui.line("    board      python3 scripts/elysia_boot.py status")
    ui.line("    run a goal ./bin/elysia master run \"<goal>\"")
    ui.line("    stop       python3 scripts/elysia_boot.py stop")
    return 0 if started or port_open(port) else 1


def cmd_stop(ui: Ui, args) -> int:
    ui.line("stopping Elysia")
    stopped = []
    for name in SERVICES:
        pid = _read_pid(name)
        if pid is None:
            ui.step(name, SKIP, "no pid file")
            continue
        if not _alive(pid):
            ui.step(name, SKIP, f"pid {pid} is gone")
            _pid_file(name).unlink(missing_ok=True)
            continue
        if ui.dry_run:
            ui.step(name, INFO, f"would stop pid {pid}")
            continue
        try:
            if IS_WIN:
                subprocess.call(["taskkill", "/PID", str(pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
            else:
                os.kill(pid, signal.SIGTERM)
                for _ in range(40):
                    if not _alive(pid):
                        break
                    time.sleep(0.25)
                if _alive(pid):
                    os.kill(pid, signal.SIGKILL)
        except OSError as e:  # noqa: BLE001
            ui.step(name, FAIL, f"{type(e).__name__}: {e}")
            continue
        _pid_file(name).unlink(missing_ok=True)
        _reap(name)
        if _alive(pid):
            # never claim a stop we did not achieve
            ui.step(name, FAIL,
                    f"pid {pid} is still running (stop it manually)")
        else:
            ui.step(name, OK, f"stopped pid {pid}")
            stopped.append(name)
    ui.line("stopped: " + (", ".join(stopped) if stopped else "nothing"))
    return 0


def cmd_status(ui: Ui, args) -> int:
    manifest = read_json(STATE_DIR / "install.json") or {}
    ports = {"model": PORT_MODEL, "agent": PORT_AGENT, "hud": PORT_HUD}
    rows = []
    for name in SERVICES:
        pid = _read_pid(name)
        up = port_open(ports[name])
        rows.append({"service": name, "port": ports[name], "port_open": up,
                     "pid": pid, "pid_alive": _alive(pid)})
    if ui.as_json:
        print(json.dumps({"platform": platform_label(),
                          "root": str(ROOT),
                          "installed_at": manifest.get("installed_at"),
                          "services": rows}, indent=1))
        return 0
    ui.line(f"Elysia status — {platform_label()}")
    ui.line(f"repository : {ROOT}")
    if manifest.get("installed_at"):
        ui.line(f"installed  : {manifest['installed_at']}")
    ui.line("")
    for r in rows:
        state = "UP" if r["port_open"] else "down"
        pid = r["pid"] if r["pid_alive"] else "-"
        ui.line(f"  {r['service']:<7} :{r['port']:<6} {state:<5} pid={pid}")
    # extras that make the status actionable
    agent = _agent_bin()
    ui.line(f"  agent bin  : {agent or 'not built'}")
    ui.line(f"  llama bin  : {_find_llama_server() or 'not found'}")
    ui.line(f"  model      : {_find_model() or 'not found'}")
    if port_open(PORT_HUD):
        try:
            import urllib.request
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{PORT_HUD}/api/scheduler",
                    timeout=3) as r:
                data = json.loads(r.read().decode())
            counts = data.get("counts") or {}
            ex = data.get("executor") or {}
            ui.line("")
            ui.line(f"  board      : {counts.get('total', 0)} tasks, "
                    f"{counts.get('ready', 0)} ready, "
                    f"{counts.get('completed', 0)} completed, "
                    f"{counts.get('failed', 0)} failed")
            ui.line(f"  executor   : running={ex.get('running')} "
                    f"inflight={len(ex.get('inflight') or [])}")
        except Exception:  # noqa: BLE001 — status must never fail
            pass
    ui.line("")
    ui.line("  control plane: ./bin/elysia master status")
    return 0


def cmd_doctor(ui: Ui, args) -> int:
    """Reuse the repo's doctor, then add the launcher's own view."""
    rc = ui.cmd([PY, str(ROOT / "elysia" / "cli.py"), "doctor"])
    ui.line("")
    ui.line("ports:")
    for name, port in (("model", PORT_MODEL), ("agent-core", PORT_AGENT),
                       ("hud", PORT_HUD)):
        ui.line(f"  {name:<11} :{port:<6} "
                f"{'UP' if port_open(port) else 'down'}")
    return rc


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="elysia_boot",
        description="Elysia universal installer + launcher "
                    "(Linux, macOS, Windows)")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true",
                        help="print every action without performing it")
    common.add_argument("--yes", "-y", action="store_true",
                        help="assume yes for prompts")
    common.add_argument("--json", action="store_true",
                        help="machine-readable output where applicable")
    sub = p.add_subparsers(dest="cmd")

    ins = sub.add_parser("install", parents=[common],
                         help="check prerequisites, create dirs/config, "
                              "build agent-core")
    ins.add_argument("--deps", action="store_true",
                     help="install missing prerequisites via the detected "
                          "package manager (winget/choco/scoop, brew, "
                          "apt/dnf/pacman/zypper/apk)")
    ins.add_argument("--build", action="store_true",
                     help="build agent-core with Go")
    ins.add_argument("--with-model", nargs="?", const="qwen1.5b",
                     default=None, metavar="NAME",
                     help="fetch the local llama.cpp runtime + GGUF model")
    ins.add_argument("--no-verify", action="store_true",
                     help="skip the compile check and doctor run")
    ins.set_defaults(fn=cmd_install)

    st = sub.add_parser("start", parents=[common],
                        help="launch the model API, agent-core and HUD")
    st.add_argument("--host", default="127.0.0.1",
                    help="HUD bind address (default 127.0.0.1; 0.0.0.0 "
                         "exposes it on your network)")
    st.add_argument("--port", type=int, default=None,
                    help=f"HUD port (default {PORT_HUD})")
    st.add_argument("--timeout", type=float, default=45.0,
                    help="seconds to wait for each service to answer")
    st.add_argument("--no-model", action="store_true",
                    help="do not start llama-server")
    st.add_argument("--no-agent", action="store_true",
                    help="do not start agent-core")
    st.add_argument("--no-hud", action="store_true",
                    help="do not start the HUD/orchestrator server")
    st.set_defaults(fn=cmd_start)

    sub.add_parser("stop", parents=[common],
                   help="stop the services started by `start`").set_defaults(
        fn=cmd_stop)
    rs = sub.add_parser("restart", parents=[common],
                        help="stop, then start")
    rs.add_argument("--host", default="127.0.0.1")
    rs.add_argument("--port", type=int, default=None)
    rs.add_argument("--timeout", type=float, default=45.0)
    rs.add_argument("--no-model", action="store_true")
    rs.add_argument("--no-agent", action="store_true")
    rs.add_argument("--no-hud", action="store_true")

    def _restart(ui, a):
        rc = cmd_stop(ui, a)
        return rc or cmd_start(ui, a)
    rs.set_defaults(fn=_restart)

    sub.add_parser("status", parents=[common],
                   help="show service/port/board state").set_defaults(
        fn=cmd_status)
    sub.add_parser("doctor", parents=[common],
                   help="repository health + ports").set_defaults(fn=cmd_doctor)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "cmd", None):
        build_parser().print_help()
        return 0
    ui = Ui(dry_run=args.dry_run, yes=args.yes,
            quiet=getattr(args, "json", False), as_json=args.json)
    try:
        return args.fn(ui, args)
    except KeyboardInterrupt:
        ui.line("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
