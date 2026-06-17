from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from eli.cognition.reasoning_modes import apply_final_reasoning_contract
except Exception:  # pragma: no cover - fallback during partial imports
    def apply_final_reasoning_contract(text, mode=None):
        return str(text or "")

_ERROR_PATTERNS = (
    "gguf streaming failed", "gguf error", "model not ready",
    "requested tokens", "exceed context window", "inference failed",
    "context window", "broker unavailable", "gguf returned empty", "llama_",
)
# Strips chat-template role leaks from the start of LLM output. Added
# "User" variants after observing mistral-7b-instruct-v0.2 opening replies
# Prevent awkward assistant identity/address boilerplate in normal replies.
# the wrong role marker. Matches at string start only; mid-sentence "user"
# is left alone (that is a persona-handoff issue, not a prefix leak).
_ROLE_PREFIX_RE = re.compile(
    r"^\s*[\"“‘']?\s*(?:"
    r"As\s+ELI(?:\s*[,:\-—])?\s*"
    r"|As\s+(?:an?\s+)?(?:AI\s+(?:assistant|model)|Assistant|AI|model|system|local\s+assistant|language\s+model|LLM)(?:\s*[,:\-—])?\s*"
    r"|Speaking\s+as\s+ELI(?:\s*[,:\-—])?\s*"
    r"|In\s+(?:my|ELI(?:'s)?)\s+(?:role|persona|voice)(?:\s+as\s+ELI)?(?:\s*[,:\-—])?\s*"
    r"|ELI\s*[:\-—]\s*"
    r"|Assistant\s*[:\-—]\s*"
    r"|AI\s*[:\-—]\s*"
    r"|<\|assistant\|>\s*"
    r"|User\s*[:\-—]\s*"
    r"|User\s+[A-Za-z]{2,20}(?:\s+[A-Za-z]{2,20})?\s*[,:]\s+"
    r"|User\s*,\s+"
    r")",
    re.IGNORECASE,
)
_OUTER_FENCE_RE = re.compile(
    r"^```(?P<lang>[a-zA-Z0-9_\-+]*)\n(?P<body>.+)\n```\s*$", re.DOTALL
)

_PLACEHOLDER_IDENTITY_RE = re.compile(
    r"(?i)"
    r"\[(?:user|name|username)\]"
    r"|<(?:local_user|username|name|redacted_name|redacted|stored_name)>"
)


def _strip_placeholder_identity(text: str) -> str:
    result = (text or "").strip()
    if not result:
        return ""

    result = _PLACEHOLDER_IDENTITY_RE.sub("unknown", result)
    result = re.sub(r"(?i)<REDACTED_NAME>", "unknown", result)
    result = re.sub(r"(?i)<REDACTED>", "unknown", result)
    result = re.sub(r"(?i)User\s*--\s*\[has_name\]\s*-->\s*unknown", "unknown", result)
    result = re.sub(r"(?i)\bunknown(?:\s+unknown)+\b", "unknown", result)
    result = re.sub(r"\s{2,}", " ", result).strip(" ,:-")
    return result

def normalize_assistant_text(user_input: str, text: str) -> str:
    result = (text or "").strip()
    if not result:
        return ""
    result = apply_final_reasoning_contract(result).strip()
    result = _ROLE_PREFIX_RE.sub("", result).strip()
    result = _strip_placeholder_identity(result).strip()
    if user_input:
        first_line = result.split("\n", 1)[0].strip()
        if first_line.lower() == user_input.strip().lower():
            result = result[len(first_line):].strip()
    result = _strip_placeholder_identity(result).strip()
    try:
        result = repair_local_persona_drift(result, user_input=user_input).strip()
    except Exception:
        pass
    return result


# No-Fake-Actions: a real action's outcome is delivered by the executor, never narrated by the
# model. A bracketed pseudo-tool-confirmation in the prose ("[Pause command executed
# successfully.]", "[Command executed]", "[Done — command ran]") is therefore always fabrication —
# the model imitating a tool result it never produced. The pattern is specific to
# execution/command-completion claims, so legitimate source tags ("[BBC — 14:23]",
# "[HackerNews/tech]") and ordinary brackets are never touched. Model-agnostic.
_FAKE_TOOL_CONFIRMATION_RE = re.compile(
    r"\s*\[[^\]\n]*?(?:"
    r"\bexecut(?:ed|ing|ion|es)\b"
    r"|\bcommand\b[^\]\n]*?\b(?:success\w*|complet\w*|done|ran)\b"
    r"|\b(?:success\w*|complet\w*|done|ran)\b[^\]\n]*?\bcommand\b"
    r")[^\]\n]*?\]",
    re.IGNORECASE,
)


def strip_fabricated_action_claims(text: str) -> str:
    """Remove model-fabricated tool/command confirmations (No-Fake-Actions). Model-agnostic."""
    return _FAKE_TOOL_CONFIRMATION_RE.sub("", str(text or ""))


def govern_output(text: str, is_grounded: bool = False,
                  evidence: Optional[str] = None) -> str:
    result = apply_final_reasoning_contract(text).strip()
    result = _strip_placeholder_identity(result).strip()
    if not result:
        return ""
    result = _ROLE_PREFIX_RE.sub("", result).strip()
    # Strip any inline second occurrence ("…\n\nAs ELI: …" etc.)
    result = re.sub(
        r"(?im)^\s*(?:as\s+eli|as\s+(?:an?\s+)?assistant|eli|assistant|ai)\s*[:\-—]\s*",
        "",
        result,
    ).strip()
    result = strip_generic_ai_identity_drift(result).strip()
    result = repair_self_user_confusion(result).strip()
    result = clean_response_style(result).strip()
    # No-Fake-Actions: drop fabricated "[… command executed …]" tool-confirmations the model
    # invents when narrating an action that never actually ran (model-agnostic guard).
    result = strip_fabricated_action_claims(result).strip()
    m = _OUTER_FENCE_RE.match(result)
    if m:
        body = m.group("body")
        if "```" not in body:
            result = body.strip()
    return result


def normalize_response(user_input: str, text: str) -> str:
    result = govern_output(text or "")
    result = normalize_assistant_text(user_input or "", result)
    return result or ""


normalise_assistant_text = normalize_assistant_text
normalise_response = normalize_response


_GENERIC_AI_IDENTITY_RE = re.compile(
    r"(?is)^\s*(?:"
    r"i[' ]?m an artificial intelligence[^.?!]*(?:[.?!]\s*)?"
    r"|i am an artificial intelligence[^.?!]*(?:[.?!]\s*)?"
    r"|as an artificial intelligence[^.?!]*(?:[.?!]\s*)?"
    r"|as an ai(?: assistant| model)?[^.?!]*(?:[.?!]\s*)?"
    r"|i do(?:n't| not) have a head[^.?!]*(?:[.?!]\s*)?"
    r"|i do(?:n't| not) have a physical body[^.?!]*(?:[.?!]\s*)?"
    r")+"
)

def strip_generic_ai_identity_drift(text: str) -> str:
    result = (text or "").strip()
    if not result:
        return ""

    cleaned = _GENERIC_AI_IDENTITY_RE.sub("", result).strip()

    # Only replace with the drift placeholder if the regex actually matched
    # AND there is nothing useful left. Short legitimate answers ("Yes.",
    # "hello world") must pass through untouched when no drift was detected.
    if cleaned == result:
        return cleaned

    if not cleaned or len(cleaned.split()) < 3:
        return "Running. That response drifted into generic model-speak; ignoring it."

    return cleaned


_MEDICAL_METAPHOR_DRIFT_RE = re.compile(
    r"(?is)"
    r"(open[- ]head surgery|open[- ]brain surgery|craniotomy|bone flap|brain tumor|epilepsy|"
    r"scalp|skull|surgeon|post-surgery|rehabilitation)"
)

_LOCAL_REPAIR_FRAME_RE = re.compile(
    r"(?is)"
    r"(open[- ](?:head|brain)\s+surgery|"
    r"performed\s+open[- ](?:head|brain)\s+surgery\s+on\s+(?:you|eli)|"
    r"(?:persona|memory|cognition|runtime|code)\s+(?:repair|surgery|update|drift))"
)

_GENERIC_MEMORY_IDENTITY_DRIFT_RE = re.compile(
    r"(?is)"
    r"(i do(?:n't| not) have personal memories|"
    r"i do(?:n't| not) have emotions|"
    r"i do(?:n't| not) have the ability to sense emotions|"
    r"i do(?:n't| not) have (?:a )?physical (?:brain|body|head)"
    r"(?:\s+or\s+(?:brain|body|head))?[^.?!]*(?:[.?!]\s*)?|"
    r"i (?:cannot|can't) remember any surgical procedure"
    r"(?:\s+in\s+(?:this|that)\s+context)?(?:[.?!]\s*)?|"
    r"beyond what is programmed|"
    r"i am an artificial intelligence)"
)


def repair_local_persona_drift(text: str, user_input: str = "") -> str:
    result = str(text or "").strip()
    if not result:
        return ""

    # The old branch replaced *any* answer containing one of the medical drift
    # keywords, even when the user's current prompt had nothing to do with ELI
    # repair/surgery metaphors. That can corrupt unrelated phatic replies.
    # Only emit the corrective "Wrong frame" response when the *user prompt*
    # itself carries the local-repair metaphor frame.
    _eli_phase13_repair_prompt = str(user_input or "")
    _eli_phase13_repair_context = bool(
        _LOCAL_REPAIR_FRAME_RE.search(_eli_phase13_repair_prompt)
    )
    if _eli_phase13_repair_context and (
        _MEDICAL_METAPHOR_DRIFT_RE.search(result)
        or _GENERIC_MEMORY_IDENTITY_DRIFT_RE.search(result)
    ):
        return (
            "Wrong frame. You meant surgery on ELI - code/persona/memory repair - "
            "not human neurosurgery. The response drifted into generic medical "
            "filler and should be regenerated from local system context."
        )
    if _GENERIC_MEMORY_IDENTITY_DRIFT_RE.search(result):
        result = _GENERIC_MEMORY_IDENTITY_DRIFT_RE.sub("", result).strip()
        result = re.sub(
            r"(?is)\b(?:however,\s+)?if\s+we\s+are\s+speaking\s+literally\b[, ]*",
            "",
            result,
        )
        result = re.sub(r"(?is)\bif\s+you\s+meant\s+something\s+else,\s+please\s+clarify\b[. ]*", "", result)
        result = re.sub(r"\s{2,}", " ", result).strip(" .,:;-")
        if not result or len(result.split()) < 4:
            return (
                "Persona drift detected. ELI should answer from local memory/runtime context, "
                "not generic AI disclaimers."
            )

    return result


# Style polish (HR-ish phrasing) — applied via clean_response_style().
# Stripping of "As ELI:" / "ELI:" / "Assistant:" prefixes is handled by
# _ROLE_PREFIX_RE inside govern_output().

_HR_PHRASE_REPLACEMENTS = (
    (re.compile(r"\bI'd be pleased to delve deeper into\b", re.I), "Here is the useful version of"),
    (re.compile(r"\bI'd be happy to provide more details about\b", re.I), "Here is more detail on"),
    # Strip the entire "feel free to ask [...]" clause — not just the phrase.
    # "Feel free to ask if you have questions." → stripped entirely.
    (re.compile(r"[^.!?\n]*\bfeel free to ask\b[^.!?\n]*[.!?]?\s*", re.I), ""),
    # Strip "I'd be happy/pleased to [do X]." — whole closing clause.
    (re.compile(r"[^.!?\n]*\bI(?:'d| would) be (?:happy|pleased|glad) to\b[^.!?\n]*[.!?]?\s*", re.I), ""),
    # Strip "Don't hesitate to ask [...]."
    (re.compile(r"[^.!?\n]*\bdon'?t hesitate to ask\b[^.!?\n]*[.!?]?\s*", re.I), ""),
    # Strip "Let me know if [you need anything / you have questions]."
    (re.compile(r"[^.!?\n]*\blet me know if (?:you|there)[^.!?\n]*[.!?]?\s*", re.I), ""),
    # Strip "Is there anything else I can [help/assist] [you with]?"
    (re.compile(r"[^.!?\n]*\bis there anything else I can\b[^.!?\n]*[.!?]?\s*", re.I), ""),
    (re.compile(r"\ba wealth of information\b", re.I), "stored information"),
    (re.compile(r"\breadily accessible\b", re.I), "available"),
    (re.compile(r"\bplease note that\b", re.I), "note:"),
    (re.compile(r"\bI hope this helps\b[^.!?\n]*[.!?]?\s*", re.I), ""),
    (re.compile(r"\bHope this helps\b[^.!?\n]*[.!?]?\s*", re.I), ""),
)


def clean_response_style(text: str) -> str:
    """Replace HR-ish stock phrases without touching technical content."""
    if not isinstance(text, str):
        return text
    out = text.strip()
    for pat, rep in _HR_PHRASE_REPLACEMENTS:
        out = pat.sub(rep, out)
    return out.strip()


# Self/user confusion repair — parameterised from runtime profile, not hardcoded.
# When the model says "my X is <user-fact>", rewrite to attribute the fact to
# the user. The rewriter pulls user identity from runtime state so shipped
# source stays user-neutral.

_USER_FACT_KEYS = (
    "github_handle", "github", "handle", "username",
    "research_focus", "research", "occupation", "role", "project",
    "first_name", "last_name", "full_name",
)


def _runtime_user_facts() -> Dict[str, str]:
    """Best-effort fetch of stored facts about the local user.

    Reads from eli.kernel.state.get_user_name() and the user_profile table if
    available. Returns {} on any failure — repair becomes a no-op.
    """
    facts: Dict[str, str] = {}
    try:
        from eli.kernel.state import get_user_name as _gun
        name = (_gun("") or "").strip()
        if name:
            facts["full_name"] = name
            parts = name.split()
            if parts:
                facts["first_name"] = parts[0]
            if len(parts) > 1:
                facts["last_name"] = parts[-1]
    except Exception:
        pass
    try:
        from eli.kernel.state import load_user_profile as _lup
        prof = _lup() or {}
        # Map preferred_name → first_name if set
        pref = (prof.get("preferred_name") or "").strip()
        if pref:
            facts["first_name"] = pref
        full = (prof.get("name") or "").strip()
        if full and "full_name" not in facts:
            facts["full_name"] = full
        for k, v in (prof or {}).items():
            if k in _USER_FACT_KEYS and v:
                facts[k] = str(v).strip()
    except Exception:
        pass
    return facts


_PRONOUN_OWNER_RE = re.compile(
    r"\b(?:I\s+(?:have|use|am|work\s+on)|my)\b",
    re.IGNORECASE,
)


def repair_self_user_confusion(text: str) -> str:
    """Catch first-person framings of facts that belong to the user.

    Example: model says "my GitHub handle is ShadowESC95" while the runtime
    profile records that handle for the user. Rewrites to attribute the fact
    to the user by stored name, so ELI does not impersonate the operator.
    """
    result = str(text or "").strip()
    if not result:
        return ""
    facts = _runtime_user_facts()
    if not facts:
        return result

    name = facts.get("first_name") or facts.get("full_name") or "the user"

    for key in ("github_handle", "github", "handle", "username"):
        val = facts.get(key)
        if not val:
            continue
        val_re = re.escape(val)
        result = re.sub(
            rf"\bI\s+(?:have|use)\s+(?:a|the|an)?\s*(?:GitHub\s+)?handle\s+(?:of\s+|is\s+)?{val_re}\b",
            f"{name}'s GitHub handle is {val}",
            result,
            flags=re.IGNORECASE,
        )
        result = re.sub(
            rf"\bmy\s+(?:GitHub\s+)?handle\s+is\s+{val_re}\b",
            f"{name}'s GitHub handle is {val}",
            result,
            flags=re.IGNORECASE,
        )
        # Bare "I am ShadowESC95" / "I'm ShadowESC95" — pure self-as-user impersonation
        result = re.sub(
            rf"\bI\s*['’]?\s*m\s+{val_re}\b|\bI\s+am\s+{val_re}\b",
            f"the user is {name} (GitHub: {val})",
            result,
            flags=re.IGNORECASE,
        )

    research = facts.get("research_focus") or facts.get("research")
    if research:
        result = re.sub(
            rf"\bI\s+work\s+on\s+{re.escape(research)}\b",
            f"{name} works on {research}",
            result,
            flags=re.IGNORECASE,
        )

    return result


# ─────────────────────────────────────────────────────────────────────
# Evidence validator: structured "no claim without evidence" gate.
#
# Used by control/diagnostic synthesis paths and the engine final pass
# to ensure model output cannot:
#   - Reference filesystem paths that are neither in evidence nor on disk
#   - Reference filenames as concrete artifacts not present in evidence
#   - Quote runtime parameter values (n_ctx, gpu_layers, batch, threads)
#     not present in evidence
#   - Emit ToT/critique scaffolding leakage ("Core Idea:", "Feasibility: 8/10",
#     "P1: PASS|FAIL", numbered approach lists)
#   - Emit PASS/FAIL audit lines for files not in the evidence audit
#   - Emit catastrophic verbatim fabrication signatures observed in past
#     failures (system-prefix paths and known-bad filenames). User-specific
#     home paths are caught at runtime via `_check_cross_user_home_paths`,
#     which resolves the live user on each call so this module ships portable.
#   - Get truncated mid-thought without a terminal punctuation mark
#
# Sanitization modes:
#   strip_silent → remove offending sentences (cleaner, default for control)
#   mark_inline  → wrap offenders as <unverified: …> (preserves shape, default for chat)
# ─────────────────────────────────────────────────────────────────────

# Path body ends in a word/slash/hyphen char so trailing sentence
# punctuation (period, comma, paren) is left out of the captured path.
# Without this, `/home/.../file.py.` would capture the trailing `.` and
# fail an evidence-equality check against the same path written without
# the sentence period.
_PATH_BODY = r"[\w./\-]*[\w/\-]"
_FAB_PATH_PREFIXES_RX = re.compile(
    r"(?<![\w/])"
    r"(?:/home/" + _PATH_BODY +
    r"|/usr/local/lib/" + _PATH_BODY +
    r"|/usr/" + _PATH_BODY +
    r"|/etc/" + _PATH_BODY +
    r"|/var/" + _PATH_BODY +
    r"|/tmp/" + _PATH_BODY +
    r"|/opt/" + _PATH_BODY + r")"
)

_FILENAME_RX = re.compile(
    r"(?<![\w/.\-])"
    r"([A-Za-z_][\w\-]*\.(?:py|json|sqlite3|gguf|md|yaml|yml|so|sh|toml|cfg|ini))"
    r"(?![\w])"
)

_RUNTIME_NUM_RX = re.compile(
    r"\b(n_ctx|context\s*size|gpu[_\s]?layers|n_gpu_layers|"
    r"batch[_\s]?size|n_batch|cpu[_\s]?threads|n_threads|max[_\s]?tokens)"
    r"\s*[:=]\s*"
    r"(\d{2,7})\b",
    re.IGNORECASE,
)

_TOT_SCAFFOLDING_RXES = (
    re.compile(r"^\s*\d+\.\s+[A-Z][\w\s\-/&]+?\s*\n\s*Core\s+Idea\s*:", re.MULTILINE),
    re.compile(r"\bFeasibility\s*:\s*\d+\s*/\s*10\b", re.IGNORECASE),
    re.compile(r"\bP\d+\s*:\s*(?:PASS|FAIL)\s*\|\s*(?:PASS|FAIL)", re.IGNORECASE),
    re.compile(r"\b(?:Tree of Thoughts|ToT|Self[-\s]Consistency|Constitutional AI)\s+(?:proposed|developed|generated)\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*The\s+highest[-\s]?scoring\s+approach\s+is\b", re.IGNORECASE | re.MULTILINE),
)

_PASS_FAIL_AUDIT_RX = re.compile(
    r"(?:^|\n)\s*(PASS|FAIL)\s+([\w./\-]+\.(?:py|json|sqlite3|so|sh))",
    re.IGNORECASE,
)

# Generic verbatim fabrication signatures — system-prefix or filename
# patterns that no live runtime would legitimately produce. These are
# user-agnostic. User-specific home paths (output references a home
# directory whose username is not the live user) are handled below by
# `_check_cross_user_home_paths`, which resolves the live user at
# runtime so this module ships portable (no machine-specific
# identifiers in source).
_FAB_VERBATIM_SIGNATURES = (
    "/usr/local/lib/eli/",
    "gpu_status.so",
)

_HOME_USER_PATH_RX = re.compile(r"/home/([\w\-]+)/[\w./\-]*[\w/\-]")


def _live_user_home_name() -> Optional[str]:
    """Live user's home directory name, resolved at runtime."""
    try:
        return Path.home().name or None
    except Exception:
        return None


def _check_cross_user_home_paths(out: str, ev: str) -> List[Dict[str, str]]:
    """Catch paths under another user's home directory not present in evidence.

    Any output reference to a home-directory path whose username segment
    differs from the live user (and which is not in the evidence packet)
    is treated as a catastrophic fabrication signature — runtime answers
    must never quote cross-user home paths the live system has no way
    to verify.
    """
    live = _live_user_home_name()
    if not live:
        return []
    found: List[Dict[str, str]] = []
    seen = set()
    for match in _HOME_USER_PATH_RX.finditer(out):
        path = match.group(0)
        user = match.group(1)
        if user == live:
            continue
        if path in ev:
            continue
        if path in seen:
            continue
        seen.add(path)
        found.append({
            "kind": "fabricated_signature",
            "value": path,
            "reason": f"path references different user (live user is '{live}') and is not in evidence",
        })
    return found

_EVASIVE_PHRASES = (
    "what specific information were you looking for",
    "what specific aspect",
    "please clarify",
    "feel free to ask",
    "let me know if",
    "how can i assist you today",
    "i'd be happy to",
    "i'll report back",
    "once the audit is complete",
    # Templated/canned phrases caught 2026-05-11 in Jay's session — these
    # are LLM filler that contradicts the persona's "no HR voice / no
    # generic chatbot" rule. The persona instructions list more (delve
    # deeper, wealth of information, readily accessible, etc.) — covered
    # here so the model's output is scrubbed even when persona rules get
    # truncated out of the system prompt under heavy context pressure.
    "that's an interesting question",
    "i apologize for the incomplete response",
    "i'd be pleased",
    "delve deeper",
    "a wealth of information",
    "readily accessible",
    "i appreciate your patience",
    "i appreciate your interest",
    "here's a brief overview",
    "based on the provided evidence",
    "based on the data you've provided",
    "based on the data provided",
    "based on the information provided",
    "as an ai language model",
    "as a language model",
    "i'm here to assist",
    "i'm here to help",
    "i cannot provide an answer to that question",
)


def _looks_truncated(text: str) -> bool:
    t = (text or "").rstrip()
    if not t:
        return False
    last_char = t[-1]
    if last_char in ".!?\"')]>}…":
        return False
    # Mid-word cut with substantive prior content
    if t[-1].isalnum() and len(t.split()) > 8:
        return True
    return False


def _strip_violating_lines(text: str, needle: str) -> str:
    """Remove every line that contains `needle`.

    Used for filesystem path / filename / audit-line violations: those
    artifacts almost always live on their own line (bullets, numbered
    items) or in short prose lines, and a sentence-level strip leaves
    orphan suffixes when filenames contain dots (`/foo/bar.py` →
    sentence regex stops at the `.`, leaves `py` behind). Whole-line
    strip is correct for the failure modes this validator targets.
    """
    if not needle or not text:
        return text
    return "\n".join(line for line in text.split("\n") if needle not in line)



# === ELI_PHASE19_EVIDENCE_VALIDATOR_TRUTH_LOCK_V1 ===
_ELI_PHASE19_GOV_LINE_CLAIM_RX = re.compile(
    r"\blines?\s+((?:\d+\s*(?:(?:,|/|-|and|or)\s*)?)+)",
    re.IGNORECASE,
)
_ELI_PHASE19_GOV_MUTATION_CLAIM_RX = re.compile(
    r"\b(?:"
    r"i(?:'|’)?ll\s+(?:delete|remove|fix|patch|edit|change|apply)"
    r"|i\s+will\s+(?:delete|remove|fix|patch|edit|change|apply)"
    r"|i(?:'|’)?ve\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r"|i\s+have\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r"|i\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r"|already\s+(?:deleted|removed|fixed|patched|edited|changed|applied)"
    r")\b",
    re.IGNORECASE,
)

def _eli_phase19_gov_line_claims(text: str) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for match in _ELI_PHASE19_GOV_LINE_CLAIM_RX.finditer(str(text or "")):
        numbers = re.findall(r"\d+", match.group(1) or "")
        if numbers:
            claims.append({"raw": match.group(0), "numbers": numbers})
    return claims

# === END ELI_PHASE19_EVIDENCE_VALIDATOR_TRUTH_LOCK_V1 ===

def validate_against_evidence(
    text: Any,
    evidence: Any = "",
    *,
    mode: str = "strip_silent",
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate model output against the supplied evidence packet.

    Args:
      text: The model's synthesized output.
      evidence: The evidence packet the model was given (deterministic
        executor output, runtime snapshot, etc.).
      mode: Sanitization mode. "strip_silent" removes violating sentences
        (cleaner output, default for control actions). "mark_inline" wraps
        violators as <unverified: …> (preserves shape, better for chat).
      project_root: Optional project root for filesystem existence checks.

    Returns:
      {
        "ok": bool,            # No violations at all
        "unsafe": bool,        # Output is fundamentally compromised; caller
                               # should fall back to deterministic evidence
        "sanitized": str,      # Output with violations addressed per `mode`
        "violations": [{"kind": str, "value": str, "reason": str}, ...],
        "stats": {
          "claims_total": int,
          "claims_unverified": int,
          "ratio": float,      # unverified / total (0.0 if no claims)
        },
      }
    """
    out = str(text or "")
    ev = str(evidence or "")
    if not out.strip():
        return {
            "ok": False,
            "unsafe": True,
            "sanitized": "",
            "violations": [{"kind": "empty", "value": "", "reason": "no output"}],
            "stats": {"claims_total": 0, "claims_unverified": 0, "ratio": 0.0},
        }

    violations: List[Dict[str, str]] = []
    sanitized = out
    claims_total = 0
    claims_unverified = 0
    catastrophic = False

    ev_lower = ev.lower()
    out_lower = out.lower()

    # 1. Catastrophic verbatim fabrication signatures
    for sig in _FAB_VERBATIM_SIGNATURES:
        if sig in out and sig not in ev:
            violations.append({
                "kind": "fabricated_signature",
                "value": sig,
                "reason": "verbatim hallucination signature observed in past failures",
            })
            catastrophic = True

    # 1b. Cross-user home-directory paths — resolved at runtime so the
    # detector stays portable. References to a home directory belonging
    # to a different user, when not present in evidence, are catastrophic.
    for v in _check_cross_user_home_paths(out, ev):
        violations.append(v)
        catastrophic = True

    # 2. ToT / critique scaffolding leakage
    for rx in _TOT_SCAFFOLDING_RXES:
        m = rx.search(out)
        if m:
            violations.append({
                "kind": "scaffolding_leakage",
                "value": m.group(0)[:80],
                "reason": "planning/critique scaffold leaked into final answer",
            })
            sanitized = rx.sub("", sanitized)
            catastrophic = True

    # 3. Filesystem paths
    seen_paths = set()
    for match in _FAB_PATH_PREFIXES_RX.findall(out):
        if match in seen_paths:
            continue
        seen_paths.add(match)
        claims_total += 1
        if match in ev:
            continue
        try:
            if Path(match).exists():
                continue
        except Exception:
            pass
        # Allow project-rooted prefix match (paths under runtime project_root
        # that do exist when checked against the live filesystem)
        claims_unverified += 1
        violations.append({
            "kind": "fabricated_path",
            "value": match,
            "reason": "path not in evidence and not on filesystem",
        })

    # 4. Numeric runtime parameter values
    for key, val in _RUNTIME_NUM_RX.findall(out):
        claims_total += 1
        val_str = str(val)
        if val_str in ev:
            continue
        claims_unverified += 1
        violations.append({
            "kind": "fabricated_runtime_value",
            "value": f"{key.strip()}={val_str}",
            "reason": "runtime parameter value not present in evidence",
        })

    # 5. PASS/FAIL audit lines for specific files
    for status, fname in _PASS_FAIL_AUDIT_RX.findall(out):
        claims_total += 1
        if fname in ev:
            continue
        claims_unverified += 1
        violations.append({
            "kind": "fabricated_audit_line",
            "value": f"{status} {fname}",
            "reason": "audit line for file not in evidence audit results",
        })

    # 5b. Phase 19 exact line-number truth lock.
    # A grounded answer may mention concrete line numbers only if every such
    # number appears in the evidence packet provided to synthesis.
    for claim in _eli_phase19_gov_line_claims(out):
        claims_total += 1
        missing = [num for num in claim.get("numbers", []) if str(num) not in ev]
        if not missing:
            continue
        claims_unverified += 1
        violations.append({
            "kind": "fabricated_line_reference",
            "value": str(claim.get("raw") or ""),
            "reason": "line number reference not present in evidence",
        })

    # 5c. Phase 19 fake-mutation truth lock.
    # Claims that a code edit was or will be applied must be evidenced. Audit
    # synthesis may propose a fix, but it cannot represent an edit as executed.
    mutation_match = _ELI_PHASE19_GOV_MUTATION_CLAIM_RX.search(out)
    if mutation_match:
        claims_total += 1
        mutation_phrase = re.sub(r"\s+", " ", mutation_match.group(0).lower()).strip()
        if mutation_phrase not in ev_lower:
            claims_unverified += 1
            violations.append({
                "kind": "unsupported_mutation_claim",
                "value": mutation_match.group(0),
                "reason": "code mutation claim not present in evidence",
            })
            catastrophic = True

    # 6. Truncated mid-thought
    if _looks_truncated(out):
        violations.append({
            "kind": "truncated",
            "value": out[-40:],
            "reason": "output appears cut off mid-thought",
        })

    # 7. Evasive / clarifying-question patterns in answer position
    for phrase in _EVASIVE_PHRASES:
        if phrase in out_lower:
            violations.append({
                "kind": "evasive_phrase",
                "value": phrase,
                "reason": "evasive/clarifying-question pattern stands in for grounded answer",
            })
            catastrophic = True
            break

    # 7b. Fabricated TEMPLATE PLACEHOLDERS — e.g. "[Story 1]", "[insert headline]",
    # "[TBD]". The model emitting fill-in-the-blank tokens instead of real content
    # is a fake answer (it pretended to have data it didn't). Never let it reach
    # the user. (Real source tags like "[BBC — 14:23]" are not matched.)
    _placeholder_rx = re.compile(
        r"\[\s*(?:story|item|headline|insert[^\]]*|placeholder|details?|tbd|todo|xxx)\s*\d*\s*\]",
        re.I,
    )
    _ph_match = _placeholder_rx.search(out)
    if _ph_match:
        violations.append({
            "kind": "fabricated_placeholder",
            "value": _ph_match.group(0),
            "reason": "template placeholder stands in for real content (fake/fabricated output)",
        })
        catastrophic = True

    # Apply sanitization mode
    if mode == "strip_silent":
        for v in violations:
            kind = v["kind"]
            if kind in ("fabricated_path", "fabricated_signature", "fabricated_audit_line", "fabricated_line_reference", "unsupported_mutation_claim"):
                sanitized = _strip_violating_lines(sanitized, v["value"])
            elif kind == "fabricated_runtime_value":
                key_part = v["value"].split("=", 1)[0].strip()
                num_part = v["value"].split("=", 1)[1].strip() if "=" in v["value"] else ""
                # Strip lines containing both the parameter name AND the value
                if num_part:
                    sanitized = "\n".join(
                        line for line in sanitized.split("\n")
                        if not (key_part.lower() in line.lower() and num_part in line)
                    )
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    elif mode == "mark_inline":
        for v in violations:
            kind = v["kind"]
            if kind in ("fabricated_path", "fabricated_signature", "fabricated_audit_line", "fabricated_line_reference", "unsupported_mutation_claim"):
                sanitized = sanitized.replace(v["value"], f"<unverified: {v['value']}>")
            elif kind == "fabricated_runtime_value":
                # mark inline near the key
                sanitized = sanitized.replace(v["value"], f"<unverified: {v['value']}>")

    ratio = (claims_unverified / claims_total) if claims_total else 0.0
    unsafe = bool(
        catastrophic
        or ratio >= 0.4
        or (claims_total >= 3 and claims_unverified >= 2)
        or not sanitized.strip()
    )
    ok = not violations

    return {
        "ok": ok,
        "unsafe": unsafe,
        "sanitized": sanitized,
        "violations": violations,
        "stats": {
            "claims_total": claims_total,
            "claims_unverified": claims_unverified,
            "ratio": ratio,
        },
    }


# ===========================================================================
# MERGED: low-level sanitizer (was eli.cognition.response_sanitizer)
# ===========================================================================
_STAGE_PREFIX_RE = re.compile(
    r'^\s*(?:eli|assistant|calmly|quietly|softly|gently|warmly|plainly|dryly)\s*:\s*["\']?',
    re.IGNORECASE,
)
_PLACEHOLDER_RE = re.compile(
    r'(?i)(?:\[(?:user|username|name)\]|<(?:user|local_user|username|name)>)'
)
# Generic assistant-speak openers that contradict ELI's dry personality.
# Strip only when they are the FULL opening clause (followed by comma/space/newline).
_FILLER_OPENER_RE = re.compile(
    r'^\s*(?:'
    r'of course[,!.]?\s*'
    r'|certainly[,!.]?\s*'
    r'|sure(?:\s+thing)?[,!.]?\s*'
    r'|absolutely[,!.]?\s*'
    r'|happy\s+to\s+help[,!.]?\s*'
    r'|great\s+question[,!.]?\s*'
    r'|excellent\s+question[,!.]?\s*'
    r'|good\s+question[,!.]?\s*'
    r'|that\'s\s+a\s+great\s+(?:question|point)[,!.]?\s*'
    r'|i\'d\s+be\s+happy\s+to[,!.]?\s*'
    r'|i\'m\s+glad\s+you\s+asked[,!.]?\s*'
    r'|short\s+answer\s*:\s*'
    r')',
    re.IGNORECASE,
)

def sanitize_assistant_text(text: Any) -> str:
    out = apply_final_reasoning_contract(text)
    out = _STAGE_PREFIX_RE.sub("", out)
    out = _FILLER_OPENER_RE.sub("", out)
    out = _PLACEHOLDER_RE.sub("", out)
    out = re.sub(r"^[\s\"']+|[\s\"']+$", "", out)
    out = re.sub(r'\s{2,}', ' ', out)
    out = re.sub(r'\s+([,.:;!?])', r'\1', out)
    out = out.strip()
    return out or "..."

# ===========================================================================
# MERGED: response-quality governance (was eli.cognition.response_governance)
# normalize_response there was renamed clean_gguf_artifacts to end the
# signature collision with this module's normalize_response(user_input, text).
# ===========================================================================
# ============================================================================
# 1. CONFABULATION DETECTION
# ============================================================================

# Patterns that signal the model is inventing specific numbers it can't know
_CONFAB_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # Invented file sizes (e.g. "cognitive_engine.py at 2.3 KB" — always wrong)
    (re.compile(r"\b\d+(?:\.\d+)?\s*(?:KB|MB|GB|bytes)\b", re.I), "file_size"),
    # Invented line counts the model couldn't know
    (re.compile(r"\blines?\s*\[\d+(?:,\s*\d+)*\]"), "line_numbers"),
    # Model claiming specific context size different from settings
    (re.compile(r"\bcontext\s+size(?:\s+tokens?)?\s*:\s*\d+", re.I), "context_claim"),
    # Model claiming GPU layers different from settings
    (re.compile(r"\bgpu\s+layers?\s*:\s*\d+", re.I), "gpu_claim"),
]

# Questions that the GGUF model typically can't answer accurately
_HARD_KNOWLEDGE_DOMAINS = [
    re.compile(r"\bquantum\s+(?:physics|computing|mechanics|entanglement|decoherence|fidelity)\b", re.I),
    re.compile(r"\bderivative|integral|eigenvector|laplacian|hamiltonian\b", re.I),
    re.compile(r"\bcircuit\s+depth|gate\s+time|qubit|superposition\b", re.I),
    re.compile(r"\bO\(\s*n\s*(?:log\s*n|²|\^2|\*\*2)\s*\)", re.I),
]


def detect_confabulation(response: str, user_input: str = "") -> List[Dict[str, str]]:
    """
    Scan a response for signs of confabulation.
    Returns list of {type, evidence, suggestion} dicts.
    """
    issues = []

    for pattern, kind in _CONFAB_PATTERNS:
        matches = pattern.findall(response)
        if matches:
            issues.append({
                "type": f"possible_confabulation:{kind}",
                "evidence": str(matches[:3]),
                "suggestion": f"Model may have invented {kind} values. Verify against actual data.",
            })

    # Check if response contradicts itself (e.g. states two different values)
    numbers = re.findall(r"\b(\d{3,})\b", response)
    if len(set(numbers)) > 5:
        issues.append({
            "type": "excessive_specific_numbers",
            "evidence": f"{len(set(numbers))} distinct large numbers in response",
            "suggestion": "High number of specific values suggests confabulation.",
        })

    return issues


def is_hard_knowledge_query(user_input: str) -> bool:
    """Return True if the query is in a domain where smaller local models typically confabulate."""
    return any(p.search(user_input) for p in _HARD_KNOWLEDGE_DOMAINS)


# ============================================================================
# 2. CONFIDENCE SCORING
# ============================================================================

def score_response_quality(
    user_input: str,
    response: str,
    intent_confidence: float = 0.5,
    memory_context: str = "",
    evidence: Optional[Dict] = None,
) -> Dict[str, any]:
    """
    Score a response's quality on multiple dimensions.
    Returns dict with overall_score (0-1) and breakdown.
    """
    scores = {}

    # Base: intent confidence
    scores["intent"] = intent_confidence

    # Length appropriateness
    response_words = len(response.split())
    input_words = len(user_input.split())
    if response_words < 3:
        scores["length"] = 0.2
    elif response_words > 500 and input_words < 10:
        scores["length"] = 0.5  # verbose response to simple question
    else:
        scores["length"] = 0.9

    # Confabulation penalty
    confab_issues = detect_confabulation(response, user_input)
    scores["confabulation"] = max(0.0, 1.0 - 0.25 * len(confab_issues))

    # Hard knowledge penalty
    if is_hard_knowledge_query(user_input):
        scores["domain_difficulty"] = 0.4  # local models are less reliable on hard-knowledge queries
    else:
        scores["domain_difficulty"] = 0.9

    # Evidence grounding
    if evidence and evidence.get("ok"):
        scores["grounded"] = 1.0
    elif evidence and not evidence.get("ok"):
        scores["grounded"] = 0.3
    else:
        scores["grounded"] = 0.6  # no evidence attempted

    # Memory context usage
    if memory_context and len(memory_context) > 100:
        # Check if response references memory content
        mem_words = set(memory_context.lower().split())
        resp_words = set(response.lower().split())
        overlap = len(mem_words & resp_words) / max(len(mem_words), 1)
        scores["memory_relevance"] = min(1.0, overlap * 10)
    else:
        scores["memory_relevance"] = 0.5

    # Overall weighted score
    weights = {
        "intent": 0.20,
        "length": 0.10,
        "confabulation": 0.25,
        "domain_difficulty": 0.20,
        "grounded": 0.15,
        "memory_relevance": 0.10,
    }
    overall = sum(scores[k] * weights[k] for k in weights)
    scores["overall"] = round(overall, 3)

    return {
        "overall_score": scores["overall"],
        "breakdown": scores,
        "confabulation_issues": confab_issues,
        "hard_knowledge": is_hard_knowledge_query(user_input),
    }


# ============================================================================
# 3. RESPONSE GOVERNANCE — the main entry point
# ============================================================================

# Threshold below which ELI should hedge or decline
CONFIDENCE_THRESHOLD_HEDGE = 0.45
CONFIDENCE_THRESHOLD_DECLINE = 0.30

# Error strings that should never appear in user-facing responses
_ERROR_LEAKAGE_PATTERNS = [
    re.compile(r"(?:Traceback|File \"|ModuleNotFoundError|ImportError|NameError|KeyError|TypeError|ValueError)", re.I),
    re.compile(r"gguf\s+(?:streaming\s+)?failed", re.I),
    re.compile(r"context\s+window\s+(?:exceeded|overflow)", re.I),
    re.compile(r"broker\s+unavailable", re.I),
    re.compile(r"requested\s+tokens.*exceed", re.I),
    re.compile(r"model\s+not\s+(?:ready|loaded)", re.I),
]

# Canned hedge/decline phrase lists removed: persona-bound LLM speaks for ELI,
# not a static phrase bank. Confidence is now flagged in the governance result
# so the engine can re-prompt or escalate; the user-facing text is always
# produced by the model with persona attached.


def govern_response(
    user_input: str,
    response: str,
    intent_confidence: float = 0.5,
    memory_context: str = "",
    evidence: Optional[Dict] = None,
) -> Dict[str, any]:
    """
    Main governance entry point. Call this before sending a response to the user.

    Returns:
        {
            "response": str,          # possibly modified response
            "original": str,          # the unmodified response
            "governed": bool,         # whether governance modified anything
            "quality": dict,          # quality scoring breakdown
            "actions": list[str],     # what governance did
        }
    """
    actions = []
    governed = False
    final_response = response

    # 1. Strip error leakage
    for pat in _ERROR_LEAKAGE_PATTERNS:
        if pat.search(final_response):
            # Don't show raw errors — replace with generic message
            final_response = re.sub(
                pat.pattern,
                "[internal error filtered]",
                final_response,
                flags=re.I,
            )
            actions.append("error_leakage_filtered")
            governed = True

    # 2. Score quality
    quality = score_response_quality(
        user_input, response, intent_confidence, memory_context, evidence
    )

    # 3. Flag confidence — never mutate the model's text with canned phrases.
    #    The engine reads `low_confidence` / `decline` flags and decides whether
    #    to re-prompt the persona LLM, escalate to the agent bus, or surface
    #    the response as-is.
    overall = quality["overall_score"]
    if overall < CONFIDENCE_THRESHOLD_DECLINE:
        actions.append(f"declined (score={overall:.2f})")
    elif overall < CONFIDENCE_THRESHOLD_HEDGE:
        actions.append(f"hedged (score={overall:.2f})")

    # 4. Flag confabulation (no canned disclaimer — engine/persona handles
    #    the user-facing wording).
    if quality["confabulation_issues"]:
        confab_types = [i["type"] for i in quality["confabulation_issues"]]
        actions.append(f"confabulation_detected: {confab_types}")

    return {
        "response": final_response,
        "original": response,
        "governed": governed,
        "quality": quality,
        "actions": actions,
        "low_confidence": overall < CONFIDENCE_THRESHOLD_HEDGE,
        "decline": overall < CONFIDENCE_THRESHOLD_DECLINE,
        "confabulation": bool(quality.get("confabulation_issues")),
    }


# ============================================================================
# 4. MEMORY STORAGE FILTER
# ============================================================================

def should_store_as_memory(text: str, role: str = "user") -> bool:
    """
    Decide whether a text should be stored in long-term memory.
    Filters out questions, commands, error strings, and ELI's own patterns.
    """
    if not text or not text.strip():
        return False

    low = text.strip().lower()

    # Never store error strings
    if any(p.search(text) for p in _ERROR_LEAKAGE_PATTERNS):
        return False

    if role == "user":
        # Don't store questions as facts
        if low.rstrip("?!.").endswith("?") or low.endswith("?"):
            return False
        question_starts = (
            "who ", "what ", "where ", "when ", "why ", "how ", "which ",
            "can you", "could you", "would you", "do you", "does ",
            "is there", "are there", "tell me", "give me", "show me",
            "list ", "explain ", "describe ", "search ", "find ",
            "open ", "close ", "play ", "pause ", "stop ", "run ",
        )
        stripped = low.rstrip("?!.")
        if any(stripped.startswith(q) for q in question_starts):
            return False
        # Too short to be a meaningful fact
        if len(low.split()) < 4:
            return False

    elif role == "assistant":
        # Don't store trivial responses
        trivial = {"ok", "ok.", "got it", "got it.", "i'm here", "i'm here.",
                    "sure", "sure.", "done", "done.", "understood"}
        if low in trivial:
            return False
        if len(low.split()) < 4:
            return False
        # Don't store ELI's own meta-patterns
        eli_patterns = (
            "i am eli", "i'm eli", "my current reasoning mode",
            "### memory system", "current time (authoritative",
            "gguf streaming",
        )
        if any(p in low for p in eli_patterns):
            return False

    return True


# ============================================================================
# 5. RESPONSE NORMALIZATION
# ============================================================================

def clean_gguf_artifacts(response: str, user_input: str = "") -> str:
    """
    Clean up common GGUF response artifacts:
    - Remove repeated sections
    - Strip markdown header spam
    - Remove "Current Time" hallucinations when not asked
    """
    if not response:
        return response

    # Remove "Current Time" sections when user didn't ask about time
    time_keywords = ("time", "clock", "hour", "when")
    if not any(k in user_input.lower() for k in time_keywords):
        response = re.sub(
            r"###?\s*Current\s+Time.*?(?=###|\n\n|\Z)",
            "",
            response,
            flags=re.DOTALL | re.I,
        )

    # Remove duplicate paragraphs (GGUF sometimes repeats itself)
    paragraphs = response.split("\n\n")
    seen = set()
    deduped = []
    for para in paragraphs:
        normalized = para.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(para)
    response = "\n\n".join(deduped)

    # Strip trailing whitespace
    response = response.strip()

    return response

# --- score_confidence: standalone wrapper for audit compatibility ---
def score_confidence(response_text: str, user_input: str = "", context: dict = None) -> float:
    """Return a confidence score 0.0-1.0 based on response quality.
    Accepts 2 or 3 arguments for audit compatibility."""
    if not response_text or len(response_text.strip()) < 5:
        return 0.0
    # Use existing scoring machinery
    # score_response_quality is defined in this module
    return score_response_quality(user_input, response_text).get("overall_score", 0.5)


# Note: role-prefix stripping, HR-phrase polish, and self/user confusion
# repair live in eli.cognition.output_governor (govern_output ->
# clean_response_style + repair_self_user_confusion). This module is the
# governance/quality scoring layer only.

