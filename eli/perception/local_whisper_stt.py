import os
import tempfile
import threading
from pathlib import Path


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


def _model_settings():
    model = _env("ELI_WHISPER_MODEL", "small.en")
    model_dir = _env("ELI_WHISPER_MODEL_DIR", "models/whisper")
    # Default to CPU so Whisper doesn't compete with the GGUF model for VRAM.
    # Set ELI_WHISPER_DEVICE=cuda to override (only useful when no GGUF is loaded).
    device = _env("ELI_WHISPER_DEVICE", "cpu")
    compute_type = _env("ELI_WHISPER_COMPUTE_TYPE", "int8")
    local_only = _env("ELI_WHISPER_LOCAL_ONLY", "0").lower() in {"1", "true", "yes", "on"}

    # Offline-by-default: when the Net toggle is off, force local-only so
    # faster-whisper loads the CACHED model instead of validating against
    # huggingface.co — which the network failsafe blocks (OfflineError on every
    # transcription). The model lives in download_root; no network is needed.
    if not local_only:
        try:
            from eli.core.config import network_allowed
            if not network_allowed():
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
    global _MODEL, _MODEL_KEY, _MODEL_LOADING

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

            log.debug(
                f"[LOCAL_STT] loading faster-whisper model={model!r} "
                f"device={device!r} compute={compute_type!r} "
                f"download_root={model_dir!r} local_only={local_only}",
            )

            try:
                _MODEL = WhisperModel(
                    model,
                    device=device,
                    compute_type=compute_type,
                    download_root=model_dir,
                    local_files_only=local_only,
                )
                _MODEL_KEY = key
                log.debug("[LOCAL_STT] faster-whisper ready")
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
    """Eagerly load whisper at startup so it claims its VRAM before the GGUF
    autotune runs. Returns True only when the model loaded onto CUDA — the
    startup dialog uses this to decide whether to cap ELI_TARGET_BATCH.
    Returns False on CPU loads (no VRAM impact on the GGUF autotune)."""
    try:
        get_model()
        if _MODEL is None:
            return False
        _, _, device, _, _ = _model_settings()
        return device == "cuda"
    except Exception:
        return False


def _do_transcribe(model, wav_path: str, language: str | None) -> str:
    segments, _info = model.transcribe(
        wav_path,
        language=language,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
        without_timestamps=True,
    )
    text = " ".join((seg.text or "").strip() for seg in segments).strip()
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


def transcribe_speech_recognition_audio(audio):
    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
    if not wav_bytes:
        return ""

    model = get_model()
    language = _env("ELI_WHISPER_LANGUAGE", "en") or None

    with tempfile.NamedTemporaryFile(prefix="eli_stt_", suffix=".wav", delete=True) as tmp:
        tmp.write(wav_bytes)
        tmp.flush()
        wav_path = tmp.name

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
                pass
            _reload_model_on_cpu()
            return _do_transcribe(_MODEL, wav_path, language)
