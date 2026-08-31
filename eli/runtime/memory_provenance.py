"""Memory provenance and verification tier for grounded recall.

Every durable fact carries:
  - verification_status: verified | hypothesis | system
  - provenance_kind: how the fact entered the store

Only *verified* memories may ground user-biography claims in CHAT synthesis.
Hypothesis-tier rows (auto-extract, inferred) are retained for audit and explicit
memory queries but are excluded from default grounding retrieval.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERIFIED = "verified"
HYPOTHESIS = "hypothesis"
SYSTEM = "system"

PROV_USER_VERBATIM = "user_verbatim"
PROV_USER_CONFIRMED = "user_confirmed"
PROV_AUTO_EXTRACT = "auto_extract"
PROV_INFERRED = "inferred"
PROV_TOOL_OBSERVATION = "tool_observation"
PROV_SYSTEM = "system_generated"

_EXCLUDED_FOR_GROUNDING = frozenset({HYPOTHESIS, SYSTEM})

_EXPLICIT_MEMORY_AUDIT_RE = re.compile(
    r"\b("
    r"what do you (?:know|remember)(?: about me)?|what have i told you|"
    r"do you remember|what(?:'s| is) in my (?:memory|profile)|"
    r"stored about me|from memory|show (?:my )?memories|list (?:my )?memories|"
    r"memory audit|unverified memories|hypothesis(?:es)?|what did i say about"
    r")\b",
    re.IGNORECASE,
)


def _tag_set(tags: Any) -> set[str]:
    if tags is None:
        return set()
    if isinstance(tags, str):
        return {t.strip().lower() for t in tags.split(",") if t.strip()}
    out: set[str] = set()
    for item in tags:
        s = str(item or "").strip().lower()
        if s:
            out.add(s)
    return out


def resolve_write_provenance(
    *,
    source: str = "user",
    kind: str = "memory",
    tags: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """Return (verification_status, provenance_kind) for a new memory row."""
    meta = dict(metadata or {})
    if meta.get("verification_status") and meta.get("provenance_kind"):
        return str(meta["verification_status"]), str(meta["provenance_kind"])

    tags_l = _tag_set(tags)
    src = str(source or "user").strip().lower()
    knd = str(kind or "memory").strip().lower()

    if "user_confirmed" in tags_l or meta.get("user_confirmed"):
        return VERIFIED, PROV_USER_CONFIRMED
    if "auto_extracted" in tags_l or meta.get("auto_extracted"):
        return HYPOTHESIS, PROV_AUTO_EXTRACT
    if src in {"tool", "executor", "observation"} or "tool_observation" in tags_l:
        return VERIFIED, PROV_TOOL_OBSERVATION
    if knd in {"reflection", "session_summary", "awareness", "proactive", "system"}:
        return SYSTEM, PROV_SYSTEM
    if src in {"awareness", "reflection", "proactive", "system", "daemon"}:
        return SYSTEM, PROV_SYSTEM
    if src == "assistant" or knd == "assistant_insight":
        return HYPOTHESIS, PROV_INFERRED
    if src == "user":
        return VERIFIED, PROV_USER_VERBATIM
    return VERIFIED, PROV_USER_VERBATIM


def is_explicit_memory_audit_query(text: str) -> bool:
    """True when the user is explicitly auditing memory (include hypothesis tier)."""
    return bool(_EXPLICIT_MEMORY_AUDIT_RE.search(str(text or "")))


def verification_filter_sql(
    cols: Iterable[str],
    *,
    alias: str = "",
    verified_only: bool = True,
) -> Tuple[str, tuple]:
    """SQL fragment excluding non-grounding tiers when verified_only=True."""
    if not verified_only:
        return "", ()
    col_set = {str(c).lower() for c in cols}
    if "verification_status" not in col_set:
        # Pre-migration DB: fall back to tag-based exclusion for auto_extract.
        prefix = alias or ""
        return (
            f" AND LOWER(COALESCE({prefix}tags, '')) NOT LIKE '%auto_extracted%' ",
            (),
        )
    prefix = alias or ""
    return (
        f" AND COALESCE({prefix}verification_status, '{VERIFIED}') NOT IN "
        f"('{HYPOTHESIS}', '{SYSTEM}') ",
        (),
    )


def hit_is_grounding_eligible(hit: Dict[str, Any]) -> bool:
    status = str(hit.get("verification_status") or VERIFIED).strip().lower()
    if status in _EXCLUDED_FOR_GROUNDING:
        return False
    tags = _tag_set(hit.get("tags"))
    if "auto_extracted" in tags and status == VERIFIED:
        # Legacy row before migration — treat as hypothesis.
        return False
    return True


def filter_grounding_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [h for h in (hits or []) if hit_is_grounding_eligible(h)]


def format_grounding_memory_line(hit: Dict[str, Any]) -> str:
    mid = hit.get("id", "?")
    txt = (hit.get("text") or hit.get("content") or "").strip()
    status = str(hit.get("verification_status") or VERIFIED)
    prov = str(hit.get("provenance_kind") or "")
    prov_bit = f" prov={prov}" if prov else ""
    return f"  - [memory_id={mid} status={status}{prov_bit}] {txt}"


def promote_hypothesis_to_verified(conn, memory_id: int) -> bool:
    """Promote a hypothesis memory after explicit user confirmation."""
    try:
        cur = conn.execute(
            """
            UPDATE memories
            SET verification_status = ?, provenance_kind = ?,
                tags = CASE
                    WHEN COALESCE(tags, '') = '' THEN 'user_confirmed'
                    WHEN INSTR(LOWER(tags), 'user_confirmed') > 0 THEN tags
                    ELSE tags || ',user_confirmed'
                END
            WHERE id = ? AND COALESCE(verification_status, ?) = ?
            """,
            (VERIFIED, PROV_USER_CONFIRMED, int(memory_id), VERIFIED, HYPOTHESIS),
        )
        return cur.rowcount > 0
    except Exception:
        return False
