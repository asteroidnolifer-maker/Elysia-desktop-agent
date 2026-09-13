#!/usr/bin/env python3
"""Video generation orchestrator - commands multiple providers to create videos."""
import requests
import json
import os
import subprocess
import time
from datetime import datetime

WORKSPACE = "/data/elysia/workspace/tools"
VIDEOS_DIR = "/data/elysia/workspace/videos"
os.makedirs(VIDEOS_DIR, exist_ok=True)


def generate_script(topic, style="educational", duration_seconds=60):
    """Generate video script using local LLM."""
    prompt = f"""Create a {style} YouTube Shorts script about "{topic}".
Duration: {duration_seconds} seconds
Format: JSON with these fields:
- title: catchy title
- hook: attention-grabbing first 3 seconds
- scenes: array of scene objects with (text, duration_seconds, visual_description)
- cta: call to action
- hashtags: array of 5 relevant hashtags
Make it engaging and viral-worthy. Output ONLY valid JSON."""
    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": "qwen3b", "prompt": prompt, "stream": False, "options": {"num_predict": 1024}},
            timeout=120
        )
        response = r.json().get("response", "")
        json_start = response.find("{")
        json_end = response.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            script = json.loads(response[json_start:json_end])
        else:
            script = {"title": topic, "hook": f"Check out {topic}!", "scenes": [{"text": response[:200], "duration_seconds": duration_seconds}], "hashtags": [topic.replace(" ", "")]}
        return {"status": "ok", "script": script}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def generate_voiceover(text, voice="default"):
    """Generate voiceover (uses espeak/piper if available, or returns text for TTS service)."""
    engines = []
    try:
        subprocess.run(["which", "espeak"], capture_output=True, check=True)
        engines.append("espeak")
    except:
        pass
    try:
        subprocess.run(["which", "piper"], capture_output=True, check=True)
        engines.append("piper")
    except:
        pass
    return {
        "text": text,
        "engines_available": engines,
        "recommended": engines[0] if engines else "external_tts",
        "command": f'espeak "{text}" -w output.wav' if "espeak" in engines else None
    }


def compile_video(scenes, audio_file=None, output_path=None):
    """Compile scenes into video using ffmpeg."""
    if output_path is None:
        output_path = os.path.join(VIDEOS_DIR, f"video_{int(time.time())}.mp4")
    ffmpeg_check = subprocess.run(["which", "ffmpeg"], capture_output=True)
    if ffmpeg_check.returncode != 0:
        return {"status": "failed", "error": "ffmpeg not installed"}
    slide_files = []
    for i, scene in enumerate(scenes):
        text = scene.get("text", f"Scene {i+1}")
        duration = scene.get("duration_seconds", 5)
        slide_path = f"/tmp/slide_{i}.png"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i",
                f"color=c=black:s=1080x1920:d={duration}",
                "-vf", f"drawtext=text='{text[:50]}':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2",
                "-frames:v", "1", slide_path
            ], capture_output=True, check=True)
            slide_files.append(slide_path)
        except:
            pass
    if slide_files:
        concat_file = "/tmp/concat.txt"
        with open(concat_file, "w") as f:
            for sf in slide_files:
                f.write(f"file '{sf}'\n")
        try:
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path
            ], capture_output=True, check=True)
            return {"status": "ok", "output": output_path, "scenes": len(scenes)}
        except Exception as e:
            return {"status": "failed", "error": str(e)}
    return {"status": "failed", "error": "No slides generated"}


def create_video_pipeline(topic, channel_name="default"):
    """Full pipeline: script -> voiceover -> video."""
    print(f"Creating video for: {topic}")
    script_result = generate_script(topic)
    if script_result["status"] != "ok":
        return script_result
    script = script_result["script"]
    scenes = script.get("scenes", [{"text": topic, "duration_seconds": 15}])
    audio = generate_voiceover(script.get("hook", topic))
    video = compile_video(scenes, output_path=os.path.join(VIDEOS_DIR, f"{channel_name}_{int(time.time())}.mp4"))
    return {
        "topic": topic,
        "channel": channel_name,
        "script": script,
        "audio": audio,
        "video": video,
        "hashtags": script.get("hashtags", []),
        "status": "completed" if video.get("status") == "ok" else "partial"
    }


if __name__ == "__main__":
    print("=== Video Generation Pipeline Test ===")
    result = create_video_pipeline("5 AI tools that will make you money in 2026", "test_channel")
    print(f"Status: {result['status']}")
    print(f"Script title: {result.get('script', {}).get('title', 'N/A')}")
    print(f"Scenes: {len(result.get('script', {}).get('scenes', []))}")
    print(f"Hashtags: {result.get('hashtags', [])}")
    print(f"Video: {result.get('video', {})}")
    output = os.path.join(WORKSPACE, "video_pipeline_result.json")
    with open(output, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"[+] Saved to {output}")
