"""
ELI Response Governance Module
===============================
Filters, scores, and governs GGUF model responses before they reach the user.

Responsibilities:
  1. Detect confabulation (invented numbers, file sizes, technical details)
  2. Flag low-confidence responses
  3. Insert "I don't know" when confidence is too low
  4. Strip error leakage from responses
  5. Block storing junk in memory

Place in: eli/cognition/response_governance.py
Wire into: cognitive_engine.py's _run_chat_reasoning_loop and _stream_chat
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

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
        scores["domain_difficulty"] = 0.4  # 7B models struggle here
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

def normalize_response(response: str, user_input: str = "") -> str:
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
    from .response_governance import score_response_quality
    return score_response_quality(user_input, response_text).get("overall_score", 0.5)


# Note: role-prefix stripping, HR-phrase polish, and self/user confusion
# repair live in eli.cognition.output_governor (govern_output ->
# clean_response_style + repair_self_user_confusion). This module is the
# governance/quality scoring layer only.

