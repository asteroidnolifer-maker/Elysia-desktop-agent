#!/usr/bin/env python3
"""AirLLM helper — COMPATIBILITY WRAPPER (no longer launches models itself).

Historically this module picked a quantised model by available RAM and started
``llama-server`` with ``subprocess.Popen``. That made it a second, uncontrolled
model launcher: it ignored ProviderManager, the resource ledger and the
configured local-model concurrency, and it could start a model while a build was
already saturating a 2-core CPU.

It now delegates to the canonical launcher,
:class:`elysia.core.modelserver.ModelServer`, which:

  - keeps at most ONE managed model process (pid-tracked),
  - derives ``--parallel`` from ``resources.local_llm_concurrency`` (1 by
    default) and the thread count from the real core count,
  - refuses to load a model when free RAM is below the configured floor,
  - reports a missing binary/model as missing instead of pretending to start.

The model catalog and RAM-based selection stay here because callers use them
for display; only *process control* moved.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elysia.core.modelserver import ModelServer, port_from_url  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.environ.get("ELYSIA_RUNTIME",
                             os.path.join(REPO_ROOT, "runtime"))


def model_path(name):
    return os.environ.get(
        "ELYSIA_MODEL_DIR",
        os.path.join(RUNTIME_DIR, "models",
                     {"qwen1.5b": "qwen15b-q4.gguf",
                      "qwen3b": "qwen3b-q4.gguf",
                      "qwen7b": "qwen7b-q4.gguf",
                      "deepseek1.5b": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
                      "deepseek7b": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf"}[name]))


def llama_bin():
    return os.environ.get("ELYSIA_LLAMA_BIN",
                          os.path.join(RUNTIME_DIR, "llama", "llama-server"))


MODELS = {
    "qwen1.5b": {"path": lambda: model_path("qwen1.5b"), "vram": 1200, "layers": 24},
    "qwen3b": {"path": lambda: model_path("qwen3b"), "vram": 2500, "layers": 36},
    "qwen7b": {"path": lambda: model_path("qwen7b"), "vram": 4500, "layers": 40},
    "deepseek1.5b": {"path": lambda: model_path("deepseek1.5b"), "vram": 1200, "layers": 24},
    "deepseek7b": {"path": lambda: model_path("deepseek7b"), "vram": 4500, "layers": 40},
}


def get_mem():
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        total = int(lines[0].split()[1]) // 1024
        avail = int(lines[2].split()[1]) // 1024
        return {"total_mb": total, "avail_mb": avail, "used_mb": total - avail}
    except (OSError, IndexError, ValueError):  # non-Linux fallback
        return {"total_mb": 0, "avail_mb": 0, "used_mb": 0}


def select_model(task="general"):
    mem = get_mem()
    usable = mem["avail_mb"] - 1500
    for name, cfg in sorted(MODELS.items(), key=lambda x: x[1]["vram"], reverse=True):
        if cfg["vram"] <= usable:
            return name, cfg
    return "qwen1.5b", MODELS["qwen1.5b"]


def _server(name=None, port=11434):
    """The canonical ModelServer for a catalog entry (or the configured model)."""
    model_file = ""
    if name:
        cfg = MODELS.get(name)
        if cfg:
            model_file = cfg["path"]()
    return ModelServer(binary=llama_bin(), model_path=model_file, port=port,
                       runtime_dir=RUNTIME_DIR)


def plan(name=None, port=11434):
    """What a start would do — no side effects, no guessing."""
    return _server(name, port).plan()


def start_model(name=None, port=11434, wait_s=8.0):
    """Start the local model through the canonical launcher.

    Returns True only when the server is actually accepting connections.
    """
    out = _server(name, port).start(wait_s=wait_s)
    print(("[+] " if out["ok"] else "[-] ") + str(out.get("detail", "")))
    return bool(out["ok"])


def stop_model(port=11434):
    out = ModelServer(port=port, runtime_dir=RUNTIME_DIR).stop()
    return bool(out["ok"])


def is_model_running(port=11434):
    return ModelServer(port=port, runtime_dir=RUNTIME_DIR).port_open()


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    srv = _server(None, port_from_url(
        os.environ.get("ELYSIA_LOCAL_URL", ""), 11434))
    print({"status": srv.status, "plan": srv.plan, "stop": srv.stop}.get(
        action, lambda: {"ok": False, "detail": f"unknown action {action}"})())
