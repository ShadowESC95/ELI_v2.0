"""A pinned GPU-layer count belongs to the model it was chosen for.

n_gpu_layers is an ABSOLUTE layer count stored under one global key, so it meant
something different on every model. Live: 7 layers -- correct for a 15.66GB 27B
on 8GB of VRAM -- carried over to a 4GB model whose 32 layers all fit in VRAM,
stranding 25 of them on the CPU. The tuner measured 32, reported "all layers on
GPU (free VRAM sufficient)", and stood down because the user's value wins. What
was missing was any record of WHICH model the pin was for.
"""
import re
from pathlib import Path

import eli.core.runtime_settings as rs


def _tuner_source() -> str:
    """Read the tuner file from disk.

    The GUI module cannot be imported headlessly (PySide6 symbols are missing),
    so importing it to inspect its source would only ever fail in CI.
    """
    root = Path(rs.__file__).resolve().parents[2]
    for rel in ("eli/gui/eli_pro_audio_gui_v2_0.py",
                "eli/gui/main_window/_mixins/settings_model.py"):
        f = root / rel
        if f.is_file() and "_canonical_layers" in f.read_text(encoding="utf-8"):
            return f.read_text(encoding="utf-8")
    raise AssertionError("tuner source not found under %s" % root)


def test_the_provenance_key_exists_and_defaults_to_unknown():
    assert "n_gpu_layers_model" in rs.DEFAULTS
    assert rs.DEFAULTS["n_gpu_layers_model"] == ""


def test_the_key_survives_a_settings_load():
    """A key the schema drops would make the whole fix a no-op."""
    loaded = rs.load_settings() or {}
    assert "n_gpu_layers_model" in loaded


def test_all_layers_is_a_policy_and_survives_a_model_swap():
    """99 / -1 mean "offload everything" -- correct on EVERY model.

    Treating them as stale would quietly downgrade "try them all, then fall back
    to the measured fit" into "just use the fallback", which is a different and
    worse behaviour on capable hardware. The loader already reduces to fit.
    """
    for pin in (99, 128, -1):
        got = rs.pinned_gpu_layers_for_model(
            "/models/phi3.gguf",
            {"n_gpu_layers": pin, "n_gpu_layers_model": "some-other-27b.gguf"})
        assert got == pin, f"'all layers' pin {pin} was discarded on a model swap"


def test_a_specific_count_from_another_model_is_dropped():
    got = rs.pinned_gpu_layers_for_model(
        "/models/phi3.gguf",
        {"n_gpu_layers": 7, "n_gpu_layers_model": "qwen-27b.gguf"})
    assert got is None


def test_a_specific_count_for_this_model_is_honoured():
    got = rs.pinned_gpu_layers_for_model(
        "/models/phi3.gguf",
        {"n_gpu_layers": 7, "n_gpu_layers_model": "phi3.gguf"})
    assert got == 7


def test_the_headless_loader_uses_the_same_rule():
    """The desktop GUI is not the only loader: server/API must not diverge."""
    root = Path(rs.__file__).resolve().parents[2]
    src = (root / "eli/cognition/gguf_inference.py").read_text(encoding="utf-8")
    assert "pinned_gpu_layers_for_model" in src, (
        "the headless/server load path resolves n_gpu_layers straight from "
        "settings again, so a stale pin still strands models on the CPU there")


def test_the_gui_defers_to_the_shared_rule():
    """GUI and headless must decide identically or they will drift apart."""
    src = _tuner_source()
    assert "pinned_gpu_layers_for_model" in src, (
        "the tuner decides pin staleness on its own again; it must share the "
        "helper with the headless loader or the two will disagree")


def test_the_pin_is_stamped_with_the_model_when_saved():
    src = _tuner_source()
    assert re.search(r'_s\["n_gpu_layers_model"\]\s*=\s*_this_model', src), (
        "the model is never recorded, so provenance stays unknown forever and "
        "a deliberate pin can never be told from an inherited one")


def test_model_identity_is_case_insensitive():
    """NTFS and default macOS filesystems are case-insensitive.

    "Phi3.gguf" and "phi3.gguf" are the same file to those users; comparing
    exactly discarded a pin they had just set, on every load.
    """
    got = rs.pinned_gpu_layers_for_model(
        "/models/phi3.gguf",
        {"n_gpu_layers": 7, "n_gpu_layers_model": "Phi3.GGUF"})
    assert got == 7


def test_windows_paths_resolve_on_any_host():
    """A backslash path must resolve even when a POSIX host reads it."""
    got = rs.pinned_gpu_layers_for_model(
        r"C:\models\phi3.gguf",
        {"n_gpu_layers": 7, "n_gpu_layers_model": "phi3.gguf"})
    assert got == 7
    assert rs.model_identity_key(r"C:\models\Phi3.gguf") == "phi3.gguf"
    assert rs.model_identity_key("/home/u/models/Phi3.gguf") == "phi3.gguf"


def test_a_different_model_is_still_rejected_after_normalisation():
    """Normalising must not make everything match."""
    assert rs.pinned_gpu_layers_for_model(
        "/models/phi3.gguf",
        {"n_gpu_layers": 7, "n_gpu_layers_model": "qwen-27b.gguf"}) is None
