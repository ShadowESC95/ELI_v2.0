"""Canonical special tokens, stop sequences, and persona drift patterns for all GGUF families.

Single source of truth for output cleaning across gguf_inference, engine, and
correction paths. Every supported chat template family (ChatML/Qwen, Llama-3,
Mistral, Gemma, Phi, GLM/ChatGLM, …) registers its turn-boundary tokens here
so redistribution users never see leaked scaffolding regardless of which model
they load.
"""
from __future__ import annotations

import re
from typing import FrozenSet, Iterable, Optional, Sequence, Tuple

# ── Turn-boundary / role tokens stripped from user-visible output ────────────
# Keep in sync with universal + family stop lists below.
SPECIAL_OUTPUT_TOKENS: Tuple[str, ...] = (
    # ChatML / Qwen / DeepSeek / OpenHermes
    "<|im_start|>",
    "<|im_end|>",
    "<|im_sep|>",
    # Llama-3
    "<|begin_of_text|>",
    "<|start_header_id|>",
    "<|end_header_id|>",
    "<|eot_id|>",
    "<|end_of_text|>",
    # Phi / Zephyr / some TinyLlama builds
    "<|end|>",
    "<|assistant|>",
    "<|user|>",
    "<|system|>",
    # Gemma
    "<start_of_turn>",
    "</start_of_turn>",
    "<end_of_turn>",
    "<|end_of_turn|>",
    "<end_of_turn>",
    # Gemma 4 / multimodal — EOI and image placeholders leak as plain text
    # when the chat template is text-only (adelic-gemma4, gemma-4-E4B, …).
    "<image|>",
    "<|image|>",
    "<|image|",
    "</image|>",
    "<|eoi|>",
    "<eoi>",
    "<|media|>",
    "<media|>",
    "<|audio|>",
    "<audio|>",
    # Thinking / channel markers some Gemma builds emit mid-stream
    "</think>",
    "<think>",
    # GLM / ChatGLM
    "[gMASK]",
    "<sop>",
    "<|observation|>",
    "<|endoftext|>",
    "<tool_response>",
    "</tool_response>",
    # Mistral / Llama-2
    "[INST]",
    "[/INST]",
    "<<SYS>>",
    "<</SYS>>",
    "<s>",
    "</s>",
    # Generic / legacy
    "<|endoftext|>",
    "<|end_of_text|>",
    "<|end_of_turn|>",
    "<|pad|>",
    "<|unk|>",
    "<|bos|>",
    "<|eos|>",
)

# Regex fallbacks for partially leaked or alternate spellings.
_SPECIAL_OUTPUT_RES: Tuple[re.Pattern[str], ...] = (
    re.compile(r"<\|end_of_turn\|>", re.I),
    re.compile(r"</?start_of_turn>", re.I),
    re.compile(r"</?end_of_turn>", re.I),
    re.compile(r"<\|im_(?:start|end)\|>", re.I),
    re.compile(r"<\|(?:redacted_)?(?:start|end)_header_id\|>", re.I),
    # Multimodal EOI / image placeholders (Gemma 4 and siblings)
    re.compile(r"</?(?:image|media|audio)\|?>", re.I),
    re.compile(r"<\|(?:image|media|audio|eoi)\|?>", re.I),
    re.compile(r"</?think>", re.I),
)

# Hard cut markers: anything at/after these is discarded (not just stripped).
# Multimodal models often emit dozens of `<image|>` tokens once they leave
# the text channel — keeping a truncated prefix is the only safe UX.
_HARD_CUT_MARKERS: Tuple[str, ...] = (
    "<image|>",
    "<|image|>",
    "<|image|",
    "</image|>",
    "<|eoi|>",
    "<eoi>",
    "<|media|>",
    "<media|>",
    "<|audio|>",
    "<audio|>",
    "</think>",
)

# ── Stop sequences (generation) ──────────────────────────────────────────────
UNIVERSAL_STOP_TOKENS: Tuple[str, ...] = (
    "<|im_start|>",
    "<|im_end|>",
    "<|user|>",
    "<|assistant|>",
    "<|system|>",
    "<|endoftext|>",
    "<|end_of_text|>",
    "<|eot_id|>",
    "<|end|>",
)

FAMILY_STOP_TOKENS: dict[str, Tuple[str, ...]] = {
    "chatml": ("<|im_end|>",),
    "llama": ("<|eot_id|>", "<|end_of_text|>", "<|start_header_id|>"),
    "mistral": ("</s>", "[INST]", "[/INST]"),
    "gemma": (
        "<end_of_turn>",
        "<start_of_turn>",
        "<image|>",
        "<|image|>",
        "<|eoi|>",
        "<eoi>",
        "</think>",
    ),
    "phi": ("<|end|>",),
    "glm": ("<|observation|>", "[gMASK]", "<|endoftext|>"),
}

# Natural-language role labels — withheld from thinking models in gguf_inference.
LABEL_STOP_TOKENS: Tuple[str, ...] = (
    "User:", "USER:", "\nUser:", "\nUSER:", "\n\nUser:", "\n\nUSER:",
    "Assistant:", "ASSISTANT:", "\nAssistant:", "\nASSISTANT:",
    "\n\nAssistant:", "\n\nASSISTANT:",
    "ELI:", "\nELI:", "\n\nELI:",
)

# ── Persona drift: generic LLM disclaimers ELI must never surface ────────────
PERSONA_DRIFT_PREFIXES: Tuple[str, ...] = (
    "i'm an ai",
    "i am an ai",
    "as an ai",
    "i'm just an ai",
    "i am just an ai",
    "i don't have a head",
    "i do not have a head",
    "i don't have personal memories",
    "i do not have personal memories",
    "i can't retain information",
    "i cannot retain information",
    "i don't have a memory like humans",
    "i do not have a memory like humans",
    "i don't store information between",
    "i do not store information between",
    "unlike humans, i don't",
    "as a language model",
    "as an llm",
    "as a large language model",
    "i'm just a large language model",
    "i am just a large language model",
    "i'm an artificial intelligence",
    "i am an artificial intelligence",
    "how can you help me today",
    "how can i help you today",
    "how may i assist you today",
    "hello! i'm an ai",
    "hello, i am an ai",
)

# Embedded chat-template family sniffing (mirrors gguf_inference routing).
def detect_template_family_from_embedded(template: str) -> Optional[str]:
    tmpl = str(template or "")
    if not tmpl:
        return None
    low = tmpl.lower()
    # GLM before phi — both use <|user|>/<|assistant|>.
    if "[gmask]" in low or "<|observation|>" in tmpl:
        return "glm"
    if "<|im_start|>" in tmpl:
        return "chatml"
    if "<|start_header_id|>" in tmpl or "<|eot_id|>" in tmpl:
        return "llama"
    if "<start_of_turn>" in tmpl:
        return "gemma"
    if "[inst]" in low:
        return "mistral"
    if "<|assistant|>" in tmpl or "<|user|>" in tmpl:
        return "phi"
    return None


def glm_filename_hint(path: str) -> bool:
    """Deprecated: use ``model_identity.is_glm_model`` (template/arch first)."""
    try:
        from eli.cognition.model_identity import is_glm_model
        return is_glm_model(path=path)
    except Exception:
        name = str(path or "").lower()
        return any(x in name for x in ("glm-", "glm_", "chatglm", "glm4", "glm-4", "glm."))


def strip_special_tokens(text: str, *, strip_edges: bool = True) -> str:
    """Remove chat-template scaffolding from model output (all families).

    ``strip_edges=False`` keeps leading/trailing whitespace — required when
    cleaning individual streamed BPE chunks so a lone ``" "`` or ``" word"``
    is not destroyed by ``.strip()``.
    """
    t = str(text or "")
    if not t:
        return ""
    # Multimodal / thinking channel leaks: keep only content BEFORE the first
    # hard-cut marker so a flood of `<image|>` never reaches the chat UI.
    cut_at = -1
    for marker in _HARD_CUT_MARKERS:
        idx = t.find(marker)
        if idx >= 0 and (cut_at < 0 or idx < cut_at):
            cut_at = idx
    if cut_at >= 0:
        t = t[:cut_at]
    # Next-turn markers: keep only content BEFORE a leaked user/system turn.
    for marker in ("<|user|>", "<|system|>", "<|observation|>",
                   "<|im_start|>", "<start_of_turn>", "[INST]"):
        if marker in t:
            t = t.split(marker)[0]
    # Assistant marker echo: keep content AFTER the last assistant header.
    if "<|assistant|>" in t:
        t = t.split("<|assistant|>")[-1]
    for tok in SPECIAL_OUTPUT_TOKENS:
        t = t.replace(tok, "")
    for rx in _SPECIAL_OUTPUT_RES:
        t = rx.sub("", t)
    # Mistral echo: keep content after last [/INST]
    if "[/INST]" in t:
        t = t.split("[/INST]")[-1]
    # ChatML: keep content after last im_end
    if "<|im_end|>" in t:
        parts = t.split("<|im_end|>")
        t = next((p for p in reversed(parts) if p.strip()), t)
    # Strip leaked ChatML role lines
    t = re.sub(r"^(?:system|user|assistant)\n", "", t, flags=re.I)
    return t.strip() if strip_edges else t


def contains_hard_cut_marker(text: str) -> bool:
    """True when text contains a multimodal/thinking channel leak marker."""
    t = str(text or "")
    if not t:
        return False
    return any(m in t for m in _HARD_CUT_MARKERS)


def stop_tokens_for_family(
    family: Optional[str],
    *,
    include_label_stops: bool = True,
) -> list[str]:
    """Ordered, deduplicated stop list for a template family."""
    out: list[str] = list(UNIVERSAL_STOP_TOKENS)
    if family and family in FAMILY_STOP_TOKENS:
        out.extend(FAMILY_STOP_TOKENS[family])
    else:
        out.extend(("<|end|>", "<|eot_id|>"))
    if include_label_stops:
        out.extend(LABEL_STOP_TOKENS)
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def is_persona_drift(text: str) -> bool:
    """True when the reply is ONLY generic model-speak (prefix match)."""
    low = str(text or "").strip().lower()
    if not low:
        return False
    return any(low.startswith(p) for p in PERSONA_DRIFT_PREFIXES)


def strip_persona_drift_prefix(text: str) -> str:
    """Remove a leading generic-LLM disclaimer; salvage remainder if any."""
    t = str(text or "").strip()
    if not t:
        return ""
    low = t.lower()
    if not any(low.startswith(p) for p in PERSONA_DRIFT_PREFIXES):
        return t
    rest = re.sub(r"^[^.!?]*[.!?]\s*", "", t, count=1).strip()
    if len(rest) >= 2 and not is_persona_drift(rest):
        return rest
    return ""
