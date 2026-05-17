from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Mapping, Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

BAD_RESPONSE_PATTERNS = [
    # Generic assistant poison
    re.compile(r"\bAs\s+an?\s+AI\b", re.I),
    re.compile(r"\bAI\s+language\s+model\b", re.I),
    re.compile(r"\btrained\s+by\s+OpenAI\b", re.I),
    re.compile(r"\bstarting\s+a\s+new\s+conversation\b", re.I),
    re.compile(r"\bprevious\s+interactions\s+may\s+not\s+be\s+readily\s+available\b", re.I),
    re.compile(r"\brest\s+assured\b", re.I),

    # Runtime / router / execution artifacts
    re.compile(r"^\s*Searching\s+for\s*:", re.I),
    re.compile(r"^\s*Search\s+query\s*:", re.I),
    re.compile(r"^\s*Looking\s+up\s*:", re.I),
    re.compile(r"^\s*Script\s+generated\s*:", re.I),
    re.compile(r'"event"\s*:\s*"artifact_generated"', re.I),
    re.compile(r"^\s*Action\s+.+\s+not\s+implemented", re.I),
    re.compile(r"^\s*Route\s*:", re.I),
    re.compile(r"^\s*Input\s*:", re.I),
    re.compile(r"^\s*Mode\s*:", re.I),
    re.compile(r"^\s*Render_preview\s*:", re.I),

    # Stack/error surfaces
    re.compile(r"\bTraceback\s+\(most\s+recent\s+call\s+last\)", re.I),
    re.compile(r"\bFile\s+\".*?\",\s+line\s+\d+", re.I),
    re.compile(r"\bNameError\b|\bTypeError\b|\bImportError\b|\bModuleNotFoundError\b", re.I),

    # Secrets/tokens
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgho_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
]


def normalise_text(text: object) -> str:
    s = "" if text is None else str(text)
    s = s.replace(str(PROJECT_ROOT), "<PROJECT_ROOT>")
    s = re.sub(r"/home/[A-Za-z0-9._-]+", "<HOME>", s)
    s = re.sub(r"/Users/[A-Za-z0-9._-]+", "<HOME>", s)
    # PHASE16C_WINDOWS_HOME_REDACTION
    s = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "<HOME>", s)
    s = re.sub(r"\s+\n", "\n", s)
    s = re.sub(r"\n{4,}", "\n\n\n", s)
    return s.strip()


def is_bad_response(response: object) -> bool:
    text = normalise_text(response)
    if len(text) < 12:
        return True
    return any(p.search(text) for p in BAD_RESPONSE_PATTERNS)


def row_is_reviewed(row: Mapping[str, Any]) -> bool:
    tags = [str(x).lower() for x in (row.get("tags") or [])]
    src = str(row.get("source") or "").lower()
    return "reviewed" in tags or src.startswith("manual:")


def row_instruction_key(row: Mapping[str, Any]) -> str:
    return normalise_text(row.get("instruction", "")).lower()


def row_pair_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        normalise_text(row.get("instruction", "")).lower(),
        normalise_text(row.get("response", "")).lower(),
    )


def clean_row(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["instruction"] = normalise_text(out.get("instruction", ""))
    out["response"] = normalise_text(out.get("response", ""))

    tags = out.get("tags") or []
    tags = ["reviewed" if str(t) == "revJSONL" else str(t) for t in tags]
    out["tags"] = tags

    if "weight" not in out:
        out["weight"] = 0.35

    return out


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")


# ELI_LEARNING_SCAFFOLD_LEAKAGE_FILTER_V1
# Appended wrapper: reject internal reasoning/scoring scaffold leakage even if
# the original BAD_RESPONSE pattern-list layout changes.
import re as _eli_learning_re

_ELI_SCAFFOLD_LEAKAGE_RE = [
    _eli_learning_re.compile(r"\bhighest[- ]scoring\s+approach\b", _eli_learning_re.I),
    _eli_learning_re.compile(r"\bfeasibility\s+score\s+of\s+\d+(?:\.\d+)?(?:/\d+)?\b", _eli_learning_re.I),
    _eli_learning_re.compile(r"\brated\s+\d+(?:\.\d+)?\b", _eli_learning_re.I),
    _eli_learning_re.compile(r"\bscore(?:d)?\s+\d+(?:\.\d+)?(?:/\d+)?\b", _eli_learning_re.I),
    _eli_learning_re.compile(r"\bUser[- ]Centric\s+Perspective\b", _eli_learning_re.I),
    _eli_learning_re.compile(r"\bFocused\s+Memory\s+&\s+Execution\s+Breakdown\b", _eli_learning_re.I),
    _eli_learning_re.compile(r"\bcritique\s+pass\b", _eli_learning_re.I),
    _eli_learning_re.compile(r"\brevision\s+pass\b", _eli_learning_re.I),
]

_eli_original_is_bad_response = is_bad_response

def is_bad_response(text):  # type: ignore[override]
    t = str(text or "")
    return bool(_eli_original_is_bad_response(t) or any(rx.search(t) for rx in _ELI_SCAFFOLD_LEAKAGE_RE))
