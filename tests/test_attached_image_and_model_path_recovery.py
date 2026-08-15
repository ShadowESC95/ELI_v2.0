"""Locks on the 2.1.83 live session (13:33–13:37) — an attached image, twice broken.

**1. One stray ']' broke every attached image.** The GUI writes the marker

    [Attached image: shot.png — path: /home/u/Pictures/shot.png]

and the router's "everything from the first slash to end of string" extractor swept
up the closing bracket. That single character did two things: the path did not exist
(`Path not found: …13-36-09.png]`) and `endswith(".png")` was False, so an attached
IMAGE routed to SUMMARIZE_FILE at 0.92 instead of ANALYZE_IMAGE.

**2. Analysing an image unloaded the chat model and could not put it back.** The GUI
loads the GGUF itself and hands it over by assigning `gguf_inference._llm` and
publishing a live runtime override — it never writes the settings keys
`get_model_path()` reads. So the path was in the process the whole time and the
lookup could not see it:

    [GGUF][ADAPTIVE] load attempt 1..8 … error=No GGUF model path configured
    [VISION] text-model restore attempt 1 failed: No GGUF model path configured
    [ANALYZE_IMAGE] fusion skipped: No GGUF model path configured

24 failed load attempts, 27.3 seconds, and — because `force_reload=True` nulled
`_llm` BEFORE checking the path — a working model destroyed by a reload that could
never have succeeded. The visible reply degraded to a raw caption plus an OCR dump,
because fusion is the step that needs the text model.
"""
import os

import pytest

from eli.execution.router_enhanced import route, _attachment_marker_path
import eli.cognition.gguf_inference as gi


@pytest.fixture
def image(tmp_path):
    p = tmp_path / "Screenshot from 2026-08-15 13-36-09.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


# ── 1. the attachment marker ────────────────────────────────────────────────
def test_marker_path_excludes_the_closing_bracket(image):
    msg = f"analyse [Attached image: {image.name} — path: {image}]"
    assert _attachment_marker_path(msg) == str(image)


def test_attached_image_routes_to_analyze_image_with_a_clean_path(image):
    r = route(f"analyse [Attached image: {image.name} — path: {image}]")
    assert r["action"] == "ANALYZE_IMAGE", "an attached image must not become a file summary"
    assert r["args"]["path"] == str(image)
    assert not r["args"]["path"].endswith("]")


def test_marker_survives_a_path_containing_spaces_and_dashes(tmp_path):
    p = tmp_path / "a folder with spaces" / "shot - final (2).png"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    r = route(f"analyse [Attached image: {p.name} — path: {p}]")
    assert r["action"] == "ANALYZE_IMAGE"
    assert r["args"]["path"] == str(p)


def test_no_marker_is_not_invented():
    assert _attachment_marker_path("analyse the latest screenshot") is None
    assert _attachment_marker_path("") is None


def test_a_real_path_ending_in_a_bracket_char_is_left_alone(tmp_path):
    """The delimiter trim must only fire when it helps — 'paper (2).pdf' is a file."""
    p = tmp_path / "paper (2).pdf"
    p.write_text("x", encoding="utf-8")
    r = route(f"analyse {p}")
    assert r["args"]["path"] == str(p)


def test_trailing_chatter_is_still_dropped(tmp_path):
    p = tmp_path / "plain.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    r = route(f"summarise {p} and tell me about it")
    assert r["action"] == "ANALYZE_IMAGE"
    assert r["args"]["path"] == str(p)


# ── 2. the model path the process is already running ────────────────────────
def _resolve():
    """Call get_model_path() as the app does.

    It short-circuits to None when PYTEST_CURRENT_TEST is set, and pytest re-sets
    that variable at the start of every phase — so deleting it in a fixture (setup
    phase) does not hold into the test body. It has to be dropped here, in the
    call phase, or this whole section silently tests the short-circuit.
    """
    os.environ.pop("PYTEST_CURRENT_TEST", None)
    return gi.get_model_path()


@pytest.fixture
def no_configured_model(monkeypatch, tmp_path):
    """A GUI-loaded install: nothing in settings, env or config points at a model."""
    for var in ("ELI_GGUF_MODEL_PATH", "ELI_GGUF_MODEL", "ELI_MODELS_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(gi, "_load_runtime_settings", lambda *a, **k: {})

    import eli.core.config as cfg
    import eli.core.paths as paths_mod
    monkeypatch.setattr(cfg, "get", lambda *a, **k: None)

    class _NoModelPaths:
        model = None
        artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setattr(paths_mod, "PATHS", _NoModelPaths())
    monkeypatch.setattr(paths_mod, "get_paths", lambda: _NoModelPaths())

    gi.set_live_runtime_override(None)
    yield
    gi.set_live_runtime_override(None)


def test_without_the_override_there_is_genuinely_nothing(no_configured_model):
    """Establishes the baseline, so the next test cannot pass by accident."""
    assert _resolve() is None


def test_the_running_model_is_found_through_the_live_override(no_configured_model, image):
    gi.set_live_runtime_override({"provider": "gguf", "loaded": True,
                                  "model_path": str(image)})
    assert _resolve() == image


def test_the_snapshot_on_disk_also_recovers_the_path(no_configured_model, image, tmp_path):
    """The in-memory override does not survive a module reload; the snapshot does."""
    import json
    from eli.core.paths import get_paths
    artifacts = get_paths().artifacts_dir
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "runtime_snapshot.json").write_text(
        json.dumps({"model_path": str(image), "loaded": True}), encoding="utf-8")
    assert _resolve() == image


def test_explicit_configuration_still_wins_over_whatever_is_loaded(
        no_configured_model, image, tmp_path):
    """The fallback is last on purpose — it must never shadow a configured model."""
    explicit = tmp_path / "explicitly-configured.gguf"
    explicit.write_bytes(b"GGUF")
    os.environ["ELI_GGUF_MODEL_PATH"] = str(explicit)
    try:
        gi.set_live_runtime_override({"model_path": str(image)})
        assert _resolve() == explicit
    finally:
        os.environ.pop("ELI_GGUF_MODEL_PATH", None)


def test_a_failed_reload_does_not_destroy_a_loaded_model(no_configured_model, monkeypatch):
    """force_reload used to null _llm and THEN discover it had no path to reload
    from, so a reload that could never succeed still took the model down."""
    sentinel = object()
    monkeypatch.setattr(gi, "_llm", sentinel, raising=False)
    with pytest.raises(FileNotFoundError):
        gi.load_model(force_reload=True)
    assert gi._llm is sentinel, "a working model was destroyed by a reload that could not run"
