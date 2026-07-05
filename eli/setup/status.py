"""Read-only setup completeness checks for first-run / grandparent setup."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ROOT = Path(__file__).resolve().parents[2]


def project_root() -> Path:
    env = os.environ.get("ELI_PROJECT_ROOT", "").strip()
    return Path(env).resolve() if env else _ROOT


def venv_python() -> Path:
    root = project_root()
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        p = root / rel
        if p.exists():
            return p
    return root / ".venv/bin/python"


def has_venv() -> bool:
    return venv_python().exists()


def has_chat_model() -> bool:
    try:
        from eli.gui.eli_pro_audio_gui_v2_0 import discover_gguf_models
        return bool(discover_gguf_models())
    except Exception:
        root = project_root()
        for base in (root / "models", root / "models" / "gguf"):
            if base.exists():
                for p in base.rglob("*.gguf"):
                    if "embed" not in p.name.lower() and "mmproj" not in p.name.lower():
                        return True
        return False


def has_embedder() -> bool:
    root = project_root()
    emb = root / "models" / "embeddings"
    if not emb.exists():
        return False
    return any(emb.rglob("*.gguf"))


def has_voice_assets() -> bool:
    try:
        from eli.runtime.voice_assets import _piper_present
        return bool(_piper_present())
    except Exception:
        root = project_root()
        piper = root / "tts_piper" / "piper"
        if piper.exists() and any(piper.rglob("*.onnx")):
            return True
        alt = root / "models" / "tts" / "piper"
        return alt.exists() and any(alt.rglob("*.onnx"))


def has_desktop_launcher() -> bool:
    apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    return (apps / "eli-v2.desktop").exists() or (apps / "eli.desktop").exists()


def stage_checks() -> List[Tuple[str, str, bool]]:
    """(id, human label, complete)"""
    return [
        ("venv", "Python environment", has_venv()),
        ("chat_model", "Chat model (AI brain)", has_chat_model()),
        ("embedder", "Memory embedder", has_embedder()),
        ("voice", "Voice models (speech)", has_voice_assets()),
        ("desktop", "App menu shortcuts", has_desktop_launcher()),
    ]


def setup_complete() -> bool:
    return all(ok for _, _, ok in stage_checks())


def status_dict() -> Dict[str, Any]:
    stages = [
        {"id": sid, "label": label, "complete": ok}
        for sid, label, ok in stage_checks()
    ]
    return {
        "root": str(project_root()),
        "python": str(venv_python()) if has_venv() else None,
        "complete": setup_complete(),
        "stages": stages,
    }


def main() -> int:
    data = status_dict()
    for row in data["stages"]:
        mark = "OK" if row["complete"] else "MISSING"
        print(f"[{mark}] {row['label']}")
    return 0 if data["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
