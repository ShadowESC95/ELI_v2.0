"""SELF_UPDATE must refresh live overlays + manifest, not narrate a generic plan."""
from __future__ import annotations

from unittest.mock import patch

from eli.runtime import control_contracts as cc


def test_self_update_compact_answer_lists_refreshed_surfaces():
    evidence = {
        "ok": True,
        "report": {
            "ok": True,
            "paths": {"project_root": "/eli", "user_db": "/eli/user.sqlite3"},
            "changed": {
                "overlays": {"ok": True},
                "world_model_runtime": True,
                "capability_manifest": {"total": 225},
            },
            "errors": [],
        },
    }
    text = cc.compact_evidence_answer("SELF_UPDATE", evidence)
    assert "Self-update result:" in text
    assert "capability_manifest" in text
    assert "world_model_runtime_refreshed: True" in text


def test_refresh_all_overlays_updates_manifest(monkeypatch):
    from eli.runtime import self_model_refresh as smr

    monkeypatch.setattr(
        "eli.cognition.persona_updater.update_persona_overlay",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "eli.cognition.persona_updater.update_user_profile_overlay",
        lambda: {"ok": True},
    )
    monkeypatch.setattr(
        "eli.cognition.user_info_builder.maybe_refresh_user_info",
        lambda reason="manual": {"ok": True},
    )
    monkeypatch.setattr(
        "eli.tools.registry.capability_updater.update_capability_manifest",
        lambda: {"total": 225},
    )

    out = smr.refresh_all_overlays_nonfatal(reason="test")
    assert out.get("capability_manifest") == {"total": 225}
    assert out.get("ok") is True
