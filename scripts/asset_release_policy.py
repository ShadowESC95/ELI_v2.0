"""Shared policy for GitHub model/voice asset releases and restore."""
from __future__ import annotations

from pathlib import Path

DEFAULT_ASSET_REPO = "ShadowESC95/ELI_v2.0"
DEFAULT_ASSET_TAG = "local-assets-v2.1"

# Voices excluded from public restore/upload (NC-SA, uncleared Lessac, Cori review).
EXCLUDED_VOICE_BASENAMES = frozenset({
    "en_US-ryan-high",
    "en_US-ryan-medium",
    "en_US-lessac-high",
    "en_US-lessac-medium",
    "en_GB-cori-high",
})


def is_excluded_voice_filename(name: str) -> bool:
    stem = Path(name).name
    if stem.endswith(".onnx.json"):
        stem = stem[:-10]
    elif stem.endswith(".onnx"):
        stem = stem[:-5]
    return stem in EXCLUDED_VOICE_BASENAMES


def flat_restore_destination(root: Path, filename: str) -> Path:
    """Map a flat GitHub Release asset filename to its project path."""
    name = Path(filename).name
    if name.endswith(".gguf"):
        lower = name.lower()
        if any(tag in lower for tag in ("nomic-embed", "embed", "bge-", "embedder")):
            return root / "models" / "embeddings" / name
        return root / "models" / name
    if name.endswith(".onnx") or name.endswith(".onnx.json"):
        return root / "tts_piper" / "piper" / name
    return root / "models" / name
