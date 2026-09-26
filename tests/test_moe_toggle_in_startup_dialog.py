from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_startup_dialog_offers_the_expert_offload_choice():
    src = (ROOT / "eli/gui/panels/startup.py").read_text(encoding="utf-8")
    assert "moe_offload_combo" in src
    assert "moe_expert_offload=_moe_mode" in src
    assert 'os.environ["ELI_MOE_EXPERT_OFFLOAD"]' in src


def test_the_setting_has_a_default():
    from eli.core.runtime_settings import DEFAULTS
    assert DEFAULTS["moe_expert_offload"] == "auto"
