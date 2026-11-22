"""The training allowlist must be operator-written, not frozen to one model family.

Before the registry, `lora_trainer_guard` accepted exactly two targets and required
`base_family == "phi3"`. That is this developer's machine hardcoded into a
redistributed product: anyone running Qwen, Llama or Mistral was refused at the
first gate, with no way to declare their own target short of editing source.

These tests pin the new contract: the allowlist still refuses anything undeclared,
but declaring is a runtime act, and the family is read from the base model's own
config.json rather than asserted.
"""
import json

import pytest

from eli.learning import target_registry as tr


@pytest.fixture()
def learning_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_LEARNING_DIR", str(tmp_path))
    from eli.core import paths
    for fn in ("data_dir", "artifacts_dir"):
        f = getattr(paths, fn, None)
        if hasattr(f, "cache_clear"):
            f.cache_clear()
    return tmp_path


def _hf_model(path, model_type="qwen3"):
    path.mkdir(parents=True, exist_ok=True)
    (path / "config.json").write_text(json.dumps({"model_type": model_type}), encoding="utf-8")
    (path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (path / "model.safetensors").write_bytes(b"\0" * 2048)
    return path


def test_builtin_targets_survive(learning_dir):
    assert {"eli_phi", "eli_phi_ultra"} <= tr.allowed_target_names()


def test_builtin_targets_keep_their_files_in_the_users_folders(learning_dir, tmp_path, monkeypatch):
    """The built-in targets named their dataset and adapters relative to the program folder, which a
    packaged install cannot write, so the dataset build failed there and only logged it. Their
    datasets are in learning_dir() and their adapters in the models folder, as an operator target's
    are; an adapter an older build trained in the program folder is still found there."""
    from pathlib import Path
    from eli.core import paths
    from eli.learning.lora_trainer_guard import build_training_plan
    models, program = tmp_path / "models", tmp_path / "program"
    monkeypatch.setenv("ELI_MODELS_DIR", str(models))
    monkeypatch.setattr(paths, "project_root", lambda: program)
    adapters = models / "lora" / "adapters"
    for name in ("eli_phi", "eli_phi_ultra"):
        target = tr.get_target(name)
        assert Path(target["dataset_path"]).parent == learning_dir / "datasets", target
        assert Path(target["adapter_path"]).parent == adapters and Path(target["output_dir"]).parent == adapters
        assert not str(target["dataset_path"]).startswith(str(program))
    plan = build_training_plan("eli_phi")["resolved_paths"]
    assert Path(plan["dataset_path"]) == Path(tr.get_target("eli_phi")["dataset_path"])
    assert Path(plan["adapter_path"]).parent == adapters

    old_dataset = program / "training" / "datasets" / Path(tr.get_target("eli_phi")["dataset_path"]).name
    old_adapter = program / "models" / "lora" / "adapters" / Path(tr.get_target("eli_phi")["adapter_path"]).name
    old_dataset.parent.mkdir(parents=True)
    old_dataset.write_text("", encoding="utf-8")
    old_adapter.mkdir(parents=True)
    target = tr.get_target("eli_phi")
    # an adapter an older build trained is still used; a dataset is built afresh where it is read
    assert Path(target["adapter_path"]) == old_adapter
    assert Path(target["dataset_path"]).parent == learning_dir / "datasets"
    assert Path(target["output_dir"]).parent == adapters               # a new adapter goes where it can be written
    assert Path(tr.get_target("eli_phi_ultra")["dataset_path"]).parent == learning_dir / "datasets"


def test_non_phi_family_can_be_declared(learning_dir, tmp_path):
    base = _hf_model(tmp_path / "qwen-base", "qwen3")
    res = tr.create_target("my_qwen", base)
    assert res["ok"], res.get("problems")
    assert res["target"]["base_family"] == "qwen3"
    assert "my_qwen" in tr.allowed_target_names()


def test_family_is_read_from_the_model_not_the_name(learning_dir, tmp_path):
    base = _hf_model(tmp_path / "confusingly-named-phi", "llama")
    res = tr.create_target("looks_like_phi", base)
    assert res["target"]["base_family"] == "llama"


def test_gguf_is_refused_as_a_base(learning_dir, tmp_path):
    gguf = tmp_path / "model.gguf"
    gguf.write_bytes(b"GGUF")
    res = tr.create_target("bad", gguf)
    assert not res["ok"]
    assert any("GGUF" in p for p in res["problems"])


def test_undeclared_target_is_still_refused(learning_dir):
    from eli.learning.lora_trainer_guard import resolve_target
    with pytest.raises(ValueError):
        resolve_target("something_nobody_declared")


def test_builtin_cannot_be_deleted(learning_dir):
    assert not tr.delete_target("eli_phi")["ok"]


def test_operator_target_round_trips(learning_dir, tmp_path):
    base = _hf_model(tmp_path / "b", "mistral")
    tr.create_target("tmp_target", base)
    assert tr.registry_path().is_file()
    assert tr.get_target("tmp_target")["base_family"] == "mistral"
    assert tr.delete_target("tmp_target")["ok"]
    assert tr.get_target("tmp_target") is None


@pytest.mark.parametrize("name", ["", "A Bad Name", "x", "has spaces", "UPPER"])
def test_bad_names_refused(learning_dir, tmp_path, name):
    base = _hf_model(tmp_path / "b2", "qwen3")
    assert not tr.create_target(name, base)["ok"]


def test_family_matching_is_tolerant_but_not_blind():
    assert tr.family_matches("phi3", "phi-3")
    assert tr.family_matches("", "anything")   # unpinned target accepts what it finds
    assert tr.family_matches("qwen3", None)    # unreadable config is not a mismatch
    assert not tr.family_matches("qwen3", "llama")


# ── the declared list is the list, everywhere ────────────────────────────────

def _declare_qwen(tmp_path):
    base = _hf_model(tmp_path / "bases" / "qwen-small", "qwen3")
    res = tr.create_target("my_qwen", base)
    assert res["ok"], res.get("problems")
    return base


def test_a_declared_target_reaches_every_learning_entry_point(learning_dir, tmp_path, capsys):
    """The trainer CLI's --target, the guard's "all", preflight_all (and LORA_STATUS on
    it) and the eval job only knew the two built-ins."""
    _declare_qwen(tmp_path)
    from eli.learning import lora_eval, lora_trainer, lora_trainer_guard as guard
    from eli.learning import training_preflight as tp

    assert "my_qwen" in [r["target"] for r in tp.preflight_all()["reports"]]
    job = lora_trainer.build_training_job("my_qwen")
    assert not any("target not allowed" in p for p in job.get("problems") or [])
    assert "Only targets the operator has declared are allowed." in job["safety_contract"]
    assert lora_trainer.main(["--target", "my_qwen"]) in (0, 1)   # argparse used to refuse it
    capsys.readouterr()
    assert not any("unsupported target" in p for p in lora_eval.build_eval_job("my_qwen")["problems"])

    guard.main(["--target", "all"])
    reports = json.loads(capsys.readouterr().out)["reports"]
    assert "my_qwen" in {r["target"] for r in reports}


def test_an_unresolved_base_is_not_called_phi_3_for_another_family(learning_dir, tmp_path):
    _declare_qwen(tmp_path)
    from eli.learning.training_preflight import preflight_target
    rep = preflight_target("my_qwen", base_model_path=tmp_path / "missing",
                           allow_default_candidates=False)
    assert rep["problems"] and "Phi-3" not in " ".join(rep["problems"])


def test_run_plans_have_one_folder_the_learning_dir(learning_dir, capsys):
    """Run plans went to PROJECT_ROOT/training/runs (the install folder on a packaged
    build) while the guard wrote to learning_dir()/runs."""
    from pathlib import Path
    from eli.learning import lora_eval, lora_trainer, lora_trainer_guard as guard
    runs = Path(learning_dir) / "runs"
    assert guard.runs_dir() == runs
    lora_trainer.main(["--target", "eli_phi"])
    assert json.loads(capsys.readouterr().out)["plan_path"].startswith(str(runs))
    report = lora_eval.write_report({"target": "eli_phi", "base_only": True})
    assert report["report_path"].startswith(str(runs))


def test_training_base_is_a_base_search_root(learning_dir, tmp_path):
    """Every training document downloads the base into training/base/."""
    from pathlib import Path
    from eli.learning.base_model_resolver import base_search_roots, discover_base_models
    assert Path(learning_dir) / "base" in base_search_roots()
    found = _hf_model(Path(learning_dir) / "base" / "tiny-llama", "llama")
    assert str(found.resolve()) in {d["path"] for d in discover_base_models()}
