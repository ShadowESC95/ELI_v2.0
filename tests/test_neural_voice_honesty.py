"""Locks on ELI telling the truth about which voice is actually speaking.

From a live session (v2.1.64): the user dropped in a voice clip and asked whether it
would be used. Settings reported ``Active voice: natural:sophia``, the diagnostics
listed ``Active model file: cs_CZ-jirka-medium.onnx``, and the log showed
``[TTS_FINAL_PIPER_ONLY] voice=en_US-amy-medium`` — three different answers to "what
voice is this?", none of which told the user the neural voice was not running at all.

Three defects, all fixed here:

1. **The fallback was silent.** ``synthesize_wav`` tried XTTS, got ``None`` when the
   neural engine was absent, and fell through to Piper with no log line. Nothing
   anywhere said the selected voice was not being used.
2. **The diagnostics lied by omission.** ``active_model`` came from
   ``find_voice_model(active)``, which cannot resolve a ``natural:``/``clone:`` id and
   returned its fallback — the alphabetically first installed voice, hence the Czech
   one — while synthesis used ``_DEFAULT_VOICE``.
3. **The remediation was impossible.** On failure the create-voice dialog said
   ``pip install -e ".[natural]"  (from the ELI project root)``. In an AppImage there
   is no project root and no writable site-packages.
"""
import re
from pathlib import Path

import pytest

from eli.perception import tts_router

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_fallback_state():
    tts_router._note_neural_fallback(None)
    yield
    tts_router._note_neural_fallback(None)


# ── 1. the fallback is observable ───────────────────────────────────────────
def test_fallback_state_starts_clean():
    assert tts_router.neural_fallback_state()["active"] is False


def test_a_neural_fallback_is_recorded_with_the_requested_voice():
    tts_router._note_neural_fallback("natural:sophia")
    st = tts_router.neural_fallback_state()
    assert st["active"] is True
    assert st["requested"] == "natural:sophia"


def test_a_fallback_always_carries_a_reason():
    """"It fell back" without why is what made this invisible for so long."""
    tts_router._note_neural_fallback("clone:jason")
    assert tts_router.neural_fallback_state()["reason"].strip()


def test_recovery_clears_the_state():
    tts_router._note_neural_fallback("natural:sophia")
    tts_router._note_neural_fallback(None)
    assert tts_router.neural_fallback_state()["active"] is False


def test_state_is_a_copy_not_the_live_dict():
    """A caller mutating the diagnostics must not corrupt the router's state."""
    tts_router._note_neural_fallback("natural:sophia")
    tts_router.neural_fallback_state()["requested"] = "tampered"
    assert tts_router.neural_fallback_state()["requested"] == "natural:sophia"


def test_the_synth_path_reports_the_fallback():
    """The bug: synthesize_wav fell through to Piper with no signal at all."""
    src = Path(REPO / "eli" / "perception" / "tts_router.py").read_text(encoding="utf-8")
    i = src.index('if str(active).startswith("natural:"):')
    block = src[i:i + 900]
    assert "_note_neural_fallback" in block, "natural: path still falls back silently"
    j = src.index('if str(active).startswith("clone:"):')
    assert "_note_neural_fallback" in src[j:j + 900], "clone: path still falls back silently"


# ── 2. the diagnostics agree with reality ───────────────────────────────────
def test_backends_expose_what_is_really_used():
    b = tts_router.available_backends()
    for key in ("active_voice", "default_voice", "neural_available", "active_model"):
        assert key in b, key


def test_neural_voice_does_not_report_an_unrelated_model_file():
    """The Czech-voice symptom: a natural: id resolved to the alphabetically first
    installed Piper model, which is neither selected nor spoken."""
    src = Path(REPO / "eli" / "perception" / "tts_router.py").read_text(encoding="utf-8")
    i = src.index("def available_backends()")
    block = src[i:i + 1200]
    assert "_DEFAULT_VOICE if _is_neural else active" in block, (
        "available_backends still resolves the model from the neural id"
    )


def test_neural_available_is_a_real_probe():
    assert isinstance(tts_router.available_backends()["neural_available"], bool)


def test_diagnostics_panel_surfaces_the_fallback():
    gui = Path(REPO / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    i = gui.index("def _refresh_tts_diagnostics")
    block = gui[i:i + 2000]
    assert "neural_fallback_state" in block, "panel does not consult the fallback state"
    assert "NOT IN USE" in block, "panel does not tell the user the voice is not running"


# ── 3. the remediation matches the runtime ──────────────────────────────────
def _create_voice_block() -> str:
    """Comments stripped deliberately.

    The fix documents the OLD impossible advice in a comment so the next reader knows
    what changed — and that comment quotes `pip install -e ".[natural]"`. Matching it
    makes the pip string appear BEFORE the is_frozen branch and the ordering assertion
    below fails against correct code. Third time this trap has bitten in this suite;
    strip comments before asserting on source.
    """
    gui = Path(REPO / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    i = gui.index("def _create_voice_from_path")
    block = gui[i:i + 4000]
    return "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


def test_packaged_builds_are_not_told_to_pip_install():
    """An AppImage has no project root; the old advice could never be followed."""
    block = _create_voice_block()
    assert "is_frozen" in block, "the advice does not branch on the runtime"
    # the pip line must be reachable only on the non-frozen branch
    assert block.index("is_frozen") < block.index("pip install -e")


def test_packaged_message_says_the_clone_will_not_be_used():
    block = _create_voice_block()
    assert "cannot synthesise cloned voices" in block


def test_source_installs_still_get_the_pip_instruction():
    assert "pip install -e" in _create_voice_block()
    assert "natural" in _create_voice_block()


# ── 4. the AppImage actually bundles the engine ─────────────────────────────
def _release_yaml() -> dict:
    import yaml
    return yaml.safe_load((REPO / ".github" / "workflows" / "release.yml").read_text())


def test_linux_bundles_the_neural_extra():
    d = _release_yaml()
    extras = (d["jobs"]["build-linux"].get("env") or {}).get(
        "OPTIONAL_EXTRAS", d["env"]["OPTIONAL_EXTRAS"])
    assert "natural" in extras.split(), "the AppImage no longer bundles XTTS"


@pytest.mark.parametrize("job", ["build-windows", "build-macos"])
def test_other_platforms_do_not_pull_the_torch_stack(job):
    """Only the linux job installs CPU torch first and guards against CUDA wheels.
    Adding `natural` globally makes windows/macos resolve torch from PyPI and blows
    the 2 GiB per-asset limit — which fails the whole release, not just one job."""
    d = _release_yaml()
    extras = (d["jobs"][job].get("env") or {}).get(
        "OPTIONAL_EXTRAS", d["env"]["OPTIONAL_EXTRAS"])
    assert "natural" not in extras.split(), f"{job} would pull the CUDA torch stack"


def test_linux_installs_the_cpu_torch_stack_before_the_extras_loop():
    d = _release_yaml()
    step = next(s for s in d["jobs"]["build-linux"]["steps"]
                if "Install dependencies" in str(s.get("name", "")))
    run = step["run"]
    cpu_at = run.index("download.pytorch.org/whl/cpu")
    loop_at = run.index("for extra in $OPTIONAL_EXTRAS")
    assert cpu_at < loop_at, "extras resolve torch before the CPU index is used"
    assert "torchaudio" in run[:cpu_at + 200], "torchaudio must come from the CPU index too"


def test_a_cuda_regression_fails_the_linux_build():
    d = _release_yaml()
    step = next(s for s in d["jobs"]["build-linux"]["steps"]
                if "Install dependencies" in str(s.get("name", "")))
    assert "nvidia-" in step["run"], "no guard against CUDA wheels re-entering the bundle"


def test_the_two_gib_asset_guard_is_still_in_place():
    """Bundling the engine only stays safe while this guard exists."""
    raw = (REPO / ".github" / "workflows" / "release.yml").read_text()
    assert "2147483648" in raw, "the GitHub 2 GiB asset-size guard is gone"


# ── 5. the engine must be COLLECTED, not just installed ─────────────────────
def test_spec_collects_the_lazy_neural_engine():
    """v2.1.65 shipped `coqui_tts-0.27.5.dist-info` with no `TTS/` package.

    pip installed it on the runner, but `eli/perception/tts_xtts.py` imports `TTS`
    lazily inside `xtts_available()`, so PyInstaller's static analysis never saw it
    and never collected the package. The extra was bundled and unusable: `import
    TTS` failed at runtime and every cloned voice fell back to Piper. Installing a
    dependency and shipping it are two different things.
    """
    spec = (REPO / "ELI.spec").read_text(encoding="utf-8")
    body = "\n".join(l for l in spec.splitlines() if not l.lstrip().startswith("#"))
    assert '"TTS", "trainer"' in body, "the spec no longer collects the clone engine"
    # both halves: importable submodules AND the package's own config/model JSON
    assert body.count('"TTS", "trainer"') >= 2, (
        "TTS must be collected for hiddenimports AND datas — submodules alone leave "
        "the engine importable but unable to build a model"
    )


def test_tts_is_imported_lazily_which_is_why_collection_is_needed():
    """Pins the reason. If this import ever moves to module scope the spec entry
    becomes belt-and-braces rather than load-bearing — worth knowing either way."""
    src = (REPO / "eli" / "perception" / "tts_xtts.py").read_text(encoding="utf-8")
    head = src[:src.index("def ")] if "def " in src else src
    assert "\nimport TTS" not in head, (
        "TTS is now a module-level import; update the spec comment accordingly"
    )


def test_spec_shims_transformers_before_probing_tts():
    """v2.1.66 shipped no TTS/ because ELI.spec did a bare `__import__("TTS")`.

    coqui-tts reaches for `transformers.pytorch_utils.isin_mps_friendly`, removed in
    transformers>=5, so the probe raised, _optional_collect reported "optional
    dependency not installed", and PyInstaller collected nothing — while pip had
    installed coqui-tts perfectly well. The shim must run BEFORE the collect, and it
    must be the project's own (tts_xtts._patch_transformers_compat), not a copy.
    """
    spec = (REPO / "ELI.spec").read_text(encoding="utf-8")
    body = "\n".join(l for l in spec.splitlines() if not l.lstrip().startswith("#"))
    assert "_patch_transformers_compat" in body, "spec no longer shims transformers"
    assert body.index("_patch_transformers_compat") < body.index('"TTS", "trainer"'), (
        "the shim must be applied before TTS is collected"
    )


def test_the_shim_actually_makes_tts_importable():
    """Not a source assertion — run it. If this breaks, the spec fix is inert.

    Skipped under the repo conftest, which replaces `transformers` with a MagicMock
    for the fast unit suite: the shim then has nothing real to patch. The binding
    check that matters happens on the build runner (release.yml asserts TTS/ was
    collected) and can be run here directly with --noconftest.
    """
    import sys
    from unittest.mock import MagicMock
    if isinstance(sys.modules.get("transformers"), MagicMock):
        pytest.skip("conftest mocks transformers; run with --noconftest for the real probe")
    from eli.perception.tts_xtts import _patch_transformers_compat
    _patch_transformers_compat()
    import importlib
    importlib.import_module("TTS")
