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
