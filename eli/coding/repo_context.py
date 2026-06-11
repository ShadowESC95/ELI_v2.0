"""Repo-context retrieval for the coding agent (Advancement C).

Given a coding task, gather RELEVANT EXISTING project code so the agent writes against
real names / imports / signatures instead of guessing — the lever that turns "fixes its
own source, supervise it" into "fixes its own source reliably". The agent previously
planned and implemented BLIND to the codebase.

Deterministic, offline, bounded: the import blocks of any files named in the task, plus
the definitions of symbols the task mentions. No model, no network. One pass over the tree.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

_ELI_ROOT = Path(__file__).resolve().parents[1]            # eli/
_PROJECT_ROOT = _ELI_ROOT.parent

_DEF_TMPL = r"^\s*(?:async\s+)?def\s+{name}\b|^\s*class\s+{name}\b"
_IMPORT_RE = re.compile(r"\s*(?:import\s|from\s[\w.]+\simport\s)")
_STOP = {
    "the", "and", "for", "with", "that", "this", "code", "file", "files", "function",
    "method", "class", "fix", "fixing", "add", "make", "write", "python", "please",
    "into", "from", "your", "you", "should", "would", "could", "have", "need", "want",
    "task", "test", "tests", "error", "errors", "bug", "issue", "using", "return",
}


def _imports_of(src: str, limit: int = 40) -> str:
    lines = [l for l in src.splitlines() if _IMPORT_RE.match(l)]
    return "\n".join(lines[:limit])


def _named_files(task: str) -> List[Path]:
    try:
        from eli.runtime.code_examiner import _extract_named_paths
        return [p for p in _extract_named_paths(task)
                if p.exists() and p.suffix == ".py"][:4]
    except Exception:
        return []


def _symbol_terms(task: str) -> List[str]:
    terms = []
    for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", task or ""):
        if t.lower() not in _STOP and t not in terms:
            terms.append(t)
    return terms[:8]


def gather_repo_context(task: str, *, max_chars: int = 4000, def_lines: int = 30) -> str:
    """Return a bounded block of relevant existing project code for `task` (or "")."""
    blocks: List[str] = []

    # 1) Files named in the task → their import blocks (real dependencies to match).
    for p in _named_files(task):
        try:
            imps = _imports_of(p.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        rel = p.relative_to(_PROJECT_ROOT)
        blocks.append(f"# {rel} (imports)\n{imps}" if imps else f"# {rel}")

    # 2) Definitions of symbols the task mentions — ONE pass over eli/.
    terms = _symbol_terms(task)
    if terms:
        pats = {t: re.compile(_DEF_TMPL.format(name=re.escape(t))) for t in terms}
        found: Dict[str, str] = {}
        for py in _ELI_ROOT.rglob("*.py"):
            if not pats:
                break
            try:
                lines = py.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            for t in list(pats):
                pat = pats[t]
                for i, line in enumerate(lines):
                    if pat.match(line):
                        rel = py.relative_to(_PROJECT_ROOT)
                        found[t] = f"# {rel}\n" + "\n".join(lines[i:i + def_lines])
                        del pats[t]
                        break
        for t in terms:                       # preserve task order
            if t in found:
                blocks.append(found[t])
                if sum(len(b) for b in blocks) > max_chars:
                    break

    return "\n\n".join(blocks).strip()[:max_chars]
