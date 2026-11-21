"""Read-only setup completeness checks for first-run / grandparent setup."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

log = logging.getLogger(__name__)

try:
    from eli.core.paths import canonical_root
    _ROOT = canonical_root(Path(__file__).resolve().parents[2])
except Exception:
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


def launcher_command(root: Path | None = None, *, headless: bool = False) -> str:
    """How a person starts ELI from this tree: RUN_ELI.sh in the portable package, eli.sh in a clone,
    eli.bat on Windows, with --headless where there is no window. Only the portable package has
    RUN_ELI.sh; naming it to a clone sent people to a file they did not have."""
    import sys
    base = Path(root) if root is not None else project_root()
    if sys.platform == "win32":
        command = f'"{base / "eli.bat"}"'
    elif (base / "RUN_ELI.sh").is_file():
        command = f'bash "{base / "RUN_ELI.sh"}"'
    else:
        command = f'"{base / "eli.sh"}"'
    return command + (" --headless" if headless else "")


def _model_folders() -> List[Path]:
    """Where model discovery looks (hardware_profile.discover_models): the models folder
    (paths.models_dir(): ELI_MODELS_DIR, else the checkout's or the data folder's) and the
    program's own models/."""
    folders: List[Path] = []
    try:
        from eli.core.paths import models_dir
        folders.append(Path(models_dir()))
    except Exception:
        log.debug("models folder unavailable", exc_info=True)
    folders.append(project_root() / "models")
    return folders


def _scan_chat_gguf(folder: Path) -> bool:
    """Filesystem scan only — must not import the full GUI (pulls in llama_cpp)."""
    if not folder.is_dir():
        return False
    for p in folder.rglob("*.gguf"):
        name = p.name.lower()
        if "embed" not in name and "mmproj" not in name:
            return True
    return False


def has_chat_model() -> bool:
    """A chat model in any folder model discovery searches. Only the program's own models/ was
    looked in, so models kept in ELI_MODELS_DIR counted as none."""
    return any(_scan_chat_gguf(folder) for folder in _model_folders())


def has_embedder() -> bool:
    try:
        from eli.core.model_download import aux_status
        return bool(aux_status("embedder").get("ok"))
    except Exception:
        from eli.core.paths import models_dir
        emb = models_dir() / "embeddings"
        if not emb.exists():
            return False
        return any(emb.rglob("*.gguf"))


def has_voice_assets() -> bool:
    try:
        from eli.runtime.voice_assets import piper_voice_ready
        from eli.perception.local_whisper_stt import whisper_cache_ready
        return bool(piper_voice_ready() and whisper_cache_ready())
    except Exception:
        root = project_root()
        piper_ok = False
        for base in (root / "tts_piper" / "piper", root / "models" / "tts" / "piper"):
            if base.exists() and any(base.rglob("*.onnx")):
                piper_ok = True
                break
        whisper = root / "models" / "whisper"
        whisper_ok = whisper.exists() and any(whisper.rglob("snapshots"))
        return piper_ok and whisper_ok


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
