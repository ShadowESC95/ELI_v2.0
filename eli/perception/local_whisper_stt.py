import os
import tempfile
import threading
from pathlib import Path

_MODEL = None
_MODEL_KEY = None
_MODEL_LOCK = threading.Lock()


def _env(name, default):
    return (os.environ.get(name, default) or default).strip()


def _model_settings():
    model = _env("ELI_WHISPER_MODEL", "small.en")
    model_dir = _env("ELI_WHISPER_MODEL_DIR", "models/whisper")
    device = _env("ELI_WHISPER_DEVICE", "cpu")
    compute_type = _env("ELI_WHISPER_COMPUTE_TYPE", "int8")
    local_only = _env("ELI_WHISPER_LOCAL_ONLY", "0").lower() in {"1", "true", "yes", "on"}

    candidate = Path(model_dir) / model
    if candidate.exists():
        model = str(candidate)

    return model, model_dir, device, compute_type, local_only


def get_model():
    global _MODEL, _MODEL_KEY

    model, model_dir, device, compute_type, local_only = _model_settings()
    key = (model, model_dir, device, compute_type, local_only)

    with _MODEL_LOCK:
        if _MODEL is not None and _MODEL_KEY == key:
            return _MODEL

        from faster_whisper import WhisperModel

        print(
            f"[LOCAL_STT] loading faster-whisper model={model!r} "
            f"device={device!r} compute={compute_type!r} "
            f"download_root={model_dir!r} local_only={local_only}",
            flush=True,
        )

        _MODEL = WhisperModel(
            model,
            device=device,
            compute_type=compute_type,
            download_root=model_dir,
            local_files_only=local_only,
        )
        _MODEL_KEY = key

        print("[LOCAL_STT] faster-whisper ready", flush=True)
        return _MODEL


def transcribe_speech_recognition_audio(audio):
    wav_bytes = audio.get_wav_data(convert_rate=16000, convert_width=2)
    if not wav_bytes:
        return ""

    model = get_model()
    language = _env("ELI_WHISPER_LANGUAGE", "en") or None

    with tempfile.NamedTemporaryFile(prefix="eli_stt_", suffix=".wav", delete=True) as tmp:
        tmp.write(wav_bytes)
        tmp.flush()

        segments, _info = model.transcribe(
            tmp.name,
            language=language,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
            without_timestamps=True,
        )

        text = " ".join((seg.text or "").strip() for seg in segments).strip()
        return " ".join(text.lower().split())
