"""ELI repair playbook — decision guide for self-maintenance, code examine, and upgrades.

Grounded, offline-safe guidance for which mechanism fixes which class of problem.
Consumed by SELF_REPAIR_PLAYBOOK (executor) and maintenance help surfaces.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

# Problem class → recommended user phrase → internal action
_REPAIR_ROUTES: Tuple[Tuple[str, str, str], ...] = (
    (
        "recurring_runtime_failure",
        'Say: "self analyse" then "self fix"',
        "SELF_PATCH",
    ),
    (
        "deterministic_known_bug",
        'Say: "self fix" (deterministic rules run first)',
        "SELF_PATCH",
    ),
    (
        "named_file_breakage",
        'Say: "examine eli/path/to/file.py for errors" then "yes, fix it"',
        "EXAMINE_CODE",
    ),
    (
        "gui_wiring_audit",
        'Say: "examine eli/gui/eli_pro_audio_gui_v2_0.py for errors"',
        "EXAMINE_CODE",
    ),
    (
        "install_or_release",
        'Say: "self upgrade"',
        "SELF_UPGRADE",
    ),
    (
        "overlay_refresh_only",
        'Say: "self update" (manifest/overlays — not a version bump)',
        "SELF_UPDATE",
    ),
    (
        "proposals_without_apply",
        'Say: "self improve" or "generate patch" then review before "self fix"',
        "SELF_IMPROVE",
    ),
    (
        "user_input_validation",
        "No patch — clarify the command (mouse/job/voice args). Not a code defect.",
        "NONE",
    ),
    (
        "cosmetic_lint_only",
        "Report-only — manual lint pass; broad EXAMINE_CODE will not auto-patch lint.",
        "NONE",
    ),
    (
        "tier3_logic_guess",
        "Confirm with Tier 1/2 or AST import — Tier 3 syntax claims are often false positives.",
        "NONE",
    ),
)


def recommend_repair_path(user_input: str) -> Dict[str, Any]:
    """Map a natural-language repair question to the best ELI mechanism."""
    low = re.sub(r"\s+", " ", str(user_input or "").lower()).strip()
    if not low:
        return {"action": "SELF_REPAIR_PLAYBOOK", "reason": "empty", "confidence": 0.5}

    if re.search(r"\b(self help|repair playbook|maintenance playbook|fix playbook|"
                 r"how do i fix|which self command|what should i run)\b", low):
        return {
            "action": "SELF_REPAIR_PLAYBOOK",
            "reason": "explicit_playbook_request",
            "confidence": 0.99,
        }

    if re.search(r"\b(upgrade|update eli|new version|appimage|release)\b", low):
        return {"action": "SELF_UPGRADE", "reason": "install_layer", "confidence": 0.92}

    if re.search(r"\b(examine|audit|scan|review)\b.{0,40}\b(gui|gui file)\b", low):
        return {
            "action": "EXAMINE_CODE",
            "reason": "scoped_gui_examine",
            "confidence": 0.94,
            "hint": "examine eli/gui/eli_pro_audio_gui_v2_0.py for errors",
        }

    if re.search(r"\b(examine|audit|scan)\b.{0,30}\b(file|module|\.py)\b", low):
        return {"action": "EXAMINE_CODE", "reason": "file_targeted_examine", "confidence": 0.90}

    if re.search(r"\b(self fix|self patch|fix your code|fix those errors)\b", low):
        return {"action": "SELF_PATCH", "reason": "failure_driven_patch", "confidence": 0.95}

    if re.search(r"\b(self analyse|self analyze|analyse failures|analyze failures)\b", low):
        return {"action": "SELF_ANALYZE", "reason": "failure_report", "confidence": 0.95}

    if re.search(r"\b(self improve|improvement cycle|generate patch)\b", low):
        return {"action": "SELF_IMPROVE", "reason": "improvement_cycle", "confidence": 0.90}

    if re.search(r"\b(lint|unused import|cosmetic|style warning)\b", low):
        return {"action": "NONE", "reason": "cosmetic_lint_only", "confidence": 0.85}

    if re.search(r"\b(mouse|levitate|sideways|which job)\b", low):
        return {"action": "NONE", "reason": "user_input_validation", "confidence": 0.88}

    return {"action": "SELF_REPAIR_PLAYBOOK", "reason": "default_playbook", "confidence": 0.75}


def _live_maintenance_snapshot() -> List[str]:
    lines: List[str] = []
    try:
        from eli.core.paths import patch_capability, source_root

        cap = patch_capability()
        lines.append(f"- patch_root: {source_root()}")
        lines.append(f"- patch_capability: {cap}")
    except Exception as exc:
        lines.append(f"- patch_capability: unavailable ({exc!r})")

    try:
        from eli.runtime.self_improvement import get_self_improvement
        from eli.runtime.failure_taxonomy import classify, is_actionable

        rows = get_self_improvement().memory.get_recent_failures(limit=15) or []
        actionable = []
        skipped_user = 0
        for r in rows:
            err = str(r.get("error") or r.get("user_input") or "")
            info = classify(err, command=str(r.get("command") or ""))
            if not is_actionable(info.get("category", "")):
                skipped_user += 1
                continue
            actionable.append(r)
        lines.append(f"- recent_failures_total: {len(rows)}")
        lines.append(f"- recent_failures_actionable: {len(actionable)}")
        lines.append(f"- recent_failures_user_input_skipped: {skipped_user}")
        if actionable:
            top = actionable[0]
            lines.append(
                f"- top_actionable: {(top.get('error') or top.get('user_input') or '')[:100]}"
            )
    except Exception as exc:
        lines.append(f"- failure_snapshot: unavailable ({exc!r})")

    return lines


def build_repair_playbook_report(question: str = "", *, live: bool = True) -> str:
    """Full grounded playbook for GUI/CLI — no GGUF synthesis required."""
    q = str(question or "").strip()
    rec = recommend_repair_path(q) if q else {"action": "SELF_REPAIR_PLAYBOOK", "reason": "overview"}

    lines = [
        "ELI repair playbook (advanced self-maintenance)",
        "",
        "Use the right mechanism for the problem class:",
        "",
        "1. Recurring runtime failures (agent DB, clustered errors)",
        "   → self analyse  →  self improve  →  self fix",
        "   Code: eli/runtime/self_maintenance.py → run_patch_cycle()",
        "",
        "2. Known deterministic bugs (aliases, bad params)",
        "   → self fix (deterministic_failure_patches runs first)",
        "",
        "3. One specific file with real breakage (syntax / failed import)",
        '   → examine eli/path/to/module.py for errors  →  "yes, fix it"',
        "   Code: eli/runtime/code_examiner.py (Tier 1–2 fixable; Tier 3 confirm only)",
        "",
        "4. GUI wiring audit (not a 25-file git sweep)",
        "   → examine eli/gui/eli_pro_audio_gui_v2_0.py for errors",
        "",
        "5. Install / version bump (AppImage, git pull, pip, index rebuild)",
        "   → self upgrade",
        "",
        "6. Overlay refresh only (not a release)",
        "   → self update",
        "",
        "Do NOT use self-fix for:",
        "  • USER_INPUT validation (invalid mouse/job/voice args — working as designed)",
        "  • Cosmetic lint (unused imports, f-string style) on broad audits",
        "  • Tier 3 logic guesses — often false positives; verify Tier 1/2 or import first",
        "",
        "Examine tiers:",
        "  Tier 1 — syntax/import (real, fixable when file named)",
        "  Tier 2 — static lint (report-only unless undefined name)",
        "  Tier 3 — LLM logic review (low confidence — confirm before any patch)",
        "",
        "AppImage patching:",
        "  Set ELI_SOURCE_ROOT=/path/to/git/checkout to patch dev tree from frozen build.",
        "  Writable overlay: ~/.local/share/ELI_v2/eli/ (see patch_capability).",
    ]

    if q:
        lines.extend([
            "",
            f"Your question: {q[:300]}",
            f"Recommended: {rec.get('action')} ({rec.get('reason')}, conf={rec.get('confidence')})",
        ])
        if rec.get("hint"):
            lines.append(f"Try: {rec['hint']}")

    if live:
        lines.extend(["", "Live snapshot:"])
        lines.extend(_live_maintenance_snapshot())

    lines.extend([
        "",
        "Quick map:",
    ])
    for _key, phrase, action in _REPAIR_ROUTES:
        lines.append(f"  • {phrase}  [{action}]")

    return "\n".join(lines)


def maintenance_help_short() -> str:
    """Compact help for maintenance_surface_help()."""
    return (
        "ELI self-maintenance:\n"
        "  self help / repair playbook — this decision guide (grounded)\n"
        "  self analyse   — failure report + root causes\n"
        "  self improve   — log improvements + proposals (no apply)\n"
        "  self fix       — deterministic + LLM patches (guarded apply)\n"
        "  self upgrade   — install update\n"
        "  examine <file> — tiered code scan; confirm to patch named files only\n"
        'Say "repair playbook" for the full advanced guide.'
    )


__all__ = [
    "build_repair_playbook_report",
    "maintenance_help_short",
    "recommend_repair_path",
]
