"""Fetch a diffusers image model's weights into the local models dir.

This is a DELIBERATE, user-run network action (ELI is offline-by-default — nothing
here runs automatically). It exists so the diffusion backend can be enabled with a
single explicit command:

    python -m eli.tools.image_engine.fetch_model segmind/SSD-1B models/image/ssd-1b

Defaults to segmind/SSD-1B → models/image/ssd-1b when called with no args.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _default_target() -> Path:
    try:
        from eli.core.paths import project_root
        root = Path(project_root())
    except Exception:
        root = Path(__file__).resolve().parents[3]
    return root / "models" / "image" / "ssd-1b"


def fetch(repo_id: str = "segmind/SSD-1B", target: str | Path | None = None) -> Path:
    """Download a diffusers model snapshot to `target`. Returns the local path."""
    dest = Path(target).expanduser() if target else _default_target()
    dest.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("huggingface_hub is required to fetch models") from exc
    # Skip the heavy fp32 duplicates; the backend loads fp16 safetensors.
    snapshot_download(
        repo_id=repo_id,
        local_dir=str(dest),
        allow_patterns=["*.json", "*.txt", "*.safetensors", "*model_index*"],
        ignore_patterns=["*.bin", "*non_ema*", "*.fp32.*"],
    )
    return dest


def _main(argv: list[str]) -> int:
    repo = argv[0] if len(argv) >= 1 else "segmind/SSD-1B"
    target = argv[1] if len(argv) >= 2 else None
    print(f"Fetching {repo} → {target or _default_target()} (this downloads several GB)…")
    try:
        dest = fetch(repo, target)
    except Exception as exc:
        print(f"Fetch failed: {exc}")
        return 1
    print(f"Done. Model weights at: {dest}")
    print("Select it in the Image tab (backend: auto/diffusion) and generate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
