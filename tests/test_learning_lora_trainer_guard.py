import json
from pathlib import Path

import pytest

from eli.learning.lora_trainer_guard import build_training_plan


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def make_fake_phi_base(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps({"model_type": "phi3"}), encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"fake-test-weights")


def make_adapter(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "adapter_config.json").write_text(
        json.dumps(
            {
                "base_model_name_or_path": "./phi-3-mini-base",
                "peft_type": "LORA",
                "task_type": "CAUSAL_LM",
                "r": 4,
                "lora_alpha": 4,
                "target_modules": ["qkv_proj"],
                "inference_mode": True,
            }
        ),
        encoding="utf-8",
    )


def make_registry(path: Path, dataset: Path, adapter: Path, base_model_path: Path | str = "phi-3-mini-base"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "targets": {
                    "eli_phi": {
                        "base_family": "phi3",
                        "base_model_path": str(base_model_path),
                        "adapter_path": str(adapter),
                        "dataset_path": str(dataset),
                        "output_dir": "out/eli_phi",
                    }
                }
            }
        ),
        encoding="utf-8",
    )


def test_rejects_non_phi_target(tmp_path):
    with pytest.raises(ValueError):
        build_training_plan("generic_gguf", project_root=tmp_path)


def test_dry_run_accepts_reviewed_phi_dataset(tmp_path):
    base = tmp_path / "phi-3-mini-base"
    make_fake_phi_base(base)

    dataset = tmp_path / "trainable.jsonl"
    adapter = tmp_path / "adapter"
    registry = tmp_path / "registry.json"

    make_adapter(adapter)
    make_registry(registry, dataset, adapter, base)

    write_jsonl(
        dataset,
        [
            {
                "instruction": "Who are you?",
                "response": "My identity is ELI: local runtime continuity shaped by memory, self-model state, and grounded tools.",
                "tags": ["reviewed", "self_model"],
                "targets": ["eli_phi"],
                "target": "eli_phi",
            }
        ],
    )

    plan = build_training_plan(
        "eli_phi",
        registry_path=registry,
        project_root=tmp_path,
    )

    assert plan["ok"] is True
    assert plan["dry_run"] is True
    assert plan["will_train"] is False
    assert plan["train_ready"] is True
    assert plan["dataset"]["rows"] == 1
    assert plan["dataset"]["reviewed_rows"] == 1
    assert plan["dataset"]["targeted_rows"] == 1
    assert plan["problems"] == []


def test_wrong_target_row_blocks_training(tmp_path):
    base = tmp_path / "phi-3-mini-base"
    make_fake_phi_base(base)

    dataset = tmp_path / "trainable.jsonl"
    adapter = tmp_path / "adapter"
    registry = tmp_path / "registry.json"

    make_adapter(adapter)
    make_registry(registry, dataset, adapter, base)

    write_jsonl(
        dataset,
        [
            {
                "instruction": "Who are you?",
                "response": "My identity is ELI: local runtime continuity shaped by memory and self-model state.",
                "tags": ["reviewed", "self_model"],
                "targets": ["openhermes"],
                "target": "openhermes",
            }
        ],
    )

    plan = build_training_plan(
        "eli_phi",
        registry_path=registry,
        project_root=tmp_path,
    )

    assert plan["ok"] is True
    assert plan["train_ready"] is False
    assert plan["dataset"]["wrong_target_rows"] == 1
    assert plan["dataset"]["generic_target_leak_rows"] == 1
    assert any("missing required target=eli_phi" in x for x in plan["problems"])


def test_cli_report_resolves_downloaded_phi_base_model(tmp_path):
    import json
    import subprocess
    import sys

    base = tmp_path / "models" / "hf" / "Phi-3-mini-4k-instruct"
    make_fake_phi_base(base)

    dataset = tmp_path / "trainable.jsonl"
    adapter = tmp_path / "adapter"
    registry = tmp_path / "registry.json"

    make_adapter(adapter)
    make_registry(registry, dataset, adapter, base)

    write_jsonl(
        dataset,
        [
            {
                "instruction": "Who are you?",
                "response": "My identity is ELI: local runtime continuity shaped by memory, self-model state, and grounded tools.",
                "tags": ["reviewed", "self_model"],
                "targets": ["eli_phi"],
                "target": "eli_phi",
            }
        ],
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "eli.learning.lora_trainer_guard",
            "--target",
            "eli_phi",
            "--registry",
            str(registry),
            "--project-root",
            str(tmp_path),
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(proc.stdout)
    report = payload["reports"][0] if "reports" in payload else payload

    assert "base_model_resolution" in report
    assert report["base_model_resolution"]["ok"] is True
    assert "models/hf/Phi-3-mini-4k-instruct" in report["config"]["base_model_path"]
    assert "models/hf/Phi-3-mini-4k-instruct" in report["adapter_config"]["base_model_name_or_path"]
    assert "phi-3-mini-base" not in report["resolved_paths"]["base_model_path"]
    assert report["dataset"]["rows"] == 1
    assert report["train_ready"] is True
    assert report["will_train"] is False
