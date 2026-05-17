from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_REPO_ID = "microsoft/Phi-3-mini-4k-instruct"
DEFAULT_LOCAL_DIR = PROJECT_ROOT / "models/hf/Phi-3-mini-4k-instruct"

TOKENIZER_MARKERS = {
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
}

WEIGHT_MARKERS = {
    "model.safetensors",
    "model.safetensors.index.json",
    "pytorch_model.bin",
    "pytorch_model.bin.index.json",
}

CONFIG_MARKERS = {
    "config.json",
}


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def inspect_base_dir(path: str | Path) -> dict[str, Any]:
    root = _resolve_path(path)

    files = set()
    if root.exists() and root.is_dir():
        files = {p.name for p in root.iterdir() if p.is_file()}

    has_config = bool(files & CONFIG_MARKERS)
    has_tokenizer = bool(files & TOKENIZER_MARKERS)
    has_weights = bool(files & WEIGHT_MARKERS)

    looks_like_adapter = (root / "adapter_config.json").exists()
    contains_gguf = any(p.suffix.lower() == ".gguf" for p in root.glob("*")) if root.exists() else False

    problems: list[str] = []
    if not root.exists():
        problems.append("Path does not exist.")
    elif not root.is_dir():
        problems.append("Path is not a directory.")
    elif looks_like_adapter:
        problems.append("Path looks like a LoRA adapter, not a trainable base model.")
    elif contains_gguf:
        problems.append("Path contains GGUF files; GGUF is inference-only, not a trainable HF base.")
    else:
        if not has_config:
            problems.append("Missing config.json.")
        if not has_tokenizer:
            problems.append("Missing tokenizer files.")
        if not has_weights:
            problems.append("Missing HF/PyTorch/Safetensors model weights.")

    return {
        "path": str(root),
        "relative": _rel(root),
        "exists": root.exists(),
        "is_dir": root.is_dir(),
        "files_seen": sorted(files),
        "has_config": has_config,
        "has_tokenizer": has_tokenizer,
        "has_weights": has_weights,
        "looks_like_adapter": looks_like_adapter,
        "contains_gguf": contains_gguf,
        "ok": not problems,
        "problems": problems,
    }


def build_bootstrap_plan(
    *,
    repo_id: str = DEFAULT_REPO_ID,
    local_dir: str | Path = DEFAULT_LOCAL_DIR,
    revision: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    resolved_local = _resolve_path(local_dir)
    status = inspect_base_dir(resolved_local)

    install_cmd = [
        "python3",
        "-m",
        "pip",
        "install",
        "-r",
        "requirements-learning.txt",
    ]

    download_cmd = [
        "python3",
        "-m",
        "eli.learning.bootstrap_phi3_base",
        "--repo-id",
        repo_id,
        "--local-dir",
        _rel(resolved_local),
        "--execute",
    ]
    if revision:
        download_cmd.extend(["--revision", revision])

    return {
        "ok": True,
        "execute": execute,
        "repo_id": repo_id,
        "revision": revision or "",
        "local_dir": str(resolved_local),
        "relative_local_dir": _rel(resolved_local),
        "already_ready": status["ok"],
        "will_download": bool(execute and not status["ok"]),
        "local_status": status,
        "commands": {
            "install_training_deps": " ".join(install_cmd),
            "download_phi3_base": " ".join(download_cmd),
            "recheck_preflight": "python3 -m eli.learning.training_preflight all",
        },
        "notes": [
            "Default mode is dry-run only.",
            "This downloads a trainable Hugging Face Phi-3 base, not a GGUF.",
            "The models/ directory is ignored by git and should stay untracked.",
            "Hugging Face access/network availability may be required.",
        ],
    }


def execute_download(plan: dict[str, Any]) -> dict[str, Any]:
    if plan["already_ready"]:
        plan["download_result"] = {
            "skipped": True,
            "reason": "local base directory already appears trainable",
        }
        return plan

    try:
        from huggingface_hub import snapshot_download
    except Exception as e:
        plan["ok"] = False
        plan["download_result"] = {
            "skipped": False,
            "error": f"Missing huggingface_hub or import failed: {e}",
        }
        return plan

    local_dir = Path(plan["local_dir"])
    local_dir.mkdir(parents=True, exist_ok=True)

    try:
        snapshot_download(
            repo_id=plan["repo_id"],
            revision=plan["revision"] or None,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
            allow_patterns=[
                "*.json",
                "*.txt",
                "*.model",
                "*.safetensors",
                "*.bin",
                "*.py",
            ],
            ignore_patterns=[
                "*.gguf",
                "*.onnx",
                "*.h5",
                "*.msgpack",
                "*.tflite",
            ],
        )
    except Exception as e:
        plan["ok"] = False
        plan["download_result"] = {
            "skipped": False,
            "error": str(e),
        }
        return plan

    after = inspect_base_dir(local_dir)
    plan["local_status_after_download"] = after
    plan["download_result"] = {
        "skipped": False,
        "ok": after["ok"],
    }
    if not after["ok"]:
        plan["ok"] = False

    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap trainable Phi-3 HF base for ELI LoRA work.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID)
    parser.add_argument("--local-dir", default=str(DEFAULT_LOCAL_DIR))
    parser.add_argument("--revision", default=None)
    parser.add_argument("--execute", action="store_true", help="Actually download the model. Default is dry-run.")
    args = parser.parse_args(argv)

    plan = build_bootstrap_plan(
        repo_id=args.repo_id,
        local_dir=args.local_dir,
        revision=args.revision,
        execute=args.execute,
    )

    if args.execute:
        plan = execute_download(plan)

    print(json.dumps(plan, indent=2))
    return 0 if plan.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
