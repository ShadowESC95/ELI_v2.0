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
        "key": "phi-4",
        "name": "Phi-4 (Q4_K_M)",
        "filename": "phi-4-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/phi-4-GGUF/resolve/main/phi-4-Q4_K_M.gguf",
        "size_gb": 8.4,
        "vram_gb": 12,
        "note": "Microsoft Phi-4, 14B dense (MIT licensed). Strong reasoning for its size on a 12GB+ GPU.",
    },
    {
        "key": "qwen3.6-35b-a3b",
        "name": "Qwen3.6-35B-A3B (UD-Q4_K_M, MoE)",
        "filename": "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf",
        "size_gb": 20.6,
        "vram_gb": 24,
        "note": "Mixture-of-experts: 35B total, ~3B active (Unsloth dynamic quant, Apache-2.0). "
                "Most capable Qwen here; needs a big GPU (or runs slowly on CPU/partial offload).",
    },
    {
        "key": "falcon-h1-34b",
        "name": "Falcon-H1-34B-Instruct (Q4_K_M)",
        "filename": "Falcon-H1-34B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/tiiuae/Falcon-H1-34B-Instruct-GGUF/resolve/main/Falcon-H1-34B-Instruct-Q4_K_M.gguf",
        "size_gb": 18.9,
        "vram_gb": 24,
        "note": "Largest option — Falcon-H1 hybrid (attention + SSM), 34B dense. Needs a 24GB+ "
                "GPU (or heavy CPU/partial offload).",
    },
]

# --------------------------------------------------------------------------- #
# Auxiliary models — NOT the chat LLM. The embedder is REQUIRED for memory/RAG #
# and is tiny, so it is fetched automatically on install; vision is optional.  #
# `subdir` places the file under models/<subdir>/ where the runtime looks.     #
# --------------------------------------------------------------------------- #
AUX_MODELS: List[Dict[str, Any]] = [
    {
        "key": "embedder",
        "name": "nomic-embed-text-v1.5 (Q4_K_M)",
        "filename": "nomic-embed-text-v1.5.Q4_K_M.gguf",
        "url": "https://huggingface.co/nomic-ai/nomic-embed-text-v1.5-GGUF/resolve/main/nomic-embed-text-v1.5.Q4_K_M.gguf",
        "subdir": "embeddings",
        "size_gb": 0.08,
        "required": True,
        "note": "Text embedder for memory / RAG / knowledge-graph recall. Required; auto-installed.",
    },
    {
        "key": "vision",
        "name": "Qwen2.5-VL-7B-Instruct (Q4_K_M)",
        "filename": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        "subdir": "vision",
        "size_gb": 4.4,
        "required": False,
        "note": "Optional vision model (screen/image understanding). Needs its mmproj too "
                "(key 'vision-mmproj').",
    },
    {
        "key": "vision-mmproj",
        "name": "Qwen2.5-VL-7B mmproj (vision projector)",
        "filename": "mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf",
        "url": "https://huggingface.co/unsloth/Qwen2.5-VL-7B-Instruct-GGUF/resolve/main/mmproj-F16.gguf",
        "subdir": "vision",
        "size_gb": 1.3,
        "required": False,
        "note": "Multimodal projector that pairs with the 'vision' model.",
    },
]


def list_aux(required_only: bool = False) -> List[Dict[str, Any]]:
    """Auxiliary (non-chat) models. required_only → just the ones ELI needs to
    function fully (the embedder)."""
    if required_only:
        return [e for e in AUX_MODELS if e.get("required")]
    return list(AUX_MODELS)


def get_aux(key: str) -> Optional[Dict[str, Any]]:
    key = str(key or "").strip().lower()
    for e in AUX_MODELS:
        if str(e.get("key", "")).lower() == key:
            return e
    return None


def download_aux(required_only: bool = True,
                 progress_cb: Optional[Callable[[int, int], None]] = None,
                 timeout: float = 60.0) -> List[Dict[str, Any]]:
    """Fetch auxiliary models (embedder, optionally vision). Returns one result
    dict per model. Idempotent — already-present files are skipped. Used by the
    installer + `--auto` so a fresh install has the embedder without a manual step."""
    out: List[Dict[str, Any]] = []
    for e in list_aux(required_only=required_only):
        out.append(download_model(e, progress_cb=progress_cb, timeout=timeout))
    return out

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
        if dest_dir:
            dest_dir = Path(dest_dir)
        else:
            # Auxiliary models (embedder, vision) live in a subdir, e.g. models/embeddings.
            _sub = str(entry.get("subdir") or "").strip()
            dest_dir = (models_dir() / _sub) if _sub else models_dir()
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
    lines = ["Chat models (download into %s):" % models_dir()]
    for e in list_catalog():
        tag = "  [default]" if e.get("default") else ""
        lines.append(
            f"  {e['key']:<14} {e['name']:<34} ~{e.get('size_gb','?')}GB"
            f"  (VRAM {e.get('vram_gb',0)}GB+){tag}"
        )
        if e.get("note"):
            lines.append(f"      {e['note']}")
    lines.append("")
    lines.append("Support models (embedder is required + auto-installed; vision is optional):")
    for e in list_aux():
        tag = "  [required]" if e.get("required") else "  [optional]"
        lines.append(f"  {e['key']:<14} {e['name']:<34} ~{e.get('size_gb','?')}GB{tag}")
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


def _download_one(entry: Dict[str, Any]) -> bool:
    """Download a single catalog entry with a progress bar. Returns ok."""
    sub = str(entry.get("subdir", "") or "")
    where = models_dir() / sub if sub else models_dir()
    print(f"\nDownloading {entry['name']}  (~{entry.get('size_gb','?')}GB) → {where}")
    res = download_model(entry, progress_cb=_cli_progress)
    sys.stdout.write("\n")
    if res.get("ok"):
        print(f"  ✅ {'Already present' if res.get('already_present') else 'Downloaded'}: {res['path']}")
        return True
    print(f"  ❌ {res.get('error')}")
    if res.get("resumable"):
        print("     Re-run to resume.")
    return False


def interactive_select() -> int:
    """Multiple-choice picker: show the catalog and let the user choose ANY number of
    models to download (not just one). The required embedder is always fetched. Used by
    the installers so the user controls exactly which models land on their machine."""
    cat = list_catalog()
    print("\nChoose which model(s) to download — you can pick several.\n")
    for i, e in enumerate(cat, 1):
        tag = "  [recommended default]" if e.get("default") else ""
        print(f"  {i:>2}. {e['key']:<16} {e['name']:<34} ~{e.get('size_gb','?')}GB "
              f"(VRAM {e.get('vram_gb',0)}GB+){tag}")
        if e.get("note"):
            print(f"      {e['note']}")
    print("\n  Enter numbers and/or names separated by spaces (e.g. '1 3' or 'qwen2.5-7b phi-4').")
    print("  Other options:  all  ·  auto (best fit for your hardware)  ·  none / Enter to skip")
    try:
        raw = input("\n  Your choice: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Skipped."); return 0

    low = raw.lower()
    if not raw or low in ("none", "skip", "n", "no"):
        print("  No chat model selected (you can add one later).")
        chosen: List[Dict[str, Any]] = []
    elif low == "all":
        chosen = list(cat)
    elif low == "auto":
        free = 0.0
        try:
            from eli.core.hardware_profile import detect_hardware
            free = (getattr(detect_hardware(), "free_vram_mb", 0) or 0) / 1024.0
        except Exception:
            pass
        chosen = [recommend_for_vram(free)]
        print(f"  Auto-selected '{chosen[0]['key']}' for ~{free:.1f}GB free VRAM.")
    else:
        chosen, seen = [], set()
        for tok in raw.replace(",", " ").split():
            e = None
            if tok.isdigit() and 1 <= int(tok) <= len(cat):
                e = cat[int(tok) - 1]
            else:
                e = get_entry(tok)
            if e and e["key"] not in seen:
                chosen.append(e); seen.add(e["key"])
            elif not e:
                print(f"  (ignored unknown choice: {tok!r})")

    rc = 0
    for e in chosen:
        if not _download_one(e):
            rc = 1
    # The embedder is required regardless of chat-model choice.
    print("\nEnsuring the required text embedder (memory/RAG)...")
    for ar in download_aux(required_only=True, progress_cb=_cli_progress):
        sys.stdout.write("\n")
        print(f"  ✅ embedder {'present' if ar.get('already_present') else 'downloaded'}: {ar['path']}"
              if ar.get("ok") else f"  ⚠️  embedder fetch failed: {ar.get('error')}")
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_fmt_catalog())
        print("\nUsage: python -m eli.core.model_download <key> | --choose | --list | --auto"
              "\n         --choose : pick MULTIPLE models interactively (recommended)")
        return 0
    if argv[0] in ("--list", "-l"):
        print(_fmt_catalog())
        return 0
    if argv[0] in ("--choose", "--select", "-c"):
        return interactive_select()
    if argv[0] in ("--list", "-l"):
        print(_fmt_catalog())
        return 0

    # Support models. `--aux` → all required aux (the embedder); `--aux-all` → every
    # aux incl. optional vision; `--aux <key>` → a specific one.
    if argv[0] in ("--aux", "--aux-all"):
        if len(argv) > 1:
            e = get_aux(argv[1])
            if not e:
                print(f"Unknown support model: {argv[1]!r}\n"); print(_fmt_catalog()); return 2
            targets = [e]
        else:
            targets = list_aux(required_only=(argv[0] == "--aux"))
        rc = 0
        for e in targets:
            print(f"Downloading {e['name']} → {models_dir() / str(e.get('subdir',''))}")
            res = download_model(e, progress_cb=_cli_progress); sys.stdout.write("\n")
            if res.get("ok"):
                print(f"✅ {'Already present' if res.get('already_present') else 'Downloaded'}: {res['path']}")
            else:
                print(f"❌ {res.get('error')}"); rc = 1
        return rc

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
    ok = bool(res.get("ok"))
    if ok:
        print(f"✅ {'Already present' if res.get('already_present') else 'Downloaded'}: {res['path']}")
    else:
        print(f"❌ {res.get('error')}")
        if res.get("resumable"):
            print("   Re-run the same command to resume.")

    # Always ensure the REQUIRED support models (the embedder) are present — RAG /
    # memory don't work without it, so a chat-model download pulls it too.
    for ar in download_aux(required_only=True, progress_cb=_cli_progress):
        sys.stdout.write("\n")
        if ar.get("ok"):
            print(f"✅ embedder {'present' if ar.get('already_present') else 'downloaded'}: {ar['path']}")
        else:
            print(f"⚠️  embedder fetch failed: {ar.get('error')} (memory/RAG will be limited)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
