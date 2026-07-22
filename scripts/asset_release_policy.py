"""Shared policy for GitHub model/voice asset releases and restore."""
from __future__ import annotations

from pathlib import Path

DEFAULT_ASSET_REPO = "ShadowESC95/ELI_v2.0"
DEFAULT_ASSET_TAG = "local-assets-v2.1"

# Voices excluded from public restore/upload (NC-SA ryan, uncleared Lessac, Cori
# under review). The licence attaches to the DATASET, so exclusion is by voice
# name — every quality variant (-low/-medium/-high) is covered, not just the
# files we happened to have locally. eli.runtime.voice_assets owns this list;
# the literal below is the fallback for when this script runs outside the package
# (portable builds copy scripts/ standalone).
try:  # pragma: no cover - trivial import shim
    from eli.runtime.voice_assets import RESTRICTED_VOICE_NAMES
except Exception:
    RESTRICTED_VOICE_NAMES = frozenset({"ryan", "lessac", "cori"})

# Kept for callers that want the exact known-file list (upload manifests/logs).
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
    if stem in EXCLUDED_VOICE_BASENAMES:
        return True
    parts = stem.split("-")
    return len(parts) >= 3 and "-".join(parts[1:-1]) in RESTRICTED_VOICE_NAMES


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
