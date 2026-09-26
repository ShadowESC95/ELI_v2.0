from types import SimpleNamespace

from eli.core import moe_offload


def _prof(moe=True, blocks=40):
    return SimpleNamespace(is_moe=moe, block_count=blocks)


def test_plans_only_for_moe_that_does_not_fit(monkeypatch):
    monkeypatch.delenv("ELI_MOE_EXPERT_OFFLOAD", raising=False)
    monkeypatch.setattr(moe_offload, "mode", lambda: "auto")
    monkeypatch.setattr(moe_offload, "profile", lambda p: _prof())
    big = moe_offload.plan("m", 20.0, free_vram_mb=7000, available_ram_gb=32)
    assert big and big["layers"] == 40 and big["experts_gb"] > 15
    assert moe_offload.plan("m", 4.0, free_vram_mb=7000, available_ram_gb=32) is None


def test_dense_model_and_off_switch_are_left_alone(monkeypatch):
    monkeypatch.setattr(moe_offload, "mode", lambda: "auto")
    monkeypatch.setattr(moe_offload, "profile", lambda p: _prof(moe=False))
    assert moe_offload.plan("m", 20.0, free_vram_mb=7000, available_ram_gb=32) is None
    monkeypatch.setattr(moe_offload, "profile", lambda p: _prof())
    monkeypatch.setattr(moe_offload, "mode", lambda: "off")
    assert moe_offload.plan("m", 20.0, free_vram_mb=7000, available_ram_gb=32) is None


def test_needs_ram_for_the_experts_and_a_gpu(monkeypatch):
    monkeypatch.setattr(moe_offload, "mode", lambda: "auto")
    monkeypatch.setattr(moe_offload, "profile", lambda p: _prof())
    assert moe_offload.plan("m", 20.0, free_vram_mb=7000, available_ram_gb=8) is None
    assert moe_offload.plan("m", 20.0, free_vram_mb=0, available_ram_gb=32) is None


def test_on_forces_even_when_it_would_fit(monkeypatch):
    monkeypatch.setattr(moe_offload, "mode", lambda: "on")
    monkeypatch.setattr(moe_offload, "profile", lambda p: _prof())
    assert moe_offload.plan("m", 4.0, free_vram_mb=24000, available_ram_gb=32)


def test_env_switch_beats_settings(monkeypatch):
    monkeypatch.setenv("ELI_MOE_EXPERT_OFFLOAD", "off")
    assert moe_offload.mode() == "off"
    monkeypatch.setenv("ELI_MOE_EXPERT_OFFLOAD", "nonsense")
    assert moe_offload.mode() == "auto"
