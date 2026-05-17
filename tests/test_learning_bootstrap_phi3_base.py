from pathlib import Path

from eli.learning.bootstrap_phi3_base import build_bootstrap_plan, inspect_base_dir


def test_bootstrap_plan_is_dry_run_by_default(tmp_path):
    plan = build_bootstrap_plan(local_dir=tmp_path / "missing-base")

    assert plan["execute"] is False
    assert plan["will_download"] is False
    assert plan["already_ready"] is False
    assert "download_phi3_base" in plan["commands"]


def test_inspect_rejects_missing_base_dir(tmp_path):
    report = inspect_base_dir(tmp_path / "does-not-exist")

    assert report["ok"] is False
    assert "Path does not exist." in report["problems"]


def test_inspect_accepts_minimal_fake_hf_base(tmp_path):
    base = tmp_path / "Phi-3-mini-4k-instruct"
    base.mkdir()

    (base / "config.json").write_text("{}", encoding="utf-8")
    (base / "tokenizer.json").write_text("{}", encoding="utf-8")
    (base / "model.safetensors.index.json").write_text("{}", encoding="utf-8")

    report = inspect_base_dir(base)

    assert report["ok"] is True
    assert report["has_config"] is True
    assert report["has_tokenizer"] is True
    assert report["has_weights"] is True


def test_inspect_rejects_gguf_base(tmp_path):
    base = tmp_path / "bad-gguf"
    base.mkdir()

    (base / "config.json").write_text("{}", encoding="utf-8")
    (base / "tokenizer.json").write_text("{}", encoding="utf-8")
    (base / "model.gguf").write_text("not really a model", encoding="utf-8")

    report = inspect_base_dir(base)

    assert report["ok"] is False
    assert any("GGUF" in p for p in report["problems"])
