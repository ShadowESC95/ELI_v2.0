from eli.learning.training_preflight import preflight_target


def test_preflight_blocks_missing_phi_base_when_isolated(tmp_path):
    report = preflight_target(
        "eli_phi",
        base_model_path=tmp_path / "missing-phi-base",
        allow_default_candidates=False,
    )

    assert report["can_train"] is False
    assert "trainable Phi-3 base model unresolved" in report["problems"]
    assert report["base_model_resolution"]["ok"] is False


def test_preflight_keeps_phi_ultra_target_scope():
    report = preflight_target("eli_phi_ultra")

    assert report["target"] == "eli_phi_ultra"
    assert report["guard_plan"]["target"] == "eli_phi_ultra"


def test_preflight_can_train_after_phi_base_download():
    report = preflight_target("eli_phi")

    assert report["base_model_resolution"]["ok"] is True
    assert report["can_train"] is True
    assert report["problems"] == []


def test_preflight_report_does_not_leak_weak_base_warning():
    report = preflight_target("eli_phi")

    blob = str(report)
    assert "base model path missing:" not in blob
    assert "trainable Phi-3 base model unresolved" not in report.get("problems", [])
