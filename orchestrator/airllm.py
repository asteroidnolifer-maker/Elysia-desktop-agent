#!/usr/bin/env python3
"""AirLLM Integration - Memory-efficient LLM inference for Elysia."""
import os, json, time, subprocess
from pathlib import Path

MODELS = {
    "qwen1.5b": {"path": "/data/elysia/runtime/models/qwen15b-q4.gguf", "vram": 1200, "layers": 24},
    "qwen3b": {"path": "/data/elysia/runtime/models/qwen3b-q4.gguf", "vram": 2500, "layers": 36},
    "qwen7b": {"path": "/data/elysia/runtime/models/qwen7b-q4.gguf", "vram": 4500, "layers": 40},
    "deepseek1.5b": {"path": "/data/elysia/runtime/models/DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf", "vram": 1200, "layers": 24},
    "deepseek7b": {"path": "/data/elysia/runtime/models/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf", "vram": 4500, "layers": 40},
}

def get_mem():
    with open("/proc/meminfo") as f:
        lines = f.readlines()
    total = int(lines[0].split()[1]) // 1024
    avail = int(lines[2].split()[1]) // 1024
    return {"total_mb": total, "avail_mb": avail, "used_mb": total - avail}

def select_model(task="general"):
    mem = get_mem()
    usable = mem["avail_mb"] - 1500
    for name, cfg in sorted(MODELS.items(), key=lambda x: x[1]["vram"], reverse=True):
        if cfg["vram"] <= usable:
            return name, cfg
    return "qwen1.5b", MODELS["qwen1.5b"]

def start_model(name=None, port=11434):
    if not name:
        name, cfg = select_model()
    else:
        cfg = MODELS.get(name)
    if not cfg or not Path(cfg["path"]).exists():
        print(f"[-] Model not found: {name}")
        return False
    cmd = ["/data/elysia/runtime/llama/llama-server",
           "--host", "127.0.0.1", "--port", str(port),
           "--model", cfg["path"], "--ctx-size", "8192",
           "--parallel", "2", "--threads", "4", "--mlock"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(3)
    print(f"[+] Started {name} on port {port}")
    return True

def is_model_running(port=11434):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(2)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except:
        return False

def ensure_model_running(port=11434):
    if is_model_running(port):
        return True
    print("[!] Model not running, starting...")
    return start_model(port=port)

def keepalive_loop(interval=30):
    import signal, sys
    running = True
    def sig_handler(sig, frame):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    print("[+] AirLLM keepalive started - models always running")
    while running:
        if not is_model_running():
            print("[!] Model died, restarting...")
            start_model()
        time.sleep(interval)

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        mem = get_mem()
        name, cfg = select_model()
        running = is_model_running()
        print(f"Memory: {mem['avail_mb']}MB available")
        print(f"Recommended: {name} ({cfg['vram']}MB)")
        print(f"Running: {running}")
    elif cmd == "start":
        start_model(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "keepalive":
        keepalive_loop()
    elif cmd == "models":
        for n, c in MODELS.items():
            print(f"  {n}: {c['vram']}MB, {c['layers']} layers")
