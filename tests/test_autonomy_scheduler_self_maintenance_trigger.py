"""Self-upgrade and LoRA retraining were both fully built -- SelfUpgrader has
real verified-download/rollback machinery, apply_code_patch() has a protected-
path guardrail, the `self_upgrade`/`lora` scheduled-task kinds both work --
but nothing inside ELI ever decided on its own to USE them. proactive_daemon.py
and autonomy_scheduler.py had zero references to either kind: a human had to
explicitly ask or pre-schedule every time, even with a newer release sitting
on GitHub or enough reviewed training data accumulated ("self-maintaining"
in name only for this specific gap).

`_maybe_check_self_upgrade` / `_maybe_check_lora_retrain` are the missing
"decide to invoke it" layer: they only ever fire in `goal_driven` operator
policy mode (the one mode that already carries elevated-autonomy semantics
elsewhere in this file), on a multi-day throttle, and they still go through
the exact same `schedule_request(..., kind=...)` entry point and downstream
safety machinery a human-typed "update ELI overnight" would use. Nothing
about the upgrade/training mechanics themselves changed.
"""
import pytest

from eli.planning import autonomy_scheduler as sched


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Never touch the real artifacts dir / operator policy / attention log."""
    monkeypatch.setattr(sched, "scheduler_state_path", lambda: tmp_path / "autonomy_scheduler.json")
    monkeypatch.setattr(sched, "append_attention", lambda **kw: None)


def _base_state():
    return {"last_self_upgrade_check": None, "last_lora_check": None}


# ── self-upgrade ─────────────────────────────────────────────────────────

def _patch_self_upgrader(monkeypatch, *, local="2.4.48", latest="v2.4.48"):
    class _FakeUpgrader:
        def _local_version(self):
            return local

        def _latest_tag(self):
            return latest

    import eli.kernel.self_upgrade as su
    monkeypatch.setattr(su, "SelfUpgrader", _FakeUpgrader)
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: True)


def test_self_upgrade_not_triggered_when_up_to_date(monkeypatch):
    _patch_self_upgrader(monkeypatch, local="2.4.48", latest="v2.4.48")
    added = sched._maybe_check_self_upgrade(_base_state(), now=1000.0)
    assert added == 0


def test_self_upgrade_triggered_when_newer_release_exists(monkeypatch):
    _patch_self_upgrader(monkeypatch, local="2.4.48", latest="v2.4.50")
    scheduled = {}

    def _fake_schedule_request(request, when_spec="", kind=None, recurring=False):
        scheduled["request"] = request
        scheduled["kind"] = kind
        return {"ok": True, "job_id": "abc123"}

    import eli.runtime.scheduled_tasks as st
    monkeypatch.setattr(st, "schedule_request", _fake_schedule_request)

    state = _base_state()
    added = sched._maybe_check_self_upgrade(state, now=1000.0)

    assert added == 1
    assert scheduled["kind"] == "self_upgrade"
    assert "v2.4.50" in scheduled["request"]
    assert state["last_self_upgrade_check"] == 1000.0


def test_self_upgrade_respects_the_check_interval_throttle(monkeypatch):
    _patch_self_upgrader(monkeypatch, local="2.4.48", latest="v2.4.50")
    calls = []

    import eli.runtime.scheduled_tasks as st
    monkeypatch.setattr(st, "schedule_request", lambda *a, **k: calls.append(1) or {"ok": True, "job_id": "x"})

    state = {"last_self_upgrade_check": 1000.0, "last_lora_check": None}
    # 1 hour later -- well inside the multi-day throttle.
    added = sched._maybe_check_self_upgrade(state, now=1000.0 + 3600)
    assert added == 0
    assert not calls


def test_self_upgrade_skips_cleanly_when_offline(monkeypatch):
    _patch_self_upgrader(monkeypatch, local="2.4.48", latest="v2.4.50")
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: False)

    state = _base_state()
    added = sched._maybe_check_self_upgrade(state, now=1000.0)
    assert added == 0
    # Still records the check happened, so it doesn't retry every tick offline.
    assert state["last_self_upgrade_check"] == 1000.0


def test_self_upgrade_never_raises_on_internal_failure(monkeypatch):
    import eli.kernel.self_upgrade as su

    class _BoomUpgrader:
        def _local_version(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(su, "SelfUpgrader", _BoomUpgrader)
    import eli.core.config as cfg
    monkeypatch.setattr(cfg, "network_allowed", lambda: True)

    added = sched._maybe_check_self_upgrade(_base_state(), now=1000.0)
    assert added == 0


# ── LoRA ──────────────────────────────────────────────────────────────────

def test_lora_not_triggered_when_nothing_is_ready(monkeypatch):
    import eli.learning.training_preflight as tp
    monkeypatch.setattr(tp, "preflight_all", lambda: {"reports": [{"target": "eli_phi", "can_train": False}]})

    added = sched._maybe_check_lora_retrain(_base_state(), now=1000.0)
    assert added == 0


def test_lora_triggered_when_a_target_is_ready(monkeypatch):
    import eli.learning.training_preflight as tp
    monkeypatch.setattr(tp, "preflight_all", lambda: {
        "reports": [{"target": "eli_phi", "can_train": True}],
    })
    scheduled = {}

    def _fake_schedule_request(request, when_spec="", kind=None, recurring=False):
        scheduled["kind"] = kind
        scheduled["request"] = request
        return {"ok": True, "job_id": "lora-1"}

    import eli.runtime.scheduled_tasks as st
    monkeypatch.setattr(st, "schedule_request", _fake_schedule_request)

    state = _base_state()
    added = sched._maybe_check_lora_retrain(state, now=2000.0)

    assert added == 1
    assert scheduled["kind"] == "lora"
    assert "eli_phi" in scheduled["request"]
    assert state["last_lora_check"] == 2000.0


def test_lora_respects_the_check_interval_throttle(monkeypatch):
    import eli.learning.training_preflight as tp
    monkeypatch.setattr(tp, "preflight_all", lambda: {
        "reports": [{"target": "eli_phi", "can_train": True}],
    })
    calls = []
    import eli.runtime.scheduled_tasks as st
    monkeypatch.setattr(st, "schedule_request", lambda *a, **k: calls.append(1) or {"ok": True, "job_id": "x"})

    state = {"last_self_upgrade_check": None, "last_lora_check": 2000.0}
    added = sched._maybe_check_lora_retrain(state, now=2000.0 + 3600)
    assert added == 0
    assert not calls


# ── gating ────────────────────────────────────────────────────────────────

def test_scheduler_tick_only_triggers_self_maintenance_in_goal_driven_mode(monkeypatch, tmp_path):
    """The whole point: every other policy mode must behave exactly as before
    -- pull-only, zero autonomous self_upgrade/lora scheduling."""
    monkeypatch.setattr(sched, "load_policy", lambda: {"mode": "proposal_only"})
    monkeypatch.setattr(sched, "safe_proposal_summary", lambda: {})
    monkeypatch.setattr(sched, "safe_goal_summary", lambda: {})

    calls = []
    monkeypatch.setattr(sched, "_maybe_check_self_upgrade", lambda *a, **k: calls.append("upgrade") or 0)
    monkeypatch.setattr(sched, "_maybe_check_lora_retrain", lambda *a, **k: calls.append("lora") or 0)

    import eli.planning.goal_tick as gt
    monkeypatch.setattr(gt, "governed_goal_tick", lambda limit, now: {"ok": True, "count": 0, "items": []})

    sched.scheduler_tick(now=1_000_000.0, cooldown_sec=0)
    assert calls == []


def test_scheduler_tick_checks_self_maintenance_in_goal_driven_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(sched, "load_policy", lambda: {"mode": "goal_driven"})
    monkeypatch.setattr(sched, "safe_proposal_summary", lambda: {})
    monkeypatch.setattr(sched, "safe_goal_summary", lambda: {})

    calls = []
    monkeypatch.setattr(sched, "_maybe_check_self_upgrade", lambda *a, **k: calls.append("upgrade") or 0)
    monkeypatch.setattr(sched, "_maybe_check_lora_retrain", lambda *a, **k: calls.append("lora") or 0)

    import eli.planning.goal_tick as gt
    monkeypatch.setattr(gt, "governed_goal_tick", lambda limit, now: {"ok": True, "count": 0, "items": []})

    sched.scheduler_tick(now=1_000_000.0, cooldown_sec=0)
    assert calls == ["upgrade", "lora"]
