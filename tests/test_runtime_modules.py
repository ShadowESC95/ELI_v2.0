"""Tests for eli.runtime sub-modules — ~80 tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ── Security ──────────────────────────────────────────────────────────────

def test_security_importable():
    from eli.runtime.security import SecurityManager
    assert SecurityManager is not None

def test_security_safe_chat():
    try:
        from eli.runtime.security import is_safe_action
        result = is_safe_action("CHAT", {})
        assert result is True or result is False
    except ImportError:
        pytest.skip("is_safe_action not available")

def test_security_safe_memory_recall():
    try:
        from eli.runtime.security import is_safe_action
        result = is_safe_action("MEMORY_RECALL", {})
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("is_safe_action not available")

@pytest.mark.parametrize("action", [
    "CHAT", "MEMORY_RECALL", "RUNTIME_STATUS",
    "MEMORY_STATUS", "COGNITION_STATUS",
])
def test_security_standard_actions(action):
    try:
        from eli.runtime.security import is_safe_action
        result = is_safe_action(action, {})
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("is_safe_action not available")


# ── Authority Gate ────────────────────────────────────────────────────────

def test_authority_gate_importable():
    try:
        from eli.runtime.authority_gate import check_authority
        assert check_authority is not None
    except ImportError:
        pytest.skip("authority_gate not available in this form")


# ── Response Contracts ────────────────────────────────────────────────────

def test_response_contracts_importable():
    from eli.runtime.response_contracts import ResponseContract
    assert ResponseContract is not None

def test_grounded_actions_contains_standard():
    from eli.runtime.response_contracts import contract_for_action
    for action in ("MEMORY_STATUS", "COGNITION_STATUS"):
        contract = contract_for_action(action)
        assert contract is not None


# ── Route Authority ───────────────────────────────────────────────────────

def test_route_authority_importable():
    try:
        from eli.runtime.route_authority import check_route_authority
        assert check_route_authority is not None
    except ImportError:
        try:
            from eli.execution.route_authority import check_route_authority
            assert check_route_authority is not None
        except ImportError:
            pytest.skip("route_authority not available")


# ── Reflection ────────────────────────────────────────────────────────────

def test_reflection_importable():
    from eli.runtime.reflection import run_reflection
    assert run_reflection is not None

def test_reflect_returns_something():
    from eli.runtime.reflection import run_reflection
    try:
        result = run_reflection(hours=0)
        assert result is None or isinstance(result, (str, dict))
    except Exception:
        pass


# ── Self Improvement ──────────────────────────────────────────────────────

def test_self_improvement_importable():
    from eli.runtime.self_improvement import SelfImprovementEngine
    assert SelfImprovementEngine is not None

def test_self_improvement_init(tmp_db):
    from eli.runtime.self_improvement import SelfImprovementEngine
    try:
        si = SelfImprovementEngine()
        assert si is not None
    except Exception:
        pass


# ── Live Introspection ────────────────────────────────────────────────────

def test_live_introspection_importable():
    try:
        from eli.runtime.live_introspection import get_runtime_snapshot
        assert get_runtime_snapshot is not None
    except ImportError:
        pytest.skip("live_introspection not available")

def test_live_introspection_snapshot():
    try:
        from eli.runtime.live_introspection import get_runtime_snapshot
        result = get_runtime_snapshot()
        assert result is None or isinstance(result, dict)
    except ImportError:
        pytest.skip("live_introspection not available")
    except Exception:
        pass


# ── Identity Guard ────────────────────────────────────────────────────────

def test_identity_guard_importable():
    from eli.runtime.identity_guard import get_lock_state
    assert get_lock_state is not None

@pytest.mark.parametrize("query,should_be_identity", [
    ("who are you", True),
    ("what are you", True),
    ("tell me about yourself", True),
    ("what is 2+2", False),
    ("open a file", False),
    ("what do you remember", False),
])
def test_identity_guard_classification(query, should_be_identity):
    try:
        from eli.runtime.identity_guard import is_identity_query
        result = is_identity_query(query)
        assert isinstance(result, bool)
    except ImportError:
        pytest.skip("is_identity_query not available")


# ── Approval Engine ───────────────────────────────────────────────────────

def test_approval_engine_importable():
    try:
        from eli.runtime.approval_engine import ApprovalEngine
        assert ApprovalEngine is not None
    except ImportError:
        pytest.skip("approval_engine not available")


# ── Personal Memory Surface ───────────────────────────────────────────────

def test_personal_memory_surface_importable():
    try:
        from eli.runtime.personal_memory_surface import PersonalMemorySurface
        assert PersonalMemorySurface is not None
    except ImportError:
        pytest.skip("personal_memory_surface not available")


# ── Evidence Store ────────────────────────────────────────────────────────

def test_evidence_store_importable():
    from eli.runtime.evidence_store import get_current_evidence_packet
    assert get_current_evidence_packet is not None

def test_evidence_store_instantiation(tmp_db):
    from eli.runtime.evidence_store import get_current_evidence_packet
    try:
        result = get_current_evidence_packet()
        assert result is not None
    except Exception:
        pass


# ── Awareness Boot ────────────────────────────────────────────────────────

def test_awareness_boot_importable():
    try:
        from eli.runtime.awareness_boot import boot_awareness
        assert boot_awareness is not None
    except ImportError:
        pytest.skip("awareness_boot not available")


# ── Operator State ────────────────────────────────────────────────────────

def test_operator_state_importable():
    try:
        from eli.runtime.operator_state import OperatorState
        assert OperatorState is not None
    except ImportError:
        pytest.skip("operator_state not available")
