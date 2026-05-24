"""
ELI Microphone Diagnostic
Run this to measure real speech vs ambient energy so you can set the
right energy threshold. Stay silent for the first 3s, then speak normally.

Usage:
    python3 eli/tools/mic_diag.py
"""
import speech_recognition as sr
import audioop
import time


def run():
    r = sr.Recognizer()
    r.energy_threshold = 50
    r.dynamic_energy_threshold = False

    mics = sr.Microphone.list_microphone_names()
    print("=== ELI MIC DIAGNOSTIC ===")
    print("Mic devices:")
    for i, m in enumerate(mics):
        print(f"  [{i}] {m}")

    print()
    print("Testing device 13 (pulse/default)...")
    m = sr.Microphone(device_index=13)
    with m as src:
        print(f"  rate={src.SAMPLE_RATE}  width={src.SAMPLE_WIDTH}")
        print()
        print("--- STAY SILENT for 3s ---")
        ambient = []
        t0 = time.time()
        while time.time() - t0 < 3.0:
            buf = src.stream.read(src.CHUNK)
            ambient.append(audioop.rms(buf, src.SAMPLE_WIDTH))
        print(f"  Ambient: min={min(ambient)}  avg={sum(ambient)//len(ambient)}  max={max(ambient)}")
        print()
        print("--- SPEAK NORMALLY for 5s (say anything) ---")
        time.sleep(0.3)
        speech = []
        t0 = time.time()
        while time.time() - t0 < 5.0:
            buf = src.stream.read(src.CHUNK)
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
    import sys
    try:
        run()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
