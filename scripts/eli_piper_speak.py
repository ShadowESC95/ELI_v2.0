#!/usr/bin/env python3
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VOICE_DIR = ROOT / "artifacts" / "tts" / "voices"
CACHE_DIR = ROOT / "artifacts" / "tts" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VOICE = os.environ.get(
    "ELI_PIPER_VOICE",
    str(VOICE_DIR / "en_US-ryan-high.onnx")
)

MAX_CHARS = int(os.environ.get("ELI_TTS_CHUNK_CHARS", "420"))

def clean_text(text: str) -> str:
    text = html.unescape(str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text

def chunk_text(text: str, max_chars: int = MAX_CHARS):
    text = clean_text(text)
    if not text:
        return []

    # Split on sentence-ish boundaries first.
    parts = re.split(r"(?<=[.!?…])\s+", text)
    chunks = []
    current = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue

        if len(part) > max_chars:
            words = part.split()
            buf = ""
            for w in words:
                trial = (buf + " " + w).strip()
                if len(trial) > max_chars and buf:
                    chunks.append(buf)
                    buf = w
                else:
                    buf = trial
            if buf:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(buf)
            continue

        trial = (current + " " + part).strip()
        if len(trial) > max_chars and current:
            chunks.append(current)
            current = part
        else:
            current = trial

    if current:
        chunks.append(current)

    return chunks

def find_piper():
    exe = shutil.which("piper")
    if exe:
        return exe
    # piper-tts sometimes installs as module/entrypoint in venv bin
    venv_exe = ROOT / ".venv" / "bin" / "piper"
    if venv_exe.exists():
        return str(venv_exe)
    return None

def play_wav(path: Path):
    for player in ("aplay", "paplay", "ffplay"):
        exe = shutil.which(player)
        if not exe:
            continue
        if player == "ffplay":
            subprocess.run([exe, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)], check=False)
        else:
            subprocess.run([exe, str(path)], check=False)
        return
    raise RuntimeError("No WAV player found: install alsa-utils or pulseaudio-utils.")

def speak(text: str, voice: str = DEFAULT_VOICE):
    piper = find_piper()
    if not piper:
        raise RuntimeError("piper executable not found. Try: python3 -m pip install --upgrade piper-tts")

    voice_path = Path(voice).expanduser().resolve()
    json_path = Path(str(voice_path) + ".json")

    if not voice_path.exists():
        raise FileNotFoundError(f"Missing Piper voice model: {voice_path}")
    if not json_path.exists():
        raise FileNotFoundError(f"Missing Piper voice config: {json_path}")

    chunks = chunk_text(text)
    if not chunks:
        return 0

    spoken = 0
    for i, chunk in enumerate(chunks, 1):
        wav = CACHE_DIR / f"tts_{os.getpid()}_{i}.wav"
        proc = subprocess.run(
            [piper, "--model", str(voice_path), "--output_file", str(wav)],
            input=chunk,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "piper failed")

        play_wav(wav)
        spoken += len(chunk)

        try:
            wav.unlink()
        except Exception:
            pass

    return spoken

if __name__ == "__main__":
    data = " ".join(sys.argv[1:]).strip() or sys.stdin.read()
    n = speak(data)
    print(f"[PIPER_SPEAK] spoken_chars={n}")
