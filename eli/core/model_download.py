"""
Curated GGUF model download helper.

This is an INSTALL-TIME convenience menu only. It is NOT part of the inference
path — ELI discovers and loads whatever .gguf files exist in models_dir() and
never hardcodes a model name or size for inference. The catalog below is a small,
data-driven set of public, single-file GGUF models offered to a new user so a
fresh install isn't dead on arrival (no model → no assistant).

Downloads:
  * route through eli.core.netguard (offline-by-default is preserved; a deliberate
    user choice opens a scoped allow_network() window, nothing is persisted),
  * are resumable (HTTP Range),
  * are validated by the GGUF magic header before being accepted,
  * require NO API key and NO extra pip dependency (stdlib urllib).

The catalog can be overridden/extended without touching code via a JSON file at
$ELI_MODEL_CATALOG or  <models_dir>/catalog.json  (same schema as CATALOG).

CLI:
    python -m eli.core.model_download --list
    python -m eli.core.model_download <key>          # e.g. qwen2.5-7b
    python -m eli.core.model_download --auto          # pick by detected VRAM
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from eli.core import netguard
from eli.core.paths import models_dir

# --------------------------------------------------------------------------- #
# Curated catalog — suggested downloads, NOT an inference-path constraint.     #
# size_gb is approximate (for display + a download sanity check, not exact).   #
# vram_gb is the rough minimum for a comfortable GPU offload; all run on CPU.  #
# --------------------------------------------------------------------------- #
CATALOG: List[Dict[str, Any]] = [
    {
        "key": "qwen2.5-3b",
        "name": "Qwen2.5-3B-Instruct (Q4_K_M)",
        "filename": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen2.5-3B-Instruct-GGUF/resolve/main/Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "size_gb": 1.8,
        "vram_gb": 4,
        "note": "Best small model. Great on 4GB+ GPUs or CPU-only.",
    },
    {
        "key": "qwen2.5-7b",
        "name": "Qwen2.5-7B-Instruct (Q4_K_M)",
        "filename": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "size_gb": 4.4,
        "vram_gb": 8,
        "note": "Recommended default. Strong general assistant on an 8GB GPU.",
        "default": True,
    },
    {
        "key": "qwen3-8b",
        "name": "Qwen3-8B (Q4_K_M)",
        "filename": "Qwen_Qwen3-8B-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen_Qwen3-8B-GGUF/resolve/main/Qwen_Qwen3-8B-Q4_K_M.gguf",
        "size_gb": 4.7,
        "vram_gb": 8,
        "note": "Newer Qwen3 (40K context, reasoning-capable). Also the LoRA base — see training/.",
    },
    {
        "key": "falcon3-10b",
        "name": "Falcon3-10B-Instruct (Q4_K_M)",
        "filename": "Falcon3-10B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Falcon3-10B-Instruct-GGUF/resolve/main/Falcon3-10B-Instruct-Q4_K_M.gguf",
        "size_gb": 5.9,
        "vram_gb": 12,
        "note": "Larger dense model. A capable step up on a 12GB+ GPU.",
    },
    {
        "key": "qwen3-30b-a3b",
        "name": "Qwen3-30B-A3B (Q4_K_M, MoE)",
        "filename": "Qwen_Qwen3-30B-A3B-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen_Qwen3-30B-A3B-GGUF/resolve/main/Qwen_Qwen3-30B-A3B-Q4_K_M.gguf",
        "size_gb": 17.4,
        "vram_gb": 20,
        "note": "Mixture-of-experts: 30B total, ~3B active. Most capable here; needs a big GPU "
                "(or runs slowly on CPU/partial offload).",
    },
]

_GGUF_MAGIC = b"GGUF"
_CHUNK = 1024 * 256  # 256 KiB


# --------------------------------------------------------------------------- #
# Catalog access                                                              #
# --------------------------------------------------------------------------- #
def _load_override_catalog() -> List[Dict[str, Any]]:
    candidates = []
    env = os.environ.get("ELI_MODEL_CATALOG")
    if env:
        candidates.append(Path(env).expanduser())
    try:
        candidates.append(models_dir() / "catalog.json")
    except Exception:
        pass
    for p in candidates:
        try:
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    return [dict(x) for x in data if isinstance(x, dict)]
        except Exception:
            continue
    return []


def list_catalog() -> List[Dict[str, Any]]:
    """Return the catalog (override file wins over the built-in list)."""
    override = _load_override_catalog()
    return override or list(CATALOG)


def get_entry(key: str) -> Optional[Dict[str, Any]]:
    key = str(key or "").strip().lower()
    for e in list_catalog():
        if str(e.get("key", "")).lower() == key:
            return e
    return None


def default_entry() -> Dict[str, Any]:
    cat = list_catalog()
    for e in cat:
        if e.get("default"):
            return e
    return cat[0]


def recommend_for_vram(free_vram_gb: Optional[float]) -> Dict[str, Any]:
    """Largest catalog model that fits the detected VRAM (CPU-only → smallest)."""
    cat = sorted(list_catalog(), key=lambda e: float(e.get("vram_gb", 0)))
    if not free_vram_gb or free_vram_gb <= 0:
        return cat[0]
    fit = [e for e in cat if float(e.get("vram_gb", 0)) <= float(free_vram_gb)]
    return (fit[-1] if fit else cat[0])


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #
def is_valid_gguf(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 1024 * 1024:
            return False
        with open(path, "rb") as f:
            return f.read(4) == _GGUF_MAGIC
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Download                                                                    #
# --------------------------------------------------------------------------- #
def download_model(
    key_or_entry: Any,
    dest_dir: Optional[Path] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: float = 60.0,
) -> Dict[str, Any]:
    """Download a catalog model, resumable, gated through netguard.

    progress_cb(downloaded_bytes, total_bytes) is called periodically; total may
    be 0 if the server omits Content-Length. Returns a result dict with ok/path.
    """
    entry = key_or_entry if isinstance(key_or_entry, dict) else get_entry(key_or_entry)
    if not entry:
        return {"ok": False, "error": f"Unknown model key: {key_or_entry!r}"}

    url = str(entry.get("url") or "").strip()
    filename = str(entry.get("filename") or "").strip() or os.path.basename(url)
    if not url or not filename:
        return {"ok": False, "error": "Catalog entry missing url/filename"}

    try:
        dest_dir = Path(dest_dir) if dest_dir else models_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": f"Cannot create models dir: {e}"}

    final_path = dest_dir / filename
    if is_valid_gguf(final_path):
        return {"ok": True, "path": str(final_path), "already_present": True,
                "name": entry.get("name"), "key": entry.get("key")}

    part_path = dest_dir / (filename + ".part")
    resume_from = part_path.stat().st_size if part_path.exists() else 0

    headers = {"User-Agent": "ELI-MKXI/2.0 (model-download)"}
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    # Deliberate, user-initiated download → scoped network window. Everything
    # still routes through guarded_urlopen so the socket guard sees the override.
    try:
        with netguard.allow_network(f"model download: {filename}"):
            req = urllib.request.Request(url, headers=headers)
            with netguard.guarded_urlopen(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200) or 200
                # Server ignored Range (200 not 206) → start fresh.
                mode = "ab"
                if resume_from > 0 and status != 206:
                    resume_from = 0
                    mode = "wb"
                total = 0
                clen = resp.headers.get("Content-Length")
                if clen and str(clen).isdigit():
                    total = int(clen) + (resume_from if status == 206 else 0)
                downloaded = resume_from
                if progress_cb:
                    try:
                        progress_cb(downloaded, total)
                    except Exception:
                        pass
                with open(part_path, mode) as out:
                    while True:
                        chunk = resp.read(_CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        downloaded += len(chunk)
                        if progress_cb:
                            try:
                                progress_cb(downloaded, total)
                            except Exception:
                                pass
    except netguard.OfflineError as e:
        return {"ok": False, "error": f"Network is off and the download could not be authorised: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Download failed: {e}",
                "resumable": bool(part_path.exists()), "part": str(part_path)}

    # Truncation guard: the stream can end "cleanly" yet short (e.g. a silently
    # half-closed connection). If the server told us the size, the bytes on disk
    # must match it — otherwise keep the .part for resume rather than renaming a
    # truncated file into place and calling it done.
    if total > 0:
        actual = part_path.stat().st_size if part_path.exists() else 0
        if actual < total:
            return {"ok": False,
                    "error": f"Download incomplete: got {actual} of {total} bytes.",
                    "resumable": True, "part": str(part_path)}

    if not is_valid_gguf(part_path):
        return {"ok": False, "error": "Downloaded file is not a valid GGUF (corrupt or wrong URL).",
                "part": str(part_path)}

    try:
        part_path.replace(final_path)
    except Exception as e:
        return {"ok": False, "error": f"Could not finalise download: {e}", "part": str(part_path)}

    return {"ok": True, "path": str(final_path), "already_present": False,
            "name": entry.get("name"), "key": entry.get("key")}


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def _fmt_catalog() -> str:
    lines = ["Available models (download into %s):" % models_dir()]
    for e in list_catalog():
        tag = "  [default]" if e.get("default") else ""
        lines.append(
            f"  {e['key']:<14} {e['name']:<34} ~{e.get('size_gb','?')}GB"
            f"  (VRAM {e.get('vram_gb',0)}GB+){tag}"
        )
        if e.get("note"):
            lines.append(f"      {e['note']}")
    return "\n".join(lines)


def _cli_progress(done: int, total: int) -> None:
    mb = done / (1024 * 1024)
    if total:
        pct = 100.0 * done / total
        sys.stdout.write(f"\r  ↓ {mb:8.1f} MB / {total/(1024*1024):.1f} MB  ({pct:5.1f}%)")
    else:
        sys.stdout.write(f"\r  ↓ {mb:8.1f} MB")
    sys.stdout.flush()


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_fmt_catalog())
        print("\nUsage: python -m eli.core.model_download <key> | --list | --auto")
        return 0
    if argv[0] in ("--list", "-l"):
        print(_fmt_catalog())
        return 0

    if argv[0] == "--auto":
        free = None
        try:
            from eli.core.hardware_profile import detect_hardware
            hw = detect_hardware()
            free = (getattr(hw, "free_vram_mb", 0) or 0) / 1024.0
        except Exception:
            free = 0
        entry = recommend_for_vram(free)
        print(f"Auto-selected '{entry['key']}' for ~{free:.1f}GB free VRAM.")
    else:
        entry = get_entry(argv[0])
        if not entry:
            print(f"Unknown model key: {argv[0]!r}\n")
            print(_fmt_catalog())
            return 2

    print(f"Downloading {entry['name']} → {models_dir()}")
    res = download_model(entry, progress_cb=_cli_progress)
    sys.stdout.write("\n")
    if res.get("ok"):
        where = res["path"]
        print(f"✅ {'Already present' if res.get('already_present') else 'Downloaded'}: {where}")
        return 0
    print(f"❌ {res.get('error')}")
    if res.get("resumable"):
        print("   Re-run the same command to resume.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
