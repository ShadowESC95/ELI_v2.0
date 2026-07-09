"""
Code examiner — examine user-named files (or a default sweep) for errors in
three confidence tiers, then offer to fix via the existing verified patch engine.

Design (user-requested, 2026-06-06):
  * Tier 1 — HIGH confidence, deterministic: syntax (ast.parse) + import smoke-test.
  * Tier 2 — MEDIUM confidence, static lint: unused imports / undefined names
    (pyflakes if importable, else a conservative AST fallback).
  * Tier 3 — LOW confidence, local-LLM logic review: suspected bugs; flagged
    `needs_confirmation` so they NEVER act without the user saying yes.

The report is deterministic and is surfaced verbatim (see engine
`_verbatim_always_actions`) so a weak local model can't corrupt grounded findings.
Fixes are NOT auto-applied: findings are stored as a pending offer; on confirm the
executor patches each finding through SelfImprovementEngine.apply_code_patch
(project-scoped, syntax-validated, import-verified, auto-revert).

100% local, model-agnostic (inference broker only), offline-safe.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

# Reuse the self-improvement engine's import/path helpers rather than re-rolling.
from eli.runtime.self_improvement import (
    _smoke_import_module,
    _dotted_module_for_path,
    PROJECT_ROOT,
)

log = get_logger(__name__)

# Cap the default sweep so the Tier-3 LLM pass stays bounded — directly limits
# the "hallucinate at scale" risk on a large tree.
MAX_SWEEP_FILES = int(os.environ.get("ELI_EXAMINE_MAX_FILES", "25"))
TIER3_MAX_FILES = int(os.environ.get("ELI_EXAMINE_TIER3_MAX_FILES", "8"))
# Max line-windows to deep-review per file (a big god-file is split into windows so the
# deep tier covers more than its first ~MAX_FILE_CHARS). Bounds the LLM cost per file.
TIER3_MAX_CHUNKS = int(os.environ.get("ELI_EXAMINE_TIER3_MAX_CHUNKS", "3"))
MAX_FILE_CHARS = 12000

TIER_CONF = {1: 0.95, 2: 0.70, 3: 0.40}

# Small alias map so "examine the orchestrator" resolves without a path.
_MODULE_ALIASES = {
    "orchestrator": "eli/cognition/orchestrator.py",
    "router": "eli/execution/router_enhanced.py",
    "executor": "eli/execution/executor_enhanced.py",
    "engine": "eli/kernel/engine.py",
    "memory": "eli/memory/memory.py",
    "grounding": "eli/runtime/grounding_escalation.py",
    "self upgrade": "eli/kernel/self_upgrade.py",
    "self-upgrade": "eli/kernel/self_upgrade.py",
    "self improvement": "eli/runtime/self_improvement.py",
}

# Curated fallback set when no files are named and git gives us nothing.
_CORE_FALLBACK = [
    "eli/execution/router_enhanced.py",
    "eli/execution/executor_enhanced.py",
    "eli/kernel/engine.py",
    "eli/cognition/orchestrator.py",
    "eli/runtime/grounding_escalation.py",
]


@dataclass
class Finding:
    file: str            # path relative to project root
    tier: int            # 1 | 2 | 3
    confidence: float    # see TIER_CONF
    kind: str            # e.g. "syntax", "import", "unused-import", "logic"
    message: str
    line: Optional[int] = None
    needs_confirmation: bool = False   # True for Tier 3

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Target resolution                                                           #
# --------------------------------------------------------------------------- #
def _rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(p)


def _inside_project(p: Path) -> bool:
    try:
        p.resolve().relative_to(PROJECT_ROOT)
        return True
    except Exception:
        return False


def _extract_named_paths(request: str) -> List[Path]:
    """Pull explicit .py paths, dotted modules, and known aliases out of a request."""
    raw = request or ""
    low = raw.lower()
    out: List[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        rp = p.resolve()
        key = str(rp)
        if key in seen:
            return
        if rp.suffix == ".py" and _inside_project(rp) and rp.exists():
            seen.add(key)
            out.append(rp)

    # 1) explicit path tokens ending in .py (eli/..., ./..., ~/..., absolute)
    for tok in re.findall(r"[~./\w-]*\.py\b", raw):
        cand = Path(os.path.expanduser(tok))
        if not cand.is_absolute():
            cand = PROJECT_ROOT / cand
        _add(cand)

    # 2) dotted modules: eli.cognition.orchestrator
    for tok in re.findall(r"\beli(?:\.\w+)+\b", raw):
        _add(PROJECT_ROOT / (tok.replace(".", "/") + ".py"))

    # 3) aliases ("the orchestrator", "the router")
    for alias, rel in _MODULE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low):
            _add(PROJECT_ROOT / rel)

    return out


def _git_recent_py(days: int = 7, max_files: int = MAX_SWEEP_FILES) -> List[Path]:
    """Recently-modified project .py files via git (working tree + recent commits)."""
    found: List[Path] = []
    seen: set[str] = set()

    def _collect(args: List[str]) -> None:
        try:
            proc = subprocess.run(
                ["git", *args], cwd=str(PROJECT_ROOT),
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            return
        if proc.returncode != 0:
            return
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line.endswith(".py"):
                continue
            p = (PROJECT_ROOT / line).resolve()
            key = str(p)
            if key in seen or not p.exists() or not _inside_project(p):
                continue
            # Keep the examiner focused on the package itself.
            if not str(p.relative_to(PROJECT_ROOT)).startswith("eli/"):
                continue
            seen.add(key)
            found.append(p)

    _collect(["ls-files", "-m"])                          # locally modified
    _collect(["log", f"--since={days} days ago", "--name-only", "--pretty=format:"])
    return found[:max_files]


def resolve_targets(request: str) -> List[Path]:
    """Files the user named, else a capped default sweep (git-recent eli/*.py,
    else a curated core set)."""
    named = _extract_named_paths(request)
    if named:
        return named[:MAX_SWEEP_FILES]
    recent = _git_recent_py()
    if recent:
        return recent
    fallback = [(PROJECT_ROOT / r).resolve() for r in _CORE_FALLBACK]
    return [p for p in fallback if p.exists()]


# --------------------------------------------------------------------------- #
# Tier 1 — deterministic (syntax + import)                                    #
# --------------------------------------------------------------------------- #
def _tier1(path: Path) -> List[Finding]:
    rel = _rel(path)
    findings: List[Finding] = []
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as e:
        return [Finding(rel, 1, TIER_CONF[1], "read-error", f"Could not read file: {e}")]

    try:
        ast.parse(src)
    except SyntaxError as e:
        # A syntax error means the file can't even be imported; report and stop.
        return [Finding(rel, 1, TIER_CONF[1], "syntax",
                        f"SyntaxError: {e.msg}", line=e.lineno)]

    dotted = _dotted_module_for_path(path)
    if dotted:
        ok, detail = _smoke_import_module(dotted, timeout=30.0)
        if not ok and detail and "skipped (infra)" not in detail:
            tail = " ".join(detail.splitlines()[-2:])[:300]
            findings.append(Finding(rel, 1, TIER_CONF[1], "import",
                                    f"Import failed: {tail}"))
    return findings


# --------------------------------------------------------------------------- #
# Tier 2 — static lint (pyflakes if available, else conservative AST)         #
# --------------------------------------------------------------------------- #
def _tier2_pyflakes(path: Path, src: str) -> Optional[List[Finding]]:
    try:
        from pyflakes.api import check as _pf_check
        from pyflakes.reporter import Reporter
    except Exception:
        return None
    import io
    rel = _rel(path)
    out, err = io.StringIO(), io.StringIO()
    try:
        _pf_check(src, rel, Reporter(out, err))
    except Exception:
        return None
    findings: List[Finding] = []
    for line in (out.getvalue() or "").splitlines():
        # format: path:line:col message
        m = re.match(rf"{re.escape(rel)}:(\d+):(?:\d+:)?\s*(.+)", line)
        if not m:
            continue
        msg = m.group(2).strip()
        # Drop star-import noise: a file using `from X import *` makes pyflakes flag
        # EVERY name it can't resolve as "may be undefined, or defined from star
        # imports" — hundreds of false positives (a GUI scan produced ~800). These are
        # not real bugs (the file imports/runs clean); surfacing them as fixable findings
        # is what made an examine return 853 mostly-bogus results.
        if ("may be undefined, or defined from star imports" in msg
                or "unable to detect undefined names" in msg):
            continue
        findings.append(Finding(rel, 2, TIER_CONF[2], "lint", msg, line=int(m.group(1))))
    return findings


def _tier2_ast_unused_imports(path: Path, src: str) -> List[Finding]:
    """Conservative fallback: flag imports whose bound name is never referenced."""
    rel = _rel(path)
    findings: List[Finding] = []
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return findings  # Tier 1 already reported it

    imported: Dict[str, int] = {}   # bound name -> lineno
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = (alias.asname or alias.name).split(".")[0]
                imported.setdefault(name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.names and node.names[0].name == "*":
                continue  # star imports — can't track
            for alias in node.names:
                name = alias.asname or alias.name
                imported.setdefault(name, node.lineno)

    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            base = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                used.add(base.id)

    # __all__ / re-export modules: skip to avoid false positives.
    if "__all__" in src:
        return findings
    for name, lineno in imported.items():
        if name == "*" or name in used:
            continue
        findings.append(Finding(rel, 2, TIER_CONF[2], "unused-import",
                                f"'{name}' imported but never used", line=lineno))
    return findings


def _tier2(path: Path) -> List[Finding]:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    pf = _tier2_pyflakes(path, src)
    if pf is not None:
        return pf
    return _tier2_ast_unused_imports(path, src)


# --------------------------------------------------------------------------- #
# Tier 3 — local-LLM logic review (low confidence, gated)                     #
# --------------------------------------------------------------------------- #
_TIER3_SYS = (
    "You are a precise code reviewer. Report ONLY concrete, specific bugs you can "
    "point to (logic errors, wrong conditions, off-by-one, unhandled None, etc.). "
    "Do NOT report style, naming, or 'consider' suggestions. If the file looks "
    "correct, return an empty list. Cite the line number for each issue."
)


def _tier3_windows(numbered: List[str]):
    """Yield (lo, hi, body) windows of WHOLE numbered lines, each <= MAX_FILE_CHARS.
    lo/hi are 1-based real line numbers (inclusive) — so a big file is reviewed across
    several windows instead of only its first ~MAX_FILE_CHARS (which left the deep tier
    blind to ~90% of the god-files). Never cuts a line mid-way (which would corrupt the
    line→number mapping)."""
    cur: List[str] = []
    total = 0
    lo = 1
    for idx, nl in enumerate(numbered, start=1):
        if cur and total + len(nl) + 1 > MAX_FILE_CHARS:
            yield (lo, idx - 1, "\n".join(cur))
            cur, total, lo = [], 0, idx
        cur.append(nl)
        total += len(nl) + 1
    if cur:
        yield (lo, len(numbered), "\n".join(cur))


def _tier3_review_window(rel: str, lo: int, hi: int, body: str, partial: bool) -> List[Finding]:
    prompt = (
        f"Review this section of a Python file ({rel}, lines {lo}-{hi}) for concrete bugs.\n"
        "Each source line is prefixed with its REAL line number and a tab — cite that "
        "exact number in 'line'; never guess a line outside this section.\n"
        + (f"This is one section of a larger file; only lines {lo}-{hi} are shown — do "
           "NOT report anything about code outside it.\n" if partial else "")
        + "Respond with ONLY a JSON array; each item: "
        '{"line": <int>, "issue": "<specific bug>"}. '
        "Empty array [] if nothing concrete is wrong.\n\n"
        f"```python\n{body}\n```"
    )
    try:
        from eli.cognition.inference_broker import get_broker
        raw = get_broker().infer(prompt, system=_TIER3_SYS, max_tokens=400, temperature=0.1)
    except Exception as e:
        log.debug(f"[EXAMINE] tier-3 window {lo}-{hi} skipped for {rel}: {e}")
        return []
    m = re.search(r"\[[\s\S]*\]", raw or "")
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except Exception:
        return []
    out: List[Finding] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        issue = str(it.get("issue") or "").strip()
        if not issue:
            continue
        line = it.get("line")
        try:
            line = int(line) if line is not None else None
        except Exception:
            line = None
        # Reject a finding citing a line outside THIS window (lo..hi) — the 7B otherwise
        # invents line numbers/issues for code it can't see.
        if line is not None and not (lo <= line <= hi):
            continue
        out.append(Finding(rel, 3, TIER_CONF[3], "logic", issue,
                           line=line, needs_confirmation=True))
    return out


def _tier3(path: Path) -> List[Finding]:
    rel = _rel(path)
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    if not src.strip():
        return []
    numbered = [f"{i + 1}\t{ln}" for i, ln in enumerate(src.splitlines())]
    windows = list(_tier3_windows(numbered))
    capped = windows[:TIER3_MAX_CHUNKS]   # bound the LLM cost per file
    partial = len(capped) > 1 or len(windows) > len(capped)
    findings: List[Finding] = []
    for (lo, hi, body) in capped:
        findings.extend(_tier3_review_window(rel, lo, hi, body, partial))
    return findings


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #
def examine(paths: List[Path], *, run_tier3: bool = True) -> List[Finding]:
    """Run the three tiers over the given files. Tier 3 is capped separately."""
    findings: List[Finding] = []
    tier3_budget = TIER3_MAX_FILES if run_tier3 else 0
    for p in paths:
        t1 = _tier1(p)
        findings.extend(t1)
        # If the file has a hard syntax error, deeper tiers are meaningless.
        if any(f.kind == "syntax" for f in t1):
            continue
        findings.extend(_tier2(p))
        if tier3_budget > 0:
            findings.extend(_tier3(p))
            tier3_budget -= 1
    return findings


# Only GENUINE BREAKAGE is auto-fixable: a syntax error, a failed import, or a truly-undefined
# name (a real NameError at runtime). Cosmetic lint — unused imports/variables, f-string style,
# redefinition warnings — is REPORT-ONLY. It doesn't break anything, and the local model botches
# such "fixes" (it once turned `import tempfile` into `import tempfile as t`, breaking every use,
# and rewrote working consensus logic). Those are never handed to the patch engine. (2026-06-09:
# a vague "run full time audit" swept the whole tree and applied 19 such botched lint patches to
# ELI's own core files.)
_REAL_BREAKAGE_KINDS = frozenset({"syntax", "import", "read-error"})


def is_real_breakage(f: "Finding") -> bool:
    """True only for findings that actually break the module (auto-fixable). Cosmetic lint and
    Tier-3 logic guesses are report-only."""
    kind = str(getattr(f, "kind", "") or "")
    if kind in _REAL_BREAKAGE_KINDS:
        return True
    if kind == "lint":  # pyflakes mixes real "undefined name" with cosmetic warnings
        return "undefined name" in str(getattr(f, "message", "") or "").lower()
    return False


def format_report(paths: List[Path], findings: List[Finding], *, allow_fix: bool = False) -> str:
    """Render the tiered report. `allow_fix` is True only when the user named specific files —
    a broad/sweep audit is REPORT-ONLY and never offers to patch."""
    examined = ", ".join(_rel(p) for p in paths[:8]) + (
        f" (+{len(paths) - 8} more)" if len(paths) > 8 else "")
    lines = [f"Examined {len(paths)} file(s): {examined or '(none)'}"]

    if not findings:
        lines.append("\nNo errors found. Tier 1 (syntax/import) and Tier 2 (static "
                     "lint) are clean; Tier 3 (logic review) flagged nothing concrete.")
        return "\n".join(lines)

    by_tier = {1: [], 2: [], 3: []}
    for f in findings:
        by_tier.get(f.tier, by_tier[3]).append(f)

    headers = {
        1: "Tier 1 — high confidence (syntax / import) — these are real:",
        2: "Tier 2 — medium confidence (static lint):",
        3: "Tier 3 — low confidence (suspected logic, PLEASE CONFIRM before fixing):",
    }
    for tier in (1, 2, 3):
        items = by_tier[tier]
        if not items:
            continue
        lines.append(f"\n{headers[tier]}")
        for f in items:
            loc = f" (line {f.line})" if f.line else ""
            lines.append(f"  - [{f.file}{loc}] {f.message}  (conf {f.confidence:.2f})")

    # Only genuine breakage is offered for fixing, and only when specific files were named.
    fixable = [f for f in findings if is_real_breakage(f)]
    cosmetic = [f for f in findings
                if f.tier in (1, 2) and not is_real_breakage(f)]
    lines.append("")
    if cosmetic:
        lines.append(f"{len(cosmetic)} cosmetic lint finding(s) (unused imports/variables, "
                     "style) are REPORT-ONLY — I won't auto-edit working code for those.")
    if fixable:
        if allow_fix:
            lines.append(f"I found {len(fixable)} genuine breakage finding(s) (syntax / failed "
                         "import / undefined name). I can attempt to fix those — each patch is "
                         "syntax-checked, import-verified, and auto-reverted if it breaks the "
                         "module. Say 'yes' to proceed.")
        else:
            lines.append(f"I found {len(fixable)} genuine breakage finding(s). This was a broad "
                         "audit, so I won't patch from it — ask me to examine the specific "
                         "file(s) by name and I'll offer to fix those.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Fix generation — finding → targeted {file, old, new} patch (broker)         #
# --------------------------------------------------------------------------- #
_FIX_SYS = (
    "You are ELI's code-patch engine. You fix ONE specific issue in a real source file. "
    "'old' MUST be copied CHARACTER-FOR-CHARACTER from the provided code (exact text, exact "
    "whitespace/indentation) — if it is not an exact substring, the patch is rejected. Make the "
    "SMALLEST change that fixes the stated issue and nothing else; preserve all surrounding "
    "behaviour, indentation, and names. Reference ONLY names that already appear in the shown "
    "imports/scope — never invent a module, import, or alias that isn't already available. If you "
    'cannot produce a safe, exact fix, return {"ok": false, "reason": "..."}.'
)


def _enclosing_scope(src: str, line: int) -> Optional[tuple]:
    """1-based (lo, hi) of the SMALLEST function/class enclosing `line` — gives the model the
    complete definition rather than an arbitrary window that may slice it in half. None if the
    file won't parse or the line is top-level."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return None
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lo = node.lineno
            hi = getattr(node, "end_lineno", None) or lo
            if lo <= line <= hi and (best is None or (hi - lo) < (best[1] - best[0])):
                best = (lo, hi)
    return best


def _file_import_block(src: str) -> str:
    """The file's top-level import lines — the names a fix is allowed to reference."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return ""
    segs = []
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            seg = ast.get_source_segment(src, node)
            if seg:
                segs.append(seg)
    return "\n".join(segs[:50])


def _build_fix_context(src: str, line) -> str:
    """Imports (so the model uses only existing names) + the FULL enclosing scope; falls back to a
    ±30-line window, then the file head."""
    lines = src.splitlines()
    if isinstance(line, int) and 1 <= line <= len(lines):
        scope = _enclosing_scope(src, line)
        if scope:
            lo, hi = scope
            body = "\n".join(lines[lo - 1:hi])
            note = f"enclosing scope, lines {lo}-{hi}; issue at line {line}"
        else:
            lo, hi = max(0, line - 30), min(len(lines), line + 30)
            body = "\n".join(lines[lo:hi])
            note = f"lines {lo + 1}-{hi}; issue near line {line}"
    else:
        body = src[:MAX_FILE_CHARS]
        note = "file head"
    body = body[:MAX_FILE_CHARS]
    imports = _file_import_block(src)
    head = (f"# file imports (use ONLY these existing names):\n{imports}\n\n" if imports else "")
    return f"{head}# code ({note}):\n{body}"


def _validate_patch(src: str, patch: Dict[str, Any]) -> Optional[str]:
    """Local pre-flight before the heavier apply engine: 'old' must be a verbatim substring and
    applying it must keep the file parseable. Returns an error string, or None when valid."""
    old, new = patch.get("old"), patch.get("new")
    if not isinstance(old, str) or not old:
        return "patch has an empty 'old'"
    if not isinstance(new, str):
        return "patch 'new' is not a string"
    if old not in src:
        return "old_code not found verbatim in file"
    try:
        ast.parse(src.replace(old, new, 1))
    except SyntaxError as e:
        return f"applying the patch breaks syntax ({e.msg} near line {e.lineno})"
    return None


def _fix_attempt_budget() -> int:
    """Model-agnostic retry budget: a weaker model botches more and needs more attempts, a
    stronger one usually lands attempt 1. Derived from the capability tier (no model identity)."""
    try:
        from eli.core.model_tier import tier_scale
        return max(2, min(4, int(round(5 - tier_scale()))))  # small 1.0→4 … frontier 4.0→2
    except Exception:
        return 3


def generate_fix_patch(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Build a VERIFIED {file, old, new, description} patch for one finding. Gathers the full
    enclosing scope + the file's imports as context, then generates → validates the patch is a
    verbatim, syntax-preserving change → retries with the specific error fed back, up to a
    tier-derived attempt budget. Model-agnostic (broker only). The returned patch is still
    re-validated by SelfImprovementEngine.apply_code_patch (import-verify + auto-revert)."""
    rel = str(finding.get("file") or "").strip()
    if not rel:
        return {"ok": False, "error": "finding has no file"}
    p = (PROJECT_ROOT / rel).resolve()
    if not _inside_project(p) or not p.exists() or p.suffix != ".py":
        return {"ok": False, "error": f"unfixable target: {rel}"}
    try:
        src = p.read_text(encoding="utf-8")
    except Exception as e:
        return {"ok": False, "error": f"read error: {e}"}

    context = _build_fix_context(src, finding.get("line"))
    base_prompt = (
        f"File: {rel}\nIssue ({finding.get('kind')}): {finding.get('message')}\n\n"
        f"```python\n{context}\n```\n\n"
        'Respond with ONLY JSON: {"old": "<verbatim snippet to replace>", '
        '"new": "<replacement>", "description": "<what this fixes>"}'
    )
    try:
        from eli.cognition.inference_broker import get_broker
        _broker = get_broker()
    except Exception as e:
        return {"ok": False, "error": f"inference unavailable: {e}"}

    attempts = _fix_attempt_budget()
    last_err = "no attempt made"
    for _i in range(1, attempts + 1):
        prompt = base_prompt if _i == 1 else (
            base_prompt + f"\n\nYour previous attempt FAILED: {last_err}. Return corrected JSON — "
            "'old' must be copied EXACTLY (character-for-character) from the code above.")
        try:
            raw = _broker.infer(prompt, system=_FIX_SYS, max_tokens=700, temperature=0.05)
        except Exception as e:
            last_err = f"inference failed: {e}"
            continue
        m = re.search(r"\{[\s\S]+\}", raw or "")
        if not m:
            last_err = "model returned no JSON object"
            continue
        try:
            patch = json.loads(m.group(0))
        except Exception as e:
            last_err = f"patch JSON parse failed: {e}"
            continue
        if patch.get("ok") is False or patch.get("reason"):
            # The model explicitly declined — that's a terminal answer, not a retry.
            return {"ok": False, "error": patch.get("reason") or "model declined to patch"}
        if not all(k in patch for k in ("old", "new")):
            last_err = "patch missing old/new"
            continue
        _verr = _validate_patch(src, patch)
        if _verr:
            last_err = _verr
            log.debug(f"[EXAMINE-FIX] {rel}: attempt {_i}/{attempts} rejected — {_verr}")
            continue
        patch["ok"] = True
        patch["file"] = rel
        patch.setdefault("description", f"examine fix: {finding.get('kind')}")
        if _i > 1:
            log.debug(f"[EXAMINE-FIX] {rel}: valid patch on attempt {_i}/{attempts}")
        return patch
    return {"ok": False, "error": f"no valid patch after {attempts} attempts: {last_err}"}


# --------------------------------------------------------------------------- #
# Pending-fix state (mirrors grounded_remediation's pending pattern)          #
# --------------------------------------------------------------------------- #
_PENDING_TTL_SECONDS = 600


def _pending_file() -> Path:
    path = PROJECT_ROOT / "artifacts" / "pending_code_fix.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# Last concrete file path the user referred to this session — so a bare follow-up
# ("please fix the file") can recover the file named a turn earlier instead of failing
# with "Path not found: missing path".
_LAST_FILE: Optional[str] = None


def set_last_file(path: Any) -> None:
    global _LAST_FILE
    _LAST_FILE = str(path or "").strip() or None


def get_last_file() -> Optional[str]:
    return _LAST_FILE


def set_pending_fix(findings: List[Finding], paths: List[Path]) -> None:
    payload = {
        "created_at": time.time(),
        "paths": [_rel(p) for p in paths],
        "findings": [f.to_dict() for f in findings],
    }
    _pending_file().write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                               encoding="utf-8")


def get_pending_fix() -> Optional[Dict[str, Any]]:
    path = _pending_file()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if time.time() - float(payload.get("created_at", 0)) > _PENDING_TTL_SECONDS:
        clear_pending_fix()
        return None
    return payload


def clear_pending_fix() -> None:
    try:
        _pending_file().unlink()
    except FileNotFoundError:
        log.debug("suppressed exception", exc_info=True)


# --------------------------------------------------------------------------- #
# Last-audit persistence — findings survive across turns/restarts so a        #
# follow-up like "list the errors you found" replays the real audit instead   #
# of the model improvising (or admitting the data is gone). No TTL: recall    #
# of the last audit is the whole point.                                       #
# --------------------------------------------------------------------------- #
def _last_audit_file() -> Path:
    path = PROJECT_ROOT / "artifacts" / "code_exam_last.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_last_audit(paths: List[Path], findings: List[Finding]) -> None:
    payload = {
        "created_at": time.time(),
        "paths": [_rel(p) for p in paths],
        "findings": [f.to_dict() for f in findings],
    }
    try:
        _last_audit_file().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.debug("suppressed exception", exc_info=True)  # persistence is best-effort; the live report already went out


def get_last_audit() -> Optional[Dict[str, Any]]:
    path = _last_audit_file()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if payload.get("findings") is not None else None


_RECALL_RE = re.compile(
    r"\b(?:"
    r"(?:list|show|give|enumerate|repeat|recap)\b.{0,60}\b(?:errors?|issues?|findings?|problems?|breakages?)\b.{0,40}\b(?:found|flagged|reported|earlier|before|audit|scan)"
    r"|(?:errors?|issues?|findings?|problems?|breakages?)\b.{0,20}\byou\s+(?:found|flagged|reported)"
    r"|(?:last|previous|that)\s+(?:audit|scan|examination|code\s+exam)"
    # Definite reference to an existing report ("list all of the 43 errors",
    # "show me those issues") — but not a fresh-scan target ("errors in <file>").
    r"|(?:list|show|give|enumerate)\b.{0,40}\b(?:the|those|these|all(?:\s+of)?(?:\s+the)?)\s+(?:\d+\s+)?(?:errors?|issues?|findings?|problems?|breakages?)\b(?!\s+in\b)"
    r")",
    re.I | re.S,
)


def is_recall_request(request: str) -> bool:
    """True when the user is asking to see the findings from the last audit
    (not to run a new one)."""
    return bool(_RECALL_RE.search(str(request or "")))


def format_saved_audit(payload: Dict[str, Any]) -> str:
    """Enumerate EVERY persisted finding — file, line, kind, message — grouped
    by file. This answers "list all of them" exactly; no summarising."""
    findings = payload.get("findings") or []
    paths = payload.get("paths") or []
    when = ""
    try:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(payload.get("created_at", 0))))
    except Exception:
        log.debug("suppressed exception", exc_info=True)
    real = [f for f in findings if is_real_breakage(Finding(**f))]
    lines = [
        f"Findings from my last code audit ({when or 'time unknown'}) — "
        f"{len(paths)} file(s) examined, {len(findings)} finding(s), "
        f"{len(real)} genuine breakage(s):"
    ]
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for f in findings:
        by_file.setdefault(str(f.get("file") or "?"), []).append(f)
    for fname in sorted(by_file):
        lines.append(f"\n{fname}:")
        for f in sorted(by_file[fname], key=lambda x: (x.get("line") or 0)):
            loc = f"line {f['line']}" if f.get("line") else "file-level"
            tag = "BREAKAGE" if is_real_breakage(Finding(**f)) else "cosmetic"
            lines.append(f"  - {loc} [{f.get('kind', '?')}/{tag}] {f.get('message', '')}")
    if not findings:
        lines.append("  (the last audit found nothing)")
    return "\n".join(lines)
