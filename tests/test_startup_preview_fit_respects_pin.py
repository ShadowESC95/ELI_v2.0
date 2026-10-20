"""The start-up window's load plan is the loader's own plan, and its GPU choices reach the loader.

Live session report (2026-10-02): the Hardware Tuning preview line showed "gpu=all layers" right next
to the real load's "gpu=10": the preview ran a fit calculation of its own and never saw the user's
pinned layers. The window now asks the planner the loader uses (gguf_inference.load_request ->
load_plan.plan), so the pin, the context, the batch and the GPUs it shows are the ones that load.

Qt-coupled GUI module: the planner call is checked at the source level; the GPU choice logic runs
against stand-in widgets.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
STARTUP = ROOT / "eli/gui/panels/startup.py"


def test_the_preview_is_the_loaders_own_plan():
    src = STARTUP.read_text(encoding="utf-8")
    i = src.index("class _PlanPreviewThread")
    block = src[i:src.index("\nclass ", i + 10)]
    assert "load_request(self._model_path, **self._overrides)" in block
    assert "load_plan.plan(" in block
    assert "unified_fit_config" not in src, "a second fit calculation came back into the window"


class _Box:
    def __init__(self, on=True, enabled=True, share=50):
        self._on, self._enabled, self._share = on, enabled, share

    def isChecked(self):
        return self._on

    def isEnabled(self):
        return self._enabled

    def value(self):
        return self._share


def _choice(rows, mode="auto"):
    try:
        from eli.gui.panels.startup import StartupModelSelectionDialog
    except Exception as exc:  # Qt bindings are stubbed in the headless test env
        pytest.skip(f"GUI panels unavailable here: {exc}")
    fake = SimpleNamespace(_gpu_rows=[(i, _Box(on, en), _Box(share=sh)) for i, (on, en, sh) in enumerate(rows)],
                           gpu_split_combo=SimpleNamespace(currentData=lambda: mode))
    return StartupModelSelectionDialog._gpu_choice(fake)


def test_every_card_ticked_means_every_card():
    assert _choice([(True, True, 50), (True, True, 50)]) == {"gpu_devices": "", "tensor_split": "",
                                                              "cpu_only": False}


def test_one_card_ticked_is_single_gpu():
    assert _choice([(False, True, 50), (True, True, 50)])["gpu_devices"] == "1"


def test_no_card_ticked_runs_on_the_processor():
    assert _choice([(False, True, 50), (False, True, 50)])["cpu_only"] is True


def test_manual_shares_reach_the_loader_as_fractions():
    out = _choice([(True, True, 30), (True, True, 90)], mode="manual")
    assert out["tensor_split"] == "0.250,0.750"


def test_a_card_without_a_gpu_runtime_is_not_counted():
    assert _choice([(True, True, 50), (True, False, 50)]) == {"gpu_devices": "", "tensor_split": "",
                                                              "cpu_only": False}
