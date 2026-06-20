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
                "ELI_MIC_PROBE_TIMEOUT", "ELI_MIC_PROBE_MAX"):
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
    monkeypatch.setattr(mr, "_candidates", lambda: [(3, None, "x")])
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
    cands = [(20, None, "pulse:default-source"),
             (20, "alsa_input.built_in", "pulse:alsa_input.built_in"),
             (20, "bluez_input.headset", "pulse:bluez_input.headset")]
    monkeypatch.setattr(mr, "_candidates", lambda: cands)
    # default-source dead, built-in live.
    live = {"alsa_input.built_in"}
    monkeypatch.setattr(mr, "_probe", lambda idx, src, t: src in live)
    c = mr.resolve_capture()
    assert c.device_index == 20
    assert c.pulse_source == "alsa_input.built_in"
    assert "alsa_input.built_in" in c.reason


def test_bluetooth_default_is_used_when_live(monkeypatch):
    # When the default route (no pin) is already live — e.g. a working BT mic —
    # it is chosen first and no PULSE_SOURCE pin is applied.
    cands = [(20, None, "pulse:default-source"),
             (20, "alsa_input.built_in", "pulse:alsa_input.built_in")]
    monkeypatch.setattr(mr, "_candidates", lambda: cands)
    monkeypatch.setattr(mr, "_probe", lambda idx, src, t: src is None)
    c = mr.resolve_capture()
    assert c.device_index == 20
    assert c.pulse_source is None


def test_fallback_when_nothing_live(monkeypatch):
    monkeypatch.setattr(mr, "_candidates", lambda: [(20, "a", "x"), (20, "b", "y")])
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

    monkeypatch.setattr(mr, "_candidates", lambda: [(1, None, "x")])
    monkeypatch.setattr(mr, "_probe", fake_probe)
    first = mr.resolve_capture()
    second = mr.resolve_capture()
    assert first is second
    assert calls["n"] == 1  # not re-probed


def test_force_rebuilds(monkeypatch):
    monkeypatch.setattr(mr, "_candidates", lambda: [(1, None, "x")])
    monkeypatch.setattr(mr, "_probe", lambda *a, **k: True)
    mr.resolve_capture()
    monkeypatch.setattr(mr, "_candidates", lambda: [(2, None, "y")])
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
