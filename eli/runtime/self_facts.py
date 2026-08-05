"""Verified facts about ELI's own construction, assembled from live sources.

Why this exists
---------------
Asked "what do you know of yourself?", ELI answered in CHAT — correctly, because
identity questions are deliberately left conversational so the persona stays its
own (SELF_REPORT is reserved for technical runtime queries). But CHAT had no
grounding for *factual* claims about internals, so the model improvised them:
it reported its databases at ``/home/jason/...`` (the real user is ``jay``, the
name came from the user's first name), named ``agent.sqlite`` instead of
``agent.sqlite3``, and invented a self-upgrade mechanism — ``./upgrade.sh`` —
that has never existed in this project.

Every fact below is READ FROM THE RUNNING SYSTEM. Nothing here is a literal
describing ELI; if a value cannot be determined it is omitted rather than
guessed, so the block can never itself become a source of confabulation.

This is the self-descriptive counterpart to ``self_status.py`` (which grounds
physical/telemetry answers with the same discipline).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

# Reviewed identity/continuity canon. It exists in the repo and was, until now,
# consumed only by the LoRA training pipeline — never at runtime, which left
# conversational identity questions with no authoritative source at all.
_CANON_REL = "training/datasets/eli_self_model_seed.reviewed.jsonl"
_CANON_MAX = 6


def _version() -> str:
    """Single source of truth for the running version — shared with self_upgrade,
    which reads pyproject first for the same reason: installed dist metadata goes
    stale on a version bump and would inject a wrong fact here."""
    try:
        from eli.kernel.self_upgrade import SelfUpgrader
        v = SelfUpgrader()._local_version()
        if v and v != "0.0.0":
            return v
    except Exception:
        log.debug("version lookup failed", exc_info=True)
    return ""


def _database_paths() -> List[str]:
    """The REAL database files, straight from the path resolver."""
    out: List[str] = []
    try:
        from eli.core import paths as _p
        for label, fn in (("user", getattr(_p, "user_db_path", None)),
                          ("agent", getattr(_p, "agent_db_path", None))):
            if callable(fn):
                out.append(f"{label} DB: {fn()}")
    except Exception:
        log.debug("db path lookup failed", exc_info=True)
    return out


def _capability_count() -> str:
    try:
        from eli.core.paths import project_root
        manifest = project_root() / "capability_manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            total = data.get("total") or len(data.get("capabilities") or [])
            if total:
                return str(int(total))
    except Exception:
        log.debug("capability manifest read failed", exc_info=True)
    return ""


def _components() -> List[str]:
    """Real component names from the AST-derived import graph."""
    try:
        from eli.runtime.codebase_graph import components
        return [str(c) for c in (components() or [])][:14]
    except Exception:
        log.debug("codebase graph unavailable", exc_info=True)
        return []


def _upgrade_mechanism() -> str:
    """How this install actually upgrades — so the model stops inventing scripts."""
    try:
        from eli.kernel.self_upgrade import _install_kind
        kind = _install_kind()
    except Exception:
        return ""
    if kind == "appimage":
        return ("upgrade path: download the newer .AppImage from the GitHub release and "
                "verify its SHA256 (eli/kernel/self_upgrade.py). There is no upgrade shell script.")
    if kind == "frozen":
        return ("upgrade path: reinstall from the platform installer in the GitHub release. "
                "There is no upgrade shell script.")
    return ("upgrade path: git pull + pip install on this source checkout "
            "(eli/kernel/self_upgrade.py). There is no upgrade shell script.")


def _canon_lines(limit: int = _CANON_MAX) -> List[str]:
    try:
        from eli.core.paths import project_root
        p = project_root() / _CANON_REL
        if not p.is_file():
            return []
        out: List[str] = []
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            resp = str(row.get("response") or "").strip()
            if resp:
                out.append(resp)
            if len(out) >= limit:
                break
        return out
    except Exception:
        log.debug("self-model canon read failed", exc_info=True)
        return []


def get_self_facts() -> Dict[str, Any]:
    """Structured verified self-facts. Missing values are omitted, never guessed."""
    facts: Dict[str, Any] = {}
    if (v := _version()):
        facts["version"] = v
    if (dbs := _database_paths()):
        facts["databases"] = dbs
    if (caps := _capability_count()):
        facts["capabilities"] = caps
    if (comps := _components()):
        facts["components"] = comps
    if (up := _upgrade_mechanism()):
        facts["upgrade"] = up
    try:
        from eli.kernel.self_upgrade import _install_kind
        facts["install_kind"] = _install_kind()
    except Exception:
        log.debug("install kind unavailable", exc_info=True)
    return facts


_ABS_PATH_RX = re.compile(r"(?:/home/[^/\s'\"`)]+|~)(?:/[^\s'\"`),]+)+")
_UPGRADE_SCRIPT_RX = re.compile(
    r"(?:scripts?\s+like\s+)?[`'\"]?(?:\./)?(?:upgrade|update|self[_-]?upgrade)\.(?:sh|bat|ps1)[`'\"]?",
    re.I,
)


def repair_self_description(text: str) -> Tuple[str, List[str]]:
    """Correct fabricated internals in a self-descriptive reply.

    Returns (repaired_text, corrections). The prompt block tells the model to use
    real values, but instruction alone is not a guarantee — the observed failure
    put the databases under ``/home/jason`` and invented ``./upgrade.sh``. A path
    or script that ELI states about ITSELF is checkable, so it is checked.

    Deliberately narrow: only ELI's own paths and upgrade mechanism are touched.
    Paths the user mentioned, or that genuinely exist, are left alone.
    """
    original = str(text or "")
    if not original.strip():
        return original, []
    # Cheap pre-check so this can sit on every reply: no path and no script
    # token means there is nothing here that could be a fabricated internal,
    # and we skip building the (comparatively expensive) fact set entirely.
    if "/home/" not in original and "~/" not in original and not _UPGRADE_SCRIPT_RX.search(original):
        return original, []

    facts = get_self_facts()
    corrections: List[str] = []
    out = original

    # Known real paths, by basename, so a fabricated directory can be corrected
    # rather than merely flagged.
    real_by_name: Dict[str, str] = {}
    for entry in facts.get("databases", []):
        _, _, p = str(entry).partition(": ")
        p = p.strip()
        if p:
            real_by_name[Path(p).name] = p

    for match in set(_ABS_PATH_RX.findall(out)):
        if match in out and any(match == v for v in real_by_name.values()):
            continue
        name = Path(match).name
        # "agent.sqlite" for "agent.sqlite3" — same slot, truncated name.
        candidate = real_by_name.get(name)
        if candidate is None:
            for real_name, real_path in real_by_name.items():
                if real_name.startswith(name) or name.startswith(real_name):
                    candidate = real_path
                    break
        if candidate and candidate != match:
            out = out.replace(match, candidate)
            corrections.append(f"path {match} -> {candidate}")
        elif Path(match).expanduser().exists():
            continue
        else:
            corrections.append(f"unverified path mentioned: {match}")

    if _UPGRADE_SCRIPT_RX.search(out):
        replacement = facts.get("upgrade") or "its documented upgrade path"
        out = _UPGRADE_SCRIPT_RX.sub("[no such script]", out)
        corrections.append(f"invented upgrade script removed; real: {replacement}")

    return out, corrections


def render_self_facts_block(include_canon: bool = True) -> str:
    """The persona-handoff block. '' when nothing could be verified."""
    facts = get_self_facts()
    if not facts:
        return ""

    lines = [
        "[VERIFIED SELF-FACTS — REAL, READ FROM THIS RUNNING SYSTEM. If you describe your own "
        "construction, storage, or upgrade mechanism, use THESE values verbatim. Do NOT invent "
        "file paths, script names, or components: if something is not listed here, say you are "
        "not sure rather than producing a plausible-looking answer.]"
    ]
    if facts.get("version"):
        lines.append(f"  version: {facts['version']}")
    if facts.get("install_kind"):
        lines.append(f"  install kind: {facts['install_kind']}")
    for db in facts.get("databases", []):
        lines.append(f"  {db}")
    if facts.get("capabilities"):
        lines.append(f"  capabilities in the manifest: {facts['capabilities']}")
    if facts.get("components"):
        lines.append(f"  real components: {', '.join(facts['components'])}")
    if facts.get("upgrade"):
        lines.append(f"  {facts['upgrade']}")

    if include_canon:
        canon = _canon_lines()
        if canon:
            lines.append("  reviewed identity canon (your own settled positions):")
            for c in canon:
                lines.append(f"    - {c[:240]}")
    return "\n".join(lines)
