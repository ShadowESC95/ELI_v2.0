"""
test_06_runtime.py
==================
Tests for eli.runtime — agent, approvals, grounded remediation, self-improvement.
"""
import importlib
import pytest


def _load(mod_path):
    return importlib.import_module(mod_path)


def test_runtime_package_init():
    assert _load("eli.runtime") is not None


def test_runtime_eli_agent_has_class():
    mod = _load("eli.runtime.eli_agent")
    syms = dir(mod)
    # Module is function-based: dispatch, main, quick_route are the public API
    matches = [s for s in syms if "Agent" in s or "Eli" in s
               or s in ("dispatch", "main", "quick_route", "run")]
    assert matches, f"No Agent class/function in eli_agent.py: {syms}"


def test_runtime_grounded_remediation_has_class():
    mod = _load("eli.runtime.grounded_remediation")
    syms = dir(mod)
    # Module is function-based: offer_for_result, try_handle_query are the public API
    matches = [s for s in syms if "Remediat" in s or "Grounded" in s
               or s in ("offer_for_result", "try_handle_query", "capture_executor_failure")]
    assert matches, f"No remediation class/function in grounded_remediation.py: {syms}"


def test_runtime_self_improvement_has_class():
    mod = _load("eli.runtime.self_improvement")
    syms = dir(mod)
    matches = [s for s in syms if "Improve" in s or "Self" in s]
    assert matches, f"No self-improvement class: {syms}"


def test_runtime_security_loadable():
    assert _load("eli.runtime.security") is not None


def test_runtime_approval_engine_loadable():
    assert _load("eli.runtime.approval_engine") is not None


def test_runtime_identity_guard_loadable():
    assert _load("eli.runtime.identity_guard") is not None


def test_runtime_authority_gate_loadable():
    assert _load("eli.runtime.authority_gate") is not None


def test_runtime_authority_state_loadable():
    assert _load("eli.runtime.authority_state") is not None


def test_runtime_awareness_boot_loadable():
    assert _load("eli.runtime.awareness_boot") is not None


def test_runtime_capability_sync_loadable():
    assert _load("eli.runtime.capability_sync") is not None


def test_runtime_code_monitor_loadable():
    assert _load("eli.runtime.code_monitor") is not None


def test_runtime_control_contracts_loadable():
    assert _load("eli.runtime.control_contracts") is not None


def test_runtime_evidence_arbitration_loadable():
    assert _load("eli.runtime.evidence_arbitration") is not None


def test_runtime_evidence_store_loadable():
    assert _load("eli.runtime.evidence_store") is not None


def test_runtime_fastpath_responder_loadable():
    assert _load("eli.runtime.fastpath_responder") is not None


def test_runtime_final_response_assembly_loadable():
    assert _load("eli.runtime.final_response_assembly") is not None


def test_runtime_final_response_provider_loadable():
    assert _load("eli.runtime.final_response_provider") is not None


def test_runtime_incident_log_loadable():
    assert _load("eli.runtime.incident_log") is not None


def test_runtime_last_trace_loadable():
    assert _load("eli.runtime.last_trace") is not None


def test_runtime_live_introspection_loadable():
    assert _load("eli.runtime.live_introspection") is not None


def test_runtime_memory_evidence_loadable():
    assert _load("eli.runtime.memory_evidence") is not None


def test_runtime_operator_feed_loadable():
    assert _load("eli.runtime.operator_feed") is not None


def test_runtime_operator_feed_normalized_loadable():
    assert _load("eli.runtime.operator_feed_normalized") is not None


def test_runtime_operator_state_loadable():
    assert _load("eli.runtime.operator_state") is not None


def test_runtime_packet_native_downstream_loadable():
    assert _load("eli.runtime.packet_native_downstream") is not None


def test_runtime_persistence_gate_loadable():
    assert _load("eli.runtime.persistence_gate") is not None


def test_runtime_personal_memory_surface_loadable():
    assert _load("eli.runtime.personal_memory_surface") is not None


def test_runtime_pipeline_models_loadable():
    assert _load("eli.runtime.pipeline_models") is not None


def test_runtime_profile_extractor_loadable():
    assert _load("eli.runtime.profile_extractor") is not None


def test_runtime_reflection_loadable():
    assert _load("eli.runtime.reflection") is not None


def test_runtime_repair_policy_loadable():
    assert _load("eli.runtime.repair_policy") is not None


def test_runtime_response_contracts_loadable():
    assert _load("eli.runtime.response_contracts") is not None


def test_runtime_response_packets_loadable():
    assert _load("eli.runtime.response_packets") is not None


def test_runtime_response_policy_loadable():
    assert _load("eli.runtime.response_policy") is not None


def test_runtime_retrieval_packets_loadable():
    assert _load("eli.runtime.retrieval_packets") is not None


def test_runtime_self_model_refresh_loadable():
    assert _load("eli.runtime.self_model_refresh") is not None


def test_runtime_single_pass_authority_loadable():
    assert _load("eli.runtime.single_pass_authority") is not None


def test_runtime_stage_packets_loadable():
    assert _load("eli.runtime.stage_packets") is not None


def test_runtime_stage_packet_store_loadable():
    assert _load("eli.runtime.stage_packet_store") is not None


def test_runtime_tool_result_models_loadable():
    assert _load("eli.runtime.tool_result_models") is not None


def test_runtime_tool_result_normalizer_loadable():
    assert _load("eli.runtime.tool_result_normalizer") is not None


def test_runtime_tool_result_store_loadable():
    assert _load("eli.runtime.tool_result_store") is not None


def test_runtime_typed_stage_bridge_loadable():
    assert _load("eli.runtime.typed_stage_bridge") is not None


def test_runtime_auth_loadable():
    assert _load("eli.runtime.auth") is not None
