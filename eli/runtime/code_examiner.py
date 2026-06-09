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


def _tier3(path: Path) -> List[Finding]:
    rel = _rel(path)
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    if not src.strip():
        return []
    # Number every source line with its REAL line number so the model cites real lines
    # (previously the file was sliced at MAX_FILE_CHARS mid-line, so cited line numbers
    # mapped to the truncated window — pure hallucination, e.g. "engine.py:132 undefined
    # 'ov'" when line 132 is `or result.get("error")`). Never cut mid-line.
    _lines = src.splitlines()
    _numbered = [f"{i + 1}\t{ln}" for i, ln in enumerate(_lines)]
    body_parts: List[str] = []
    total = 0
    for nl in _numbered:
        if total + len(nl) + 1 > MAX_FILE_CHARS:
            break
        body_parts.append(nl)
        total += len(nl) + 1
    shown_to = len(body_parts)            # last real line number the model can see
    truncated = shown_to < len(_lines)
    body = "\n".join(body_parts)
    prompt = (
        f"Review this Python file ({rel}) for concrete bugs.\n"
        "Each source line is prefixed with its REAL line number and a tab — cite that "
        "exact number in 'line'; never guess a line you cannot see.\n"
        + (f"NOTE: only lines 1-{shown_to} are shown (rest truncated); do NOT report "
           "anything about code you cannot see.\n" if truncated else "")
        + "Respond with ONLY a JSON array; each item: "
        '{"line": <int>, "issue": "<specific bug>"}. '
        "Empty array [] if nothing concrete is wrong.\n\n"
        f"```python\n{body}\n```"
    )
    try:
        from eli.cognition.inference_broker import get_broker
        raw = get_broker().infer(prompt, system=_TIER3_SYS, max_tokens=400, temperature=0.1)
    except Exception as e:
        log.debug(f"[EXAMINE] tier-3 review skipped for {rel}: {e}")
        return []

    m = re.search(r"\[[\s\S]*\]", raw or "")
    if not m:
        return []
    try:
        items = json.loads(m.group(0))
    except Exception:
        return []
    findings: List[Finding] = []
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
        # Reject a finding that cites a line the model never saw (1..shown_to). The 7B
        # otherwise invents line numbers/issues for code outside the shown window.
        if line is not None and not (1 <= line <= shown_to):
            continue
        findings.append(Finding(rel, 3, TIER_CONF[3], "logic", issue,
                                line=line, needs_confirmation=True))
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


def format_report(paths: List[Path], findings: List[Finding]) -> str:
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

    n_fixable = len([f for f in findings if not f.needs_confirmation])
    n_confirm = len([f for f in findings if f.needs_confirmation])
    lines.append("")
    if n_fixable:
        lines.append(f"I can attempt to fix the {n_fixable} high/medium-confidence "
                     "finding(s) — each patch is syntax-checked, import-verified, and "
                     "auto-reverted if it breaks the module. Say 'yes' to proceed.")
    if n_confirm:
        lines.append(f"The {n_confirm} Tier-3 item(s) are low-confidence guesses — "
                     "I will only touch them if you explicitly confirm those too "
                     "('yes, including the logic ones').")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Fix generation — finding → targeted {file, old, new} patch (broker)         #
# --------------------------------------------------------------------------- #
_FIX_SYS = (
    "You are ELI's code-patch engine. Produce the smallest correct fix for the "
    "stated issue. 'old' MUST be copied character-for-character from the provided "
    "code window. Change only what's needed. If you cannot produce a safe fix, "
    'return {"ok": false, "reason": "..."}.'
)


def generate_fix_patch(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Build a targeted {file, old, new, description} patch for one finding using
    a code window around the reported line. Returns {"ok": False, ...} when no safe
    patch is produced. The patch is applied by SelfImprovementEngine.apply_code_patch
    (which re-validates syntax, smoke-imports, and auto-reverts)."""
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

    lines = src.splitlines()
    line = finding.get("line")
    if isinstance(line, int) and 1 <= line <= len(lines):
        lo, hi = max(0, line - 25), min(len(lines), line + 25)
        window = "\n".join(lines[lo:hi])
        window_note = f"(lines {lo + 1}-{hi}, issue near line {line})"
    else:
        window = src[:MAX_FILE_CHARS]
        window_note = "(file head)"

    prompt = (
        f"File: {rel}\nIssue ({finding.get('kind')}): {finding.get('message')}\n\n"
        f"Code window {window_note}:\n```python\n{window}\n```\n\n"
        'Respond with ONLY JSON: {"old": "<verbatim snippet to replace>", '
        '"new": "<replacement>", "description": "<what this fixes>"}'
    )
    try:
        from eli.cognition.inference_broker import get_broker
        raw = get_broker().infer(prompt, system=_FIX_SYS, max_tokens=600, temperature=0.05)
    except Exception as e:
        return {"ok": False, "error": f"inference failed: {e}"}

    m = re.search(r"\{[\s\S]+\}", raw or "")
    if not m:
        return {"ok": False, "error": "model returned no JSON patch"}
    try:
        patch = json.loads(m.group(0))
    except Exception as e:
        return {"ok": False, "error": f"patch JSON parse failed: {e}"}
    if patch.get("ok") is False or patch.get("reason"):
        return {"ok": False, "error": patch.get("reason") or "model declined to patch"}
    if not all(k in patch for k in ("old", "new")):
        return {"ok": False, "error": "patch missing old/new"}
    patch["ok"] = True
    patch["file"] = rel
    patch.setdefault("description", f"examine fix: {finding.get('kind')}")
    return patch


# --------------------------------------------------------------------------- #
# Pending-fix state (mirrors grounded_remediation's pending pattern)          #
# --------------------------------------------------------------------------- #
_PENDING_TTL_SECONDS = 600


def _pending_file() -> Path:
    path = PROJECT_ROOT / "artifacts" / "pending_code_fix.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
        pass
