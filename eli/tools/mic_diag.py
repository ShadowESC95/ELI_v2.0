"""
ELI Microphone Diagnostic
Probes every input device for one that actually delivers audio, then measures
real speech vs ambient energy so you can set the right energy threshold.
Stay silent for the first 3s, then speak normally.

Usage:
    python3 eli/tools/mic_diag.py            # auto-resolve a working device
    python3 eli/tools/mic_diag.py 20         # force a specific device index
"""
import audioop
import sys
import time

import speech_recognition as sr


def _probe_device(idx, seconds=0.6):
    """Open a device briefly and return its mean RMS, or None if it can't read.

    A dead device (raw ALSA "default" wired through dead JACK PCMs, or a stale
    Bluetooth default source) either errors on open or blocks; we cap the read
    count so probing can't hang.
    """
    try:
        m = sr.Microphone(device_index=idx)
        with m as src:
            reads = max(1, int(seconds * src.SAMPLE_RATE / src.CHUNK))
            rms_vals = []
            for _ in range(reads):
                buf = src.stream.read(src.CHUNK, exception_on_overflow=False)
                rms_vals.append(audioop.rms(buf, src.SAMPLE_WIDTH))
            return sum(rms_vals) // len(rms_vals)
    except Exception:
        return None


def _resolve_device():
    """Prefer the 'pulse' device by name (PulseAudio/PipeWire); fall back to the
    first input device that opens. Returns (index, name) or (None, None)."""
    names = sr.Microphone.list_microphone_names()
    pulse = next((i for i, n in enumerate(names) if n == "pulse"), None)
    if pulse is not None:
        return pulse, names[pulse]
    # Otherwise probe in order for the first device that yields a reading.
    for i, n in enumerate(names):
        if _probe_device(i, seconds=0.3) is not None:
            return i, n
    return None, None


def run():
    r = sr.Recognizer()
    r.energy_threshold = 50
    r.dynamic_energy_threshold = False

    names = sr.Microphone.list_microphone_names()
    print("=== ELI MIC DIAGNOSTIC ===")
    print("Mic devices:")
    for i, m in enumerate(names):
        print(f"  [{i}] {m}")
    print()

    if len(sys.argv) > 1:
        idx = int(sys.argv[1])
        label = names[idx] if 0 <= idx < len(names) else "?"
        print(f"Using device {idx} ({label}) from command line.")
    else:
        idx, label = _resolve_device()
        if idx is None:
            print("No working input device found. Check your system default source "
                  "(e.g. a stale Bluetooth mic) and that a mic is connected.")
            return
        print(f"Auto-selected device {idx} ({label}).")
        print(f"  → To pin ELI to it: export ELI_MIC_DEVICE_INDEX={idx}")
    print()

    m = sr.Microphone(device_index=idx)
    with m as src:
        print(f"  rate={src.SAMPLE_RATE}  width={src.SAMPLE_WIDTH}")
        print()
        print("--- STAY SILENT for 3s ---")
        ambient = []
        t0 = time.time()
        while time.time() - t0 < 3.0:
            buf = src.stream.read(src.CHUNK, exception_on_overflow=False)
            ambient.append(audioop.rms(buf, src.SAMPLE_WIDTH))
        print(f"  Ambient: min={min(ambient)}  avg={sum(ambient)//len(ambient)}  max={max(ambient)}")
        print()
        print("--- SPEAK NORMALLY for 5s (say anything) ---")
        time.sleep(0.3)
        speech = []
        t0 = time.time()
        while time.time() - t0 < 5.0:
            buf = src.stream.read(src.CHUNK, exception_on_overflow=False)
            e = audioop.rms(buf, src.SAMPLE_WIDTH)
            speech.append(e)
            elapsed = time.time() - t0
            bar = "#" * (e // 20)
            print(f"\r  t={elapsed:.1f}s  RMS={e:5d}  {bar[:60]}", end="", flush=True)
        print()
        print(f"  Speech: min={min(speech)}  avg={sum(speech)//len(speech)}  max={max(speech)}")
        print()

        ambient_max = max(ambient)
        speech_max = max(speech)
        speech_avg = sum(speech) // len(speech)
        recommended = int(ambient_max * 1.2)

        print(f"  Ambient max:   {ambient_max}")
        print(f"  Speech max:    {speech_max}")
        print(f"  Speech avg:    {speech_avg}")
        print(f"  Recommended threshold: {recommended}  (ambient_max * 1.2)")
        print(f"  Speech clears threshold? {speech_max > recommended}")
        print()
        if speech_avg < ambient_max:
            print("  WARNING: speech avg is BELOW ambient max.")
            print("  Background noise is as loud as your voice.")
            print("  Fix: reduce background noise or move mic closer.")
        elif speech_avg > recommended:
            print(f"  OK: normal speech reliably clears threshold {recommended}.")
            print(f"  Set ELI_STT_ENERGY_THRESHOLD={recommended} or rely on calibration.")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
