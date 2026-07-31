"""
ELI microphone resolver — pick a capture device that actually delivers audio,
for any user on any machine, with a Bluetooth or wired mic, with no manual
configuration.

Why this exists
---------------
"Just use the OS default input" is not enough in the wild:

* On Linux/PipeWire+Pulse the default *source* is frequently a stale or phantom
  device — e.g. a Bluetooth headset that disconnected but is still registered as
  default. Opening it blocks forever and never delivers frames.
* The raw ALSA ``default`` PCM is often wired through dead JACK/virtual PCMs and
  blocks on read.
* Probing audio devices in-process is unsafe: opening some ALSA plugin PCMs (or
  abandoning a blocked PortAudio stream) can segfault the interpreter.

Strategy
--------
Resolve a *working* device by actively probing candidates, each probe isolated
in a short-lived **subprocess** (so a hang or segfault cannot take ELI down) and
bounded by a timeout (so a dead device cannot stall startup). An active read is
both the correct liveness signal (a suspended PipeWire source resumes within
~1s when actually read) and far faster than recording-to-file.

* Linux + Pulse/PipeWire: candidates are Pulse *sources* (the default route
  first, then every non-monitor source — wired before Bluetooth before the
  rest). The winner is pinned for ELI's process only via ``PULSE_SOURCE`` — the
  system default is never modified.
* Everywhere else: candidates are PortAudio input devices (default first).

Result is cached for the process. Honors ``ELI_MIC_DEVICE_INDEX`` (explicit
override, no probing) and ``ELI_MIC_AUTORESOLVE=0`` (disable, use OS default).
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:  # logging is best-effort; never let it break resolution
    from eli.utils.log import get_logger  # type: ignore

    log = get_logger(__name__)
except Exception:  # pragma: no cover - logging optional
    import logging

    log = logging.getLogger(__name__)


@dataclass
class CaptureChoice:
    """A resolved capture target.

    device_index: PortAudio index to hand to ``sr.Microphone`` (None = default).
    pulse_source: if set, ELI should ``os.environ['PULSE_SOURCE'] = …`` before
        opening the mic so libpulse connects to this specific source.
    reason: human-readable explanation, surfaced in diagnostics/logs.
    device_name: PortAudio name captured in the SAME enumeration as device_index.
        Indices are not stable between ``PyAudio()`` instances, so callers should
        re-resolve via :func:`live_device_index` rather than trust the raw index.
    """

    device_index: Optional[int]
    pulse_source: Optional[str]
    reason: str
    device_name: Optional[str] = None


_CACHED: Optional[CaptureChoice] = None


@contextlib.contextmanager
def _quiet_alsa():
    """Silence the ALSA/JACK stderr storm PortAudio emits while enumerating devices.

    Constructing ``pyaudio.PyAudio()`` on Linux probes every ALSA plugin and the JACK
    server, printing dozens of ``Unknown PCM``/``jack server is not running`` lines each
    time — pure noise that makes a healthy launch look broken. Redirect fd 2 for the
    duration; always restored, and a no-op if the dup fails.
    """
    saved = None
    devnull = None
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved = os.dup(2)
        os.dup2(devnull, 2)
    except Exception:
        saved = None
    try:
        yield
    finally:
        try:
            if saved is not None:
                os.dup2(saved, 2)
                os.close(saved)
            if devnull is not None:
                os.close(devnull)
        except Exception:
            log.debug("mic_resolver: stderr restore failed", exc_info=True)


def _device_name_at(index: Optional[int]) -> Optional[str]:
    """PortAudio device name at ``index`` in a fresh enumeration (None if unavailable)."""
    if index is None:
        return None
    try:
        import pyaudio
    except Exception:
        return None
    p = None
    try:
        with _quiet_alsa():
            p = pyaudio.PyAudio()
            if 0 <= index < p.get_device_count():
                return str(p.get_device_info_by_index(index).get("name") or "") or None
    except Exception:
        return None
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:
                log.debug("mic_resolver: PyAudio terminate failed", exc_info=True)
    return None


def live_device_index(choice: "CaptureChoice") -> Optional[int]:
    """Re-resolve ``choice`` to an index valid in THIS process, by device name.

    PortAudio indices are NOT stable across ``PyAudio()`` instances on Linux: the list
    is rebuilt each time and shifts with whichever ALSA/JACK plugins happen to
    initialise. The resolver probed with one instance (e.g. 'pulse' at 14 of 19) and the
    caller opens with another (which may only see 10) — handing the raw integer over
    then blows up with "Device index out of range" and silently falls back to the OS
    default, which can be a completely different microphone. Look the NAME up freshly
    against the enumeration the caller will actually use; fall back to the stored index
    only when the name can't be found (or was never captured).
    """
    name = getattr(choice, "device_name", None)
    idx = choice.device_index
    if not name:
        return idx
    try:
        import pyaudio
    except Exception:
        return idx
    p = None
    try:
        with _quiet_alsa():
            p = pyaudio.PyAudio()
            count = p.get_device_count()
            # Exact name match on an input-capable device wins.
            for i in range(count):
                try:
                    info = p.get_device_info_by_index(i)
                except Exception:
                    continue
                if info.get("maxInputChannels", 0) > 0 and str(info.get("name") or "") == name:
                    return i
            # Name is gone (device unplugged / different audio stack): only trust the
            # stored index if it is still in range AND still an input device.
            if idx is not None and 0 <= idx < count:
                try:
                    if p.get_device_info_by_index(idx).get("maxInputChannels", 0) > 0:
                        return idx
                except Exception:
                    log.debug("mic_resolver: device info read failed", exc_info=True)
            return None  # let the caller use the OS default rather than a wrong device
    except Exception:
        return idx
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:
                log.debug("mic_resolver: PyAudio terminate failed", exc_info=True)


def _autoresolve_enabled() -> bool:
    return os.environ.get("ELI_MIC_AUTORESOLVE", "1").lower() not in {"0", "false", "no", "off"}


def _probe_timeout() -> float:
    try:
        return max(1.5, float(os.environ.get("ELI_MIC_PROBE_TIMEOUT", "3.0")))
    except (TypeError, ValueError):
        return 3.0


def _max_candidates() -> int:
    try:
        return max(1, int(os.environ.get("ELI_MIC_PROBE_MAX", "8")))
    except (TypeError, ValueError):
        return 8


# ── PortAudio enumeration (in-process: enumeration is safe; opening is not) ──
def _pulse_device_index() -> Optional[int]:
    """Index of the PortAudio 'pulse' device (PipeWire/PulseAudio route)."""
    try:
        import pyaudio
    except Exception:
        return None
    p = None
    try:
        with _quiet_alsa():
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                try:
                    info = p.get_device_info_by_index(i)
                except Exception:
                    continue
                if info.get("maxInputChannels", 0) > 0 and info.get("name") == "pulse":
                    return i
    except Exception:
        return None
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:
                log.debug("mic_resolver: PyAudio.terminate() failed", exc_info=True)
    return None


def _input_device_indices() -> List[Tuple[int, str]]:
    """All PortAudio input devices as (index, name), default first.

    The NAME is captured here, inside the very enumeration that produced the index —
    the only place the two are guaranteed to correspond (indices shift between
    PyAudio instances; see live_device_index).
    """
    try:
        import pyaudio
    except Exception:
        return []
    p = None
    out: List[Tuple[int, str]] = []
    try:
        with _quiet_alsa():
            p = pyaudio.PyAudio()
        default_idx: Optional[int] = None
        try:
            default_idx = int(p.get_default_input_device_info().get("index"))
        except Exception:
            default_idx = None
        _seen: set = set()
        if default_idx is not None:
            try:
                _dn = str(p.get_device_info_by_index(default_idx).get("name") or "")
            except Exception:
                _dn = ""
            out.append((default_idx, _dn)); _seen.add(default_idx)
        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
            except Exception:
                continue
            if info.get("maxInputChannels", 0) > 0 and i not in _seen:
                out.append((i, str(info.get("name") or ""))); _seen.add(i)
    except Exception:
        return out
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:
                log.debug("mic_resolver: PyAudio.terminate() failed", exc_info=True)
    return out


# ── PulseAudio/PipeWire source enumeration (subprocess, isolated) ──
def _pactl(*args: str, timeout: float = 2.0) -> Optional[str]:
    try:
        r = subprocess.run(
            ["pactl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode == 0:
            return r.stdout
    except Exception:
        return None
    return None


def _pulse_sources() -> Tuple[List[str], Optional[str]]:
    """Return (ordered non-monitor source names, default source name).

    Order: default first, then wired ``alsa_input`` sources, then Bluetooth,
    then anything else. Monitors are excluded — they are loopbacks of outputs,
    not microphones.
    """
    listing = _pactl("list", "short", "sources")
    if listing is None:
        return [], None
    default = (_pactl("get-default-source") or "").strip() or None

    names: List[str] = []
    for line in listing.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[1].strip()
        if not name or name.endswith(".monitor"):
            continue
        names.append(name)

    def rank(n: str) -> int:
        if default and n == default:
            return 0
        if n.startswith("alsa_input"):
            return 1
        if n.startswith("bluez_input"):
            return 2
        return 3

    names.sort(key=rank)
    return names, default


# ── Probe a single candidate in an isolated subprocess ──
def _probe(device_index: Optional[int], pulse_source: Optional[str], timeout: float) -> bool:
    """True if the candidate delivers audio frames within ``timeout`` seconds.

    Runs ``python -m eli.perception.mic_resolver --probe`` so a hang or segfault
    is confined to the child; the parent enforces the timeout.
    """
    cmd = [
        sys.executable,
        "-m",
        "eli.perception.mic_resolver",
        "--probe",
        "-" if device_index is None else str(device_index),
        pulse_source or "-",
    ]
    env = dict(os.environ)
    env.pop("ELI_MIC_DEVICE_INDEX", None)  # don't recurse into override logic
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return r.returncode == 0 and r.stdout.strip().startswith("LIVE")
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def _candidates() -> List[Tuple[Optional[int], Optional[str], str, Optional[str]]]:
    """Ordered (device_index, pulse_source, label, device_name) candidates to probe.

    device_name is captured alongside the index in the same enumeration, so the pair
    stays consistent even though the index alone would not be.
    """
    cands: List[Tuple[Optional[int], Optional[str], str, Optional[str]]] = []
    if sys.platform.startswith("linux"):
        pulse_idx = _pulse_device_index()
        if pulse_idx is not None:
            # Default route first (no pin), then each real source explicitly.
            cands.append((pulse_idx, None, "pulse:default-source", "pulse"))
            sources, default = _pulse_sources()
            for s in sources:
                if default and s == default:
                    continue  # already covered by the default-route probe
                cands.append((pulse_idx, s, f"pulse:{s}", "pulse"))
            return cands
    # Generic (macOS/Windows, or Linux without a Pulse route): PortAudio devices.
    for idx, nm in _input_device_indices():
        cands.append((idx, None, f"portaudio:{idx}", nm))
    if not cands:
        cands.append((None, None, "portaudio:default", None))
    return cands


def resolve_capture(force: bool = False) -> CaptureChoice:
    """Resolve a working capture device, probing candidates as needed (cached)."""
    global _CACHED
    if _CACHED is not None and not force:
        return _CACHED

    # 1) Explicit override — honoured verbatim, no probing.
    explicit = os.environ.get("ELI_MIC_DEVICE_INDEX")
    if explicit is not None:
        try:
            _CACHED = CaptureChoice(int(explicit), None, "ELI_MIC_DEVICE_INDEX override")
            return _CACHED
        except (TypeError, ValueError):
            log.debug("mic_resolver: invalid ELI_MIC_DEVICE_INDEX=%r, ignoring", explicit, exc_info=True)

    # 2) Auto-resolve disabled — use OS default.
    if not _autoresolve_enabled():
        _CACHED = CaptureChoice(None, None, "autoresolve disabled (ELI_MIC_AUTORESOLVE=0)")
        return _CACHED

    # 3) Probe candidates until one delivers audio.
    timeout = _probe_timeout()
    limit = _max_candidates()
    cands = _candidates()[:limit]
    for device_index, pulse_source, label, device_name in cands:
        if _probe(device_index, pulse_source, timeout):
            # The NAME came from the same enumeration as the index (see _candidates);
            # re-looking it up here would race the very instability we guard against.
            _CACHED = CaptureChoice(device_index, pulse_source, f"probed live: {label}",
                                    device_name=device_name)
            log.debug(f"[MIC] resolved capture → {_CACHED.reason} "
                      f"(index={device_index}, name={_CACHED.device_name!r})")
            return _CACHED

    # 4) Nothing probed live — fall back to OS default; the STT calibration
    #    watchdog prevents a hang, and diagnostics will flag the dead mic.
    _CACHED = CaptureChoice(None, None, "no live capture device found; using OS default")
    log.warning(
        "[MIC] No input device delivered audio during probing. Falling back to the OS "
        "default. Connect a mic, check the system default input source, or set "
        "ELI_MIC_DEVICE_INDEX to a known-good device."
    )
    return _CACHED


def diagnostics() -> dict:
    """Snapshot for stt_diagnostics() (does not force a probe)."""
    c = _CACHED
    return {
        "autoresolve_enabled": _autoresolve_enabled(),
        "probe_timeout_s": _probe_timeout(),
        "resolved_device_index": None if c is None else c.device_index,
        "resolved_pulse_source": None if c is None else c.pulse_source,
        "resolved_reason": None if c is None else c.reason,
    }


# ── Subprocess probe entrypoint ──
def _run_probe(device_arg: str, source_arg: str) -> int:
    """Open the target, read ~1s of audio, print LIVE on success. Exit 0 = live."""
    if source_arg and source_arg != "-":
        os.environ["PULSE_SOURCE"] = source_arg
    try:
        import audioop

        import pyaudio
    except Exception as e:  # pragma: no cover
        print(f"DEAD import: {e}")
        return 2

    p = pyaudio.PyAudio()
    try:
        if device_arg and device_arg != "-":
            idx: Optional[int] = int(device_arg)
        else:
            idx = None
            if not sys.platform.startswith("linux"):
                try:
                    idx = int(p.get_default_input_device_info().get("index"))
                except Exception:
                    idx = None
        st = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=idx,
            frames_per_buffer=1024,
        )
        frames = b""
        for _ in range(16):  # ~1s at 16 kHz / 1024
            frames += st.read(1024, exception_on_overflow=False)
        st.close()
        print(f"LIVE rms={audioop.rms(frames, 2)} bytes={len(frames)}")
        return 0
    except Exception as e:
        print(f"DEAD open/read: {e}")
        return 3
    finally:
        try:
            p.terminate()
        except Exception:
            log.debug("mic_resolver: PyAudio.terminate() failed", exc_info=True)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--probe":
        sys.exit(_run_probe(sys.argv[2], sys.argv[3]))
    # Manual run: print the resolved choice.
    print(resolve_capture(force=True))
