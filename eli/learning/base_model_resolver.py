from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from eli.utils.log import get_logger


def _eli_canonical_root_PROJECT_ROOT() -> Path:
    # Canonical env-honoring root — __file__ resolves into the read-only
    # bundle in frozen builds (identical to this path in source installs).
    try:
        from eli.core.paths import project_root
        return Path(project_root())
    except Exception:
        return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _eli_canonical_root_PROJECT_ROOT()

log = get_logger(__name__)

DEFAULT_PHI3_BASE_CANDIDATES = [
    PROJECT_ROOT / "phi-3-mini-base",
    PROJECT_ROOT / "models/hf/phi-3-mini-base",
    PROJECT_ROOT / "models/hf/Phi-3-mini-4k-instruct",
    PROJECT_ROOT / "models/hf/Phi-3-mini-128k-instruct",
]

TOKENIZER_MARKERS = {
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
}

WEIGHT_MARKERS = {
    "pytorch_model.bin",
    "model.safetensors",
    "model.safetensors.index.json",
}


def _as_path(path: Any) -> Path:
    p = Path(str(path)).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def inspect_base_candidate(path: Any, *, source: str = "candidate") -> dict[str, Any]:
    p = _as_path(path)

    exists = p.exists()
    is_file = p.is_file()
    is_dir = p.is_dir()
    is_gguf = is_file and p.suffix.lower() == ".gguf"

    looks_like_lora_adapter = False
    has_config = False
    has_tokenizer = False
    has_weights = False

    if is_dir:
        names = {x.name for x in p.iterdir()}
        looks_like_lora_adapter = (
            "adapter_config.json" in names
            or "adapter_model.safetensors" in names
            or "adapter_model.bin" in names
        )
        has_config = "config.json" in names
        has_tokenizer = bool(names & TOKENIZER_MARKERS)
        has_weights = bool(names & WEIGHT_MARKERS) or any(
            x.name.startswith("model-") and x.name.endswith(".safetensors")
            for x in p.iterdir()
        )

    item = {
        "source": source,
        "path": str(p),
        "relative": _rel(p),
        "exists": exists,
        "is_file": is_file,
        "is_dir": is_dir,
        "is_gguf": is_gguf,
        "looks_like_lora_adapter": looks_like_lora_adapter,
        "has_config": has_config,
        "has_tokenizer": has_tokenizer,
        "has_weights": has_weights,
        "ok": False,
    }

    if not exists:
        item["problem"] = "Path does not exist."
    elif is_gguf:
        item["problem"] = "GGUF is an inference artifact, not a trainable Hugging Face base model directory."
    elif not is_dir:
        item["problem"] = "Path is not a directory."
    elif looks_like_lora_adapter:
        item["problem"] = "Path looks like a LoRA adapter directory, not a base model."
    elif not has_config:
        item["problem"] = "Missing config.json."
    elif not has_tokenizer:
        item["problem"] = "Missing tokenizer files."
    elif not has_weights:
        item["problem"] = "Missing trainable model weights."
    else:
        item["ok"] = True

    return item


def base_search_roots() -> list[Path]:
    """Where a trainable Hugging Face base model may live on any install.

    Deliberately not Phi-specific: a redistributed copy has whatever the operator
    downloaded, and the layout differs between a dev checkout (models/hf) and a
    packaged install (data dir).
    """
    roots: list[Path] = [PROJECT_ROOT / "models" / "hf", PROJECT_ROOT / "models", PROJECT_ROOT]
    try:
        from eli.core.paths import models_dir, data_dir
        roots.insert(0, Path(models_dir()) / "hf")
        roots.append(Path(data_dir()) / "models" / "hf")
    except Exception:
        log.debug("[lora] eli.core.paths unavailable; using project-relative roots only",
                  exc_info=True)
    override = os.environ.get("ELI_HF_BASE_DIR")
    if override:
        roots.insert(0, Path(override).expanduser())
    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def discover_base_models(roots: list[Path] | None = None) -> list[dict[str, Any]]:
    """Every trainable HF base directory found under the search roots, any family.

    Each entry carries the family the model declares for itself (config.json
    model_type), so the caller never has to guess from the folder name.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in (roots if roots is not None else base_search_roots()):
        try:
            if not root.is_dir():
                continue
            children = sorted(root.iterdir())
        except Exception:
            continue
        for child in children:
            if not child.is_dir() or str(child.resolve()) in seen:
                continue
            item = inspect_base_candidate(child, source="discovered")
            seen.add(str(child.resolve()))
            if not item.get("ok"):
                continue
            try:
                from eli.learning.target_registry import detect_family
                item["family"] = detect_family(child)
            except Exception:
                item["family"] = None
            try:
                item["size_gb"] = round(
                    sum(f.stat().st_size for f in child.rglob("*") if f.is_file()) / 1024 ** 3, 2)
            except Exception:
                item["size_gb"] = None
            found.append(item)
    return found


def resolve_base_model_path(
    path: Any = None,
    *,
    allow_default_candidates: bool = True,
) -> dict[str, Any]:
    """
    Resolve a local trainable Hugging Face Phi-3 base model.

    If path is supplied and allow_default_candidates=False, only that explicit
    path is tested. This is required for isolated unit tests so they do not
    silently pass by falling back to a downloaded real model.

    If allow_default_candidates=True, the resolver may fall back to known local
    Phi-3 base locations.
    """
    checked: list[dict[str, Any]] = []

    if path:
        checked.append(inspect_base_candidate(path, source="argument"))

    if allow_default_candidates:
        for candidate in DEFAULT_PHI3_BASE_CANDIDATES:
            checked.append(inspect_base_candidate(candidate, source="default_candidate"))

    if allow_default_candidates and not any(i.get("ok") for i in checked):
        # No Phi-3 in the known spots. Before refusing, look for ANY trainable base
        # the operator has downloaded — the point of a redistributed trainer.
        checked.extend(discover_base_models())

    for item in checked:
        if item.get("ok"):
            return {
                "ok": True,
                "path": item["path"],
                "relative": item["relative"],
                "source": item["source"],
                "checked": checked,
                "problems": [],
                "warnings": [],
            }

    return {
        "ok": False,
        "path": "",
        "relative": "",
        "source": "",
        "checked": checked,
        "problems": ["No valid local trainable Phi-3 base model directory found."],
        "warnings": [],
    }


def main(argv=None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=None)
    ap.add_argument(
        "--no-default-candidates",
        action="store_true",
        help="Only test the explicit path; do not fall back to known local Phi-3 candidates.",
    )
    args = ap.parse_args(argv)

    payload = resolve_base_model_path(
        args.path,
        allow_default_candidates=not args.no_default_candidates,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
