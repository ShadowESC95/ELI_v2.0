"""Voice library: index-driven catalog, licence policy, md5-verified download."""
from __future__ import annotations

import json

import pytest

from eli.runtime import voice_assets as va


_INDEX = {
    "en_US-amy-medium": {
        "name": "amy", "quality": "medium",
        "language": {"code": "en_US", "family": "en", "name_english": "English",
                     "country_english": "United States"},
        "files": {"en/en_US/amy/medium/en_US-amy-medium.onnx": {"size_bytes": 63201294,
                                                                "md5_digest": "aaa"},
                  "en/en_US/amy/medium/en_US-amy-medium.onnx.json": {"size_bytes": 4882,
                                                                     "md5_digest": "bbb"},
                  "en/en_US/amy/medium/MODEL_CARD": {"size_bytes": 281, "md5_digest": "ccc"}},
    },
    "en_US-ryan-high": {
        "name": "ryan", "quality": "high",
        "language": {"code": "en_US", "family": "en", "name_english": "English",
                     "country_english": "United States"},
        "files": {"en/en_US/ryan/high/en_US-ryan-high.onnx": {"size_bytes": 120786792,
                                                              "md5_digest": "ddd"}},
    },
    "de_DE-thorsten-medium": {
        "name": "thorsten", "quality": "medium",
        "language": {"code": "de_DE", "family": "de", "name_english": "German",
                     "country_english": "Germany"},
        "files": {"de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx": {"size_bytes": 63201294,
                                                                          "md5_digest": "eee"}},
    },
}


@pytest.fixture()
def indexed(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "_piper_dest", lambda: tmp_path)
    (tmp_path / va._INDEX_FILENAME).write_text(json.dumps(_INDEX), encoding="utf-8")
    return tmp_path


# ── licence policy ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("voice_id,expected", [
    ("en_US-ryan-high", True),
    ("en_US-ryan-low", True),          # licence is dataset-level, not per quality
    ("en_US-lessac-medium", True),
    ("en_GB-cori-medium", True),
    ("en_US-amy-medium", False),
    ("en_GB-northern_english_male-medium", False),
])
def test_restricted_is_dataset_level(voice_id, expected):
    assert va.is_restricted(voice_id) is expected


def test_voice_name_of_handles_multipart_names():
    assert va.voice_name_of("en_GB-northern_english_male-medium") == "northern_english_male"
    assert va.voice_name_of("en_US-amy-medium") == "amy"
    assert va.voice_name_of("nonsense") == ""


def test_release_policy_excludes_every_quality_of_a_restricted_voice():
    import sys
    sys.path.insert(0, "scripts")
    from asset_release_policy import is_excluded_voice_filename as excluded
    assert excluded("en_US-ryan-low.onnx")
    assert excluded("en_US-lessac-low.onnx.json")
    assert excluded("en_GB-cori-medium.onnx")
    assert not excluded("en_US-amy-medium.onnx")


# ── catalog ─────────────────────────────────────────────────────────────────
def test_list_available_voices_reads_index_without_network(indexed, monkeypatch):
    monkeypatch.setattr(va, "fetch_voice_index",
                        lambda *a, **k: pytest.fail("must not hit network"))
    rows = va.list_available_voices()
    assert {r["id"] for r in rows} == set(_INDEX)
    amy = next(r for r in rows if r["id"] == "en_US-amy-medium")
    assert amy["country"] == "United States"
    assert amy["size_mb"] == pytest.approx(60.3, abs=0.2)  # .onnx only, not MODEL_CARD
    assert amy["restricted"] is False


def test_language_filter_accepts_family_and_locale(indexed):
    assert {r["id"] for r in va.list_available_voices(language="en")} == {
        "en_US-amy-medium", "en_US-ryan-high"}
    assert {r["id"] for r in va.list_available_voices(language="de_DE")} == {
        "de_DE-thorsten-medium"}


def test_installed_only_filters_on_presence(indexed, monkeypatch):
    monkeypatch.setattr(va, "_voice_present_strict",
                        lambda vid: vid == "en_US-amy-medium")
    rows = va.list_available_voices(installed_only=True)
    assert [r["id"] for r in rows] == ["en_US-amy-medium"]


def test_catalog_falls_back_to_curated_list_when_index_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "_piper_dest", lambda: tmp_path)  # no index cached
    rows = va.list_available_voices(language="en_US")
    assert rows and all(r["id"].startswith("en_US") for r in rows)
    assert any(r["id"] == "en_US-amy-medium" for r in rows)


# ── download ────────────────────────────────────────────────────────────────
def test_download_uses_indexed_paths_and_verifies_md5(indexed, monkeypatch):
    """A corrupted body must be rejected, not written as a valid voice."""
    import hashlib
    payload = b"not-the-real-model"
    good = hashlib.md5(payload).hexdigest()
    idx = json.loads((indexed / va._INDEX_FILENAME).read_text())
    files = idx["en_US-amy-medium"]["files"]
    for path in files:
        files[path]["md5_digest"] = good if path.endswith(".onnx") else "wrong-digest"
    (indexed / va._INDEX_FILENAME).write_text(json.dumps(idx), encoding="utf-8")

    requested = []

    class _Resp:
        def __init__(self, data): self._data, self._done = data, False
        def read(self, _n=-1):
            if self._done:
                return b""
            self._done = True
            return self._data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class _NG:
        @staticmethod
        def allow_network(_reason):
            class _C:
                def __enter__(self): return None
                def __exit__(self, *a): return False
            return _C()

        @staticmethod
        def guarded_urlopen(req, timeout=0):
            requested.append(req.full_url)
            return _Resp(payload)

    # Patch the attribute on the package, not sys.modules: `from eli.core import
    # netguard` reads the already-bound attribute once the real module has been
    # imported by an earlier test, so a sys.modules patch alone is ignored in a
    # full-suite run (it passed standalone and failed in-suite).
    import eli.core
    monkeypatch.setattr(eli.core, "netguard", _NG, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "eli.core.netguard", _NG)
    monkeypatch.setattr(va, "_voice_present_strict", lambda vid: False)
    res = va.download_voice("en_US-amy-medium")

    assert res["ok"] is False and "checksum" in res["error"]
    # exact indexed path was used (not a derived guess), and the bad file is gone
    assert any(u.endswith("en/en_US/amy/medium/en_US-amy-medium.onnx") for u in requested)
    assert not list(indexed.glob("*.part"))
    assert not (indexed / "en_US-amy-medium.onnx.json").exists()


def test_download_short_circuits_when_already_present(indexed, monkeypatch):
    monkeypatch.setattr(va, "_voice_present_strict", lambda vid: True)
    monkeypatch.setattr(va, "_mirror_piper_to_packaged_layout",
                        lambda v: pytest.fail("no mirror unless asked"))
    res = va.download_voice("en_US-amy-medium")
    assert res == {"ok": True, "asset": "piper", "already_present": True,
                   "voice": "en_US-amy-medium"}


def test_voice_index_is_offline_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(va, "_piper_dest", lambda: tmp_path)
    assert va.voice_index() == {}  # never raises, never fetches


# ── character base resolution ───────────────────────────────────────────────
def test_character_base_prefers_ideal_when_installed():
    from eli.perception import voice_fx
    spec = voice_fx.get_preset("char:hal")
    installed = {"en_US-lessac-medium", "en_GB-alan-medium", "en_US-amy-medium"}
    assert voice_fx.resolve_base_voice(spec, installed) == "en_US-lessac-medium"


def test_character_base_walks_the_chain_and_never_picks_foreign_or_wrong_gender():
    """The bug: a missing base fell through to the first .onnx alphabetically —
    a Czech voice. Male characters must also never land on a female voice."""
    from eli.perception import voice_fx
    shipped = {"cs_CZ-jirka-medium", "de_DE-thorsten-medium", "en_US-amy-medium",
               "en_GB-alan-medium"}  # no lessac/joe/ryan, no northern_english_male
    for char in ("hal", "tars", "rick", "jarvis"):
        got = voice_fx.resolve_base_voice(voice_fx.get_preset(char), shipped)
        assert got == "en_GB-alan-medium", f"{char} -> {got}"
    assert voice_fx.resolve_base_voice(
        voice_fx.get_preset("glados"), shipped) == "en_US-amy-medium"


def test_character_base_falls_back_to_default_when_nothing_matches():
    from eli.perception import voice_fx
    got = voice_fx.resolve_base_voice(voice_fx.get_preset("hal"),
                                      {"cs_CZ-jirka-medium"}, default="en_US-amy-medium")
    assert got == "en_US-amy-medium"


def test_resolve_accepts_legacy_string_fallback():
    from eli.perception import voice_fx
    spec = {"base": "missing-voice", "fallback": "en_GB-alan-medium"}
    assert voice_fx.resolve_base_voice(spec, {"en_GB-alan-medium"}) == "en_GB-alan-medium"


# ── shipped-asset integrity ─────────────────────────────────────────────────
def test_no_voice_ships_without_its_config():
    """A .onnx with no .onnx.json is unusable — Piper can't load it, so it is
    ~60 MB of dead weight invisible to list_voices(). Guards a real regression:
    the packaged pack once had 17 models but only 5 configs."""
    from pathlib import Path
    from eli.runtime.voice_assets import incomplete_voices
    dirs = [d for d in (Path("models/tts/piper"), Path("tts_piper/piper")) if d.is_dir()]
    if not dirs or not any(d.glob("*.onnx") for d in dirs):
        pytest.skip("no voice assets on this box (CI clone)")
    broken = incomplete_voices([d for d in dirs])
    assert not broken, (
        "voices present without their .onnx.json config: "
        + ", ".join(sorted({b['voice'] for b in broken}))
        + " — run eli.runtime.voice_assets.repair_voice_configs()")
