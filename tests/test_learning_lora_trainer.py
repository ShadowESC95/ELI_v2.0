import json
import subprocess
import sys
from pathlib import Path

import pytest

from eli.learning import lora_trainer


def test_build_training_job_is_dry_run_by_default():
    job = lora_trainer.build_training_job("eli_phi")
    assert job["execute"] is False
    assert job["will_train"] is False
    assert "GGUF files are never trained directly." in job["safety_contract"]


def test_build_training_job_rejects_generic_target():
    job = lora_trainer.build_training_job("generic_gguf")
    assert job["ok"] is False
    assert job["will_train"] is False
    assert any("target not allowed" in p for p in job["problems"])


def test_execute_is_blocked_when_preflight_fails(monkeypatch, tmp_path):
    dataset = tmp_path / "data.jsonl"
    dataset.write_text(
        json.dumps({
            "instruction": "x",
            "response": "y",
            "tags": ["reviewed"],
            "targets": ["eli_phi"],
        }) + "\n",
        encoding="utf-8",
    )

    base = tmp_path / "base"
    base.mkdir()

    def fake_preflight(target):
        return {
            "can_train": False,
            "problems": ["forced failure"],
            "missing_modules": [],
            "base_model_resolution": {"ok": False},
            "guard_plan": {
                "config": {
                    "target": target,
                    "base_model_path": str(base),
                    "dataset_path": str(dataset),
                    "adapter_path": str(tmp_path / "adapter"),
                    "output_dir": str(tmp_path / "out"),
                },
                "resolved_paths": {
                    "base_model_path": str(base),
                    "dataset_path": str(dataset),
                    "adapter_path": str(tmp_path / "adapter"),
                    "output_dir": str(tmp_path / "out"),
                },
                "adapter_config": {"r": 4, "lora_alpha": 4, "target_modules": ["qkv_proj"]},
            },
        }

    monkeypatch.setattr(lora_trainer, "preflight_target", fake_preflight)

    job = lora_trainer.build_training_job("eli_phi", execute=True)
    assert job["will_train"] is False
    assert "forced failure" in job["problems"]


def test_execute_blocks_active_adapter_overwrite(monkeypatch, tmp_path):
    dataset = tmp_path / "data.jsonl"
    dataset.write_text(
        json.dumps({
            "instruction": "x",
            "response": "y",
            "tags": ["reviewed"],
            "targets": ["eli_phi"],
        }) + "\n",
        encoding="utf-8",
    )

    base = tmp_path / "base"
    base.mkdir()
    adapter = tmp_path / "adapter"
    adapter.mkdir()

    def fake_preflight(target):
        return {
            "can_train": True,
            "problems": [],
            "missing_modules": [],
            "base_model_resolution": {"ok": True},
            "guard_plan": {
                "config": {
                    "target": target,
                    "base_model_path": str(base),
                    "dataset_path": str(dataset),
                    "adapter_path": str(adapter),
                    "output_dir": str(adapter),
                },
                "resolved_paths": {
                    "base_model_path": str(base),
                    "dataset_path": str(dataset),
                    "adapter_path": str(adapter),
                    "output_dir": str(adapter),
                },
                "adapter_config": {"r": 4, "lora_alpha": 4, "target_modules": ["qkv_proj"]},
            },
        }

    monkeypatch.setattr(lora_trainer, "preflight_target", fake_preflight)

    job = lora_trainer.build_training_job("eli_phi", execute=True)
    assert job["will_train"] is False
    assert any("must not equal active adapter_path" in p for p in job["problems"])


def test_cli_dry_run_does_not_train():
    proc = subprocess.run(
        [sys.executable, "-m", "eli.learning.lora_trainer", "--target", "eli_phi"],
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    assert payload["execute"] is False
    assert payload["will_train"] is False
    assert payload["result"]["skipped"] is True

def test_phi3_rope_scaling_normalizer_adds_legacy_type():
    rope = {
        "rope_type": "longrope",
        "short_factor": [1.0],
        "long_factor": [1.0],
    }
    fixed = lora_trainer._normalize_phi3_rope_scaling_dict(rope)
    assert fixed["type"] == "longrope"
    assert fixed["rope_type"] == "longrope"


def test_phi3_rope_scaling_normalizer_infers_longrope():
    rope = {
        "short_factor": [1.0],
        "long_factor": [1.0],
    }
    fixed = lora_trainer._normalize_phi3_rope_scaling_dict(rope)
    assert fixed["type"] == "longrope"

def test_phi3_rope_scaling_normalizer_forces_longrope_when_factors_exist():
    rope = {
        "rope_type": "default",
        "short_factor": [1.0],
        "long_factor": [1.0],
    }
    fixed = lora_trainer._normalize_phi3_rope_scaling_dict(rope)
    assert fixed["type"] == "longrope"
    assert fixed["rope_type"] == "longrope"


def test_phi3_rope_scaling_normalizer_nulls_default_4k_rope():
    rope = {
        "rope_theta": 10000.0,
        "rope_type": "default",
        "type": "dynamic",
    }
    fixed = lora_trainer._normalize_phi3_rope_scaling_dict(rope)
    assert fixed is None

def test_trainer_does_not_store_print_trainable_parameters_return_value():
    from pathlib import Path

    src = Path("eli/learning/lora_trainer.py").read_text(encoding="utf-8")

    assert '"trainable_parameters": trainable_parameter_report' in src
    assert '"trainable_parameters": model.print_trainable_parameters()' not in src
    assert '"trainable_parameters": str(model.print_trainable_parameters())' not in src
    assert "trainable_parameters = model.print_trainable_parameters()" not in src
    assert "trainable_parameters = str(model.print_trainable_parameters())" not in src

def test_peft_trainable_parameter_report_contains_summary():
    from eli.learning.lora_trainer import _peft_trainable_parameter_report

    class P:
        def __init__(self, n, requires_grad):
            self._n = n
            self.requires_grad = requires_grad

        def numel(self):
            return self._n

    class M:
        def named_parameters(self):
            return [
                ("frozen.weight", P(100, False)),
                ("lora.weight", P(25, True)),
            ]

    report = _peft_trainable_parameter_report(M())

    assert report["trainable"] == 25
    assert report["total"] == 125
    assert report["trainable_percent"] == 20.0
    assert "trainable params: 25" in report["summary"]
    assert "all params: 125" in report["summary"]


# ---------------------------------------------------------------------
# Updated Phi-3 RoPE expectations:
# default 4k RoPE remains default; factor-based long-context RoPE becomes longrope.
# These override older definitions above.
# ---------------------------------------------------------------------

def test_phi3_rope_scaling_normalizer_infers_longrope():
    from eli.learning import lora_trainer

    rope = {
        "short_factor": [1.0],
        "long_factor": [1.0],
    }
    fixed = lora_trainer._normalize_phi3_rope_scaling_dict(rope)
    assert fixed["type"] == "longrope"
    assert fixed["rope_type"] == "longrope"


def test_phi3_rope_scaling_normalizer_forces_longrope_when_factors_exist():
    from eli.learning import lora_trainer

    rope = {
        "rope_type": "default",
        "short_factor": [1.0],
        "long_factor": [1.0],
    }
    fixed = lora_trainer._normalize_phi3_rope_scaling_dict(rope)
    assert fixed["type"] == "longrope"
    assert fixed["rope_type"] == "longrope"


def test_phi3_rope_scaling_normalizer_nulls_default_4k_rope():
    from eli.learning import lora_trainer

    rope = {
        "rope_theta": 10000.0,
        "partial_rotary_factor": 1.0,
        "rope_type": "default",
    }
    fixed = lora_trainer._normalize_phi3_rope_scaling_dict(rope)
    assert fixed is not None
    assert fixed["rope_type"] == "default"
    assert fixed["type"] == "default"

