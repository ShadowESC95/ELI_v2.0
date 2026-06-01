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
# Model resolution — MODEL-AGNOSTIC. No model name or size is hardcoded on the
# vision inference path. Paths resolve in priority order:
#   1. env  (ELI_VISION_MODEL / _MMPROJ, ELI_VISION_FAST_MODEL / _MMPROJ)
#   2. settings.json (vision_model_path / vision_mmproj_path / vision_fast_*)
#   3. structural discovery: any GGUF in the models dir that has a paired
#      projector (mmproj/clip) GGUF beside it is a VL model. Largest such pair
#      = primary; smallest distinct pair = fast glance. Pairing is gated on real
#      filename affinity, so a generically named projector is never mis-paired
#      to an unrelated text model (it's left unresolved → honest "not configured"
#      + install hint, never a wrong guess).
# The required llama-cpp chat handler is resolved per-model too (config override
# → filename auto-detect → generic Llava fallback), so ANY VL family llama-cpp
# supports works — not just one.
# ---------------------------------------------------------------------------

# Quant/format/role tokens that carry no model-identity signal — ignored when
# matching a projector to its base model.
_GENERIC_TOKENS = frozenset({
    "f16", "f32", "bf16", "fp16", "q2", "q3", "q4", "q5", "q6", "q8",
    "k", "m", "s", "l", "xl", "xs", "0", "1",
    "gguf", "instruct", "chat", "it", "base", "model", "text", "mmproj",
    "proj", "projector", "clip", "encoder", "vision", "mtmd",
})


def _safe_size(p) -> int:
    try:
        return int(p.stat().st_size)
    except Exception:
        return 0


def _model_tokens(stem: str) -> set:
    import re as _re
    toks = {t for t in _re.split(r"[^a-z0-9]+", stem.lower()) if t}
    return {t for t in toks if t not in _GENERIC_TOKENS and len(t) > 1}


def _is_projector(path) -> bool:
    n = str(path).lower()
    return any(k in n for k in ("mmproj", "clip", "projector", "-proj", "_proj", "mtmd"))


def _discover_vl_pairs(models_dir):
    """[(base_path, projector_path, base_size)] for every GGUF that has a paired
    projector beside it, largest first. Structural + name-affinity — assumes NO
    specific model name. Affinity must be > 0, so unrelated models are never
    paired to a generic projector."""
    out = []
    try:
        ggufs = list(Path(models_dir).rglob("*.gguf"))
    except Exception:
        return out
    projectors = [p for p in ggufs if _is_projector(p)]
    bases = [p for p in ggufs if not _is_projector(p)]
    seen_base = set()
    for proj in projectors:
        proj_tokens = _model_tokens(proj.stem)
        scored = []
        for b in bases:
            if b in seen_base or b.parent != proj.parent:
                continue
            affinity = len(proj_tokens & _model_tokens(b.stem))
            if affinity > 0:
                scored.append((affinity, _safe_size(b), b))
        if not scored:
            continue
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        base = scored[0][2]
        seen_base.add(base)
        out.append((base, proj, _safe_size(base)))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def _candidate_model_dirs():
    """Every plausible models directory, strongest signal first. The directory
    holding the resolved text model is the most reliable indicator of where the
    user actually keeps GGUFs (layouts vary: ./models, models/gguf/base, etc.)."""
    dirs = []
    env = os.getenv("ELI_MODELS_DIR")
    if env:
        dirs.append(Path(env).expanduser())
    try:
        from eli.core import config as _c
        mp = _c.get_gguf_model_path()
        if mp:
            dirs.append(Path(mp).expanduser().parent)
        dirs.append(Path(_c.get_model_dir()))
    except Exception:
        pass
    try:
        from eli.core.paths import project_root
        dirs.append(Path(project_root()) / "models")
    except Exception:
        pass
    dirs.append(Path("models"))
    seen, out = set(), []
    for d in dirs:
        try:
            rp = d.resolve()
        except Exception:
            continue
        if rp in seen or not rp.exists():
            continue
        seen.add(rp)
        out.append(rp)
    return out


_discovery_cache = None


def _discovered_pairs():
    global _discovery_cache
    if _discovery_cache is None:
        merged, seen_base = [], set()
        for d in _candidate_model_dirs():
            for base, proj, size in _discover_vl_pairs(d):
                rb = base.resolve()
                if rb in seen_base:
                    continue
                seen_base.add(rb)
                merged.append((base, proj, size))
        merged.sort(key=lambda t: t[2], reverse=True)
        _discovery_cache = merged
    return _discovery_cache


# Filename-substring → llama-cpp chat-handler class. DATA, extensible, and
# overridable via the `vision_chat_handler` setting. A handler is architecture-
# specific in llama-cpp (you cannot run Qwen-VL through the Moondream handler),
# so a hint table + explicit override is the correct abstraction — not a single
# hardcoded handler. Most specific hints first.
_HANDLER_HINTS = (
    ("moondream",      "MoondreamChatHandler"),
    ("qwen2.5-vl",     "Qwen25VLChatHandler"),
    ("qwen2-vl",       "Qwen25VLChatHandler"),
    ("qwen25vl",       "Qwen25VLChatHandler"),
    ("qwen2vl",        "Qwen25VLChatHandler"),
    ("minicpm",        "MiniCPMv26ChatHandler"),
    ("nanollava",      "NanoLlavaChatHandler"),
    ("obsidian",       "ObsidianChatHandler"),
    ("llama-3-vision", "Llama3VisionAlphaChatHandler"),
    ("llama3-vision",  "Llama3VisionAlphaChatHandler"),
    ("llava-v1.6",     "Llava16ChatHandler"),
    ("llava-1.6",      "Llava16ChatHandler"),
    ("llava16",        "Llava16ChatHandler"),
    ("llava-v1.5",     "Llava15ChatHandler"),
    ("llava-1.5",      "Llava15ChatHandler"),
    ("llava",          "Llava15ChatHandler"),
)

# Generic fallback when no hint matches — Llava 1.5 is the most widely-shared
# multimodal GGUF chat format.
_DEFAULT_HANDLER = "Llava15ChatHandler"


def _resolve_handler_class(model_path: str, explicit: str = ""):
    """Resolve the llama-cpp chat-handler class for a VL model.
    config override → filename auto-detect → generic. Returns (cls, name)."""
    from llama_cpp import llama_chat_format as _lcf
    name = (explicit or "").strip()
    if not name:
        low = os.path.basename(str(model_path or "")).lower()
        for hint, cls in _HANDLER_HINTS:
            if hint in low:
                name = cls
                break
    if not name:
        name = _DEFAULT_HANDLER
    handler_cls = getattr(_lcf, name, None)
    if handler_cls is None:
        available = sorted(n for n in dir(_lcf) if n.endswith("ChatHandler"))
        raise RuntimeError(
            f"vision chat handler {name!r} not available in this llama-cpp build; "
            f"set 'vision_chat_handler' to one of: {available}"
        )
    return handler_cls, name
_DEFAULT_PROMPT = (
    "You are ELI looking at the user's screen. Describe what is shown clearly "
    "and concisely: the application(s) in focus, what the user appears to be "
    "doing, and any important text, code, errors, or UI state. Be specific and "
    "factual. Do not invent anything you cannot actually see."
)

# Example repo shown in the install hint ONLY as a worked example — ELI works
# with any VL GGUF + projector, this is not a required model.
_EXAMPLE_HF_REPO = "unsloth/Qwen2.5-VL-7B-Instruct-GGUF"


def _cfg(key: str, default: Any = None) -> Any:
    try:
        from eli.core import config
        val = config.get(key, default)
        return default if val is None else val
    except Exception:
        return default


def vision_settings() -> Dict[str, Any]:
    """Resolve the active vision configuration from settings (+ env overrides),
    falling back to structural discovery so no model name is hardcoded."""
    pairs = _discovered_pairs()
    disc_primary = pairs[0] if pairs else None
    disc_fast = pairs[-1] if len(pairs) >= 2 else None  # smallest distinct pair

    def _resolve(env_key: str, cfg_key: str, disc_path) -> str:
        v = (os.environ.get(env_key) or "").strip()
        if v:
            return v
        v = str(_cfg(cfg_key, "") or "").strip()
        if v:
            return v
        return str(disc_path) if disc_path else ""

    model = _resolve("ELI_VISION_MODEL", "vision_model_path",
                     disc_primary[0] if disc_primary else None)
    mmproj = _resolve("ELI_VISION_MMPROJ", "vision_mmproj_path",
                      disc_primary[1] if disc_primary else None)
    chat_handler = (os.environ.get("ELI_VISION_HANDLER")
                    or str(_cfg("vision_chat_handler", "") or "")).strip()
    fast_chat_handler = (os.environ.get("ELI_VISION_FAST_HANDLER")
                         or str(_cfg("vision_fast_chat_handler", "") or "")).strip()

    def _as_int(v, d):
        try:
            return int(v)
        except Exception:
            return d

    return {
        "enabled": bool(_cfg("vision_enabled", True)),
        "model_path": model,
        "mmproj_path": mmproj,
        "chat_handler": chat_handler,
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
        # --- Fast glance model (Moondream) ---
        "fast_enabled": bool(_cfg("vision_fast_enabled", True)),
        "fast_model_path": _resolve("ELI_VISION_FAST_MODEL", "vision_fast_model_path",
                                    disc_fast[0] if disc_fast else None),
        "fast_mmproj_path": _resolve("ELI_VISION_FAST_MMPROJ", "vision_fast_mmproj_path",
                                     disc_fast[1] if disc_fast else None),
        "fast_chat_handler": fast_chat_handler,
        "fast_n_ctx": _as_int(_cfg("vision_fast_n_ctx", 2048), 2048),
        "fast_n_gpu_layers": _as_int(_cfg("vision_fast_n_gpu_layers", 99), 99),
        # Co-resident mode: keep the text model loaded and run Moondream
        # alongside it (no swap → no ~15s text-model reload per glance). OFF by
        # default until VRAM fit is confirmed on this 8GB GPU; flip to true once
        # tested. When false, fast glances hot-swap like the primary model.
        "fast_no_swap": bool(_cfg("vision_fast_no_swap", False)),
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
        _resolve_handler_class(s["model_path"], s.get("chat_handler", ""))
    except Exception as e:
        return False, f"llama-cpp-python multimodal handler unavailable: {e}"
    return True, "ready"


def fast_vision_available() -> Tuple[bool, str]:
    """Return (available, reason) for the local Moondream fast-glance model.

    Local-only: requires the Moondream GGUF + mmproj files to exist on disk.
    No network, no API — same constructor-with-local-path path as the primary
    model.
    """
    s = vision_settings()
    if not s["enabled"] or not s["fast_enabled"]:
        return False, "Fast vision is disabled."
    if not s["fast_model_path"] or not s["fast_mmproj_path"]:
        return False, "Fast (Moondream) model path or mmproj path is not configured."
    mp, pp = _abs(s["fast_model_path"]), _abs(s["fast_mmproj_path"])
    if not Path(mp).exists():
        return False, f"Fast model file not found: {mp}"
    if not Path(pp).exists():
        return False, f"Fast projector (mmproj) file not found: {pp}"
    try:
        import llama_cpp  # noqa: F401
        _resolve_handler_class(s["fast_model_path"], s.get("fast_chat_handler", ""))
    except Exception as e:
        return False, f"fast vision handler unavailable: {e}"
    return True, "ready"


def install_hint() -> str:
    """Human-readable instructions for obtaining a local vision model.

    Model-agnostic: ANY multimodal GGUF + its projector works. ELI auto-detects
    the llama-cpp handler from the filename; override with vision_chat_handler if
    your model isn't auto-detected.
    """
    s = vision_settings()
    cur_model = s["model_path"] or "(none found — drop a VL GGUF + its mmproj in models/)"
    cur_mmproj = s["mmproj_path"] or "(none found)"
    return (
        "Local vision needs ANY multimodal (VL) GGUF model + its mmproj (vision "
        "projector) — e.g. Qwen2.5-VL, LLaVA, MiniCPM-V, Moondream, NanoLLaVA. "
        "They are not bundled (several GB). Drop both files into models/ and ELI "
        "will discover the pair automatically.\n\n"
        f"Example (one of many valid models):\n"
        f"  huggingface-cli download {_EXAMPLE_HF_REPO} \\\n"
        "    *Q4_K_M.gguf *mmproj*.gguf --local-dir models/\n\n"
        "Resolution order: ELI_VISION_MODEL/_MMPROJ env → vision_model_path/"
        "vision_mmproj_path settings → auto-discovery of any projector-paired GGUF.\n"
        f"  currently resolved model  = {cur_model}\n"
        f"  currently resolved mmproj = {cur_mmproj}\n\n"
        "If the chat handler isn't auto-detected from the filename, set "
        "vision_chat_handler (e.g. 'Llava16ChatHandler') or ELI_VISION_HANDLER."
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


def _load_vl(settings: Dict[str, Any], fast: bool = False):
    from llama_cpp import Llama

    # Vision encoder on CPU by default — GPU clip segfaults on this build/GPU.
    if not bool(_cfg("vision_clip_on_gpu", False)):
        _force_cpu_clip()

    if fast:
        # Local glance model — constructor takes a local clip file; never
        # from_pretrained (the only thing that would hit the network).
        model = _abs(settings["fast_model_path"])
        mmproj = _abs(settings["fast_mmproj_path"])
        n_ctx = int(settings["fast_n_ctx"])
        n_gpu_layers = int(settings["fast_n_gpu_layers"])
        _Handler, _hname = _resolve_handler_class(model, settings.get("fast_chat_handler", ""))
    else:
        model = _abs(settings["model_path"])
        mmproj = _abs(settings["mmproj_path"])
        n_ctx = int(settings["n_ctx"])
        n_gpu_layers = int(settings["n_gpu_layers"])
        _Handler, _hname = _resolve_handler_class(model, settings.get("chat_handler", ""))

    log.debug(f"[VISION] handler={_hname} model={os.path.basename(model)} (model-agnostic resolve)")
    handler = _Handler(clip_model_path=mmproj, verbose=False)
    llm = Llama(
        model_path=model,
        chat_handler=handler,
        n_ctx=n_ctx,
        n_gpu_layers=n_gpu_layers,
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


# --- Co-resident fast model: loaded once (before the text model) and kept ---
_resident_fast_vl = None


def load_resident_fast_model() -> Tuple[bool, str]:
    """Load the fast (Moondream) model once and keep it resident in VRAM.

    Called BEFORE the text model so the autotuner/cap sizes the 7B to the
    remainder. Idempotent. 100% local — no network. Returns (ok, reason).
    """
    global _resident_fast_vl
    if _resident_fast_vl is not None:
        return True, "already resident"
    ok, reason = fast_vision_available()
    if not ok:
        return False, reason
    try:
        _resident_fast_vl = _load_vl(vision_settings(), fast=True)
        log.debug("[VISION] fast model (Moondream) loaded resident (co-resident mode)")
        return True, "loaded"
    except Exception as e:
        _resident_fast_vl = None
        log.debug(f"[VISION] resident fast-model load failed: {e}")
        return False, f"resident load failed: {e}"


def unload_resident_fast_model() -> None:
    """Close the resident fast model (shutdown)."""
    global _resident_fast_vl
    if _resident_fast_vl is not None:
        _close_vl(_resident_fast_vl)
        _resident_fast_vl = None


def resident_fast_loaded() -> bool:
    return _resident_fast_vl is not None


def describe_image(
    image_path: str,
    prompt: Optional[str] = None,
    *,
    max_tokens: Optional[int] = None,
    prefer_fast: bool = False,
) -> Dict[str, Any]:
    """
    Run a local VL model on an image and return a description.

    prefer_fast=True uses the small Moondream model when available (for ambient
    glances / quick "what's on my screen"), falling back to the primary model.
    Both are 100% local GGUF — no API, no network at inference. Hot-swaps the
    text model out and back, unless the fast model is in co-resident (no-swap)
    mode. Returns {ok, text, error, model, elapsed, swapped}.
    """
    started = time.time()
    image_path = _abs(image_path)
    if not image_path or not Path(image_path).exists():
        return {"ok": False, "text": "", "error": f"Image not found: {image_path}",
                "swapped": False}

    settings = vision_settings()

    # Choose the model: fast (Moondream) when asked and available, else primary.
    use_fast = False
    if prefer_fast:
        _fok, _freason = fast_vision_available()
        if _fok:
            use_fast = True
    if not use_fast:
        ok, reason = vision_available()
        if not ok:
            # If a fast glance was wanted but neither is ready, surface both reasons.
            if prefer_fast:
                _fok, _freason = fast_vision_available()
                reason = f"{reason} (fast: {_freason})"
            return {"ok": False, "text": "", "error": reason, "hint": install_hint(),
                    "swapped": False}

    # If the fast model is already resident (co-resident mode), reuse it: no
    # load, no swap, no close — just infer. This is the ~3.5s path.
    use_resident = bool(use_fast and _resident_fast_vl is not None)
    no_swap = bool(use_resident or (use_fast and settings.get("fast_no_swap")))
    if use_fast:
        # Moondream is tuned for SHORT, direct queries — long ELI-voice prompts
        # confuse it. Use a terse native prompt; OCR + the text-model fusion
        # supply the accurate detail it can't resolve.
        prompt = str(_cfg("vision_fast_prompt", "Describe what is shown in this image in one or two sentences.")).strip()
    else:
        prompt = (prompt or settings["default_prompt"]).strip()
    max_tokens = int(max_tokens or settings["max_tokens"])
    _model_path = settings["fast_model_path"] if use_fast else settings["model_path"]

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
        vl = _resident_fast_vl if use_resident else _load_vl(settings, fast=use_fast)
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
            # Free VRAM held by the text model before loading VL — UNLESS the
            # fast model runs co-resident (no_swap), in which case both fit and
            # we skip the costly text-model unload/reload entirely.
            if not no_swap:
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
                    "model": Path(_model_path).name,
                    "swapped": swapped}
        except Exception as e:
            log.debug(f"[VISION] inference failed: {e}")
            return {"ok": False, "text": "", "error": f"Vision inference failed: {e}",
                    "swapped": swapped}
        finally:
            # Never close the RESIDENT model — it stays loaded for reuse.
            if not use_resident:
                _close_vl(vl)
            # Restore the text model only if we actually swapped it out. In
            # co-resident (no_swap) mode it was never unloaded — leave it.
            if text_was_loaded and swapped:
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
