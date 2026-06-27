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
_GPU_TOTAL_MB: Optional[int] = None  # cached total VRAM of GPU 0
# Below this total VRAM, STT stays on CPU so the main GGUF model keeps the GPU.
_WHISPER_GPU_MIN_MB = int(os.environ.get("ELI_WHISPER_GPU_MIN_MB", "12000"))


def _env(name, default):
    return (os.environ.get(name, default) or default).strip()


def _gpu_total_mb() -> int:
    """Total VRAM of GPU 0 in MB (0 if no GPU / can't tell). Cheap, cached."""
    global _GPU_TOTAL_MB
    if _GPU_TOTAL_MB is not None:
        return _GPU_TOTAL_MB
    mb = 0
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
        if out.returncode == 0 and out.stdout.strip():
            mb = int(out.stdout.splitlines()[0].strip())
    except Exception:
        mb = 0
    _GPU_TOTAL_MB = mb
    return mb


def _model_settings():
    # small.en (not base.en): base.en mis-transcribes too much on real speech
    # ("hair with stings") — accuracy is driven by model size, so small.en stays
    # the floor. To still claw back VRAM for the 7B's GPU layers we keep STT on
    # GPU but in int8_float16 (below) rather than dropping to a smaller model.
    # Override with ELI_WHISPER_MODEL=base.en/tiny.en (faster, less accurate) or
    # medium.en (more accurate, larger footprint).
    model = _env("ELI_WHISPER_MODEL", "small.en")
    model_dir = _env("ELI_WHISPER_MODEL_DIR", "models/whisper")
    # Prefer GPU for speed (CPU int8 is too slow); get_model() falls back to CPU
    # automatically if the CUDA load fails / OOMs. Force CPU with
    # ELI_WHISPER_DEVICE=cpu. On GPU we use int8_float16 (int8 weights, float16
    # compute): ~half the weight VRAM of plain float16 with WER essentially equal
    # to float16, so the main-model VRAM budget (preloaded before the GGUF) is
    # larger without costing transcription accuracy.
    # VRAM-aware default: GPU whisper claims ~2GB that the larger, more important main
    # GGUF model needs. On a small card it preloads first and starves the main model
    # onto few-GPU-layers / CPU (the observed slowdown: free_vram=4083MB → gpu_layers=11).
    # So default to GPU only when the card is big enough to hold whisper AND a typical
    # main model; otherwise CPU (small.en int8 on CPU is ~1-2s for a short command).
    # An explicit ELI_WHISPER_DEVICE always wins.
    _explicit_device = (os.environ.get("ELI_WHISPER_DEVICE", "") or "").strip().lower()
    if _explicit_device:
        device = _explicit_device
    else:
        device = "cuda" if _gpu_total_mb() >= _WHISPER_GPU_MIN_MB else "cpu"
    compute_type = _env(
        "ELI_WHISPER_COMPUTE_TYPE", "int8_float16" if device == "cuda" else "int8")
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
            pass
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
