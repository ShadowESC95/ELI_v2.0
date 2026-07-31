"""PortAudio indices aren't stable across PyAudio instances — resolve by NAME.

The resolver probed 'pulse' at index 14 of a 19-device enumeration and handed that
integer to sr.Microphone, which saw only 10 devices → "Device index out of range" →
silent fallback to a possibly-different microphone. live_device_index() re-resolves
against the enumeration the caller will actually open with.
"""
from __future__ import annotations
import pytest
from eli.perception.mic_resolver import CaptureChoice, live_device_index


class _FakeInfo(dict):
    pass


class _FakePyAudio:
    """Enumeration stub: names in order, all input-capable unless prefixed '!'."""
    def __init__(self, names): self._names = names
    def get_device_count(self): return len(self._names)
    def get_device_info_by_index(self, i):
        n = self._names[i]
        return _FakeInfo(name=n.lstrip("!"), maxInputChannels=0 if n.startswith("!") else 2)
    def terminate(self): pass


@pytest.fixture
def fake_pa(monkeypatch):
    def _install(names):
        import types, sys
        mod = types.ModuleType("pyaudio")
        mod.PyAudio = lambda: _FakePyAudio(names)
        monkeypatch.setitem(sys.modules, "pyaudio", mod)
    return _install


def test_stale_index_is_re_resolved_by_name(fake_pa):
    # probed at 14 in a 19-device list; this process sees 10 with 'pulse' at 7
    fake_pa(["a", "b", "c", "d", "e", "f", "g", "pulse", "h", "i"])
    c = CaptureChoice(device_index=14, pulse_source=None, reason="probed", device_name="pulse")
    assert live_device_index(c) == 7   # not 14, not a crash


def test_missing_device_yields_none_not_a_wrong_device(fake_pa):
    # the named device is gone AND the stored index is out of range → OS default
    fake_pa(["mic0", "mic1"])
    c = CaptureChoice(device_index=14, pulse_source=None, reason="probed", device_name="pulse")
    assert live_device_index(c) is None


def test_stored_index_kept_only_if_still_an_input(fake_pa):
    # name gone, index in range but that slot is OUTPUT-only → must not select it
    fake_pa(["mic0", "!speaker", "mic2"])
    c = CaptureChoice(device_index=1, pulse_source=None, reason="probed", device_name="gone")
    assert live_device_index(c) is None
    # same setup but the slot IS an input → keep it
    c2 = CaptureChoice(device_index=2, pulse_source=None, reason="probed", device_name="gone")
    assert live_device_index(c2) == 2


def test_no_name_passes_index_through_unchanged(fake_pa):
    # explicit ELI_MIC_DEVICE_INDEX override / legacy cache: behaviour unchanged
    fake_pa(["mic0", "mic1", "mic2", "mic3"])
    c = CaptureChoice(device_index=3, pulse_source=None, reason="override")
    assert live_device_index(c) == 3


def test_exact_name_match_not_substring(fake_pa):
    fake_pa(["pulse_monitor", "pulse", "pulseaudio"])
    c = CaptureChoice(device_index=99, pulse_source=None, reason="probed", device_name="pulse")
    assert live_device_index(c) == 1
