#!/usr/bin/env python3
"""Voice profile + prosody — the foundation for tone/emotion detection.

This is deliberately SEPARATE from wake-word detection (`wakeword.py`). The wake
word is "did the user say the trigger phrase?"; this is "HOW did the user say it?"
— pitch, energy, rate, intonation — which is what tone/emotion (happy, angry,
excited) and question-vs-statement are built on.

What's real today (no external model, numpy only):
  • analyze_prosody()      — per-clip F0 (pitch) track, energy, voiced ratio, rate,
                             and terminal-pitch slope, all from autocorrelation.
  • question_or_statement()— rising terminal pitch ⇒ question (a genuinely useful,
                             working cue).
  • build_profile()        — a personal baseline (mean/std pitch, energy, rate) from
                             "train my voice" samples, so later tone calls are scored
                             RELATIVE to how this user normally speaks.

Scaffolded for later (clear extension points, marked TODO):
  • classify_tone()        — returns prosody-derived AROUSAL (calm↔excited/angry) and
                             the question/statement cue now; the categorical emotion
                             label stays "neutral" until a small classifier is trained
                             on LABELLED samples (e.g. "train my voice" prompting the
                             user to say a line happy / angry / excited / neutral).
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import numpy as np

from eli.utils.log import get_logger
log = get_logger(__name__)

SR = 16000

# Emotions the labelled-capture flow collects + the classifier learns. Extensible:
# add a label here and a prompt in the TRAIN_VOICE script and it's picked up.
EMOTIONS = ["neutral", "happy", "angry", "excited", "sad"]

# Feature order for the emotion classifier (prosody → vector).
_FEAT_KEYS = ["f0_mean", "f0_std", "f0_range", "energy_mean", "energy_std",
              "voiced_ratio", "speaking_rate", "terminal_pitch_slope"]

import threading as _threading
import time as _time
_last_tone: Dict[str, Any] = {}
_last_tone_ts: float = 0.0
_tone_lock = _threading.Lock()


def set_last_tone(tone: Dict[str, Any]) -> None:
    """STT publishes the most recent user-tone read here; cognition reads it (fresh
    only) to adapt its response. Decoupled side-channel — no callback signature change."""
    global _last_tone, _last_tone_ts
    with _tone_lock:
        _last_tone = dict(tone or {})
        _last_tone_ts = _time.time()


def get_last_tone(max_age_s: float = 12.0) -> Dict[str, Any]:
    """The most recent user-tone read, or {} if stale/none."""
    with _tone_lock:
        if _last_tone and (_time.time() - _last_tone_ts) <= max_age_s:
            return dict(_last_tone)
    return {}


def _dir() -> Path:
    try:
        from eli.core.paths import models_dir
        d = models_dir() / "voice_profile"
    except Exception:
        d = Path(__file__).resolve().parents[2] / "models" / "voice_profile"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _samples_dir() -> Path:
    d = _dir() / "samples"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _profile_path() -> Path:
    return _dir() / "profile.json"


def _to_float(audio_int16: np.ndarray) -> np.ndarray:
    return np.asarray(audio_int16).ravel().astype(np.float32) / 32768.0


def _resample(x: np.ndarray, sr_in: int, sr_out: int = SR) -> np.ndarray:
    if sr_in == sr_out or len(x) == 0:
        return x.astype(np.float32)
    n_out = int(round(len(x) * sr_out / sr_in))
    if n_out <= 1:
        return np.zeros(0, dtype=np.float32)
    return np.interp(np.linspace(0, len(x), n_out, endpoint=False),
                     np.arange(len(x), dtype=np.float32), x.astype(np.float32)).astype(np.float32)


# ── prosody (autocorrelation F0 + energy) ────────────────────────────────────
def _f0_autocorr(frame: np.ndarray, sr: int, fmin: float, fmax: float) -> float:
    """Fundamental frequency of one frame via autocorrelation, 0 if unvoiced."""
    frame = frame - float(np.mean(frame))
    if float(np.sqrt(np.mean(frame ** 2))) < 1e-3:
        return 0.0
    corr = np.correlate(frame, frame, mode="full")[len(frame) - 1:]
    if corr[0] <= 0:
        return 0.0
    lo = int(sr / fmax)
    hi = min(len(corr) - 1, int(sr / fmin))
    if hi <= lo:
        return 0.0
    seg = corr[lo:hi]
    peak = int(np.argmax(seg)) + lo
    # voicing test: clear periodicity (peak well above the zero-lag energy floor)
    if corr[peak] < 0.3 * corr[0]:
        return 0.0
    return float(sr / peak) if peak > 0 else 0.0


def analyze_prosody(audio_int16: np.ndarray, sr: int = SR,
                    fmin: float = 70.0, fmax: float = 350.0) -> Dict[str, Any]:
    """Per-clip prosodic features. Pure numpy, no model. Returns pitch/energy/rate
    stats + a terminal-pitch slope (semitones/sec over the voiced tail)."""
    x = _to_float(audio_int16)
    if sr != SR:
        x = _resample(x, sr, SR)
        sr = SR
    if len(x) < sr // 10:
        return {"ok": False, "reason": "clip too short"}
    win = int(0.04 * sr)
    hop = int(0.02 * sr)
    f0s, energies = [], []
    for s in range(0, len(x) - win, hop):
        fr = x[s:s + win]
        energies.append(float(np.sqrt(np.mean(fr ** 2))))
        f0s.append(_f0_autocorr(fr, sr, fmin, fmax))
    f0s = np.array(f0s, dtype=np.float32)
    energies = np.array(energies, dtype=np.float32)
    voiced = f0s[f0s > 0]
    voiced_ratio = float(len(voiced) / max(1, len(f0s)))
    # terminal pitch slope over the last 30% of voiced frames (semitones/sec)
    term_slope = 0.0
    if len(voiced) >= 6:
        tail = voiced[max(0, int(len(voiced) * 0.7)):]
        if len(tail) >= 3:
            semis = 12.0 * np.log2(np.clip(tail, 1e-3, None) / max(1e-3, float(np.median(voiced))))
            t = np.arange(len(tail), dtype=np.float32) * (hop / sr)
            try:
                term_slope = float(np.polyfit(t, semis, 1)[0])
            except Exception:
                term_slope = 0.0
    # speaking-rate proxy: voiced-onset count per second (energy peaks)
    rate = 0.0
    if len(energies) > 3:
        thr = float(np.mean(energies) + 0.5 * np.std(energies))
        onsets = int(np.sum((energies[1:] > thr) & (energies[:-1] <= thr)))
        rate = float(onsets / (len(x) / sr))
    return {
        "ok": True,
        "f0_mean": float(np.mean(voiced)) if len(voiced) else 0.0,
        "f0_std": float(np.std(voiced)) if len(voiced) else 0.0,
        "f0_range": float(np.ptp(voiced)) if len(voiced) else 0.0,
        "energy_mean": float(np.mean(energies)),
        "energy_std": float(np.std(energies)),
        "voiced_ratio": voiced_ratio,
        "speaking_rate": rate,
        "terminal_pitch_slope": term_slope,   # +ve = rising (question-like)
        "duration_s": float(len(x) / sr),
    }


def question_or_statement(prosody: Dict[str, Any]) -> Tuple[str, float]:
    """Rising terminal pitch ⇒ question. Returns (label, confidence)."""
    if not prosody.get("ok"):
        return ("unknown", 0.0)
    slope = float(prosody.get("terminal_pitch_slope", 0.0))   # semitones/sec
    # ~>2 st/s rise over the tail is a reliable interrogative cue.
    if slope > 2.0:
        return ("question", float(min(1.0, slope / 6.0)))
    if slope < -1.0:
        return ("statement", float(min(1.0, abs(slope) / 6.0)))
    return ("statement", 0.4)


# ── labelled emotion: storage + a prototype (nearest-centroid) classifier ────
def _labelled_dir() -> Path:
    d = _dir() / "labelled"
    d.mkdir(parents=True, exist_ok=True)
    return d


def add_labelled_sample(audio_int16: np.ndarray, sr: int, label: str) -> Optional[Path]:
    """Persist one emotion-labelled clip (from the TRAIN_VOICE prompts: 'say this
    happy/angry/excited')."""
    label = str(label or "neutral").strip().lower()
    try:
        import soundfile as sf
        x = _to_float(audio_int16)
        if sr != SR:
            x = _resample(x, sr, SR)
        d = _labelled_dir() / label
        d.mkdir(parents=True, exist_ok=True)
        idx = len(list(d.glob("*.wav")))
        p = d / f"{label}_{idx:03d}.wav"
        sf.write(str(p), x, SR)
        return p
    except Exception as e:
        log.debug(f"[VOICE] add_labelled_sample failed: {e}")
        return None


def labelled_counts() -> Dict[str, int]:
    out: Dict[str, int] = {}
    try:
        for d in _labelled_dir().iterdir():
            if d.is_dir():
                out[d.name] = len(list(d.glob("*.wav")))
    except Exception:
        pass
    return out


def _feature_vector(prosody: Dict[str, Any]) -> np.ndarray:
    return np.array([float(prosody.get(k, 0.0)) for k in _FEAT_KEYS], dtype=np.float32)


def _emotion_model_path() -> Path:
    return _dir() / "emotion_model.json"


def train_emotion_classifier() -> Dict[str, Any]:
    """Train a nearest-centroid emotion classifier on the labelled clips. Robust for
    the small data a quick enrollment yields (no overfitting); upgradeable to a real
    NN later without touching callers. Stores per-dim normalisation + a centroid per
    emotion."""
    try:
        import soundfile as sf
    except Exception as e:
        return {"ok": False, "error": f"soundfile unavailable: {e}"}
    vecs: List[np.ndarray] = []
    labels: List[str] = []
    for d in sorted(_labelled_dir().glob("*")):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.wav")):
            try:
                data, sr = sf.read(str(f), dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)
                pr = analyze_prosody((data * 32767).astype(np.int16), sr)
                if pr.get("ok"):
                    vecs.append(_feature_vector(pr))
                    labels.append(d.name)
            except Exception:
                pass
    uniq = sorted(set(labels))
    if len(vecs) < 4 or len(uniq) < 2:
        return {"ok": False, "error": f"need ≥2 emotions with samples (have {len(vecs)} clips, {len(uniq)} labels)"}
    X = np.stack(vecs)
    mu = X.mean(axis=0)
    sd = X.std(axis=0) + 1e-6
    Xn = (X - mu) / sd
    centroids = {lab: Xn[[i for i, l in enumerate(labels) if l == lab]].mean(axis=0).tolist()
                 for lab in uniq}
    _emotion_model_path().write_text(json.dumps({
        "norm_mean": mu.tolist(), "norm_std": sd.tolist(),
        "centroids": centroids, "labels": uniq,
        "samples": len(vecs), "counts": labelled_counts(),
    }, indent=2))
    return {"ok": True, "labels": uniq, "samples": len(vecs)}


def _load_emotion_model() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_emotion_model_path().read_text())
    except Exception:
        return None


def _classify_emotion(prosody: Dict[str, Any]) -> Tuple[str, float]:
    m = _load_emotion_model()
    if not m or not prosody.get("ok"):
        return ("neutral", 0.0)
    try:
        mu = np.array(m["norm_mean"], dtype=np.float32)
        sd = np.array(m["norm_std"], dtype=np.float32)
        v = (_feature_vector(prosody) - mu) / sd
        dists = {lab: float(np.linalg.norm(v - np.array(c, dtype=np.float32)))
                 for lab, c in m["centroids"].items()}
        order = sorted(dists.items(), key=lambda kv: kv[1])
        best, d0 = order[0]
        d1 = order[1][1] if len(order) > 1 else d0 + 1.0
        # confidence from the margin to the runner-up (closer + clearer ⇒ higher)
        conf = float(max(0.0, min(1.0, (d1 - d0) / (d1 + 1e-6))))
        return (best, conf)
    except Exception:
        return ("neutral", 0.0)


def classify_tone(audio_int16: np.ndarray, sr: int = SR) -> Dict[str, Any]:
    """Prosody-derived tone read. AROUSAL + question/statement are real today; the
    categorical EMOTION label is a scaffold (neutral until a labelled classifier is
    trained — see module docstring). Scored relative to the user's profile if built."""
    pr = analyze_prosody(audio_int16, sr)
    if not pr.get("ok"):
        return {"ok": False, "reason": pr.get("reason", "no prosody")}
    prof = get_profile()
    # arousal proxy: z-scored energy + pitch variability vs the user's baseline.
    e0 = prof.get("energy_mean", pr["energy_mean"]) or pr["energy_mean"]
    es = prof.get("energy_std_across", 0.0) or 1e-6
    f0v0 = prof.get("f0_std", pr["f0_std"]) or 1e-6
    arousal = 0.0
    try:
        arousal = 0.5 * ((pr["energy_mean"] - e0) / (es + 1e-6)) + 0.5 * ((pr["f0_std"] - f0v0) / (f0v0 + 1e-6))
    except Exception:
        pass
    arousal = float(max(-1.0, min(1.0, arousal)))
    qs, qconf = question_or_statement(pr)
    emotion, econf = _classify_emotion(pr)   # trained classifier, or ('neutral',0)
    trained = _load_emotion_model() is not None
    return {
        "ok": True,
        "arousal": arousal,                 # -1 calm … +1 excited/agitated
        "intent": qs, "intent_confidence": qconf,
        "emotion": emotion, "emotion_confidence": econf,
        "emotion_model": trained,
        "prosody": pr,
        "note": ("arousal + question/statement are prosody-derived; categorical "
                 "emotion is from the labelled classifier" if trained else
                 "arousal + question/statement work; emotion is 'neutral' until "
                 "'train my voice' collects labelled samples"),
    }


# ── enrollment + profile ─────────────────────────────────────────────────────
def add_sample(audio_int16: np.ndarray, sr: int = SR) -> Optional[Path]:
    """Persist one natural-speech sample for the voice baseline."""
    try:
        import soundfile as sf
        x = _to_float(audio_int16)
        if sr != SR:
            x = _resample(x, sr, SR)
        d = _samples_dir()
        idx = len(list(d.glob("voice_*.wav")))
        p = d / f"voice_{idx:03d}.wav"
        sf.write(str(p), x, SR)
        return p
    except Exception as e:
        log.debug(f"[VOICE] add_sample failed: {e}")
        return None


def sample_count() -> int:
    try:
        return len(list(_samples_dir().glob("voice_*.wav")))
    except Exception:
        return 0


def build_profile() -> Dict[str, Any]:
    """Aggregate prosody across the captured samples into a personal baseline so tone
    reads are RELATIVE to how this user normally speaks."""
    try:
        import soundfile as sf
    except Exception as e:
        return {"ok": False, "error": f"soundfile unavailable: {e}"}
    feats: List[Dict[str, Any]] = []
    for f in sorted(_samples_dir().glob("voice_*.wav")):
        try:
            data, sr = sf.read(str(f), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            pr = analyze_prosody((data * 32767).astype(np.int16), sr)
            if pr.get("ok"):
                feats.append(pr)
        except Exception:
            pass
    if not feats:
        return {"ok": False, "error": "no usable voice samples — run 'train my voice' first"}

    def _m(k):
        return float(np.mean([f[k] for f in feats]))

    profile = {
        "ok": True,
        "samples": len(feats),
        "f0_mean": _m("f0_mean"),
        "f0_std": _m("f0_std"),
        "energy_mean": _m("energy_mean"),
        "energy_std_across": float(np.std([f["energy_mean"] for f in feats])),
        "speaking_rate": _m("speaking_rate"),
        "voiced_ratio": _m("voiced_ratio"),
    }
    _profile_path().write_text(json.dumps(profile, indent=2))
    # Also (re)train the labelled-emotion classifier if labelled samples exist, so a
    # single "train my voice" session builds the baseline AND the emotion model.
    try:
        em = train_emotion_classifier()
        profile["emotion_model"] = em
    except Exception as e:
        profile["emotion_model"] = {"ok": False, "error": str(e)}
    return profile


def get_profile() -> Dict[str, Any]:
    try:
        return json.loads(_profile_path().read_text())
    except Exception:
        return {}


def has_profile() -> bool:
    return _profile_path().exists()
