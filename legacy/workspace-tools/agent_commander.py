#!/usr/bin/env python3
"""Agent commander - commands multiple AI agents from different providers."""
import requests
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKSPACE = "/data/elysia/workspace/tools"
AGENTS_DIR = "/data/elysia/workspace/agents"
os.makedirs(AGENTS_DIR, exist_ok=True)

PROVIDERS = {
    "local": {"endpoint": "http://localhost:11434", "model": "qwen3b"},
    "ollama": {"endpoint": "http://localhost:11434", "model": "llama3"},
}


def call_local_llm(prompt, model="qwen3b", max_tokens=2048):
    """Call local llama-server or Ollama."""
    try:
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": max_tokens}},
            timeout=120
        )
        return {"provider": "local", "model": model, "response": r.json().get("response", ""), "status": "ok"}
    except Exception as e:
        return {"provider": "local", "model": model, "error": str(e), "status": "failed"}


def call_openai(prompt, api_key=None, model="gpt-3.5-turbo"):
    """Call OpenAI API."""
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return {"provider": "openai", "error": "No API key set", "status": "no_key"}
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 2048},
            timeout=60
        )
        data = r.json()
        return {"provider": "openai", "model": model, "response": data["choices"][0]["message"]["content"], "status": "ok"}
    except Exception as e:
        return {"provider": "openai", "model": model, "error": str(e), "status": "failed"}


def call_anthropic(prompt, api_key=None, model="claude-3-haiku-20240307"):
    """Call Anthropic API."""
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"provider": "anthropic", "error": "No API key set", "status": "no_key"}
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 2048, "messages": [{"role": "user", "content": prompt}]},
            timeout=60
        )
        data = r.json()
        return {"provider": "anthropic", "model": model, "response": data["content"][0]["text"], "status": "ok"}
    except Exception as e:
        return {"provider": "anthropic", "model": model, "error": str(e), "status": "failed"}


def command_agents(prompt, providers=None, parallel=True):
    """Send prompt to multiple AI agents and collect responses."""
    if providers is None:
        providers = ["local"]
    calls = {
        "local": lambda: call_local_llm(prompt),
        "openai": lambda: call_openai(prompt),
        "anthropic": lambda: call_anthropic(prompt),
    }
    results = {}
    if parallel:
        with ThreadPoolExecutor(max_workers=len(providers)) as executor:
            futures = {executor.submit(calls[p]): p for p in providers if p in calls}
            for future in as_completed(futures):
                provider = futures[future]
                results[provider] = future.result()
    else:
        for p in providers:
            if p in calls:
                results[p] = calls[p]()
    return {"prompt": prompt, "providers": providers, "responses": results}


def delegate_task(task_description, agent_roles=None):
    """Delegate a complex task to specialized agents."""
    if agent_roles is None:
        agent_roles = ["researcher", "coder", "reviewer"]
    prompts = {
        "researcher": f"You are a research agent. Research and provide detailed findings for: {task_description}",
        "coder": f"You are a coding agent. Write code to solve: {task_description}",
        "reviewer": f"You are a code reviewer. Review and suggest improvements for work on: {task_description}",
        "planner": f"You are a planning agent. Create a detailed step-by-step plan for: {task_description}",
        "writer": f"You are a writing agent. Write content about: {task_description}",
    }
    results = {}
    for role in agent_roles:
        prompt = prompts.get(role, f"You are a {role} agent. Handle: {task_description}")
        results[role] = call_local_llm(prompt)
    return {"task": task_description, "delegated_to": agent_roles, "results": results}


if __name__ == "__main__":
    print("=== Agent Commander Test ===")
    print("\n1. Testing local LLM:")
    result = call_local_llm("What are the top 3 trending YouTube Shorts topics right now? Be brief.")
    print(f"  Status: {result['status']}")
    if result['status'] == 'ok':
        print(f"  Response: {result['response'][:200]}")
    print("\n2. Delegating task to multiple agents:")
    delegation = delegate_task("Find 5 viral YouTube Shorts ideas for a tech channel", ["researcher", "planner"])
    for role, res in delegation["results"].items():
        print(f"  {role}: {res.get('response', res.get('error', 'unknown'))[:150]}")
    output = os.path.join(WORKSPACE, "agent_commander_result.json")
    with open(output, "w") as f:
        json.dump({"local_test": result, "delegation": delegation}, f, indent=2, default=str)
    print(f"\n[+] Saved to {output}")
