"""Model-readiness: tier detection, GGUF embedded-template routing, and tier/ctx
auto-scaling of cognition budgets. Behaviour-preserving for the current model."""
from __future__ import annotations
from unittest.mock import patch
import eli.core.model_tier as MT
import eli.cognition.gguf_inference as GI
from eli.core.cognition_tunables import snapshot


def test_tier_defaults_small_and_scale_one():
    assert MT.detect_tier() == "small"
    assert MT.tier_scale() == 1.0


def test_tier_from_env_override(monkeypatch):
    monkeypatch.setenv("ELI_MODEL_TIER", "large")
    assert MT.detect_tier() == "large"
    assert MT.tier_scale() == 2.5


def test_embedded_template_family_detection():
    cases = {"<|im_start|>": "chatml", "<|start_header_id|>": "llama",
             "<start_of_turn>": "gemma", "[INST]": "mistral",
             "<|assistant|>": "phi", "novel{{x}}": None}
    for tmpl, expect in cases.items():
        GI._TEMPLATE_FAMILY_CACHE.clear()
        with patch.object(GI, "_gguf_model_metadata", return_value={"tokenizer.chat_template": tmpl}):
            assert GI._gguf_template_family() == expect


def test_format_prompt_routes_by_family():
    from pathlib import Path
    # filename fallback (no embedded template) → chatml for an openhermes-style name
    with patch.object(GI, "get_model_path", return_value=Path("openhermes-2.5-mistral-7b.Q3_K_M.gguf")), \
         patch.object(GI, "_gguf_template_family", return_value=None):
        assert GI._format_prompt("SYS", "hi").startswith("<|im_start|>")
    # embedded template OVERRIDES the filename (future-proof)
    with patch.object(GI, "get_model_path", return_value=Path("some-future-model.gguf")), \
         patch.object(GI, "_gguf_template_family", return_value="llama"):
        assert "<|start_header_id|>" in GI._format_prompt("SYS", "hi")
    with patch.object(GI, "get_model_path", return_value=Path("x.gguf")), \
         patch.object(GI, "_gguf_template_family", return_value="gemma"):
        assert "<start_of_turn>" in GI._format_prompt("SYS", "hi")


def test_gather_autoscale_small_unchanged():
    base = snapshot()
    assert base["cog.mem_semantic_shown"] == 24  # small tier → defaults unchanged


def test_gather_autoscale_large_scales_and_clamps():
    with patch("eli.core.model_tier.tier_scale", return_value=2.5):
        big = snapshot()
    assert big["cog.mem_semantic_shown"] == 60      # 24 * 2.5
    assert big["cog.rerank_top_k"] == 50            # 20 * 2.5
    assert big["cog.mem_semantic_recall"] <= 100    # clamped to max


def test_gather_autoscale_off_respects_fixed(monkeypatch):
    import eli.core.config as C
    C.set("cog.gather_auto_scale", 0)
    try:
        with patch("eli.core.model_tier.tier_scale", return_value=2.5):
            s = snapshot()
        assert s["cog.mem_semantic_shown"] == 24  # auto off → unchanged
    finally:
        C.delete("cog.gather_auto_scale")
