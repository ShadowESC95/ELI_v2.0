"""User-declared LoRA training targets — the registry that replaces the Phi-3 lock.

The guard's safety contract was right: refuse to train anything the operator has
not explicitly declared. What was wrong was *which* targets it would accept.
`ALLOWED_TARGETS = {"eli_phi", "eli_phi_ultra"}` plus `base_family must be phi3`
is this machine's two targets frozen into a redistributed product — anyone running
Qwen, Llama or Mistral was refused before the first gate.

The allowlist is still an allowlist. It is now *written by the operator* (through the
Training tab, or create_target()) into the user data dir, instead of being frozen in
source. Every other invariant of the contract is untouched: reviewed rows only, rows
scoped to the target, GGUF never trained directly, an existing adapter never
overwritten.

Family is not asserted, it is *read* — from the base model's own config.json
(``model_type``). A target whose declared family stops matching what is on disk is a
problem the guard reports, rather than a name the guard guesses at.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

# Shipped defaults. These stay as built-ins so an existing install keeps working
# byte-for-byte; they are no longer the *only* thing that can be trained.
BUILTIN_TARGETS: dict[str, dict[str, Any]] = {
    "eli_phi": {
        "description": "ELI Phi profile / Phi-3-compatible adapter target",
        "base_family": "phi3",
        "base_model_path": "./phi-3-mini-base",
        "adapter_path": "models/lora/adapters/eli-lora-adapter-phi3",
        "dataset_path": "training/datasets/eli_supervised_v0.eli_phi.trainable.jsonl",
        "output_dir": "models/lora/adapters/eli-lora-adapter-phi3-next",
        "builtin": True,
    },
    "eli_phi_ultra": {
        "description": "ELI Phi Ultra profile / Phi-3-compatible ultra adapter target",
        "base_family": "phi3",
        "base_model_path": "./phi-3-mini-base",
        "adapter_path": "models/lora/adapters/eli-lora-adapter-phi3-ultra",
        "dataset_path": "training/datasets/eli_supervised_v0.eli_phi_ultra.trainable.jsonl",
        "output_dir": "models/lora/adapters/eli-lora-adapter-phi3-ultra-next",
        "builtin": True,
    },
}

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,47}$")


def _learning_dir() -> Path:
    from eli.core.paths import learning_dir
    return Path(learning_dir())


def registry_path() -> Path:
    """Operator-written targets. Lives in the user data dir, never in the install —
    a packaged build mounts read-only (see test_runtime_paths_follow_the_data_dir)."""
    return _learning_dir() / "targets.json"


def _models_root() -> Path:
    from eli.core.paths import models_dir
    return Path(models_dir())


# ── family detection ───────────────────────────────────────────────────────────

def detect_family(base_model_path: Any) -> Optional[str]:
    """The model's own declared ``model_type`` from config.json, or None.

    This is what makes the registry family-agnostic: nothing here enumerates the
    families ELI knows about, so a model type released after this build still
    resolves correctly.
    """
    try:
        cfg = Path(str(base_model_path)).expanduser() / "config.json"
        if not cfg.is_file():
            return None
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception:
        return None
    mt = data.get("model_type")
    return str(mt).strip().lower() or None if mt else None


def family_matches(declared: Any, actual: Any) -> bool:
    """Tolerant family comparison: 'phi3' matches 'phi-3' and 'Phi3'.

    An empty declared family means the operator did not pin one — anything the base
    model reports is accepted, and the guard records what it found.
    """
    d = re.sub(r"[^a-z0-9]", "", str(declared or "").lower())
    a = re.sub(r"[^a-z0-9]", "", str(actual or "").lower())
    if not d:
        return True
    if not a:
        return True  # unreadable config is reported separately, not as a mismatch
    return d == a or d.startswith(a) or a.startswith(d)


# ── registry i/o ───────────────────────────────────────────────────────────────

def _read_user_registry() -> dict[str, dict[str, Any]]:
    path = registry_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    targets = data.get("targets")
    if not isinstance(targets, dict):
        return {}
    return {str(k): dict(v) for k, v in targets.items() if isinstance(v, dict)}


def _write_user_registry(targets: dict[str, dict[str, Any]]) -> Path:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "targets": targets}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def load_registry() -> dict[str, dict[str, Any]]:
    """Built-ins overlaid with operator targets. Operator entries win on name clash."""
    merged: dict[str, dict[str, Any]] = {k: dict(v) for k, v in BUILTIN_TARGETS.items()}
    for name, cfg in _read_user_registry().items():
        base = dict(merged.get(name) or {})
        base.update(cfg)
        base["builtin"] = bool(merged.get(name, {}).get("builtin", False))
        merged[name] = base
    return merged


def allowed_target_names() -> set[str]:
    return set(load_registry().keys())


def get_target(name: str) -> Optional[dict[str, Any]]:
    return load_registry().get(str(name or "").strip())


def list_targets() -> list[dict[str, Any]]:
    """Every declared target with live status, newest operator targets last."""
    out: list[dict[str, Any]] = []
    for name, cfg in load_registry().items():
        item = dict(cfg)
        item["name"] = name
        base = _resolve(cfg.get("base_model_path"))
        item["base_exists"] = bool(base and base.is_dir())
        item["actual_family"] = detect_family(base) if base else None
        item["family_ok"] = family_matches(cfg.get("base_family"), item["actual_family"])
        ds = _resolve(cfg.get("dataset_path"))
        item["dataset_exists"] = bool(ds and ds.is_file())
        out.append(item)
    out.sort(key=lambda x: (not x.get("builtin"), str(x.get("name"))))
    return out


def _resolve(value: Any) -> Optional[Path]:
    if not value:
        return None
    p = Path(str(value)).expanduser()
    if p.is_absolute():
        return p
    try:
        from eli.core.paths import project_root
        return (Path(project_root()) / p).resolve()
    except Exception:
        return p.resolve()


# ── mutation ───────────────────────────────────────────────────────────────────

def validate_name(name: str) -> Optional[str]:
    name = str(name or "").strip()
    if not _NAME_RE.match(name):
        return ("Name must be 2-48 characters, lowercase letters/digits/underscore/hyphen, "
                "starting with a letter or digit.")
    return None


def create_target(
    name: str,
    base_model_path: Any,
    *,
    description: str = "",
    base_family: str = "",
    dataset_path: Any = None,
    adapter_path: Any = None,
    output_dir: Any = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Declare a new training target. Returns {ok, target|problems}.

    The base model is validated here rather than at train time so the operator finds
    out a GGUF is not trainable while they are still choosing, not forty minutes into
    a run.
    """
    name = str(name or "").strip()
    problems: list[str] = []

    err = validate_name(name)
    if err:
        problems.append(err)

    existing = load_registry()
    if name in existing and not overwrite:
        problems.append(f"Target {name!r} already exists.")
    if name in BUILTIN_TARGETS and not overwrite:
        problems.append(f"{name!r} is a built-in target name.")

    from eli.learning.base_model_resolver import inspect_base_candidate
    base = inspect_base_candidate(base_model_path, source="registry")
    if not base.get("ok"):
        problems.append(base.get("problem") or "Base model is not a trainable directory.")

    if problems:
        return {"ok": False, "problems": problems}

    family = str(base_family or "").strip().lower() or (detect_family(base["path"]) or "")
    learn = _learning_dir()
    adapters = _models_root() / "lora" / "adapters"

    cfg = {
        "description": str(description or f"Operator target for {name}"),
        "base_family": family,
        "base_model_path": str(base["path"]),
        "adapter_path": str(_resolve(adapter_path) or adapters / f"eli-lora-{name}"),
        "dataset_path": str(_resolve(dataset_path) or learn / "datasets" / f"{name}.trainable.jsonl"),
        "output_dir": str(_resolve(output_dir) or adapters / f"eli-lora-{name}-next"),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "builtin": False,
    }

    user = _read_user_registry()
    user[name] = cfg
    _write_user_registry(user)
    return {"ok": True, "name": name, "target": cfg, "problems": []}


def delete_target(name: str) -> dict[str, Any]:
    """Remove an operator target. Built-ins cannot be deleted; nothing on disk is
    touched — adapters and datasets outlive the registry entry on purpose."""
    name = str(name or "").strip()
    if name in BUILTIN_TARGETS:
        return {"ok": False, "problems": [f"{name!r} is a built-in target and cannot be removed."]}
    user = _read_user_registry()
    if name not in user:
        return {"ok": False, "problems": [f"No such target: {name!r}"]}
    user.pop(name)
    _write_user_registry(user)
    return {"ok": True, "name": name, "problems": []}


__all__ = [
    "BUILTIN_TARGETS", "registry_path", "load_registry", "allowed_target_names",
    "get_target", "list_targets", "create_target", "delete_target",
    "detect_family", "family_matches", "validate_name",
]
