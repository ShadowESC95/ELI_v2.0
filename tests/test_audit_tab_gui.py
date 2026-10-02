"""New feature (2026-10-02): desktop GUI tab for the orchestrator audit chain
(eli.runtime.orchestrator_audit_ledger). Previously the only audit view was
the separate web dashboard — none of the Qt desktop app's screenshots from a
live session had anywhere to see it.

A "Stages" column (which of the 12 pipeline stages ran) was in the first
draft and removed: it was built from a deterministic action+mode rule, not
from anything confirming each stage actually completed, and would have
silently shown a plan as a fact. See test_orchestrator_audit_ledger.py's
test_no_fabricated_stage_mask_column for the schema-level lock.

Qt-coupled GUI module, not directly executable in CI — verified at the
source-text level (established pattern, see
test_moe_gpu_layer_print_matches_what_loads.py).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py"


def _audit_tab_block() -> str:
    src = GUI.read_text(encoding="utf-8")
    i = src.index("def refresh_audit_tab(self):")
    j = src.index("def create_settings_tab(self):", i)
    return src[i:j]


def test_audit_tab_is_registered_in_init_ui():
    src = GUI.read_text(encoding="utf-8")
    assert "self.create_audit_tab()" in src


def test_audit_tab_reads_the_orchestrator_ledger_not_evidence_ledger():
    block = _audit_tab_block()
    assert "orchestrator_audit_ledger" in block
    assert "verify_chain" in block
    assert "recent_turns" in block


def test_audit_tab_shows_an_integrity_banner_and_a_table():
    block = _audit_tab_block()
    assert "audit_integrity_label" in block
    assert "audit_table" in block
    assert "QTableWidget" in block


def test_audit_table_columns_cover_only_real_fields():
    block = _audit_tab_block()
    i = block.index("setHorizontalHeaderLabels")
    j = block.index("])", i)
    header = block[i:j]
    for col in ("Time", "Request", "Action", "Agents", "Confidence", "Outcome"):
        assert col in header
    assert "content" not in header.lower()
    assert "response" not in header.lower()
    # No per-stage "did it really run" claim — see module docstring.
    assert "Stages" not in header
    assert "Stage" not in header


def test_audit_tab_has_refresh_and_verify_actions():
    block = _audit_tab_block()
    assert "refresh_audit_tab" in block
    assert "Verify Chain" in block


def test_audit_tab_auto_refreshes_on_a_timer():
    block = _audit_tab_block()
    assert "QTimer(self)" in block
    assert ".start()" in block


def test_no_stage_mask_decoder_left_in_the_gui():
    src = GUI.read_text(encoding="utf-8")
    assert "_decode_stage_mask" not in src
    assert "stage_mask" not in src
