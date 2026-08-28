"""Tests for eli.perception.mic_resolver — device resolution logic.

These mock the actual audio probe so they are deterministic and never touch a
real microphone (CI-safe).
"""
import importlib

import pytest

import eli.perception.mic_resolver as mr


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Fresh module-level cache and clean env for every test.
    mr._CACHED = None
    for var in ("ELI_MIC_DEVICE_INDEX", "ELI_MIC_AUTORESOLVE", "PULSE_SOURCE",
                "ELI_MIC_PULSE_SOURCE", "ELI_MIC_PROBE_TIMEOUT", "ELI_MIC_PROBE_MAX"):
        monkeypatch.delenv(var, raising=False)
    yield
    mr._CACHED = None


def test_explicit_override_skips_probing(monkeypatch):
    monkeypatch.setenv("ELI_MIC_DEVICE_INDEX", "7")
    called = {"probe": False}
    monkeypatch.setattr(mr, "_probe", lambda *a, **k: called.__setitem__("probe", True) or True)
    c = mr.resolve_capture()
    assert c.device_index == 7
    assert c.pulse_source is None
    assert called["probe"] is False  # never probed


def test_invalid_override_falls_through(monkeypatch):
    monkeypatch.setenv("ELI_MIC_DEVICE_INDEX", "not-an-int")
    monkeypatch.setattr(mr, "_candidates", lambda: [(3, None, "x", "mic-x")])
    monkeypatch.setattr(mr, "_probe", lambda *a, **k: True)
    c = mr.resolve_capture()
    assert c.device_index == 3


def test_autoresolve_disabled_uses_default(monkeypatch):
    monkeypatch.setenv("ELI_MIC_AUTORESOLVE", "0")
    monkeypatch.setattr(mr, "_probe", lambda *a, **k: pytest.fail("should not probe"))
    c = mr.resolve_capture()
    assert c.device_index is None
    assert "disabled" in c.reason


def test_picks_first_live_candidate(monkeypatch):
    cands = [(20, None, "pulse:default-source", "pulse"),
             (20, "alsa_input.built_in", "pulse:alsa_input.built_in", "pulse"),
             (20, "bluez_input.headset", "pulse:bluez_input.headset", "pulse")]
    monkeypatch.setattr(mr, "_candidates", lambda: cands)
    # default-source dead, built-in live.
    live = {"alsa_input.built_in"}
    monkeypatch.setattr(mr, "_probe", lambda idx, src, t: src in live)
    c = mr.resolve_capture()
    assert c.device_index == 20
    assert c.pulse_source == "alsa_input.built_in"
    assert "alsa_input.built_in" in c.reason


def test_default_source_is_pinned_when_live(monkeypatch):
    # Explicit default-source pin is tried before the unpinned default route.
    cands = [(20, "bluez_input.default", "pulse:bluez_input.default", "pulse"),
             (20, None, "pulse:default-source", "pulse")]
    monkeypatch.setattr(mr, "_candidates", lambda: cands)
    monkeypatch.setattr(mr, "_probe", lambda idx, src, t: src == "bluez_input.default")
    c = mr.resolve_capture()
    assert c.device_index == 20
    assert c.pulse_source == "bluez_input.default"


def test_fallback_when_nothing_live(monkeypatch):
    monkeypatch.setattr(mr, "_candidates", lambda: [(20, "a", "x", "pulse"), (20, "b", "y", "pulse")])
    monkeypatch.setattr(mr, "_probe", lambda *a, **k: False)
    c = mr.resolve_capture()
    assert c.device_index is None
    assert c.pulse_source is None
    assert "no live" in c.reason.lower()


def test_result_is_cached(monkeypatch):
    calls = {"n": 0}

    def fake_probe(idx, src, t):
        calls["n"] += 1
        return True

    monkeypatch.setattr(mr, "_candidates", lambda: [(1, None, "x", "mic-x")])
    monkeypatch.setattr(mr, "_probe", fake_probe)
    first = mr.resolve_capture()
    second = mr.resolve_capture()
    assert first is second
    assert calls["n"] == 1  # not re-probed


def test_force_rebuilds(monkeypatch):
    monkeypatch.setattr(mr, "_candidates", lambda: [(1, None, "x", "mic-x")])
    monkeypatch.setattr(mr, "_probe", lambda *a, **k: True)
    mr.resolve_capture()
    monkeypatch.setattr(mr, "_candidates", lambda: [(2, None, "y", "mic-y")])
    c = mr.resolve_capture(force=True)
    assert c.device_index == 2


def test_pulse_source_ordering(monkeypatch):
    # default first, then alsa_input (wired), then bluez, then other.
    listing = "\n".join([
        "1\tother_input\tPipeWire\ts16le\tIDLE",
        "2\talsa_input.pci\tPipeWire\ts16le\tIDLE",
        "3\tbluez_input.hs\tPipeWire\ts16le\tIDLE",
        "4\talsa_output.x.monitor\tPipeWire\ts16le\tSUSPENDED",  # excluded
        "5\tbluez_input.default\tPipeWire\ts16le\tIDLE",
    ])

    def fake_pactl(*args, **kw):
        if args[:2] == ("list", "short"):
            return listing
        if args[:1] == ("get-default-source",):
            return "bluez_input.default\n"
        return None

    monkeypatch.setattr(mr, "_pactl", fake_pactl)
    names, default = mr._pulse_sources()
    assert default == "bluez_input.default"
    assert "alsa_output.x.monitor" not in names  # monitors excluded
    assert names[0] == "bluez_input.default"      # default first
    assert names.index("alsa_input.pci") < names.index("bluez_input.hs")
    assert names.index("bluez_input.hs") < names.index("other_input")


def test_diagnostics_shape_without_probe():
    d = mr.diagnostics()
    assert set(d) >= {"autoresolve_enabled", "probe_timeout_s",
                      "resolved_device_index", "resolved_reason"}
    # No probe forced → resolved fields are None.
    assert d["resolved_device_index"] is None


def test_module_imports_clean():
    importlib.reload(mr)


def test_rank_usb_before_analog():
    assert mr._rank_capture_name("Trust GXT USB Audio")[0] < mr._rank_capture_name("HDA Analog")[0]


def test_rank_airpods_before_builtin():
    assert mr._rank_capture_name("Jay's AirPods Pro")[0] < mr._rank_capture_name(
        "MacBook Pro Microphone"
    )[0]


def test_rank_turtle_beach_chat_before_game():
    chat = mr._rank_capture_name("Headset Microphone (Turtle Beach Recon Chat)")
    game = mr._rank_capture_name("Headset (Turtle Beach Recon Game)")
    assert chat[0] < game[0]


def test_rank_headset_before_webcam():
    assert mr._rank_capture_name("USB Headset Microphone")[0] < mr._rank_capture_name(
        "Logitech Webcam C920"
    )[0]


def test_os_default_breaks_ties_not_beats_usb():
    assert mr._rank_capture_name("Built-in Microphone", is_os_default=True)[0] > \
        mr._rank_capture_name("USB Audio Device", is_os_default=False)[0]
    # Same tier: default wins tie-break (secondary key)
    a = mr._rank_capture_name("Line In", is_os_default=True)
    b = mr._rank_capture_name("Aux Port", is_os_default=False)
    assert a[0] == b[0] and a[1] < b[1]


def test_linux_hardware_usb_before_pulse(monkeypatch):
    monkeypatch.setattr(mr.sys, "platform", "linux")
    default_idx = 0
    devices = [
        (0, "default"),
        (3, "Trust GXT 232 Microphone: USB Audio (hw:1,0)"),
        (5, "pulse"),
    ]
    monkeypatch.setattr(mr, "_enumerate_input_devices", lambda: (default_idx, devices))
    monkeypatch.setattr(mr, "_pulse_device_index", lambda: 5)
    monkeypatch.setattr(
        mr,
        "_pulse_sources",
        lambda: (["alsa_input.usb-trust"], "alsa_input.usb-trust"),
    )
    cands = mr._candidates()
    labels = [c[2] for c in cands]
    assert labels[0] == "portaudio:3:Trust GXT 232 Microphone: USB Audio (hw:1,0)"
    usb_pos = next(i for i, l in enumerate(labels) if l.startswith("portaudio:3:"))
    pulse_pos = next(i for i, l in enumerate(labels) if l.startswith("pulse:"))
    assert usb_pos < pulse_pos


def test_windows_ranked_portaudio_candidates(monkeypatch):
    monkeypatch.setattr(mr.sys, "platform", "win32")
    devices = [
        (0, "Microphone Array (Realtek Audio)"),
        (1, "Microsoft Sound Mapper - Input"),
        (2, "Headset Microphone (Turtle Beach Recon Chat)"),
        (3, "Headset (Turtle Beach Recon Game)"),
    ]
    monkeypatch.setattr(mr, "_enumerate_input_devices", lambda: (0, devices))
    labels = [c[2] for c in mr._portaudio_candidates()]
    assert labels[0].startswith("portaudio:2:")
    assert labels.index("portaudio:2:Headset Microphone (Turtle Beach Recon Chat)") < \
        labels.index("portaudio:3:Headset (Turtle Beach Recon Game)")
    assert labels[-1].startswith("portaudio:1:")  # Sound Mapper last


def test_macos_ranked_portaudio_candidates(monkeypatch):
    monkeypatch.setattr(mr.sys, "platform", "darwin")
    devices = [
        (0, "MacBook Pro Microphone"),
        (1, "Jay's AirPods Pro"),
    ]
    monkeypatch.setattr(mr, "_enumerate_input_devices", lambda: (0, devices))
    labels = [c[2] for c in mr._portaudio_candidates()]
    assert labels[0].startswith("portaudio:1:")
    assert "AirPods" in labels[0]


def test_usb_hardware_wins_over_silent_pulse(monkeypatch):
    cands = [
        (3, None, "portaudio:3:Trust USB", "Trust USB"),
        (5, "alsa_input.default", "pulse:alsa_input.default", "pulse"),
    ]
    monkeypatch.setattr(mr, "_candidates", lambda: cands)

    def probe(idx, src, t):
        return idx == 3

    monkeypatch.setattr(mr, "_probe", probe)
    c = mr.resolve_capture()
    assert c.device_index == 3
    assert c.pulse_source is None
    assert c.device_name == "Trust USB"
    assert "probed live" in c.reason


def test_eli_mic_pulse_source_falls_back_to_hardware(monkeypatch):
    monkeypatch.setenv("ELI_MIC_PULSE_SOURCE", "dead.source")
    monkeypatch.setattr(mr, "_pulse_device_index", lambda: 5)
    monkeypatch.setattr(mr, "_candidates", lambda: [(3, None, "portaudio:3:USB", "USB")])
    calls = []

    def probe(idx, src, t):
        calls.append((idx, src))
        return idx == 3

    monkeypatch.setattr(mr, "_probe", probe)
    c = mr.resolve_capture()
    assert calls[0] == (5, "dead.source")
    assert c.device_index == 3
    assert c.device_name == "USB"


def test_explicit_override_records_device_name(monkeypatch):
    monkeypatch.setenv("ELI_MIC_DEVICE_INDEX", "7")
    monkeypatch.setattr(mr, "_device_name_at", lambda idx: "Mock USB Mic" if idx == 7 else None)
    c = mr.resolve_capture()
    assert c.device_index == 7
    assert c.device_name == "Mock USB Mic"
