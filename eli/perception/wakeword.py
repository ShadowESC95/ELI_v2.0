#!/usr/bin/env python3
"""Self-trained, fully-local wake-word detector (openWakeWord features + a custom head).

100% local, no account, no third-party service, and no unavailable pre-trained
model: ELI trains its OWN "computer"/"eli" detector using its OWN Piper TTS to
synthesise the wake phrase across many voices/speeds, then MIXES those positives
with music/noise at random SNRs — that augmentation is what makes the detector
robust *over* background music, which is the whole point. Features come from
openWakeWord's open melspectrogram→embedding extractor; the trained part is a tiny
classifier head we own.

Pipeline:
  synth positives (Piper) + augment (mix noise) + negatives → openWakeWord
  embeddings → train a small torch head → save → stream-detect in the mic loop.

The mic loop falls back to the existing transcription matcher whenever no trained
model is present, so this can never break voice. Train with the WAKE_TRAIN action
("train the wake word") or `python -m eli.perception.wakeword`.
"""
from __future__ import annotations
import os
import json
import math
import threading
from pathlib import Path
from typing import Optional, List

import numpy as np

from eli.utils.log import get_logger
log = get_logger(__name__)

SR = 16000
CLIP_S = 1.5
CLIP_N = int(SR * CLIP_S)            # 24000 samples
_DEFAULT_PHRASES = ["computer", "hey computer", "eli", "hey eli"]


def _model_dir() -> Path:
    try:
        from eli.core.paths import models_dir
        d = models_dir() / "wakeword"
    except Exception:
        d = Path(__file__).resolve().parents[2] / "models" / "wakeword"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _head_path() -> Path:
    return _model_dir() / "eli_wake_head.pt"


def _meta_path() -> Path:
    return _model_dir() / "eli_wake_meta.json"


def is_trained() -> bool:
    return _head_path().exists() and _meta_path().exists()


# ── audio helpers ────────────────────────────────────────────────────────────
def _resample(x: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    if sr_in == sr_out or len(x) == 0:
        return x.astype(np.float32)
    n_out = int(round(len(x) * sr_out / sr_in))
    if n_out <= 1:
        return np.zeros(0, dtype=np.float32)
    xp = np.arange(len(x), dtype=np.float32)
    fp = x.astype(np.float32)
    return np.interp(np.linspace(0, len(x), n_out, endpoint=False), xp, fp).astype(np.float32)


def _fix_len(x: np.ndarray, n: int = CLIP_N) -> np.ndarray:
    """Centre-pad / crop a float32 [-1,1] clip to exactly n samples."""
    x = np.asarray(x, dtype=np.float32).ravel()
    if len(x) == n:
        return x
    if len(x) > n:
        start = max(0, (len(x) - n) // 2)
        return x[start:start + n]
    out = np.zeros(n, dtype=np.float32)
    off = (n - len(x)) // 2
    out[off:off + len(x)] = x
    return out


def _to_int16(x: np.ndarray) -> np.ndarray:
    return np.clip(x * 32767.0, -32768, 32767).astype(np.int16)


def _mix_snr(sig: np.ndarray, noise: np.ndarray, snr_db: float) -> np.ndarray:
    """Mix a noise bed into a signal at a target SNR (both float32 [-1,1])."""
    if len(noise) < len(sig):
        reps = int(math.ceil(len(sig) / max(1, len(noise))))
        noise = np.tile(noise, reps)
    noise = noise[:len(sig)]
    ps = float(np.mean(sig ** 2)) + 1e-9
    pn = float(np.mean(noise ** 2)) + 1e-9
    g = math.sqrt(ps / (pn * (10 ** (snr_db / 10.0))))
    out = sig + g * noise
    peak = float(np.max(np.abs(out))) + 1e-9
    return (out / peak * 0.97).astype(np.float32) if peak > 1.0 else out.astype(np.float32)


# ── openWakeWord feature extractor (lazy singleton) ──────────────────────────
_af_lock = threading.Lock()
_af = None


def _features():
    global _af
    with _af_lock:
        if _af is None:
            from openwakeword.utils import AudioFeatures
            _af = AudioFeatures(ncpu=max(1, (os.cpu_count() or 2) // 2))
        return _af


def _embed(clips_int16: np.ndarray) -> np.ndarray:
    """clips_int16: (N, CLIP_N) int16 → (N, T, 96) float32 embeddings."""
    af = _features()
    emb = np.asarray(af.embed_clips(clips_int16, batch_size=64), dtype=np.float32)
    return emb


def _flat_dim_from(emb: np.ndarray) -> int:
    return int(emb.shape[1] * emb.shape[2])


# ── tiny custom head ─────────────────────────────────────────────────────────
def _build_head(in_dim: int):
    import torch.nn as nn
    return nn.Sequential(
        nn.Linear(in_dim, 96), nn.ReLU(),
        nn.Dropout(0.2),
        nn.Linear(96, 32), nn.ReLU(),
        nn.Linear(32, 1),
    )


# ── Piper synthesis of positives / negatives ────────────────────────────────
_voice_cache: dict = {}


def _load_voice(model_path: Path):
    key = str(model_path)
    if key not in _voice_cache:
        from piper import PiperVoice
        _voice_cache[key] = PiperVoice.load(str(model_path))
    return _voice_cache[key]


def _synth(text: str, model_path: Path, length_scale: float = 1.0) -> Optional[np.ndarray]:
    """Synthesise text → float32 16k clip, or None on failure."""
    try:
        from piper import SynthesisConfig
        v = _load_voice(model_path)
        try:
            cfg = SynthesisConfig(length_scale=length_scale)
            chunks = list(v.synthesize(text, syn_config=cfg))
        except Exception:
            chunks = list(v.synthesize(text))
        if not chunks:
            return None
        pcm = b"".join(getattr(c, "audio_int16_bytes", b"") for c in chunks)
        sr = int(getattr(chunks[0], "sample_rate", 22050) or 22050)
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        return _resample(x, sr, SR)
    except Exception as e:
        log.debug(f"[WAKE] synth failed ({text!r}): {e}")
        return None


def _voice_models(limit: int = 6) -> List[Path]:
    out: List[Path] = []
    try:
        from eli.perception.tts_router import list_voices, find_voice_model
        for name in list_voices():
            m = find_voice_model(name)
            if m and Path(m).exists():
                out.append(Path(m))
            if len(out) >= limit:
                break
    except Exception as e:
        log.debug(f"[WAKE] voice discovery failed: {e}")
    return out


# A small set of non-wake words/phrases for hard negatives (synthesised too).
_NEG_WORDS = [
    "open the door", "what time is it", "play some music", "volume up",
    "tell me a story", "computer science", "complete the task", "hello there",
    "good morning", "the weather today", "set a timer", "thank you very much",
    "elimination", "elephant", "celebrate", "company meeting", "calculator",
]


def _noise_beds() -> List[np.ndarray]:
    """Noise/music beds for augmentation. Real clips from models/wakeword/noise/
    (any .wav/.mp3 the user drops in) plus synthetic white/pink noise so training
    works out of the box even with no music files."""
    beds: List[np.ndarray] = []
    ndir = _model_dir() / "noise"
    if ndir.exists():
        try:
            import soundfile as sf
            for f in list(ndir.glob("*.wav")) + list(ndir.glob("*.flac")):
                try:
                    data, sr = sf.read(str(f), dtype="float32")
                    if data.ndim > 1:
                        data = data.mean(axis=1)
                    beds.append(_resample(data, sr, SR))
                except Exception:
                    pass
        except Exception:
            pass
    # synthetic noise (always available)
    rng = np.random.default_rng(0)
    white = rng.standard_normal(SR * 4).astype(np.float32) * 0.3
    pink = np.cumsum(rng.standard_normal(SR * 4)).astype(np.float32)
    pink = (pink - pink.mean()) / (np.std(pink) + 1e-9) * 0.3
    beds.extend([white, pink])
    return beds


def train_model(phrases: Optional[List[str]] = None, *, per_voice_speeds=(0.85, 1.0, 1.15),
                augment_per_clip: int = 4, epochs: int = 80) -> dict:
    """Synthesise + augment + embed + train the custom head. Local; CPU-fine.
    Returns {ok, positives, negatives, threshold, ...}."""
    import torch
    phrases = phrases or _DEFAULT_PHRASES
    voices = _voice_models()
    if not voices:
        return {"ok": False, "error": "no Piper voices found to synthesise the wake phrase"}
    beds = _noise_beds()

    pos: List[np.ndarray] = []
    for ph in phrases:
        for vm in voices:
            for ls in per_voice_speeds:
                clip = _synth(ph, vm, length_scale=ls)
                if clip is None or len(clip) < SR // 4:
                    continue
                base = _fix_len(clip)
                pos.append(base)
                # augmented copies mixed with noise/music at random SNR
                for _ in range(augment_per_clip):
                    bed = beds[np.random.randint(len(beds))]
                    snr = float(np.random.uniform(0.0, 15.0))
                    pos.append(_fix_len(_mix_snr(base, bed, snr)))

    neg: List[np.ndarray] = []
    for w in _NEG_WORDS:
        vm = voices[np.random.randint(len(voices))]
        clip = _synth(w, vm, length_scale=float(np.random.uniform(0.85, 1.15)))
        if clip is not None and len(clip) >= SR // 4:
            neg.append(_fix_len(clip))
    # noise/music-only negatives (so music alone never fires)
    for bed in beds:
        for _ in range(8):
            start = np.random.randint(0, max(1, len(bed) - CLIP_N))
            seg = bed[start:start + CLIP_N]
            neg.append(_fix_len(seg * float(np.random.uniform(0.5, 1.5))))

    if len(pos) < 8 or len(neg) < 8:
        return {"ok": False, "error": f"insufficient samples (pos={len(pos)}, neg={len(neg)})"}

    X = np.stack([_to_int16(c) for c in (pos + neg)])
    y = np.array([1] * len(pos) + [0] * len(neg), dtype=np.float32)
    emb = _embed(X)                                   # (N, T, 96)
    flat = emb.reshape(emb.shape[0], -1)              # (N, T*96)

    Xt = torch.tensor(flat, dtype=torch.float32)
    yt = torch.tensor(y, dtype=torch.float32).unsqueeze(1)
    head = _build_head(flat.shape[1])
    opt = torch.optim.Adam(head.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor([len(neg) / max(1, len(pos))]))
    head.train()
    for _ in range(epochs):
        opt.zero_grad()
        out = head(Xt)
        loss = lossf(out, yt)
        loss.backward()
        opt.step()
    head.eval()
    with torch.no_grad():
        scores = torch.sigmoid(head(Xt)).numpy().ravel()
    # threshold = midpoint between the positive 5th-pct and negative 95th-pct,
    # clamped — favours precision so music doesn't false-fire.
    p_lo = float(np.percentile(scores[y == 1], 5))
    n_hi = float(np.percentile(scores[y == 0], 95))
    thr = float(min(0.9, max(0.5, (p_lo + n_hi) / 2)))

    torch.save({"state_dict": head.state_dict(), "in_dim": flat.shape[1],
                "emb_shape": list(emb.shape[1:])}, _head_path())
    _meta_path().write_text(json.dumps({
        "phrases": phrases, "threshold": thr, "clip_s": CLIP_S, "sr": SR,
        "positives": len(pos), "negatives": len(neg),
        "emb_shape": list(emb.shape[1:]),
        "pos_score_p5": p_lo, "neg_score_p95": n_hi,
    }, indent=2))
    return {"ok": True, "positives": len(pos), "negatives": len(neg),
            "threshold": thr, "pos_p5": p_lo, "neg_p95": n_hi}


# ── streaming detector ───────────────────────────────────────────────────────
class WakeDetector:
    def __init__(self):
        import torch
        meta = json.loads(_meta_path().read_text())
        ckpt = torch.load(_head_path(), map_location="cpu")
        self.threshold = float(meta.get("threshold", 0.7))
        self.head = _build_head(int(ckpt["in_dim"]))
        self.head.load_state_dict(ckpt["state_dict"])
        self.head.eval()
        self._torch = torch

    def score_audio(self, audio_int16: np.ndarray) -> float:
        """Max wake score over 1.5s windows sliding across the given int16 clip."""
        x = np.asarray(audio_int16, dtype=np.int16).ravel()
        if len(x) < CLIP_N:
            x = np.pad(x, (0, CLIP_N - len(x)))
        wins = []
        step = SR // 2
        for s in range(0, max(1, len(x) - CLIP_N + 1), step):
            wins.append(x[s:s + CLIP_N])
        if not wins:
            wins = [x[:CLIP_N]]
        emb = _embed(np.stack(wins))
        flat = emb.reshape(emb.shape[0], -1)
        with self._torch.no_grad():
            sc = self._torch.sigmoid(self.head(self._torch.tensor(flat, dtype=self._torch.float32))).numpy().ravel()
        return float(np.max(sc)) if len(sc) else 0.0

    def is_wake(self, audio_int16: np.ndarray) -> bool:
        return self.score_audio(audio_int16) >= self.threshold


_detector_lock = threading.Lock()
_detector: Optional[WakeDetector] = None


def get_detector() -> Optional[WakeDetector]:
    """Return the trained detector, or None if not trained / unavailable.
    Cached; safe to call every loop. Never raises."""
    global _detector
    if not is_trained():
        return None
    with _detector_lock:
        if _detector is None:
            try:
                _detector = WakeDetector()
            except Exception as e:
                log.debug(f"[WAKE] detector load failed: {e}")
                return None
        return _detector


if __name__ == "__main__":
    print("[WAKE] training local wake-word model (Piper + augmentation)…")
    print(json.dumps(train_model(), indent=2))
