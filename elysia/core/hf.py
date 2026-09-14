"""HuggingFace integration for Elysia: curated models + datasets + inference.

Elysia stays offline-first, so "HF integration" is three concrete things:

  1. a curated catalog of top open models with local-GGUF candidates that
     drop into the existing runtime (`orchestrator/airllm.py` /
     `runtime/restore-model.sh`) so `airllm.py start <name>` works unchanged,
  2. a curated dataset catalog (the classic small sets used to fine-tune or
     evaluate coding/reasoning agents) with direct Hub URLs,
  3. an optional HF Inference provider preset: set ``HF_TOKEN`` and Elysia
     can route chat to ``https://router.huggingface.co/v1``
     (OpenAI-compatible endpoint) like any other cloud provider.

Nothing downloads automatically; every fetch is an explicit operator command
(``elysia hf model <id>`` / direct URLs) so the machine's disk and the user's
bandwidth stay under their control. Keys come from the environment only.
"""
from __future__ import annotations

import json
import os
import urllib.request

from .config import ProviderConfig

HF_BASE = "https://huggingface.co"
HF_INFER_URL = "https://router.huggingface.co/v1"

# ---------------------------------------------------------------------------
# Curated models — top open models, local GGUF candidates where they exist.
# size_mb is the GGUF Q4_K_M ballpark (what restore-model.sh-style fetches use)
# ---------------------------------------------------------------------------

MODELS: dict[str, dict] = {
    "qwen2.5-coder-7b": {
        "repo": "Qwen/Qwen2.5-Coder-7B-Instruct",
        "gguf": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "file_hint": "qwen2.5-coder-7b-instruct-q4_k_m*.gguf",
        "size_mb": 4700,
        "capabilities": ["chat", "coding", "reasoning"],
        "note": "best local coding model in this size class",
    },
    "qwen2.5-coder-3b": {
        "repo": "Qwen/Qwen2.5-Coder-3B-Instruct",
        "gguf": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
        "file_hint": "qwen2.5-coder-3b-instruct-q4_k_m*.gguf",
        "size_mb": 2000,
        "capabilities": ["chat", "coding"],
        "note": "fits 8GB machines",
    },
    "qwen2.5-1.5b": {
        "repo": "Qwen/Qwen2.5-1.5B-Instruct",
        "gguf": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "file_hint": "qwen2.5-1.5b-instruct-q4_k_m*.gguf",
        "size_mb": 1000,
        "capabilities": ["chat"],
        "note": "the default Elysia local model tier",
    },
    "deepseek-coder-1.3b": {
        "repo": "deepseek-ai/deepseek-coder-1.3b-instruct",
        "gguf": "TheBloke/deepseek-coder-1.3b-instruct-GGUF",
        "file_hint": "deepseek-coder-1.3b-instruct.q4_k_m*.gguf",
        "size_mb": 900,
        "capabilities": ["chat", "coding"],
        "note": "tiny coder, fast on CPU",
    },
    "deepseek-r1-distill-7b": {
        "repo": "deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
        "gguf": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "file_hint": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M*.gguf",
        "size_mb": 4700,
        "capabilities": ["chat", "reasoning"],
        "note": "reasoning distill; matches airllm.py deepseek7b slot",
    },
    "llama-3.2-3b": {
        "repo": "meta-llama/Llama-3.2-3B-Instruct",
        "gguf": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "file_hint": "Llama-3.2-3B-Instruct-Q4_K_M*.gguf",
        "size_mb": 2000,
        "capabilities": ["chat"],
        "note": "general assistant tier",
    },
    "phi-4-mini": {
        "repo": "microsoft/Phi-4-mini-instruct",
        "gguf": "microsoft/Phi-4-mini-instruct-gguf",
        "file_hint": "*q4_k_m*.gguf",
        "size_mb": 2400,
        "capabilities": ["chat", "reasoning"],
        "note": "strong small reasoning model",
    },
    "granite-3.1-8b": {
        "repo": "ibm-granite/granite-3.1-8b-instruct",
        "gguf": "ibm-granite/granite-3.1-8b-instruct-GGUF",
        "file_hint": "*Q4_K_M*.gguf",
        "size_mb": 4900,
        "capabilities": ["chat", "coding"],
        "note": "enterprise-focused, Apache-2.0",
    },
}

# ---------------------------------------------------------------------------
# Curated datasets — classic agent fine-tune/eval sets (direct Hub URLs).
# ---------------------------------------------------------------------------

DATASETS: dict[str, dict] = {
    "glaive-function-calling": {
        "repo": "glaiveai/glaive-function-calling-v2",
        "url": f"{HF_BASE}/datasets/glaiveai/glaive-function-calling-v2",
        "task": "tool_calling",
        "note": "tool/function-call conversations for the hermes style",
    },
    "openhermes": {
        "repo": "teknium/OpenHermes-2.5",
        "url": f"{HF_BASE}/datasets/teknium/OpenHermes-2.5",
        "task": "instruction",
        "note": "1M instruction pairs, the classic agent-tune corpus",
    },
    "wizardlm-evol": {
        "repo": "WizardLMTeam/WizardLM evol instruct V2",
        "url": f"{HF_BASE}/datasets/WizardLMTeam/WizardLM_evol_instruct_V2_196k",
        "task": "instruction",
        "note": "evol-instruct depth training",
    },
    "codefeedback": {
        "repo": "m-a-p/CodeFeedback-Filtered-Instruction",
        "url": f"{HF_BASE}/datasets/m-a-p/CodeFeedback-Filtered-Instruction",
        "task": "coding",
        "note": "coding Q&A filtered by execution feedback",
    },
    "magicoder": {
        "repo": "ise-uiuc/Magicoder-Evol-Instruct-110K",
        "url": f"{HF_BASE}/datasets/ise-uiuc/Magicoder-Evol-Instruct-110K",
        "task": "coding",
        "note": "evol-code instructions, good implementer tuning set",
    },
    "humaneval": {
        "repo": "openai_humaneval",
        "url": f"{HF_BASE}/datasets/openai_humaneval",
        "task": "eval",
        "note": "canonical code-generation benchmark",
    },
    "mbpp": {
        "repo": "mbpp",
        "url": f"{HF_BASE}/datasets/mbpp",
        "task": "eval",
        "note": "mostly-basic-python-problems benchmark",
    },
    "swe-bench-lite": {
        "repo": "princeton-nlp/SWE-bench_Lite",
        "url": f"{HF_BASE}/datasets/princeton-nlp/SWE-bench_Lite",
        "task": "eval",
        "note": "real-repo issue-fixing eval for agent loops",
    },
}

# ---------------------------------------------------------------------------
# HF Inference provider (activates when HF_TOKEN is present)
# ---------------------------------------------------------------------------

def inference_provider() -> ProviderConfig | None:
    """HF Inference as a normal OpenAI-compatible provider (needs HF_TOKEN)."""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        return None
    return ProviderConfig(
        kind="openai",
        label="hf-inference",
        base_url=HF_INFER_URL,
        api_key=token,
        model=os.environ.get("HF_MODEL", "meta-llama/Llama-3.3-70B-Instruct"),
        capabilities=["chat", "reasoning", "long_context"],
        concurrency=2,
        timeout_s=300,
        priority=20,
    )


# ---------------------------------------------------------------------------
# Optional Hub metadata resolver (never required; degrades to the catalog)
# ---------------------------------------------------------------------------

def resolve(repo_id: str, timeout_s: int = 10) -> dict:
    """Fetch public metadata for a model/dataset repo from the Hub.

    Uses only stdlib; on any failure returns what we can (offline degrades
    to {'ok': False}) so CLI stays usable with no network.
    """
    url = f"{HF_BASE}/api/models/{repo_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "elysia"})
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            data = json.loads(r.read().decode())
        siblings = data.get("siblings") or []
        return {
            "ok": True, "repo": repo_id,
            "downloads": data.get("downloads"),
            "likes": data.get("likes"),
            "last_modified": data.get("lastModified"),
            "files": [s.get("rfilename") for s in siblings[:20]],
        }
    except Exception as e:  # noqa: BLE001 — offline-first: degrade, don't raise
        return {"ok": False, "repo": repo_id, "error": str(e)[:200]}


def recommend(available_mb: int) -> str:
    """Best curated local model for the available RAM (GGUF Q4 ballpark)."""
    fits = [(m["size_mb"], name) for name, m in MODELS.items()
            if m["size_mb"] <= available_mb]
    if not fits:
        return "qwen2.5-1.5b"
    return max(fits)[1]


def describe() -> dict:
    return {
        "models": [{"name": n, **m} for n, m in sorted(MODELS.items())],
        "datasets": [{"name": n, **d} for n, d in sorted(DATASETS.items())],
        "inference_ready": bool(os.environ.get("HF_TOKEN")),
        "inference_url": HF_INFER_URL,
    }
