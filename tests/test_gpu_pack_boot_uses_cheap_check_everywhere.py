"""v2.4.38 fixed the redownload/stall loop by making `ensure_gpu_pack_for_hardware()`
try the cheap, non-subprocess `gpu_pack_looks_installed()` check before ever
falling back to the expensive, up-to-180s subprocess probe
`gpu_pack_operational()`. That fixed the PyInstaller rthook / background
activation path -- but it turned out to be one of FOUR independent call sites
that each decide "is the GPU pack ready" on a normal launch, and the other
three still called the live probe unconditionally:

  1. `packaging/pyinstaller/eli_entry.py::_first_run_gpu_offer()` -- despite
     the name, runs on EVERY frozen GUI launch (Windows/Linux), before
     `eli.gui.app.main` is even imported. Once a GPU pack had been chosen, it
     hit the live probe every single boot -- likely the dominant real-world
     cause of the original stall report.
  2. `eli/gui/panels/startup.py::_refresh_gpu_pack_controls()` -- the
     Startup Model Selection dialog every returning user sees, live-probed
     to render one status label.
  3. `eli/gui/panels/startup.py::_wiz_refresh_gpu_pack_controls()` -- the
     first-run setup wizard's own separate copy of the same status check.

All three now try `gpu_pack_looks_installed()` first, matching the pattern
`ensure_gpu_pack_for_hardware()` already established. The one live-probe call
that legitimately remains (`eli_entry.py`, right after `_run_progress_dialog`
completes a fresh install) is deliberately NOT changed -- verifying a
just-finished install is exactly the case the live probe exists for.

Regression guard, source-level: these are GUI/frozen-entry functions with no
practical way to exercise end to end in this test suite (no display, no
frozen build), so this pins the actual fix the same way the sibling GPU-pack
test files in this project already do -- by asserting on the source text
itself.
"""
from pathlib import Path

ENTRY = Path("packaging/pyinstaller/eli_entry.py")
STARTUP = Path("eli/gui/panels/startup.py")


def _code(p: Path) -> str:
    return "\n".join(
        l for l in p.read_text(encoding="utf-8").splitlines()
        if not l.strip().startswith("#")
    )


def _function_body(text: str, def_line: str) -> str:
    start = text.index(def_line)
    rest = text[start + len(def_line):]
    # Next top-level (4-space-indent) "def " marks the end of this function.
    for marker in ("\n    def ", "\ndef "):
        idx = rest.find(marker)
        if idx != -1:
            rest = rest[:idx]
    return rest


def test_first_run_gpu_offer_tries_the_cheap_check_first():
    body = _function_body(_code(ENTRY), "def _first_run_gpu_offer(")
    assert "gpu_pack_looks_installed(dest)" in body, (
        "the every-launch GPU chooser still calls the live subprocess probe "
        "unconditionally -- the exact redownload/stall bug, at a call site "
        "the original fix missed"
    )
    # The live probe may still appear (post-install verification, or as an
    # `or` fallback), but the cheap check must be tried first / be present.
    cheap_idx = body.index("gpu_pack_looks_installed(dest)")
    first_live_gate = body.find("if _gp.gpu_pack_operational(dest):")
    if first_live_gate != -1:
        assert cheap_idx < first_live_gate, (
            "gpu_pack_operational() is still gating ahead of the cheap check"
        )


def test_startup_dialog_status_tries_the_cheap_check_first():
    body = _function_body(_code(STARTUP), "def _refresh_gpu_pack_controls(")
    assert "gpu_pack_looks_installed(dest)" in body, (
        "the Startup Model Selection dialog's GPU status label still forces "
        "a live subprocess probe on every normal launch"
    )


def test_setup_wizard_status_tries_the_cheap_check_first():
    body = _function_body(_code(STARTUP), "def _wiz_refresh_gpu_pack_controls(")
    assert "gpu_pack_looks_installed(dest)" in body, (
        "the first-run setup wizard's own copy of the GPU status check still "
        "forces a live subprocess probe"
    )


def test_post_install_verification_still_uses_the_live_probe():
    """The one live-probe call that SHOULD remain: right after a fresh
    install finishes, confirming it actually installed correctly. Don't
    accidentally remove this one along with the boot-time ones."""
    code = _code(ENTRY)
    assert code.count("gpu_pack_operational(dest)") >= 2, (
        "expected the post-install verification's live probe to still be "
        "present alongside the boot-time cheap-first checks"
    )
