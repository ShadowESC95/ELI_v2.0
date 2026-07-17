"""Behaviour lock: a named speaker never falls through to a different one.

_voice_names_for_sink splits an alias into bare tokens, so a sink called
"small speaker" also answers to "speaker". The old resolver walked sinks in
order and accepted `voice_name in query`, so that generic token swallowed
"kitchen speaker" — audio went to the wrong device and ELI reported success.

Same rule as the media-target lock: an explicitly named target is either honoured
or refused, never quietly swapped.
"""

import pytest

import eli.runtime.local_connectivity as lc


def _sink(alias: str, sid: str, number: int) -> dict:
    s = {"id": sid, "name": sid, "alias": alias, "display_name": alias,
         "custom_name": alias, "device_number": number}
    s["voice_names"] = lc._voice_names_for_sink(alias, sid, number)
    return s


@pytest.fixture
def sinks(monkeypatch):
    rows = [
        _sink("small speaker", "alsa_output.pci-0000_00_1f.3.analog-stereo", 1),
        _sink("amp", "bluez_output.16_0A_E4_BC_A5_0D.1", 2),
        _sink("kitchen speaker", "alsa_output.usb-kitchen.analog-stereo", 3),
    ]
    monkeypatch.setattr(lc, "list_audio_outputs", lambda: {"sinks": rows})
    return rows


def _alias(query):
    hit = lc.resolve_audio_sink(query)
    return hit["alias"] if hit else None


def test_alias_split_still_produces_the_generic_token(sinks):
    """Guards the premise: this token is why the fall-through was possible."""
    assert "speaker" in sinks[0]["voice_names"]
    assert "speaker" in sinks[2]["voice_names"]


def test_exact_name_wins_over_another_sinks_generic_token(sinks):
    """The original bug: 'kitchen speaker' resolved to 'small speaker'."""
    assert _alias("kitchen speaker") == "kitchen speaker"


@pytest.mark.parametrize("query,expected", [
    ("small speaker", "small speaker"),
    ("kitchen speaker", "kitchen speaker"),
    ("amp", "amp"),
    ("Kitchen Speaker", "kitchen speaker"),
    ("  amp  ", "amp"),
])
def test_exact_names_resolve_to_themselves(sinks, query, expected):
    assert _alias(query) == expected


def test_unique_partial_resolves(sinks):
    assert _alias("kitchen") == "kitchen speaker"
    assert _alias("small") == "small speaker"


def test_name_inside_a_phrase_resolves(sinks):
    assert _alias("play through the amp") == "amp"
    assert _alias("play through the kitchen speaker") == "kitchen speaker"
    assert _alias("play through the small speaker") == "small speaker"


def test_longest_name_wins_inside_a_phrase(sinks):
    """'kitchen speaker' must beat the bare 'speaker' token it contains."""
    assert _alias("route audio to the kitchen speaker now") == "kitchen speaker"


def test_unknown_speaker_is_refused_not_substituted(sinks):
    """Previously matched 'speaker' and played through the wrong device."""
    assert lc.resolve_audio_sink("garden speaker") is None
    assert lc.resolve_audio_sink("conservatory speaker") is None


def test_device_number_resolves(sinks):
    assert _alias("device 2") == "amp"
    assert _alias("device 3") == "kitchen speaker"


def test_out_of_range_device_number_is_refused(sinks):
    assert lc.resolve_audio_sink("device 9") is None


def test_empty_query_is_refused(sinks):
    assert lc.resolve_audio_sink("") is None
    assert lc.resolve_audio_sink(None) is None


def test_os_sink_id_resolves(sinks):
    assert _alias("bluez_output.16_0A_E4_BC_A5_0D.1") == "amp"


def test_route_audio_reports_the_sink_it_refused(sinks, monkeypatch):
    out = lc.route_audio_by_name("garden speaker")
    assert out["ok"] is False and "garden speaker" in out["error"]
