"""ELI-assisted behavioural test generation (Phase 4).

ELI grows its own behavioural test coverage: it reads a target function (source,
signature, docstring, real call sites), writes a pytest test for it via the local
model, then **sandbox-verifies** the test — only tests that actually PASS against
the current implementation are accepted into `tests/generated/` (a reviewable
area). A generated test that fails almost always means the *test* guessed wrong, so
it is rejected, not merged — that's the gate that keeps the suite honest and green.

Design:
  - select_targets()  → untested public functions from a curated SAFE set (pure-ish,
    deterministic, cheap to import — no GUI/daemons/side effects).
  - build_prompt()    → function source + signature + docstring + call sites.
  - generate_test()   → ask the local model (broker; model-agnostic) for a pytest test.
  - verify_test()     → run the candidate under pytest IN ISOLATION; accept iff it
    collects ≥1 test and passes.
  - run_testgen()     → orchestrate N targets; write accepted tests + a manifest
    (accepted / rejected-with-reason) for human review.

100% local, bounded, exception-isolated. Kill switch ELI_TESTGEN=0. Heavy (one
model call per target) → intended for the scheduled/overnight `testgen` task; on
the CPU build it is slow (see eli-cpu-only-llama-build).
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

REPO = Path(__file__).resolve().parents[2]
GEN_DIR = REPO / "tests" / "generated"
MANIFEST = GEN_DIR / "_manifest.json"
# Candidates are verified UNDER tests/ so the repo conftest + testpaths apply
# (fixed location, independent of GEN_DIR which a test may redirect).
_VERIFY_TMP = REPO / "tests" / "generated" / "_tmp"

# Curated safe, pure-ish modules whose public functions are deterministic and
# cheap to import (no GUI, no daemons, no model, no network). Start small +
# trustworthy; expand as confidence grows.
SAFE_MODULES = (
    "eli.core.dag",
    "eli.core.model_tier",
    "eli.cognition.reasoning_modes",
    "eli.runtime.grounding_escalation",
    "eli.runtime.report_pipeline",
    "eli.planning.habits",
    "eli.runtime.scheduled_tasks",
)

AskFn = Callable[..., str]


def enabled() -> bool:
    return os.environ.get("ELI_TESTGEN", "1").strip().lower() not in ("0", "false", "no", "off")


# --------------------------------------------------------------------------- #
# Target selection                                                            #
# --------------------------------------------------------------------------- #
class Target:
    __slots__ = ("module", "name", "func", "source")

    def __init__(self, module: str, name: str, func: Any, source: str):
        self.module, self.name, self.func, self.source = module, name, func, source

    @property
    def qual(self) -> str:
        return f"{self.module}:{self.name}"


def _already_generated() -> set:
    if not MANIFEST.exists():
        return set()
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return {e["qual"] for e in data.get("entries", []) if e.get("accepted")}
    except Exception:
        return set()


def select_targets(limit: int = 5, modules: Optional[List[str]] = None) -> List[Target]:
    done = _already_generated()
    out: List[Target] = []
    for dotted in (modules or SAFE_MODULES):
        try:
            mod = importlib.import_module(dotted)
        except Exception:
            continue
        for name, obj in sorted(vars(mod).items()):
            if name.startswith("_") or not inspect.isfunction(obj):
                continue
            if getattr(obj, "__module__", None) != dotted:
                continue
            qual = f"{dotted}:{name}"
            if qual in done:
                continue
            try:
                src = inspect.getsource(obj)
            except (OSError, TypeError):
                continue
            out.append(Target(dotted, name, obj, src))
            if len(out) >= limit:
                return out
    return out


def _call_sites(name: str, max_hits: int = 5) -> List[str]:
    hits: List[str] = []
    try:
        r = subprocess.run(["grep", "-rn", "--include=*.py", f"{name}(", str(REPO / "eli")],
                           capture_output=True, text=True, timeout=30)
        for line in (r.stdout or "").splitlines():
            if f"def {name}(" in line:
                continue
            hits.append(line.strip()[:160])
            if len(hits) >= max_hits:
                break
    except Exception:
        pass
    return hits


# --------------------------------------------------------------------------- #
# Generation                                                                  #
# --------------------------------------------------------------------------- #
def build_prompt(t: Target) -> str:
    sig = ""
    try:
        sig = str(inspect.signature(t.func))
    except (ValueError, TypeError):
        pass
    sites = _call_sites(t.name)
    return (
        f"Write a single pytest test module for the function `{t.name}` from "
        f"`{t.module}` (signature `{t.name}{sig}`).\n\n"
        f"SOURCE:\n```python\n{t.source[:2500]}\n```\n\n"
        + ("REAL CALL SITES (how it's used):\n" + "\n".join(sites) + "\n\n" if sites else "")
        + "Requirements:\n"
        f"- `from {t.module} import {t.name}` (or import the module).\n"
        "- Test the ACTUAL behaviour with concrete inputs/outputs; assert real values.\n"
        "- Pure/deterministic only — no network, no real model, no GUI, no sleeps.\n"
        "- The test MUST pass against the implementation shown. If a branch needs a "
        "fixture/mock, keep it minimal and correct.\n"
        "- Output ONLY the python test file content, no prose, no markdown fences."
    )


def generate_test(t: Target, ask: AskFn) -> str:
    sys_p = ("You are ELI writing a rigorous, correct pytest test for one of your own "
             "functions. Output only valid python — a complete test module.")
    raw = ask(build_prompt(t), system=sys_p, max_tokens=1200, temperature=0.2)
    code = re.sub(r"^```[a-z]*\n?", "", str(raw or "").strip(), flags=re.MULTILINE)
    code = re.sub(r"\n?```$", "", code.strip(), flags=re.MULTILINE).strip()
    return code


# --------------------------------------------------------------------------- #
# Verification (the gate)                                                      #
# --------------------------------------------------------------------------- #
def verify_test(code: str) -> Dict[str, Any]:
    """Run the candidate under pytest in isolation. Accept iff it parses, collects
    ≥1 test, and passes. Returns {accepted, reason, output}."""
    if not code or len(code) < 30:
        return {"accepted": False, "reason": "empty/short candidate"}
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"accepted": False, "reason": f"syntax error: {e}"}
    _VERIFY_TMP.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix="_cand_test.py", prefix="test_cand_", dir=str(_VERIFY_TMP))
    os.close(fd)
    try:
        Path(path).write_text(code, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", path, "-q", "-p", "no:cacheprovider", "--no-header"],
            cwd=str(REPO), capture_output=True, text=True, timeout=180)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"(\d+) passed", out)
        n_pass = int(m.group(1)) if m else 0
        failed = bool(re.search(r"\d+ (failed|error)", out)) or r.returncode != 0
        accepted = (n_pass >= 1) and not failed
        reason = "ok" if accepted else ("no tests collected" if n_pass == 0 else "failed/errored")
        return {"accepted": accepted, "reason": reason, "passed": n_pass, "output": out[-1500:]}
    except subprocess.TimeoutExpired:
        return {"accepted": False, "reason": "timeout"}
    except Exception as e:
        return {"accepted": False, "reason": f"verify error: {e}"}
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #
def _default_ask() -> AskFn:
    from eli.cognition import gguf_inference as g
    g.load_model()

    def _ask(prompt, system=None, max_tokens=1200, temperature=0.2):
        return g.chat_completion(prompt, system=system, max_tokens=max_tokens,
                                 temperature=temperature, top_p=0.85)
    return _ask


def _safe_filename(t: Target) -> str:
    base = (t.module.replace(".", "_") + "__" + t.name)
    base = re.sub(r"[^a-zA-Z0-9_]", "_", base)
    return f"test_gen_{base}.py"


def run_testgen(limit: int = 5, ask: Optional[AskFn] = None,
                modules: Optional[List[str]] = None) -> Dict[str, Any]:
    """Generate + sandbox-verify tests for up to `limit` untested functions.
    Accepted tests are written to tests/generated/; all outcomes recorded in the
    manifest for review. Returns a summary."""
    if not enabled():
        return {"ok": False, "reason": "disabled (ELI_TESTGEN=0)"}
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    ask = ask or _default_ask()
    targets = select_targets(limit=limit, modules=modules)
    accepted, rejected = [], []
    for t in targets:
        try:
            code = generate_test(t, ask)
            v = verify_test(code)
        except Exception as e:
            rejected.append({"qual": t.qual, "reason": f"gen error: {e}"})
            continue
        if v.get("accepted"):
            fname = _safe_filename(t)
            header = (f"# Auto-generated behavioural test for {t.qual}\n"
                      f"# Generated by eli.runtime.test_generator (Phase 4) — sandbox-verified.\n"
                      f"# Review before trusting; regenerate with the testgen task.\n")
            (GEN_DIR / fname).write_text(header + code + "\n", encoding="utf-8")
            accepted.append({"qual": t.qual, "file": f"tests/generated/{fname}",
                             "passed": v.get("passed"), "accepted": True})
        else:
            rejected.append({"qual": t.qual, "reason": v.get("reason"), "accepted": False})

    _write_manifest(accepted + rejected)
    return {"ok": True, "targets": len(targets),
            "accepted": len(accepted), "rejected": len(rejected),
            "accepted_files": [a["file"] for a in accepted]}


def _write_manifest(new_entries: List[Dict[str, Any]]) -> None:
    existing = []
    if MANIFEST.exists():
        try:
            existing = json.loads(MANIFEST.read_text(encoding="utf-8")).get("entries", [])
        except Exception:
            existing = []
    by_qual = {e.get("qual"): e for e in existing}
    for e in new_entries:
        by_qual[e["qual"]] = {**e, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    MANIFEST.write_text(json.dumps(
        {"updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "entries": list(by_qual.values())},
        indent=2), encoding="utf-8")


__all__ = ["run_testgen", "select_targets", "generate_test", "verify_test",
           "build_prompt", "enabled", "Target"]
