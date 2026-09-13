#!/usr/bin/env python3
"""
Elysia worker_local.py — one lightweight agent instance (NO opencode).

Loop: claim task from the SQLite board -> prompt the LOCAL model via brain.py
-> parse file blocks -> write them into the workspace -> QA-check -> mark
done/failed -> claim next. Bounded: max 2 model calls per task (1 + 1 retry).

Usage: worker_local.py <workerID> <workspaceDir> [maxTasks]
"""
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import brain  # noqa: E402

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
TASKBOARD = os.path.join(ORCH_DIR, "taskboard.py")
REPO_ROOT = os.path.dirname(ORCH_DIR)   # /data/elysia-run (read-only context)

# ---------- context attach: give the model the REAL files, not just names ----
# The 1.5B model hallucinates "document this code" tasks when it only sees file
# names. We therefore attach compact content for owned files that already exist
# plus any existing files the task description names (reference only — writes
# stay sandboxed to the owned files inside the workspace).

CONTEXT_BUDGET = 9000      # total attached-reference chars (ctx slot ~4096 tok)
VERBATIM_MAX = 1200        # files smaller than this are included in full
SURFACE_MAX = 2600         # larger files are reduced to a structural surface
SKIP_DIRS = {"node_modules", "dist", "coverage", ".git", "runtime", "store",
             "quarantine", "build", ".cache", "__pycache__", "logs",
             ".adaptive", ".monitor"}
PATH_TOKEN_RE = re.compile(r"[\w./-]+\.(?:jsonc|json|ya?ml|jsx|tsx|js|ts|py|go|md|sh)(?![\w./])")


def file_surface(rel, text):
    """A compact but accurate summary of a large file: for code files, every
    def/class/export/route declaration line; for md, the heading outline."""
    lines = text.splitlines()
    ext = rel.rsplit(".", 1)[-1].lower()
    out = []
    if ext == "md":
        out = [l.strip() for l in lines if l.lstrip().startswith("#")]
    elif ext in ("py",):
        pat = re.compile(r"^\s*(async\s+def|def|class|@[a-zA-Z_])[^:]*")
        out = [l.rstrip()[:110] for l in lines if pat.match(l)]
    elif ext == "go":
        pat = re.compile(r"^\s*(func|type|var|const)\s+")
        out = [l.rstrip()[:110] for l in lines if pat.match(l)]
    elif ext in ("ts", "tsx", "js", "jsx"):
        pat = re.compile(r"^\s*(export\s+)?(default\s+)?(async\s+)?"
                         r"(function|class|const|let|interface|type|enum)\s+")
        out = [l.rstrip()[:110] for l in lines if pat.match(l)]
    elif ext == "json":
        return text[:SURFACE_MAX]  # config is usually worth seeing verbatim
    else:
        # sh/yml/unknown: first lines + any obvious section markers
        out = [l.rstrip()[:110] for l in lines[:60]]
    return "\n".join(out)[:SURFACE_MAX]


def render_file(rel, text, used):
    """Render one context file within the remaining budget. Markdown is kept
    verbatim whenever it fits (doc-edit tasks need the whole current file)."""
    n = len(text)
    ext = rel.rsplit(".", 1)[-1].lower()
    if (n <= VERBATIM_MAX or ext == "md") and used + n <= CONTEXT_BUDGET:
        body = text
        tag = "full"
    else:
        body = file_surface(rel, text)
        tag = "surface"
    if not body or used + len(body) > CONTEXT_BUDGET:
        return "", used
    block = (f"### {rel}  ({tag})\n"
             f"```\n{body}\n```\n")
    return block, used + len(block)


def find_reference(rel):
    """Locate a referenced file in the workspace or the repo root."""
    rel = rel.lstrip("./").lstrip("/")
    if ".." in rel:
        return None
    for base in (WS_DIR_FALLBACK, REPO_ROOT):
        cand = os.path.join(base, rel)
        if os.path.isfile(cand) and not any(
                part in SKIP_DIRS for part in rel.split("/")):
            return cand
    return None


def collect_context(task, ws_dir):
    """-> (context_string, reference_texts). Reads real file content for owned
    files that already exist + files named in title/description. The reference
    texts feed the anti-hallucination grounding check on doc outputs."""
    owned = task.get("files") or []
    if isinstance(owned, str):
        try:
            owned = json.loads(owned)
        except Exception:
            owned = []
    text = f"{task.get('title') or ''}\n{task.get('description') or ''}"
    refs = re.findall(PATH_TOKEN_RE, text)
    want = []
    for o in owned:  # owned files first (edits need current content)
        if isinstance(o, str) and o:
            want.append((o, True))
    for r in refs:
        if r not in [w[0] for w in want]:
            want.append((r, False))
    blocks, used, ref_texts = [], 0, []
    for rel, is_owned in want:
        path = os.path.join(ws_dir, rel) if is_owned else find_reference(rel)
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue
        if not content.strip():
            continue
        ref_texts.append(content)
        block, used = render_file(rel, content, used)
        if block:
            blocks.append(block)
    if not blocks:
        return "", ref_texts
    head = ("EXISTING FILE CONTENTS (REFERENCE ONLY — do not claim these as "
            "owned; write ONLY your owned files, and base your work on the "
            "REAL content below, never on guesses):\n\n")
    return head + "\n".join(blocks) + "\n", ref_texts


WS_DIR_FALLBACK = os.environ.get("ELYSIA_WS",
                                 os.path.join(REPO_ROOT, "workspace"))

# ---------- binding instructions (orchestrator/INSTRUCTIONS.md) ----------
def load_instructions():
    p = os.path.join(ORCH_DIR, "INSTRUCTIONS.md")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""

INSTRUCTIONS = load_instructions()

# ---------- grounding check: doc output must reflect the reference files ----
STOPWORDS = set("""the and for with from that this these those file files task
tasks code based only real content json your you all any new out each then when
what which there their same some more must name value setting below above used
use not are can have will should about write written output own owned provided
reference section above document do does work system agent agents list key keys
path paths into than very other one two first last its it's been being get make
make sure ensure also would could may might like just well up down over under
""".split())


def ref_tokens(texts):
    """Distinctive identifier tokens from the reference file contents."""
    toks = {}
    for t in texts:
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]{3,}", t):
            w = m.group(0).lower()
            if w in STOPWORDS or w.isdigit():
                continue
            toks[w] = toks.get(w, 0) + 1
    return set(toks)


def grounding_ok(content, ref_texts, min_hits=2):
    """True if the produced text borrows >= min_hits distinctive tokens from
    the attached reference files (anti-hallucination for doc tasks)."""
    if not ref_texts:
        return True
    rt = ref_tokens(ref_texts)
    if len(rt) < 4:          # not enough signal to judge
        return True
    got = {m.group(0).lower()
           for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]{3,}", content)}
    return len(rt & got) >= min_hits


def log(worker, msg):
    line = f"[{worker}] {msg}"
    print(line, flush=True)
    with open(os.path.join(ORCH_DIR, "logs", f"worker-{worker}.log"), "a") as f:
        f.write(line + "\n")


def tb(*args):
    """Run taskboard.py and return stdout."""
    import subprocess
    r = subprocess.run([sys.executable, TASKBOARD, *args],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def build_prompt(task, ws_dir):
    files = task.get("files") or []
    files_str = ", ".join(files) if files else "any appropriate files"
    desc = task.get("description") or task["title"]
    ctx, ref_texts = collect_context(task, ws_dir)
    ctx_block = ("\n" + ctx) if ctx else ""
    instr = ("BINDING INSTRUCTIONS — apply every time:\n" + INSTRUCTIONS
             + "\n\n") if INSTRUCTIONS else ""
    return (instr +
            f"TASK: {task['title']}\n"
            f"DETAILS: {desc}\n"
            f"FILES YOU OWN (write full content for these): {files_str}\n"
            f"Workspace root: {ws_dir}{ctx_block}\n\n"
            "Write the COMPLETE content for each file you own, as fenced code "
            "blocks with the path after the language, e.g. ```md README.md. "
            "If reference file contents were provided above, base your work on "
            "those REAL contents — never invent APIs, endpoints, or structure."
    ), ref_texts


def run_jest(ws_dir, test_files):
    """Run jest on given test files. Returns {rc, summary, output}."""
    try:
        r = subprocess.run(["npx", "jest", *test_files, "--silent"],
                           cwd=ws_dir, capture_output=True, text=True,
                           timeout=240)
        out = (r.stdout or r.stderr or "").strip()
        lines = out.splitlines()
        # prefer a 'Tests:' summary line if present
        summary = next((l for l in lines if l.strip().startswith("Tests:")),
                       lines[-1][:160] if lines else "")
        return {"rc": r.returncode, "summary": summary, "output": out}
    except subprocess.TimeoutExpired:
        return {"rc": 124, "summary": "TIMEOUT", "output": ""}
    except Exception as e:
        return {"rc": 1, "summary": f"error: {e}", "output": ""}


def run_task(worker, task, ws_dir):
    tid = task["id"]
    # taskboard returns 'files' as a JSON-encoded string — normalize it.
    raw_files = task.get("files") or []
    if isinstance(raw_files, str):
        try:
            raw_files = json.loads(raw_files)
        except Exception:
            raw_files = []
    owned = [f for f in raw_files if isinstance(f, str) and f]
    if not owned:
        # HARD RULE: a task with no owned files is malformed. Never let the
        # model freestyle into the workspace (this burned real files before).
        log(worker, f"task #{tid} REJECTED: no owned files — refusing to run")
        tb("finish", str(tid), "failed", worker, "rejected: task has no owned files")
        return False
    prompt, ref_texts = build_prompt(task, ws_dir)
    messages = [{"role": "system", "content": brain.SYSTEM_PROMPT},
                {"role": "user", "content": prompt}]

    for attempt in (1, 2, 3):
        text, err = brain.chat(messages, max_tokens=2048)
        if err:
            log(worker, f"task #{tid} attempt {attempt}: model error: {err[:120]}")
            time.sleep(3)
            continue
        files = brain.parse_file_blocks(text, owned)
        if not files:
            log(worker, f"task #{tid} attempt {attempt}: no file blocks parsed "
                        f"(raw {len(text or '')} chars)")
            # retry with a corrective nudge
            messages.append({"role": "assistant", "content": text[:500]})
            messages.append({"role": "user", "content":
                             "Output the file(s) now as fenced blocks with paths."})
            continue

        wrote, failed = [], []
        for path, content in files.items():
            path = path.lstrip("/").replace("..", "_")  # sandbox to workspace
            if owned and path not in owned:
                # model mislabeled the block (e.g. wrote a directory name).
                # Single-file task -> remap to the owned file; otherwise refuse.
                if len(owned) == 1:
                    log(worker, f"task #{tid}: remapping block '{path}' -> '{owned[0]}'")
                    path = owned[0]
                else:
                    log(worker, f"task #{tid}: refusing out-of-scope file {path}")
                    failed.append(f"{path}: not in owned files")
                    continue
            dest = os.path.join(ws_dir, path)
            ok, reason = brain.qa_check(path, content)
            if not ok:
                failed.append(f"{path}: {reason}")
                continue
            # anti-hallucination: markdown must borrow from the reference files
            if path.endswith(".md") and not grounding_ok(content, ref_texts):
                failed.append(f"{path}: content is not grounded in the "
                              "provided reference files (invented details)")
                continue
            try:
                os.makedirs(os.path.dirname(dest) or ws_dir, exist_ok=True)
                with open(dest, "w") as f:
                    f.write(content)
                wrote.append(path)
            except OSError as e:
                failed.append(f"{path}: write error {e}")

        if wrote:
            result = f"wrote {', '.join(wrote)}"
            if failed:
                result += f"; QA rejected: {'; '.join(failed)}"
            # Testing-first: verify written test files with jest.
            # If they fail, ONE repair loop: feed the errors back to the model
            # (this is the mistake-monitoring agents do on their own work).
            test_files = [p for p in wrote if p.endswith(".test.ts")]
            if test_files:
                r = run_jest(ws_dir, test_files)
                if r["rc"] != 0 and r["summary"]:
                    log(worker, f"task #{tid}: jest failed; asking model to repair")
                    messages.append({"role": "assistant", "content": text[-800:]})
                    messages.append({"role": "user", "content":
                                     f"The test file {test_files[0]} failed jest:\n"
                                     f"{r['summary'][:600]}\n\nRewrite the COMPLETE "
                                     f"file so all tests pass. One fenced block, "
                                     f"path after the language. Imports must match "
                                     f"the real source modules."})
                    t2, err2 = brain.chat(messages, max_tokens=2048)
                    files2 = brain.parse_file_blocks(t2, test_files) if not err2 else {}
                    if files2:
                        for p, c in files2.items():
                            dest = os.path.join(ws_dir, p)
                            try:
                                os.makedirs(os.path.dirname(dest) or ws_dir, exist_ok=True)
                                with open(dest, "w") as f:
                                    f.write(c)
                            except OSError:
                                continue
                        r = run_jest(ws_dir, test_files)
                result += f"; jest rc={r['rc']} {r['summary'][:100]}"
                log(worker, f"task #{tid} final jest rc={r['rc']} {r['summary'][:120]}")
            log(worker, f"task #{tid} DONE — {result}")
            tb("finish", str(tid), "done", worker, result)
            return True
        log(worker, f"task #{tid} attempt {attempt}: all files failed QA: {failed}")
        messages.append({"role": "user", "content":
                         "Your output failed validation: " + "; ".join(failed) +
                         f". Write ONLY this exact file path: {owned[0]}. "
                         "Full content, one fenced block, path right after the language."})

    tb("finish", str(tid), "failed", worker, "no valid output after 3 attempts")
    log(worker, f"task #{tid} FAILED")
    return False


def main():
    worker = sys.argv[1] if len(sys.argv) > 1 else "w0"
    ws_dir = sys.argv[2] if len(sys.argv) > 2 else "/data/elysia-run/workspace"
    max_tasks = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    os.makedirs(os.path.join(ORCH_DIR, "logs"), exist_ok=True)

    if not brain.health():
        log(worker, "local model DOWN; exiting")
        sys.exit(1)

    done = 0
    for _ in range(max_tasks):
        raw = tb("claim", worker)
        try:
            task = json.loads(raw)
        except Exception:
            task = None
        if not task or task is None:
            log(worker, "board empty; exiting")
            break
        log(worker, f"claimed #{task['id']}: {task['title']}")
        run_task(worker, task, ws_dir)
        done += 1
    log(worker, f"worker finished ({done} tasks)")


if __name__ == "__main__":
    main()
