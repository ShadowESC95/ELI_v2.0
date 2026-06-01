#!/usr/bin/env python3
"""
ELI local vision — true image understanding via a local GGUF vision-language
model (default: Qwen2.5-VL-7B), run through llama-cpp-python's multimodal
chat handler.

100% local, no network at inference time. Because a 7B VL model will not
co-reside with the 7B text model on an 8GB GPU, this module HOT-SWAPS: it
unloads the text model, loads the VL model, runs the vision call, then always
restores the text model (even on failure). The whole swap holds the shared
gguf_inference LLM lock so no text-generation call can race a half-loaded GPU.

Public API:
    vision_settings()                  -> dict of vision config
    vision_available()                 -> (ok: bool, reason: str)
    describe_image(path, prompt=None)  -> {ok, text, error, ...}
    install_hint()                     -> human-readable download instructions
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:
    from eli.utils.log import get_logger  # type: ignore
    log = get_logger("eli.vision")
except Exception:  # pragma: no cover
    import logging
    log = logging.getLogger("eli.vision")


# ---------------------------------------------------------------------------
# Defaults — Qwen2.5-VL-7B GGUF (same family as the default text model)
# ---------------------------------------------------------------------------

_DEFAULT_VISION_MODEL = "models/Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf"
_DEFAULT_VISION_MMPROJ = "models/mmproj-Qwen2.5-VL-7B-Instruct-f16.gguf"
_DEFAULT_PROMPT = (
    "You are ELI looking at the user's screen. Describe what is shown clearly "
    "and concisely: the application(s) in focus, what the user appears to be "
    "doing, and any important text, code, errors, or UI state. Be specific and "
    "factual. Do not invent anything you cannot actually see."
)

# Hugging Face source for the install hint (the user downloads these once).
_HF_REPO = "unsloth/Qwen2.5-VL-7B-Instruct-GGUF"


def _cfg(key: str, default: Any = None) -> Any:
    try:
        from eli.core import config
        val = config.get(key, default)
        return default if val is None else val
    except Exception:
        return default


def vision_settings() -> Dict[str, Any]:
    """Resolve the active vision configuration from settings (+ env overrides)."""
    model = (os.environ.get("ELI_VISION_MODEL")
             or str(_cfg("vision_model_path", _DEFAULT_VISION_MODEL) or "")).strip()
    mmproj = (os.environ.get("ELI_VISION_MMPROJ")
              or str(_cfg("vision_mmproj_path", _DEFAULT_VISION_MMPROJ) or "")).strip()

    def _as_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

    return {
        "enabled": bool(_cfg("vision_enabled", True)),
        "model_path": model,
        "mmproj_path": mmproj,
        "n_ctx": _as_int(_cfg("vision_n_ctx", 4096), 4096),
        # All layers on GPU by default — the text model is unloaded first, so the
        # ~7GB freed is enough for a 7B Q4 VL + clip. Lower if you hit OOM.
        "n_gpu_layers": _as_int(_cfg("vision_n_gpu_layers", 99), 99),
        "n_batch": _as_int(_cfg("vision_n_batch", 256), 256),
        # Downscale large screenshots before vision: a 4K/dual-monitor grab
        # produces thousands of image tokens (e.g. 3840×1440 → ~4000 tokens),
        # which overflows the context and can crash the clip encoder. The
        # longest side is capped to this many pixels; exact text is still
        # covered by the full-resolution OCR pass that runs alongside.
        "max_image_px": _as_int(_cfg("vision_max_image_px", 1280), 1280),
        "max_tokens": _as_int(_cfg("vision_max_tokens", 512), 512),
        "temperature": float(_cfg("vision_temperature", 0.2) or 0.2),
        "repeat_penalty": float(_cfg("vision_repeat_penalty", 1.3) or 1.3),
        "default_prompt": str(_cfg("vision_default_prompt", _DEFAULT_PROMPT) or _DEFAULT_PROMPT),
    }


def _abs(p: str) -> str:
    return str(Path(os.path.expanduser(p)).resolve()) if p else ""


def vision_available() -> Tuple[bool, str]:
    """Return (available, reason). Available means model + mmproj files exist."""
    s = vision_settings()
    if not s["enabled"]:
        return False, "Vision is disabled (set vision_enabled=true to turn it on)."
    if not s["model_path"] or not s["mmproj_path"]:
        return False, "Vision model path or mmproj path is not configured."
    mp, pp = _abs(s["model_path"]), _abs(s["mmproj_path"])
    if not Path(mp).exists():
        return False, f"Vision model file not found: {mp}"
    if not Path(pp).exists():
        return False, f"Vision projector (mmproj) file not found: {pp}"
    try:
        import llama_cpp  # noqa: F401
        from llama_cpp.llama_chat_format import Qwen25VLChatHandler  # noqa: F401
    except Exception as e:
        return False, f"llama-cpp-python multimodal support unavailable: {e}"
    return True, "ready"


def install_hint() -> str:
    """Human-readable instructions for obtaining the local vision model."""
    s = vision_settings()
    return (
        "Local vision needs a Qwen2.5-VL GGUF model + its mmproj (vision projector). "
        "They are not bundled (several GB). Download once, e.g.:\n\n"
        f"  huggingface-cli download {_HF_REPO} \\\n"
        "    Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf mmproj-F16.gguf \\\n"
        "    --local-dir models/\n\n"
        f"Then point settings at them (expected by default):\n"
        f"  vision_model_path = {s['model_path']}\n"
        f"  vision_mmproj_path = {s['mmproj_path']}\n\n"
        "Filenames vary by repo — set vision_model_path / vision_mmproj_path to match "
        "whatever you downloaded (or ELI_VISION_MODEL / ELI_VISION_MMPROJ env vars)."
    )


def _downscaled_png_bytes(path: str, max_px: int) -> Optional[bytes]:
    """Return PNG bytes of the image downscaled so its longest side <= max_px.

    Returns None if PIL is unavailable or downscaling isn't needed/possible, in
    which case the caller falls back to the original file bytes.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            w, h = img.width, img.height
            longest = max(w, h)
            if max_px <= 0 or longest <= max_px:
                return None  # no downscale needed
            scale = max_px / float(longest)
            new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size, Image.LANCZOS)
            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as e:
        log.debug(f"[VISION] downscale failed ({e}); using original image")
        return None


def _image_data_uri(path: str, max_px: int = 0) -> str:
    """Encode an image as a base64 data URI, downscaling first if it's huge."""
    small = _downscaled_png_bytes(path, max_px) if max_px else None
    if small is not None:
        b64 = base64.b64encode(small).decode("ascii")
        return f"data:image/png;base64,{b64}"
    p = Path(path)
    ext = p.suffix.lower().lstrip(".") or "png"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif",
            "bmp": "bmp", "webp": "webp", "tif": "tiff", "tiff": "tiff"}.get(ext, "png")
    data = p.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/{mime};base64,{b64}"


# Module-level handle so a loaded VL model could be reused within one swap
# window if ever needed; normally loaded and closed per call.
_vl_llm = None


_mtmd_cpu_patched = False


def _force_cpu_clip() -> None:
    """Force the mtmd/clip vision context onto CPU.

    llama-cpp-python hardcodes `ctx_params.use_gpu = True` for the vision
    encoder (llama_chat_format.py), and on some GPUs (e.g. RTX 2060 SUPER,
    compute 7.5) that CUDA path segfaults inside `mtmd_helper_eval_chunk_single`.
    Running the vision encoder on CPU avoids the crash; the language decoder
    still runs on GPU via n_gpu_layers. We patch the params right before the
    native init so we don't depend on copying the handler's __init__ body.
    """
    global _mtmd_cpu_patched
    if _mtmd_cpu_patched:
        return
    try:
        import llama_cpp.mtmd_cpp as mtmd_cpp
        _orig = mtmd_cpp.mtmd_init_from_file

        def _patched(clip_path, model, params):
            try:
                params.use_gpu = False
            except Exception:
                pass
            return _orig(clip_path, model, params)

        mtmd_cpp.mtmd_init_from_file = _patched
        _mtmd_cpu_patched = True
        log.debug("[VISION] mtmd vision encoder forced to CPU (avoids CUDA clip segfault)")
    except Exception as e:
        log.debug(f"[VISION] could not force CPU clip: {e}")


def _load_vl(settings: Dict[str, Any]):
    from llama_cpp import Llama
    from llama_cpp.llama_chat_format import Qwen25VLChatHandler

    # Vision encoder on CPU by default — GPU clip segfaults on this build/GPU.
    if not bool(_cfg("vision_clip_on_gpu", False)):
        _force_cpu_clip()

    mmproj = _abs(settings["mmproj_path"])
    model = _abs(settings["model_path"])
    handler = Qwen25VLChatHandler(clip_model_path=mmproj, verbose=False)
    llm = Llama(
        model_path=model,
        chat_handler=handler,
        n_ctx=int(settings["n_ctx"]),
        n_gpu_layers=int(settings["n_gpu_layers"]),
        n_batch=int(settings["n_batch"]),
        logits_all=False,
        verbose=False,
    )
    return llm


def _close_vl(llm) -> None:
    try:
        if llm is not None:
            llm.close()
    except Exception:
        pass


def describe_image(
    image_path: str,
    prompt: Optional[str] = None,
    *,
    max_tokens: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run the local VL model on an image and return a description.

    Hot-swaps the text model out and back. Returns:
        {ok: bool, text: str, error: str, model: str, elapsed: float, swapped: bool}
    """
    started = time.time()
    image_path = _abs(image_path)
    if not image_path or not Path(image_path).exists():
        return {"ok": False, "text": "", "error": f"Image not found: {image_path}",
                "swapped": False}

    ok, reason = vision_available()
    if not ok:
        return {"ok": False, "text": "", "error": reason, "hint": install_hint(),
                "swapped": False}

    settings = vision_settings()
    prompt = (prompt or settings["default_prompt"]).strip()
    max_tokens = int(max_tokens or settings["max_tokens"])

    # Coordinate with the text model: hold the shared LLM lock for the whole
    # swap so no text-generation call reaches a half-loaded GPU.
    try:
        from eli.cognition import gguf_inference as gi
    except Exception as e:
        return {"ok": False, "text": "", "error": f"Inference core unavailable: {e}",
                "swapped": False}

    lock = getattr(gi, "_LLM_CALL_LOCK", None)
    text_was_loaded = False
    vl = None
    swapped = False

    def _do_vision() -> Dict[str, Any]:
        nonlocal vl
        vl = _load_vl(settings)
        messages = [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": _image_data_uri(image_path, int(settings.get("max_image_px", 1280)))}},
                {"type": "text", "text": prompt},
            ],
        }]
        out = vl.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=float(settings["temperature"]),
            # Curb repetition loops: on a repetitive screen (e.g. a terminal of
            # identical lines) low-temp VL output can latch onto one phrase and
            # repeat it for the whole budget. repeat_penalty + top_k break that.
            repeat_penalty=float(settings.get("repeat_penalty", 1.3)),
            top_p=0.9,
            top_k=40,
        )
        text = ""
        try:
            text = str(out["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            text = ""
        return {"text": text}

    def _run() -> Dict[str, Any]:
        nonlocal text_was_loaded, swapped
        try:
            text_was_loaded = bool(getattr(gi, "is_loaded", lambda: False)())
        except Exception:
            text_was_loaded = False
        try:
            # Free VRAM held by the text model before loading VL.
            try:
                gi.unload_model()
            except Exception as ue:
                log.debug(f"[VISION] text-model unload failed (continuing): {ue}")
            swapped = True
            res = _do_vision()
            if not res.get("text"):
                return {"ok": False, "text": "",
                        "error": "Vision model returned no description.",
                        "swapped": swapped}
            return {"ok": True, "text": res["text"], "error": "",
                    "model": Path(settings["model_path"]).name,
                    "swapped": swapped}
        except Exception as e:
            log.debug(f"[VISION] inference failed: {e}")
            return {"ok": False, "text": "", "error": f"Vision inference failed: {e}",
                    "swapped": swapped}
        finally:
            _close_vl(vl)
            # ALWAYS try to restore the text model — losing it would brick ELI.
            if text_was_loaded:
                for attempt in range(2):
                    try:
                        gi.load_model(force_reload=True)
                        break
                    except Exception as re:
                        log.debug(f"[VISION] text-model restore attempt {attempt+1} failed: {re}")
                        time.sleep(0.5)

    if lock is not None:
        with lock:
            result = _run()
    else:
        result = _run()

    result["elapsed"] = round(time.time() - started, 2)
    return result
