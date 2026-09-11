"""Model-agnostic identity: chat family + thinking from GGUF metadata.

Priority (never brand/filename first):
  1. ``tokenizer.chat_template`` content
  2. ``general.architecture`` (and related header keys)
  3. Filename / path substrings — last resort only for redistributed files
     that ship without readable metadata

Callers should pass whatever they have (loaded llm metadata, on-disk path).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Optional

from eli.cognition.model_output_tokens import detect_template_family_from_embedded

# ``general.architecture`` → chat-template family used by ELI's prompt builders.
# Keys are lowercase exact architecture strings from GGUF headers.
ARCHITECTURE_TO_FAMILY: dict[str, str] = {
    # ChatML / Qwen-family
    "qwen": "chatml",
    "qwen2": "chatml",
    "qwen2moe": "chatml",
    "qwen2vl": "chatml",
    "qwen3": "chatml",
    "qwen3moe": "chatml",
    "qwen3vl": "chatml",
    "deepseek": "chatml",
    "deepseek2": "chatml",
    "deepseek3": "chatml",
    "smollm": "chatml",
    "smollm2": "chatml",
    "smollm3": "chatml",
    "stablelm": "chatml",
    "starcoder": "chatml",
    "starcoder2": "chatml",
    "command-r": "chatml",
    "command-r7b": "chatml",
    # Llama-3 header format (llama-2 often ships [INST] — template wins when present)
    "llama": "llama",
    # Mistral / Llama-2 style
    "mistral": "mistral",
    "mixtral": "mistral",
    # Gemma
    "gemma": "gemma",
    "gemma2": "gemma",
    "gemma3": "gemma",
    "gemma3n": "gemma",
    "gemma4": "gemma",
    # Phi
    "phi2": "phi",
    "phi3": "phi",
    "phimoe": "phi",
    # GLM / ChatGLM
    "chatglm": "glm",
    "glm4": "glm",
    "glm4moe": "glm",
}

# Architectures whose *default* chat template enables a thinking channel even
# when the Jinja is not readable. Keep this narrow — never "any deepseek".
ARCHITECTURE_DEFAULT_THINKING: frozenset[str] = frozenset({
    "smollm3",
    "qwen3",
    "qwen3moe",
})

# Filename last-resort markers (only when template + arch unavailable).
_FILENAME_FAMILY_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("glm", ("glm-", "glm_", "chatglm", "glm4", "glm-4")),
    ("gemma", ("gemma",)),
    ("phi", ("phi-3", "phi3", "phi-4", "phi4", "phi-2")),
    ("llama", ("llama-3", "llama3", "meta-llama-3", "llama_3")),
    ("mistral", ("mistral", "mixtral")),
    ("chatml", (
        "qwen", "deepseek", "openhermes", "hermes", "dolphin",
        "zephyr", "stable-code", "starcoder", "chatml", "smollm", "twil",
    )),
)


def _norm_arch(architecture: Optional[str]) -> str:
    return str(architecture or "").strip().lower()


def family_from_architecture(architecture: Optional[str]) -> Optional[str]:
    """Map GGUF ``general.architecture`` → chat family, or None if unknown."""
    arch = _norm_arch(architecture)
    if not arch:
        return None
    if arch in ARCHITECTURE_TO_FAMILY:
        return ARCHITECTURE_TO_FAMILY[arch]
    # Prefix match for versioned arches (e.g. qwen2.5 → treat like qwen2)
    for key, fam in ARCHITECTURE_TO_FAMILY.items():
        if arch.startswith(key):
            return fam
    return None


def family_from_filename(path: Optional[str | Path]) -> Optional[str]:
    """Last-resort family guess from path. Prefer template/arch instead."""
    name = str(path or "").lower()
    if not name:
        return None
    # ChatML fine-tunes on Mistral bases must win over plain "mistral".
    _chatml_on_mistral = ("openhermes", "hermes", "dolphin", "zephyr", "neural")
    if any(x in name for x in _chatml_on_mistral):
        return "chatml"
    for fam, markers in _FILENAME_FAMILY_MARKERS:
        if any(m in name for m in markers):
            return fam
    return None


def resolve_chat_family(
    *,
    template: Optional[str] = None,
    architecture: Optional[str] = None,
    path: Optional[str | Path] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Optional[str]:
    """Resolve chat-template family: template → architecture → filename."""
    md = dict(metadata or {})
    tmpl = str(template if template is not None else md.get("tokenizer.chat_template") or "")
    fam = detect_template_family_from_embedded(tmpl)
    if fam:
        return fam
    arch = architecture if architecture is not None else md.get("general.architecture")
    fam = family_from_architecture(arch)
    if fam:
        return fam
    return family_from_filename(path)


def template_enables_thinking(template: Optional[str]) -> bool:
    """True when the embedded chat template opts into a thinking/reasoning channel."""
    tmpl = str(template or "")
    if not tmpl:
        return False
    low = tmpl.lower()
    # Explicit default-on (SmolLM3 / Qwen3 style Jinja).
    if re.search(r"enable_thinking\s*=\s*true", tmpl, flags=re.I):
        return True
    if "enable_thinking" in low and re.search(
        r"enable_thinking\s+is\s+not\s+defined", low
    ):
        # Default branch usually sets thinking true when undefined.
        if re.search(r"set\s+enable_thinking\s*=\s*true", low):
            return True
    if "<think>" in tmpl or "</think>" in tmpl or "redacted_thinking" in low:
        return True
    if "reasoning_content" in low or "reasoning channel" in low:
        return True
    return False


def architecture_default_thinking(architecture: Optional[str]) -> bool:
    """Narrow arch allowlist for default thinking when Jinja is unreadable."""
    arch = _norm_arch(architecture)
    if not arch:
        return False
    if arch in ARCHITECTURE_DEFAULT_THINKING:
        return True
    return any(arch.startswith(a) for a in ARCHITECTURE_DEFAULT_THINKING)


def is_thinking_model(
    *,
    template: Optional[str] = None,
    architecture: Optional[str] = None,
    path: Optional[str | Path] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Whether the model defaults to emitting a thinking block.

    Order: chat template → architecture default → (no filename brand list).
    Behavior-based empty-stream retry remains the safety net for unknowns.
    """
    md = dict(metadata or {})
    tmpl = str(template if template is not None else md.get("tokenizer.chat_template") or "")
    if template_enables_thinking(tmpl):
        return True
    arch = architecture if architecture is not None else md.get("general.architecture")
    if architecture_default_thinking(arch):
        return True
    # Filename is intentionally NOT consulted — redistributed renames must work.
    _ = path  # kept for API symmetry with resolve_chat_family
    return False


def is_glm_model(
    *,
    template: Optional[str] = None,
    architecture: Optional[str] = None,
    path: Optional[str | Path] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> bool:
    return resolve_chat_family(
        template=template,
        architecture=architecture,
        path=path,
        metadata=metadata,
    ) == "glm"


def read_gguf_identity(path: Optional[str | Path]) -> dict[str, Any]:
    """Best-effort on-disk identity (no weights load)."""
    out: dict[str, Any] = {
        "path": str(path or ""),
        "architecture": "",
        "template": "",
        "family": None,
        "thinking": False,
        "draft_only": False,
    }
    if not path:
        return out
    p = Path(str(path))
    try:
        from eli.cognition.model_load_diagnostics import (
            gguf_architecture,
            gguf_metadata,
            is_draft_only_gguf,
        )
        arch = gguf_architecture(p) or ""
        md = gguf_metadata(p) or {}
        tmpl = str(md.get("tokenizer.chat_template") or "")
        out["architecture"] = arch
        out["template"] = tmpl
        out["family"] = resolve_chat_family(template=tmpl, architecture=arch, path=p)
        out["thinking"] = is_thinking_model(template=tmpl, architecture=arch, path=p)
        out["draft_only"] = bool(is_draft_only_gguf(p, arch))
    except Exception:
        out["family"] = family_from_filename(p)
    return out
