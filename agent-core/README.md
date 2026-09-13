Agent-Core (Lightweight offline agent)
====================================

This directory contains a minimal Go-based "agent-core" designed to run on low-resource devices (custom Android ROMs, embedded Linux) and provide an HTTP JSON RPC to perform offline model inference using locally installed inference binaries (e.g., llama.cpp based binary).

Key features
- Minimal HTTP server (port 8085) providing `/status`, `/models`, `/task` endpoints.
- ModelManager to register local model files and invoke an external inference binary.
- ThermalManager reads `/sys/class/thermal` sensors to detect high temperature and throttle tasks.
- TaskQueue schedules tasks respecting thermal constraints and runs inference via ModelManager.

Important notes
- This agent does NOT ship model inference binaries; you must provide a compatible `inference` binary on the device (named `inference` in the same folder or update ModelManager to include full path).
- Running heavy inference on phones requires sufficient RAM and CPU. The task scheduling and thermal throttling aim to reduce overheating.
- For fully offline privacy-first setups, supply local GGUF/LLama models and an appropriate inference binary compiled for the target device.

Quickstart (build on a Linux host for Android aarch64)

1. Install Go 1.20+ on build host.
2. cd agent-core
3. GOOS=linux GOARCH=arm64 go build -o bin/agent-core ./
4. Copy `bin/agent-core` to your device (e.g., /data/local/tmp/) and ensure execute permission.
5. Place a compatible `inference` binary alongside the agent and your model files, and register models via the HTTP API or config file (future).
6. Start the binary: `./agent-core` (may require root to access sysfs sensors or to set CPU governors).

Android integration (custom ROM)
- Place the binary in a directory included in init scripts or create a simple init service to start it on boot.
- Ensure SELinux policies allow execution (or run in permissive mode during testing).
- Provide a wrapper script or systemd-like service to supervise the agent binary.
