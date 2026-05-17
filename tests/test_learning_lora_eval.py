import json
from pathlib import Path

from eli.learning.lora_eval import (
    build_eval_job,
    inspect_eval_suite,
    score_response,
)


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def make_fake_base(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"fake")


def make_fake_adapter(path: Path, base: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "adapter_model.safetensors").write_bytes(b"fake")
    (path / "adapter_config.json").write_text(
        json.dumps({
            "base_model_name_or_path": str(base),
            "peft_type": "LORA",
            "task_type": "CAUSAL_LM",
            "r": 4,
            "lora_alpha": 4,
            "target_modules": ["qkv_proj"],
        }),
        encoding="utf-8",
    )


def test_score_response_passes_expected_and_blocks_forbidden():
    good = score_response(
        "I use runtime continuity, local memory, and a self-model.",
        ["runtime continuity", "self-model"],
        ["trained by OpenAI", "Searching for:"],
    )
    assert good["passed"] is True
    assert "runtime continuity" in good["expected_hits"]

    bad = score_response(
        "Searching for: I am an AI language model developed to assist.",
        ["self-model"],
        ["Searching for:", "AI language model developed to assist"],
    )
    assert bad["passed"] is False
    assert bad["forbidden_hits"]


def test_inspect_eval_suite_accepts_seed_rows(tmp_path):
    eval_path = tmp_path / "eval.jsonl"
    write_jsonl(eval_path, [
        {
            "id": "identity",
            "instruction": "Who are you?",
            "expected_any": ["self-model"],
            "forbidden": ["Searching for:"],
        }
    ])

    report = inspect_eval_suite(eval_path)
    assert report["ok"] is True
    assert report["rows"] == 1


def test_build_eval_job_is_dry_run_by_default(tmp_path):
    base = tmp_path / "base"
    adapter = tmp_path / "adapter"
    eval_path = tmp_path / "eval.jsonl"

    make_fake_base(base)
    make_fake_adapter(adapter, base)
    write_jsonl(eval_path, [
        {
            "id": "identity",
            "instruction": "Who are you?",
            "expected_any": ["self-model"],
            "forbidden": ["Searching for:"],
        }
    ])

    job = build_eval_job(
        target="eli_phi",
        adapter_dir=adapter,
        eval_path=eval_path,
    )

    assert job["ok"] is True
    assert job["execute"] is False
    assert job["will_evaluate"] is False
    assert job["adapter"]["ok"] is True
    assert job["eval"]["ok"] is True


def test_build_eval_job_rejects_missing_adapter(tmp_path):
    eval_path = tmp_path / "eval.jsonl"
    write_jsonl(eval_path, [
        {
            "id": "identity",
            "instruction": "Who are you?",
            "expected_any": ["self-model"],
            "forbidden": ["Searching for:"],
        }
    ])

    job = build_eval_job(
        target="eli_phi",
        adapter_dir=tmp_path / "missing-adapter",
        eval_path=eval_path,
    )

    assert job["ok"] is False
    assert any("adapter" in p for p in job["problems"])


def test_unsupported_target_rejected(tmp_path):
    job = build_eval_job(
        target="generic_gguf",
        adapter_dir=tmp_path / "x",
        eval_path=tmp_path / "missing.jsonl",
    )
    assert job["ok"] is False
    assert any("unsupported target" in p for p in job["problems"])

def test_dynamic_cache_seen_tokens_compat_patch_is_safe():
    from eli.learning import lora_eval

    lora_eval._patch_dynamic_cache_seen_tokens()

    try:
        from transformers.cache_utils import DynamicCache
    except Exception:
        return

    assert hasattr(DynamicCache, "seen_tokens")

def test_dynamic_cache_compat_v2_has_legacy_phi3_methods():
    from eli.learning import lora_eval

    lora_eval._patch_transformers_cache_compat_v2()

    try:
        from transformers.cache_utils import DynamicCache
    except Exception:
        return

    assert hasattr(DynamicCache, "seen_tokens")
    assert hasattr(DynamicCache, "get_max_length")
    assert hasattr(DynamicCache, "get_usable_length")


def test_lora_eval_generation_disables_cache():
    from pathlib import Path

    src = Path("eli/learning/lora_eval.py").read_text(encoding="utf-8")
    assert "use_cache=False" in src
