#!/usr/bin/env python3
"""One-shot generator for artifacts/sounds/alarm.wav (run from repo root)."""
import math
import struct
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "artifacts" / "sounds" / "alarm.wav"
path.parent.mkdir(parents=True, exist_ok=True)
sr = 22050
duration = 0.35
freq = 880.0
samples = [
    int(32767 * 0.4 * math.sin(2 * math.pi * freq * i / sr))
    for i in range(int(sr * duration))
]
with wave.open(str(path), "w") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    wf.writeframes(b"".join(struct.pack("<h", s) for s in samples))
print(f"Wrote {path} ({path.stat().st_size} bytes)")
