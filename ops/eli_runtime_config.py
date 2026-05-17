#!/usr/bin/env python3
"""
eli_runtime_config.py

Bump runtime settings and/or switch the active GGUF model with one command.

USAGE:

  # Show current settings:
  python3 ops/eli_runtime_config.py show

  # Switch back to mistral-7b with sane defaults:
  python3 ops/eli_runtime_config.py preset mistral

  # Switch to openhermes with proper context:
  python3 ops/eli_runtime_config.py preset openhermes

  # List available local models:
  python3 ops/eli_runtime_config.py list

  # Set arbitrary values:
  python3 ops/eli_runtime_config.py set n_ctx=8192 max_tokens=2048 n_gpu_layers=33

  # Switch model by filename (auto-resolves to models/gguf/base/<name>):
  python3 ops/eli_runtime_config.py model openhermes-2.5-mistral-7b.Q3_K_M.gguf

  # Combo — switch + tune in one shot:
  python3 ops/eli_runtime_config.py preset openhermes max_tokens=2048

Backups every change to config/settings.json.<TS>.bak.
Writes a single change-log line to ops/reports/runtime_config_changes.log.
"""
from __future__ import annotations

import sys
import os
import json
import shutil
import datetime
from pathlib import Path

def _find_project_root() -> Path:
    for key in ("ELI_PROJECT_ROOT", "ELI_HOME"):
        raw = os.environ.get(key, "").strip()
        if raw:
            candidate = Path(raw).expanduser().resolve()
            if (candidate / "eli").is_dir() and (candidate / "config").is_dir():
                return candidate

    start = Path(__file__).resolve()
    for cur in (start.parent, *start.parents):
        if (cur / "eli").is_dir() and (cur / "config").is_dir():
            return cur

    raise RuntimeError("Could not locate ELI project root from ops/eli_runtime_config.py")


ROOT = _find_project_root()
SETTINGS = ROOT / "config" / "settings.json"
MODELS_DIR = ROOT / "models" / "gguf" / "base"
LOG = ROOT / "ops" / "reports" / "runtime_config_changes.log"

# Presets tuned for an RTX 2060 SUPER 8GB. Adjust gpu_layers if your card
# is bigger/smaller. Each preset includes the model path so a single
# `preset` command is enough to switch.
PRESETS = {
    "mistral": {
        "_description": "Mistral 7B Q3_K_M — balanced default, ~4GB VRAM",
        "model_filename": "mistral-7b-instruct-v0.2.Q3_K_M.gguf",
        "n_ctx": 8192,
        "n_gpu_layers": 33,
        "n_threads": 10,
        "batch_size": 512,
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "openhermes": {
        "_description": "OpenHermes 2.5 Mistral 7B Q3_K_M — chattier persona, ~4GB VRAM",
        "model_filename": "openhermes-2.5-mistral-7b.Q3_K_M.gguf",
        "n_ctx": 8192,
        "n_gpu_layers": 33,
        "n_threads": 10,
        "batch_size": 512,
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "qwen": {
        "_description": "Qwen 2.5 3B Q4_K_M — faster, lighter, ~2GB VRAM",
        "model_filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "n_ctx": 8192,
        "n_gpu_layers": 35,
        "n_threads": 10,
        "batch_size": 512,
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "stable-code": {
        "_description": "Stable Code 3B Q4_K_M — coding-tuned, ~2GB VRAM",
        "model_filename": "stable-code-3b.Q4_K_M.gguf",
        "n_ctx": 16384,
        "n_gpu_layers": 35,
        "n_threads": 10,
        "batch_size": 512,
        "max_tokens": 2048,
        "temperature": 0.4,
    },
    "deepseek-r1": {
        "_description": "DeepSeek R1 Distill Qwen 1.5B Q4_K_M — reasoning, fast, ~1.2GB VRAM",
        "model_filename": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "n_ctx": 16384,
        "n_gpu_layers": 33,
        "n_threads": 10,
        "batch_size": 512,
        "max_tokens": 2048,
        "temperature": 0.6,
    },
    "deepseek-coder": {
        "_description": "DeepSeek Coder 1.3B Q5_K_M — small code model, ~1GB VRAM",
        "model_filename": "deepseek-coder-1.3b-instruct.Q5_K_M.gguf",
        "n_ctx": 8192,
        "n_gpu_layers": 33,
        "n_threads": 10,
        "batch_size": 512,
        "max_tokens": 2048,
        "temperature": 0.4,
    },
    "tinyllama": {
        "_description": "TinyLlama 1.1B Q5_K_M — smallest, smoke-test, ~700MB VRAM",
        "model_filename": "tinyllama-1.1b-chat-v1.0.Q5_K_M.gguf",
        "n_ctx": 4096,
        "n_gpu_layers": 33,
        "n_threads": 10,
        "batch_size": 512,
        "max_tokens": 1024,
        "temperature": 0.7,
    },
}


def load_settings() -> dict:
    if not SETTINGS.is_file():
        print(f"FATAL: {SETTINGS} not found", file=sys.stderr)
        sys.exit(2)
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def backup_settings():
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bk = SETTINGS.with_suffix(f".json.{ts}.bak")
    shutil.copy2(SETTINGS, bk)
    return bk


def save_settings(settings: dict):
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def log_change(action: str, details: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {action}: {details}\n")


def list_models():
    print(f"Models in {MODELS_DIR.relative_to(ROOT)}:")
    if not MODELS_DIR.is_dir():
        print(f"  (directory does not exist)")
        return
    for f in sorted(MODELS_DIR.glob("*.gguf")):
        sz_mb = f.stat().st_size / 1_000_000
        print(f"  {f.name}  ({sz_mb:.0f} MB)")
    print()
    print("Presets (use `preset <name>`):")
    for name, cfg in PRESETS.items():
        marker = "✓" if (MODELS_DIR / cfg["model_filename"]).is_file() else "✗"
        print(f"  {marker} {name:18}  {cfg['_description']}")
        print(f"     -> {cfg['model_filename']}")


def show_settings():
    s = load_settings()
    print(f"Current settings ({SETTINGS.relative_to(ROOT)}):")
    for k in sorted(s.keys()):
        print(f"  {k:24} = {s[k]}")


def apply_preset(name: str, extras: dict | None = None):
    if name not in PRESETS:
        print(f"FATAL: unknown preset {name!r}. Known: {', '.join(PRESETS.keys())}",
              file=sys.stderr)
        return 2
    preset = PRESETS[name]
    model_filename = preset["model_filename"]
    model_path = MODELS_DIR / model_filename
    if not model_path.is_file():
        print(f"WARNING: model file {model_path.relative_to(ROOT)} does not exist.",
              file=sys.stderr)
        print(f"         Apply preset anyway? Settings will be wrong until you "
              f"download the model.", file=sys.stderr)
        if input("         Continue? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 1

    s = load_settings()
    bk = backup_settings()
    print(f"backup -> {bk.relative_to(ROOT)}")

    # Apply preset values (excluding the meta key + model_filename)
    for k, v in preset.items():
        if k.startswith("_") or k == "model_filename":
            continue
        s[k] = v

    # Set the model paths consistently across all the keys settings.json uses
    abs_model = str(model_path.resolve())
    for key in ("model_path", "bundled_model_path", "custom_model_path", "gguf_model_path"):
        s[key] = abs_model

    # Apply any extra k=v overrides from the command line
    if extras:
        for k, v in extras.items():
            s[k] = v

    save_settings(s)
    log_change("preset", f"{name} -> {model_filename} | extras={extras or '{}'}")

    print(f"Applied preset: {name}")
    print(f"  description : {preset['_description']}")
    print(f"  model       : {model_filename}")
    print(f"  n_ctx       : {s['n_ctx']}")
    print(f"  n_gpu_layers: {s['n_gpu_layers']}")
    print(f"  max_tokens  : {s['max_tokens']}")
    print()
    print(f"Run `elix` to launch with the new config.")
    return 0


def apply_set(kvs: list[str]):
    """Parse k=v args and apply to settings.json."""
    extras = {}
    for kv in kvs:
        if "=" not in kv:
            print(f"FATAL: malformed key=value: {kv!r}", file=sys.stderr)
            return 2
        k, v = kv.split("=", 1)
        k = k.strip()
        v = v.strip()
        # Coerce types
        if v.lower() in ("true", "false"):
            extras[k] = v.lower() == "true"
        elif v.replace(".", "", 1).replace("-", "", 1).isdigit():
            extras[k] = float(v) if "." in v else int(v)
        else:
            extras[k] = v

    s = load_settings()
    bk = backup_settings()
    print(f"backup -> {bk.relative_to(ROOT)}")
    for k, v in extras.items():
        old = s.get(k, "<unset>")
        s[k] = v
        print(f"  {k}: {old} -> {v}")
    save_settings(s)
    log_change("set", str(extras))
    return 0


def apply_model(filename: str):
    """Switch model by filename (auto-resolves to models/gguf/base/<name>)."""
    model_path = MODELS_DIR / filename
    if not model_path.is_file():
        print(f"FATAL: {model_path.relative_to(ROOT)} does not exist.", file=sys.stderr)
        list_models()
        return 2

    s = load_settings()
    bk = backup_settings()
    print(f"backup -> {bk.relative_to(ROOT)}")
    abs_model = str(model_path.resolve())
    for key in ("model_path", "bundled_model_path", "custom_model_path", "gguf_model_path"):
        s[key] = abs_model
    save_settings(s)
    log_change("model", f"-> {filename}")
    print(f"Switched model -> {filename}")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1].lower()
    args = sys.argv[2:]

    if cmd == "show":
        show_settings()
        return 0
    if cmd == "list":
        list_models()
        return 0
    if cmd == "preset":
        if not args:
            print(f"Usage: preset <name> [k=v ...]", file=sys.stderr)
            print(f"Known: {', '.join(PRESETS.keys())}")
            return 2
        name = args[0]
        extras_kv = args[1:]
        extras = {}
        for kv in extras_kv:
            if "=" in kv:
                k, v = kv.split("=", 1)
                v = v.strip()
                if v.lower() in ("true", "false"):
                    extras[k.strip()] = v.lower() == "true"
                elif v.replace(".", "", 1).replace("-", "", 1).isdigit():
                    extras[k.strip()] = float(v) if "." in v else int(v)
                else:
                    extras[k.strip()] = v
        return apply_preset(name, extras or None)
    if cmd == "set":
        if not args:
            print(f"Usage: set k=v [k=v ...]", file=sys.stderr)
            return 2
        return apply_set(args)
    if cmd == "model":
        if not args:
            print(f"Usage: model <filename.gguf>", file=sys.stderr)
            list_models()
            return 2
        return apply_model(args[0])

    print(f"Unknown command: {cmd}", file=sys.stderr)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
