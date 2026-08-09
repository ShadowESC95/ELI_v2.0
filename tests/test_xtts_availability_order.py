"""Lock on the XTTS availability check patching BEFORE it probes.

coqui-tts reaches for ``transformers.pytorch_utils.isin_mps_friendly`` during its
own import, and transformers>=5 dropped that name. `tts_xtts` carries a shim that
restores it. But `xtts_available()` was written as:

    try:
        import TTS            # needs the shim to succeed
    except Exception:
        return False
    _patch_transformers_compat()   # never reached

so the import raised, the function returned False, and the patch that would have
fixed it sat one line below. Neural voice was silently off on a machine with
torch, coqui-tts and the 1.8GB XTTS weights all present and working — while the
user's own settings had `tts_voice: natural:sophia` selected and every reply fell
back to Piper, advising them to install what they already had.

The ordering was swapped deliberately, to stop a ModuleNotFoundError traceback on
launches without the optional extra. That was a real problem — but the shim
already handles it internally by returning quietly when transformers or torch is
missing, so quieting the console cost the entire feature.
"""
import inspect

from eli.perception import tts_xtts


def test_patch_runs_before_the_import_probe():
    """The whole bug in one assertion: order inside xtts_available()."""
    # Strip the docstring first: it discusses `import TTS` in prose, and matching
    # that instead of the statement is exactly how this assertion would lie.
    src = inspect.getsource(tts_xtts.xtts_available)
    body = src[src.index('"""', src.index('"""') + 3) + 3:] if '"""' in src else src
    patch_at = body.index("_patch_transformers_compat()")
    import_at = body.index("import TTS")
    assert patch_at < import_at, (
        "xtts_available() probes `import TTS` before applying the compat shim; "
        "the import needs the shim, so it can only ever return False"
    )


def test_shim_is_quiet_when_transformers_is_absent(monkeypatch):
    """The reason the order was swapped. It must hold with the order restored,
    or the traceback comes back."""
    import builtins

    real_import = builtins.__import__

    def no_transformers(name, *a, **k):
        if name.startswith("transformers"):
            raise ModuleNotFoundError("No module named 'transformers'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(tts_xtts, "_COMPAT_PATCHED", False)
    monkeypatch.setattr(builtins, "__import__", no_transformers)

    tts_xtts._patch_transformers_compat()   # must not raise


def test_shim_is_quiet_when_torch_is_absent(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_torch(name, *a, **k):
        if name == "torch":
            raise ModuleNotFoundError("No module named 'torch'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(tts_xtts, "_COMPAT_PATCHED", False)
    monkeypatch.setattr(builtins, "__import__", no_torch)

    tts_xtts._patch_transformers_compat()   # must not raise


def test_shim_runs_at_most_once(monkeypatch):
    """It sits on an availability probe called from list_voices()."""
    monkeypatch.setattr(tts_xtts, "_COMPAT_PATCHED", False)
    tts_xtts._patch_transformers_compat()
    assert tts_xtts._COMPAT_PATCHED is True


def test_availability_is_cheap():
    """Called from tts_router.list_voices() — it must never pull the 1.8GB model."""
    src = inspect.getsource(tts_xtts.xtts_available)
    assert "_get_model" not in src


def test_natural_available_tracks_xtts_available():
    assert tts_xtts.natural_available() == tts_xtts.xtts_available()


def test_natural_voices_listed_only_when_backend_is_usable():
    voices = tts_xtts.list_natural_voices()
    if tts_xtts.xtts_available():
        assert voices, "backend usable but no natural voices exposed"
        assert all(v.startswith(tts_xtts.NATURAL_PREFIX) for v in voices)
    else:
        assert voices == []
