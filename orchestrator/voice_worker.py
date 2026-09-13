#!/usr/bin/env python3
"""
Elysia voice_worker.py — process voice commands via Whisper STT (agent6).

Listens for the hotword "Elysia", records audio, transcribes it using
agent6's Whisper model, and routes recognized commands to the taskboard:
add, claim, done, fail.

Usage: voice_worker.py <workerID> <workspaceDir>
"""
import json
import os
import re
import subprocess
import sys
import time
import signal
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain  # noqa: E402

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
TASKBOARD = os.path.join(ORCH_DIR, "taskboard.py")
REPO_ROOT = os.path.dirname(ORCH_DIR)
WS_DIR_FALLBACK = os.path.join(REPO_ROOT, "workspace")

# Hotword configuration
HOTWORD_CONF = os.path.join(ORCH_DIR, "voice_hotword.conf")
DEFAULT_HOTWORD = "Elysia"
hotword = DEFAULT_HOTWORD

# Load hotword config
try:
    with open(HOTWORD_CONF, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("hotword="):
                hotword = line.split("=", 1)[1].strip()
                break
except OSError:
    pass

# Agent6 (Whisper STT) configuration
AGENT_CORE_URL = "http://127.0.0.1:8085"


def agent6_stt(audio_wav_path):
    """Send audio to agent6 for Whisper transcription."""
    try:
        with open(audio_wav_path, "rb") as f:
            audio_bytes = f.read()
        # agent-core uses OpenAI-compatible API; send audio as base64-ish
        # embedded in JSON. Whisper tiny model is loaded in agent6.
        payload = json.dumps({
            "input": audio_bytes.hex(),
            "model": "whisper-tiny",
        }).encode()
        req = urllib.request.Request(
            f"{AGENT_CORE_URL}/v1/audio/transcriptions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read().decode())
        text = result.get("text", "") if isinstance(result, dict) else ""
        return text.strip()
    except Exception as e:
        print(f"[voice] agent6 STT error: {e}", flush=True)
        return ""


def add_task_to_board(title, description, ws_dir):
    """Add a new task to the taskboard."""
    try:
        result = subprocess.run(
            ["python3", TASKBOARD, "add", title, description or title],
            capture_output=True, text=True, timeout=30,
            cwd=ws_dir,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[voice] add_task error: {e}", flush=True)
        return False


def claim_task(ws_dir, worker):
    """Claim the highest priority open task."""
    try:
        result = subprocess.run(
            ["python3", TASKBOARD, "claim", worker],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            task = json.loads(result.stdout.strip())
            if task and task.get("id"):
                return task["id"]
    except Exception as e:
        print(f"[voice] claim error: {e}", flush=True)
    return None


def finish_task(ws_dir, task_id, worker, result_text):
    """Mark a task as done."""
    try:
        result = subprocess.run(
            ["python3", TASKBOARD, "finish", str(task_id), "done", worker, result_text or "voice-completed"],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[voice] finish error: {e}", flush=True)
        return False


def process_command(command, ws_dir, worker):
    """Parse and route a voice command to the taskboard."""
    cmd = command.strip().lower()
    print(f"[voice] recognized: '{cmd}'", flush=True)

    # Task addition: "Elysia add task: <description>"
    m = re.match(r"add task:\s*(.+)", cmd)
    if m:
        desc = m.group(1).strip()
        if add_task_to_board(f"Voice-added: {desc}", desc, ws_dir):
            print("[voice] task added to board", flush=True)
        else:
            print("[voice] failed to add task", flush=True)
        return

    # Claim a task
    if re.match(r"claim", cmd):
        tid = claim_task(ws_dir, worker)
        if tid:
            print(f"[voice] claimed task #{tid}", flush=True)
        else:
            print("[voice] no tasks available to claim", flush=True)
        return

    # Mark task done
    m = re.match(r"task\s+(\d+)\s+done", cmd)
    if m:
        tid = int(m.group(1))
        if finish_task(ws_dir, tid, worker, f"completed via voice: {cmd}"):
            print(f"[voice] task #{tid} marked done", flush=True)
        else:
            print(f"[voice] failed to finish task #{tid}", flush=True)
        return

    # Mark task failed
    m = re.match(r"task\s+(\d+)\s+fail", cmd)
    if m:
        tid = int(m.group(1))
        if finish_task(ws_dir, tid, worker, f"failed via voice: {cmd}"):
            print(f"[voice] task #{tid} marked failed", flush=True)
        else:
            print(f"[voice] failed to mark task #{tid} as failed", flush=True)
        return

    # Status/board query
    if cmd in ("what's open", "status", "list tasks"):
        try:
            result = subprocess.run(
                ["python3", TASKBOARD, "list"],
                capture_output=True, text=True, timeout=30,
            )
            print(f"[voice] board:\n{result.stdout}", flush=True)
        except Exception as e:
            print(f"[voice] status error: {e}", flush=True)
        return

    # Unknown command
    print(f"[voice] unknown command: '{cmd}'", flush=True)


def main():
    worker = sys.argv[1] if len(sys.argv) > 1 else "voice0"
    ws_dir = sys.argv[2] if len(sys.argv) > 2 else WS_DIR_FALLBACK

    print(f"[voice] starting worker {worker}, ws={ws_dir}", flush=True)
    print(f"[voice] hotword: '{hotword}'", flush=True)

    # Verify taskboard access
    try:
        result = subprocess.run(
            ["python3", TASKBOARD, "list", "open"],
            capture_output=True, text=True, timeout=10,
        )
        print(f"[voice] board check: {result.stdout.strip()}", flush=True)
    except Exception as e:
        print(f"[voice] board check failed: {e}", flush=True)

    print(f"[voice] listening for hotword '{hotword}'...", flush=True)
    print("[voice] say 'Elysia add task: <description>' or 'claim' or 'task X done'", flush=True)

    running = True

    def handle_signal(signum, frame):
        nonlocal running
        running = False
        print("[voice] shutting down...", flush=True)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while running:
        # Record audio (3 seconds)
        wav_path = f"/tmp/elysia_voice_{int(time.time())}.wav"

        try:
            record_result = subprocess.run(
                [
                    "arecord",
                    "-f", "S16_LE",
                    "-c", "1",
                    "-r", "16000",
                    "-d", "3",
                    wav_path,
                ],
                capture_output=True,
                timeout=5,
            )
            if record_result.returncode == 0 and os.path.exists(wav_path):
                # Transcribe via agent6 Whisper
                text = agent6_stt(wav_path)
                # Clean up
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

                if text:
                    print(f"[voice] transcribed: '{text}'", flush=True)
                    # Check for hotword
                    if hotword.lower() in text.lower():
                        cmd_text = text.lower().replace(hotword.lower(), "").strip()
                        if cmd_text:
                            process_command(cmd_text, ws_dir, worker)
                    elif cmd_text := text.strip():
                        process_command(cmd_text, ws_dir, worker)
                else:
                    print("[voice] no speech detected", flush=True)
            else:
                print("[voice] recording failed", flush=True)
        except Exception as e:
            print(f"[voice] recording/STT error: {e}", flush=True)

        # Throttle: wait before next listening cycle
        for _ in range(30):  # ~3 seconds at 100ms iterations
            if not running:
                break
            time.sleep(0.1)

    print("[voice] worker stopped", flush=True)


if __name__ == "__main__":
    main()