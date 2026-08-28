"""Portable GGUF / inference diagnostics — model-agnostic, path-agnostic.

Answers grounded questions about load compatibility, runtime version, and the
executor failure log without hardcoding user names, machine paths, or model IDs.
All DB paths come from ``eli.core.paths``; model checks read the GGUF header.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)


def _ts_fmt(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts or "")


def query_executor_failures(*, limit: int = 50) -> List[Dict[str, Any]]:
    """Open failures from agent.sqlite3 (executor post-dispatch), portable."""
    try:
        from eli.core.paths import agent_db_path
        db = Path(agent_db_path())
    except Exception:
        log.debug("agent_db_path unavailable", exc_info=True)
        return []
    if not db.is_file():
        return []
    limit = max(1, min(int(limit or 50), 200))
    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        try:
            if not con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='failures'"
            ).fetchone():
                return []
            rows = con.execute(
                """
                SELECT id, ts, timestamp, command, error, source, status,
                       COALESCE(occurrence_count, 1) AS occurrence_count
                FROM failures
                WHERE COALESCE(status, 'open') NOT IN ('resolved', 'closed')
                ORDER BY COALESCE(timestamp, ts, id) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()
    except Exception:
        log.debug("failure log query failed", exc_info=True)
        return []


def _categorize_failure(row: Dict[str, Any]) -> str:
    cmd = str(row.get("command") or "")
    err = str(row.get("error") or "")
    if cmd.startswith("PLAY_MEDIA"):
        return "PLAY_MEDIA (Spotify unreachable / bad query)"
    if "Unsupported executor action" in err:
        return "Unsupported executor action (router alias not implemented)"
    if cmd.startswith("ANALYZE_PDF"):
        return "ANALYZE_PDF (path parse / not a PDF)"
    if cmd.startswith("MOUSE_CONTROL"):
        return "MOUSE_CONTROL (invalid command)"
    if cmd.startswith("SMART_HOME") or cmd.strip() == "turn off light":
        return "SMART_HOME (no device configured)"
    if cmd.startswith("SHELL_EXEC"):
        return "SHELL_EXEC"
    if cmd.startswith("CHECK_JOB"):
        return "CHECK_JOB (missing job id)"
    if cmd.startswith("GENERATE_DOCUMENT") or "Document generation failed" in err:
        return "Document generation (GGUF unavailable or empty output)"
    if "GGUF" in err.upper():
        return "GGUF inference"
    return "Other executor failure"


def format_failure_log_report(*, limit: int = 50, last_only: bool = False) -> str:
    """Grounded executor-failure audit — NOT GGUF console empty-response events."""
    rows = query_executor_failures(limit=1 if last_only else limit)
    try:
        from eli.core.paths import agent_db_path
        db_path = str(agent_db_path())
    except Exception:
        db_path = "agent.sqlite3"

    if not rows:
        return (
            "Executor failure log (agent.sqlite3 → failures table):\n"
            f"- database: {db_path}\n"
            "- open failures: 0\n\n"
            "Note: this table records executor actions that returned ok=false "
            "(e.g. Spotify unreachable, unsupported action aliases). It does NOT "
            "store GGUF inference console lines such as 'empty response after retry' — "
            "those appear in the terminal log and in runtime_snapshot / load errors."
        )

    cats = Counter(_categorize_failure(r) for r in rows)
    lines = [
        "Executor failure log (agent.sqlite3 → failures table):",
        f"- database: {db_path}",
        f"- open failures shown: {len(rows)}",
        "",
        "Category summary:",
    ]
    for name, count in cats.most_common():
        lines.append(f"  • {count} × {name}")
    lines.append("")
    lines.append("Entries (newest first):")

    for i, r in enumerate(rows, 1):
        cmd = str(r.get("command") or "")[:72]
        err = str(r.get("error") or "").replace("\n", " ")[:140]
        when = _ts_fmt(r.get("timestamp") or r.get("ts"))
        occ = int(r.get("occurrence_count") or 1)
        occ_s = f" (×{occ})" if occ > 1 else ""
        lines.append(f"  {i}. [{when}] {cmd}")
        lines.append(f"     → {err}{occ_s}")

    lines.append("")
    lines.append(
        "These are distinct from GGUF load/inference errors. For model load "
        "compatibility and empty-response diagnosis, ask for a GGUF diagnostics report."
    )
    return "\n".join(lines)


def format_gguf_diagnostics_report(
    *,
    question: str = "",
    model_path: Optional[str] = None,
) -> str:
    """Live GGUF runtime, compatibility preflight, and last load error."""
    from eli.cognition.model_load_diagnostics import (
        MIN_MODERN_ARCH_VERSION,
        gguf_architecture,
        gpu_pack_is_too_old,
        installed_llama_version,
        installed_llama_version_tuple,
        preflight_gguf_model,
    )

    lines: List[str] = ["GGUF diagnostics (live, portable):"]

    ver = installed_llama_version()
    ver_t = installed_llama_version_tuple()
    lines.append(f"- llama-cpp-python: {ver}")
    if gpu_pack_is_too_old():
        lines.append(
            "- active runtime: downloaded GPU pack is older than the bundled runtime "
            f"(needs >={'.'.join(map(str, MIN_MODERN_ARCH_VERSION))} for Nemotron / hybrid SSM). "
            "Try ELI_DISABLE_GPU_PACK=1 for one run, or reinstall the GPU pack."
        )
    min_ver = ".".join(map(str, MIN_MODERN_ARCH_VERSION))
    if ver_t and ver_t < MIN_MODERN_ARCH_VERSION:
        lines.append(
            f"- runtime note: installed {ver} is below {min_ver}. "
            "Hybrid attention+SSM and Nemotron architectures require an upgrade: "
            "pip install -U 'llama-cpp-python>={min_ver}'"
        )

    # Loaded / configured model
    snap_model = ""
    load_err = ""
    try:
        from eli.runtime.deterministic_grounding_gate import _inference_runtime_lines
        lines.append("")
        lines.append(_inference_runtime_lines())
    except Exception:
        log.debug("inference runtime block unavailable", exc_info=True)

    try:
        from eli.cognition import gguf_inference as gi
        ov = gi.get_live_runtime_override() or gi.get_last_load_params() or {}
        if ov.get("model_path"):
            snap_model = str(ov.get("model_name") or ov.get("model_path"))
        load_err = str(getattr(gi, "_last_load_error", "") or "").strip()
    except Exception:
        log.debug("gguf_inference state unavailable", exc_info=True)

    # Optional explicit model path (e.g. Nemotron the user asked about)
    check_paths: List[Path] = []
    if model_path:
        check_paths.append(Path(str(model_path)).expanduser())
    else:
        try:
            from eli.cognition.gguf_inference import get_model_path
            mp = get_model_path()
            if mp:
                check_paths.append(Path(str(mp)).expanduser())
        except Exception:
            log.debug("get_model_path unavailable", exc_info=True)
        try:
            from eli.core.runtime_settings import load_settings
            settings = load_settings() or {}
            for key in ("bundled_model_path", "custom_model_path", "model_path", "gguf_model_path"):
                raw = settings.get(key)
                if raw:
                    p = Path(str(raw)).expanduser()
                    if p not in check_paths:
                        check_paths.append(p)
        except Exception:
            log.debug("settings model paths unavailable", exc_info=True)

    if load_err:
        lines.extend(["", "Last GGUF load error on this session:", f"  {load_err[:800]}"])

    compat_blocks: List[str] = []
    for p in check_paths:
        if not p.is_file():
            continue
        arch = gguf_architecture(p) or "unknown"
        pre = preflight_gguf_model(p)
        block = [f"Model file: {p.name}", f"  architecture (from GGUF header): {arch}"]
        if pre:
            block.append(f"  preflight: WILL NOT LOAD on this runtime — {pre[:500]}")
        else:
            block.append("  preflight: architecture appears compatible with this runtime")
        compat_blocks.append("\n".join(block))

    if compat_blocks:
        lines.extend(["", "Model compatibility (header-based, not filename guesses):"])
        lines.extend(compat_blocks)

    lines.extend([
        "",
        "Common GGUF inference failures (console, not in failures table):",
        "  • 'unknown model architecture' — upgrade llama-cpp-python (>={})".format(min_ver),
        "  • 'missing tensor … ssm_conv1d' — hybrid SSM model on old runtime or stale GPU pack",
        "  • 'Empty after cleaning' / 'empty response after retry' — thinking model burned "
        "the token budget inside a reasoning block, or generation was aborted during shutdown",
        "  • Slow replies with few output tokens — requested GPU layers exceed VRAM; effective "
        "layers run partly on CPU (see requested vs effective in inference runtime above)",
    ])

    q = (question or "").strip()
    if q:
        lines.extend(["", f"Question context: {q[:200]}"])
    return "\n".join(lines)


__all__ = [
    "format_failure_log_report",
    "format_gguf_diagnostics_report",
    "query_executor_failures",
]
