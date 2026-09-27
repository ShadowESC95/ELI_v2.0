from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_gui_model_loader_also_computes_a_moe_plan():
    # eli/gui/eli_pro_audio_gui_v2_0.py builds Llama(...) itself — it does not go through
    # gguf_inference.load_model() — so the MoE offload hook has to be wired in here separately,
    # or the startup dialog's model load silently ignores the moe_expert_offload setting.
    src = (ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert "import moe_offload as _moe_offload_gui" in src and "_moe_offload_gui.plan_for_load" in src
    assert "_build_llama" in src and "expert_offload_params" in src
    assert '"moe_expert_offload": bool(_moe_gui)' in src
