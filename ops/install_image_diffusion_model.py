#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download and register a local diffusion model for ELI image generation."
    )
    parser.add_argument(
        "--repo",
        default="segmind/SSD-1B",
        help="Hugging Face repo id to download.",
    )
    parser.add_argument(
        "--dest",
        default="models/image/ssd-1b",
        help="Destination directory relative to the project root.",
    )
    parser.add_argument(
        "--set-defaults",
        action="store_true",
        help="Update ELI runtime settings to use this diffusion model by default.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    dest = (root / args.dest).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    print(f"[image-model] repo : {args.repo}")
    print(f"[image-model] dest : {dest}")

    from huggingface_hub import snapshot_download

    downloaded = snapshot_download(
        repo_id=args.repo,
        local_dir=str(dest),
        allow_patterns=[
            "model_index.json",
            "scheduler/*",
            "tokenizer/*",
            "tokenizer_2/*",
            "text_encoder/config.json",
            "text_encoder/model.fp16.safetensors",
            "text_encoder/model.safetensors",
            "text_encoder_2/config.json",
            "text_encoder_2/model.fp16.safetensors",
            "text_encoder_2/model.safetensors",
            "unet/config.json",
            "unet/diffusion_pytorch_model.fp16.safetensors",
            "unet/diffusion_pytorch_model.safetensors",
            "vae/config.json",
            "vae/diffusion_pytorch_model.fp16.safetensors",
            "vae/diffusion_pytorch_model.safetensors",
        ],
        )
    print(f"[image-model] downloaded -> {downloaded}")

    if args.set_defaults:
        from eli.core.runtime_settings import load_settings, save_settings

        settings = load_settings() or {}
        updates = {
            "image_backend": "diffusion",
            "image_model_path": str(dest),
            "image_device": "cuda",
            "image_quality_preset": settings.get("image_quality_preset", "ultra") or "ultra",
            "image_steps": int(settings.get("image_steps", 36) or 36),
            "image_guidance": float(settings.get("image_guidance", 7.2) or 7.2),
            "image_default_count": 1,
            "image_auto_open": True,
        }
        save_settings(updates)
        print("[image-model] runtime settings updated for diffusion backend")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
