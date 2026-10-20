import os
import tempfile
import threading
from pathlib import Path
from typing import Optional


from eli.utils.log import get_logger
log = get_logger(__name__)

_MODEL = None
_MODEL_KEY = None
_MODEL_LOCK = threading.Lock()
_MODEL_LOADING = False   # True while a download/load is in progress
_MODEL_READY = threading.Event()  # set once the model is loaded successfully
_CUDA_FAILED = False  # set permanently once CUDA OOM occurs; prevents re-escalation


def _env(name, default):
    return (os.environ.get(name, default) or default).strip()


def _whisper_hub_dir(model: str) -> str:
    """HF cache folder name faster-whisper uses under download_root."""
    return f"models--Systran--faster-whisper-{model.replace('/', '--')}"


def _whisper_weights_mb(model: str, model_dir: str) -> float:
    """This whisper model's weights on disk (its model.bin), 0 when not downloaded."""
    candidates = list(Path(model_dir).glob(f"{_whisper_hub_dir(model)}/snapshots/*/model.bin"))
    candidates.append(Path(model) / "model.bin")
    for f in candidates:
        try:
            return f.resolve().stat().st_size / 1_048_576
        except OSError:
            continue
    return 0.0


_DEVICE_DECIDED: dict = {}


def _whisper_card() -> Optional[dict]:
    """The card ctranslate2 runs whisper on: CUDA device 0, the first NVIDIA card in bus order
    (eli/__init__.py sets CUDA_DEVICE_ORDER=PCI_BUS_ID). None otherwise: ctranslate2 is CUDA only."""
    try:
        from eli.core.hardware_profile import get_live_gpu_telemetry
        cards = [d for d in (get_live_gpu_telemetry().get("devices") or []) if d.get("vendor") == "nvidia"]
    except Exception:
        log.debug("whisper card unknown", exc_info=True)
        return None
    return cards[0] if cards else None


def _footprint_file() -> Path:
    from eli.core.paths import data_dir
    return Path(data_dir()) / "runtime" / "whisper_gpu.json"


def _footprint_key(card: dict, model: str) -> str:
    return f"{card.get('name')}|{int(card.get('total_mb') or 0)}|{model}"


def _measured_footprint_mb(card: dict, model: str) -> Optional[float]:
    """What whisper was measured holding on this card, weights and working buffers, after its warm-up."""
    import json
    try:
        return float(json.loads(_footprint_file().read_text(encoding="utf-8"))[_footprint_key(card, model)])
    except Exception:
        return None


def _record_footprint(card: dict, model: str, mb: float) -> None:
    import json
    path = _footprint_file()
    try:
        table = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        table[_footprint_key(card, model)] = round(float(mb), 1)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(table, indent=1), encoding="utf-8")
    except Exception:
        log.debug("whisper footprint not recorded", exc_info=True)


def _gpu_room_for_whisper(model: str, model_dir: str) -> bool:
    """GPU only when its card still holds this whisper model after the language model takes every
    layer it can: whisper on the GPU must not cost the language model layers. What whisper needs is
    its measured footprint on this card (weights and working buffers), or its weights until measured;
    what the language model needs is its load plan (eli/core/load_plan.py), or, loaded, what it holds.
    Unknown either way: the CPU, so the language model keeps the GPU."""
    card = _whisper_card()
    if card is None or not card.get("free_mb"):         # ctranslate2 offloads to NVIDIA only
        return False
    need = _measured_footprint_mb(card, model) or _whisper_weights_mb(model, model_dir)
    if need <= 0:
        return False
    try:
        import sys
        from eli.core.hardware_profile import vram_reserve_mb
        room = float(card["free_mb"]) - float(vram_reserve_mb())
        gi = sys.modules.get("eli.cognition.gguf_inference")
        if gi is None or getattr(gi, "_llm", None) is None:
            # not loaded yet: what its plan puts on this card
            from eli.core import config, load_plan
            from eli.cognition.gguf_inference import load_request
            plan = load_plan.plan(load_request(config.get_gguf_model_path()))
            if plan is None or plan.cpu_only:
                return False
            if plan.n_gpu_layers < plan.blocks + 1 or plan.experts_in_ram:
                return False                       # the language model already wants more than the cards hold
            same = [d.index for d in plan.devices if d.name.lower() == "cuda0"] or \
                [d.index for d in plan.devices if d.description == card.get("name")]
            room -= float(plan.use_mb.get(same[0], 0.0)) if same else max(plan.use_mb.values(), default=0.0)
        return room >= need
    except Exception:
        log.debug("whisper GPU room unknown", exc_info=True)
        return False


def whisper_cache_ready(
    model_dir: Optional[str] = None,
    model: Optional[str] = None,
) -> bool:
    """True when the whisper weights are already on disk (no HF download needed)."""
    model = model or _env("ELI_WHISPER_MODEL", "small.en")
    root = Path(_resolve_model_dir(model_dir or _env("ELI_WHISPER_MODEL_DIR", "models/whisper")))
    direct = root / model
    if direct.exists():
        return True
    hub = root / _whisper_hub_dir(model)
    snaps = hub / "snapshots"
    if snaps.is_dir():
        for snap in snaps.iterdir():
            if snap.is_dir() and any(snap.iterdir()):
                return True
    return False


def resident_footprint_gib() -> float:
    """On-disk size of the cached whisper model, as a RAM-reservation proxy.

    Whisper loads once at startup and stays resident for the whole session (CPU or GPU
    depending on device). A hardware-capacity check run before it loads — the startup
    dialog's tuning pass, before the engine and its support models exist — undercounts
    what's actually committed unless this is reserved explicitly rather than relying on
    load order. 0.0 if the cache isn't there yet (nothing to reserve for).
    """
    try:
        model = _env("ELI_WHISPER_MODEL", "small.en")
        root = Path(_resolve_model_dir(_env("ELI_WHISPER_MODEL_DIR", "models/whisper")))
        from eli.core.mem_units import dir_size_gib
        direct = root / model
        if direct.exists():
            return dir_size_gib(direct)
        hub = root / _whisper_hub_dir(model)
        if hub.is_dir():
            return dir_size_gib(hub)
    except Exception:
        pass
    return 0.0


def whisper_status() -> dict:
    """Lightweight STT runtime snapshot — does not load the model."""
    try:
        model, model_dir, device, compute_type, local_only = _model_settings()
        return {
            "model": model,
            "model_dir": model_dir,
            "device_configured": device,
            "compute_type": compute_type,
            "local_only": local_only,
            "cache_ready": whisper_cache_ready(model_dir, model),
            "loaded": _MODEL is not None,
            "loading": _MODEL_LOADING,
            "cuda_failed": _CUDA_FAILED,
            "gpu_total_mb": int((_whisper_card() or {}).get("total_mb") or 0),
        }
    except Exception as exc:
        return {"error": repr(exc)}


def _offline_whisper_missing_message() -> str:
    return (
        "Whisper STT model not installed locally. ELI is offline-by-default, so "
        "voice transcription cannot download from huggingface.co. "
        "On the server host run: .venv/bin/python -m eli.runtime.voice_assets "
        "(or re-run ./INSTALL_ELI.sh with network enabled)."
    )


def _resolve_model_dir(raw: str) -> str:
    """Absolute whisper cache dir — relative paths break when cwd != install root."""
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    try:
        from eli.core.paths import project_root
        return str((Path(project_root()) / p).resolve())
    except Exception:
        return str(Path(raw).expanduser().resolve())


def _model_settings():
    # small.en, not base.en: base.en mis-transcribes real speech ("hair with stings") and accuracy
    # follows model size, so small.en is the floor. To still recover VRAM for the 7B's GPU layers,
    # keep STT on GPU in int8_float16 rather than a smaller model. ELI_WHISPER_MODEL overrides
    # (base.en/tiny.en faster, medium.en more accurate).
    model = _env("ELI_WHISPER_MODEL", "small.en")
    model_dir = _resolve_model_dir(_env("ELI_WHISPER_MODEL_DIR", "models/whisper"))
    # Prefer GPU for speed, get_model() falls back to CPU if CUDA fails. ELI_WHISPER_DEVICE=cpu
    # forces CPU. int8_float16 on GPU: about half the VRAM of float16 at equal WER.
    # VRAM-aware default: on the GPU only when the card holds the language model and this whisper
    # model both (measured). An explicit ELI_WHISPER_DEVICE wins.
    _explicit_device = (os.environ.get("ELI_WHISPER_DEVICE", "") or "").strip().lower()
    if _explicit_device:
        device = _explicit_device
    else:
        # decided once per model: whisper's own memory, once loaded, would otherwise turn the answer
        # round on the next call and reload it on the other device
        if model not in _DEVICE_DECIDED:
            _DEVICE_DECIDED[model] = "cuda" if _gpu_room_for_whisper(model, model_dir) else "cpu"
        device = _DEVICE_DECIDED[model]
    compute_type = _env(
        "ELI_WHISPER_COMPUTE_TYPE", "int8_float16" if device == "cuda" else "int8")
    local_only = _env("ELI_WHISPER_LOCAL_ONLY", "0").lower() in {"1", "true", "yes", "on"}

    # Offline by default: when Net is off, force local-only so faster-whisper loads the cached model
    # instead of validating against huggingface.co, which the network failsafe blocks (OfflineError
    # on every transcription). The model lives in download_root; no network is needed.
    if not local_only:
        try:
            from eli.core.netguard import should_block_network
            if should_block_network():
                local_only = True
        except Exception:
            local_only = True

    # If CUDA has previously OOM'd this session, stay on CPU permanently
    if _CUDA_FAILED:
        device = "cpu"
        compute_type = "int8"

    candidate = Path(model_dir) / model
    if candidate.exists():
        model = str(candidate)

    return model, model_dir, device, compute_type, local_only


def get_model():
    global _MODEL, _MODEL_KEY, _MODEL_LOADING, _CUDA_FAILED

    model, model_dir, device, compute_type, local_only = _model_settings()
    key = (model, model_dir, device, compute_type, local_only)

    # Fast path — model already loaded and key matches
    if _MODEL is not None and _MODEL_KEY == key:
        return _MODEL

    with _MODEL_LOCK:
        # Re-check after acquiring lock (another thread may have loaded it)
        if _MODEL is not None and _MODEL_KEY == key:
            return _MODEL

        # Another thread is currently downloading — wait for it
        if _MODEL_LOADING:
            pass  # fall through; will wait on _MODEL_READY below

        else:
            _MODEL_LOADING = True
            _MODEL_READY.clear()

            from faster_whisper import WhisperModel

            if local_only and not whisper_cache_ready(model_dir, model):
                raise RuntimeError(_offline_whisper_missing_message())

            log.debug(
                f"[LOCAL_STT] loading faster-whisper model={model!r} "
                f"device={device!r} compute={compute_type!r} "
                f"download_root={model_dir!r} local_only={local_only}",
            )

            try:
                try:
                    _MODEL = WhisperModel(
                        model,
                        device=device,
                        compute_type=compute_type,
                        download_root=model_dir,
                        local_files_only=local_only,
                    )
                    log.debug(f"[LOCAL_STT] faster-whisper ready on {device}")
                except Exception as _stt_dev_err:
                    # GPU load failed/OOM'd — fall back to CPU and remember, so
                    # the rest of the session stays on CPU (no repeated OOMs).
                    if str(device).lower() == "cuda":
                        _CUDA_FAILED = True
                        log.debug(
                            f"[LOCAL_STT] CUDA load failed "
                            f"({type(_stt_dev_err).__name__}: {_stt_dev_err}); "
                            f"falling back to CPU")
                        device, compute_type = "cpu", "int8"
                        key = (model, model_dir, device, compute_type, local_only)
                        _MODEL = WhisperModel(
                            model, device="cpu", compute_type="int8",
                            download_root=model_dir, local_files_only=local_only,
                        )
                        log.debug("[LOCAL_STT] faster-whisper ready on cpu (fallback)")
                    else:
                        raise
                _MODEL_KEY = key
            finally:
                _MODEL_LOADING = False
                _MODEL_READY.set()  # unblock any waiters even on failure

            return _MODEL

    # We didn't win the load race — wait for the loader to finish then return
    _MODEL_READY.wait(timeout=300)
    if _MODEL is None:
        raise RuntimeError("[LOCAL_STT] model failed to load in background thread")
    return _MODEL


def preload_model() -> bool:
    """Load whisper at startup, before the language model is planned, so the memory it holds is
    already taken when the load plan measures what each card has free. On a GPU it transcribes one
    second of silence: its working buffers are allocated on the first transcription, and the plan
    keeps only what llama.cpp itself was measured to need free. True when it is on CUDA."""
    try:
        model = _env("ELI_WHISPER_MODEL", "small.en")
        _card = _whisper_card() if _MODEL is None else None
        _free_before_load = (_card or {}).get("free_mb")
        get_model()
        if _MODEL is None:
            return False
        _, _, device, _, _ = _model_settings()
        if device != "cuda":
            return False
        try:
            import numpy as np
            from eli.perception.audio_samples import SPEECH_RATE
            segments, _info = _MODEL.transcribe(np.zeros(int(SPEECH_RATE), dtype=np.float32), beam_size=5,
                                                vad_filter=False, without_timestamps=True)
            for _seg in segments:
                pass
        except Exception:
            log.debug("[LOCAL_STT] warm-up transcription skipped", exc_info=True)
        if _free_before_load is not None:
            card = _whisper_card()
            if card and card.get("free_mb") is not None:
                _record_footprint(card, model, max(0.0, float(_free_before_load) - float(card["free_mb"])))
        return True
    except Exception:
        return False


def _audio_for_whisper(path):
    """The recording as 16 kHz mono samples, which faster-whisper takes without opening the file
    itself. It opens files with PyAV, and PyAV 18 refused the argument faster-whisper 1.2.1 passes:
    every transcription in the packaged app failed ("open() got an unexpected keyword argument
    'metadata_errors'"). The path itself when the file cannot be read here."""
    try:
        from eli.perception.audio_samples import SPEECH_RATE, read_mono
        return read_mono(path, SPEECH_RATE)[0]
    except Exception:
        log.debug("[LOCAL_STT] could not read %s as samples; faster-whisper opens it", path, exc_info=True)
        return str(path)


def _do_transcribe(model, wav_path: str, language: str | None) -> str:
    segments, _info = model.transcribe(
        _audio_for_whisper(wav_path),
        language=language,
        # beam_size=5 (faster-whisper's default) restores sentence punctuation
        # (. , ? !) that greedy beam_size=1 suppresses, and improves accuracy.
        # condition_on_previous_text stays False to avoid Whisper repetition loops.
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        without_timestamps=True,
    )
    text = " ".join((seg.text or "").strip() for seg in segments).strip()
    # Preserve punctuation; collapse whitespace only. Case is normalised by the
    # consuming wake/command layer (audio_stt), not here.
    return " ".join(text.lower().split())


def _reload_model_on_cpu() -> None:
    """Replace the global model with a CPU instance so STT survives VRAM exhaustion.
    Sets _CUDA_FAILED so get_model() never attempts CUDA again this session."""
    global _MODEL, _MODEL_KEY, _CUDA_FAILED
    _CUDA_FAILED = True  # set before loading so _model_settings() returns cpu/int8
    from faster_whisper import WhisperModel
    model_name, model_dir, _device, _compute, local_only = _model_settings()
    log.warning("[LOCAL_STT] CUDA OOM — reloading whisper on CPU (int8); CUDA disabled for this session")
    _MODEL = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        download_root=model_dir,
        local_files_only=local_only,
    )
    _MODEL_KEY = (model_name, model_dir, "cpu", "int8", local_only)


def _transcribe_path_with_fallback(wav_path: str, language: str | None) -> str:
    """Transcribe a file path, retrying once on CPU if CUDA runs out of VRAM."""
    model = get_model()
    try:
        return _do_transcribe(model, wav_path, language)
    except RuntimeError as exc:
        _exc_str = str(exc).lower()
        _is_vram_failure = (
            "out of memory" in _exc_str
            or "cublas_status_alloc_failed" in _exc_str
            or "cuda error" in _exc_str
            or "cufft" in _exc_str
        )
        if not _is_vram_failure:
            raise
        # CUDA VRAM failure: flush cache and retry once on CPU
        log.warning("[LOCAL_STT] CUDA failure during transcription — flushing cache and retrying on CPU")
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        _reload_model_on_cpu()
        return _do_transcribe(_MODEL, wav_path, language)


def transcribe_speech_recognition_audio(audio):
    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
    if not wav_bytes:
        return ""

    language = _env("ELI_WHISPER_LANGUAGE", "en") or None

    with tempfile.NamedTemporaryFile(prefix="eli_stt_", suffix=".wav", delete=True) as tmp:
        tmp.write(wav_bytes)
        tmp.flush()
        return _transcribe_path_with_fallback(tmp.name, language)


def transcribe_file(path: str, language: str | None = None) -> str:
    """Transcribe an arbitrary local audio file (wav/webm/ogg/mp3 — decoded via
    PyAV by faster-whisper). Powers the browser-voice endpoint; nothing leaves
    the box. Mirrors the CUDA→CPU VRAM fallback of the live-mic path."""
    lang = language or (_env("ELI_WHISPER_LANGUAGE", "en") or None)
    return _transcribe_path_with_fallback(str(path), lang)
