"""The startup dialog's Target batch must become the load's requested batch.

Live report (2.4.58): dialog set to 256, ELI loaded 512. The tuner treats the
Settings-tab batch spinbox as a pinned user choice that beats its own number, and
that spinbox still held the previous session's value, so the operator's fresh,
explicit request was silently overridden. The accept path must carry the dialog's
value into the spinbox before tuning runs.
"""
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text()


def test_dialog_target_batch_is_copied_into_the_spinbox_before_tuning():
    carry = SRC.index("dlg.target_batch_spin.value()")
    tune = SRC.index("self._apply_hardware_recommendation_for_model(selected_path)", carry)
    assert "self.batch_size_input.setValue(_dlg_batch)" in SRC[carry:tune]
