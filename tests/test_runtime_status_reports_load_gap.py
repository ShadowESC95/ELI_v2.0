"""Every runtime-status surface must state when what loaded differs from what was
requested (layers 7 asked, 6 loaded), from one shared rule, runtime_load_facts()."""
from __future__ import annotations

import json

from eli.runtime.truth_report import format_runtime_truth, runtime_load_facts

# The exact shape the GUI's snapshot writer produces since 2.4.55: requested and
# effective are separate blocks, and there is no top-level "clamped" flag.
CLAMPED_SNAPSHOT = {
    "provider": "gguf",
    "model_name": "Qwen3.6-35B-A3B-Q4_K_M.gguf",
    "model_path": "/models/Qwen3.6-35B-A3B-Q4_K_M.gguf",
    "n_ctx": 12200, "n_gpu_layers": 6, "n_threads": 10, "n_batch": 512,
    "loaded": True, "load_mode": "GPU",
    "requested": {"n_ctx": 12200, "n_gpu_layers": 7, "n_threads": 10, "n_batch": 512},
    "effective": {"n_ctx": 12200, "n_gpu_layers": 6, "n_threads": 10, "n_batch": 512},
}
CLEAN_SNAPSHOT = {
    **CLAMPED_SNAPSHOT,
    "n_gpu_layers": 7,
    "effective": {"n_ctx": 12200, "n_gpu_layers": 7, "n_threads": 10, "n_batch": 512},
}
SETTINGS = {
    "n_ctx": 12200, "n_gpu_layers": 7, "batch_size": 512, "max_tokens": 6100,
    "temperature": 0.7, "use_mmap": True, "use_mlock": True, "n_threads": 10,
    "hw_profile_n_ctx": 10240, "hw_profile_n_gpu_layers": 7,
    "hw_profile_batch_size": 256,
}


# ── the shared rule ─────────────────────────────────────────────────────────

def test_a_reduced_load_is_reported_as_a_difference():
    facts = runtime_load_facts(CLAMPED_SNAPSHOT, SETTINGS)
    assert facts["consistent"] is False
    assert facts["clamped"] is True
    assert any("GPU layers: requested 7, loaded 6" in d for d in facts["differences"])


def test_only_the_parameters_that_actually_differ_are_listed():
    facts = runtime_load_facts(CLAMPED_SNAPSHOT, SETTINGS)
    joined = " ".join(facts["differences"])
    assert "context" not in joined and "batch" not in joined


def test_an_untouched_load_is_consistent():
    facts = runtime_load_facts(CLEAN_SNAPSHOT, SETTINGS)
    assert facts["consistent"] is True
    assert facts["differences"] == []
    assert facts["clamped"] is False


def test_the_tuner_suggestion_is_shown_but_never_counts_as_an_inconsistency():
    """The tuner's numbers legitimately differ from a load that used the
    operator's own values -- that is by design, and must not read as a fault."""
    facts = runtime_load_facts(CLEAN_SNAPSHOT, SETTINGS)
    assert facts["tuner_recommendation"] == {
        "n_ctx": 10240, "n_gpu_layers": 7, "n_batch": 256}
    assert facts["consistent"] is True
    assert "not what loaded" in facts["tuner_note"]


def test_a_snapshot_from_before_the_requested_split_still_surfaces_a_saved_mismatch():
    """A writer that predates the requested/effective split collapses both onto
    what loaded; the saved setting is then the only record of what was wanted."""
    flat = {"n_ctx": 4096, "n_gpu_layers": 7, "n_batch": 512,
            "requested": {"n_ctx": 4096, "n_gpu_layers": 7, "n_batch": 512},
            "effective": {"n_ctx": 4096, "n_gpu_layers": 7, "n_batch": 512}}
    facts = runtime_load_facts(flat, {"n_ctx": 12200, "n_gpu_layers": 7, "batch_size": 512})
    assert any("saved setting 12200, loaded 4096" in d for d in facts["differences"])


def test_no_data_does_not_raise_and_claims_nothing_is_wrong():
    for snap, cfg in ((None, None), ({}, {}), ({}, SETTINGS)):
        facts = runtime_load_facts(snap, cfg)
        assert facts["differences"] == [] and facts["clamped"] is False


# ── each surface ────────────────────────────────────────────────────────────

def _report():
    return {"runtime_snapshot": CLAMPED_SNAPSHOT, "settings": SETTINGS,
            "gguf": {}, "gpu": {}, "git": {}, "import_health": {}, "platform": {}}


def test_truth_report_carries_the_comparison_and_a_real_clamped_flag():
    payload = json.loads(format_runtime_truth(_report()))
    assert payload["effective"]["clamped"] is True, (
        "the snapshot never sets `clamped`; it must be derived, not read")
    assert payload["load_facts"]["differences"]


def test_the_compact_user_visible_card_states_the_difference():
    from eli.runtime.user_visible_response_surface import coerce_user_visible
    text = coerce_user_visible(format_runtime_truth(_report()))
    assert "Loaded differently from what was requested" in text
    assert "GPU layers: requested 7, loaded 6" in text
    assert "Tuner suggestion" in text and "not what loaded" in text


def test_the_compact_card_says_so_when_nothing_differs():
    from eli.runtime.user_visible_response_surface import coerce_user_visible
    rep = _report()
    rep["runtime_snapshot"] = CLEAN_SNAPSHOT
    text = coerce_user_visible(format_runtime_truth(rep))
    assert "Requested and loaded values match." in text
    assert "Loaded differently" not in text


def test_the_executor_runtime_status_states_the_difference():
    import eli.execution.executor_enhanced as ex
    text = ex._format_runtime_status({"settings": SETTINGS, "runtime": CLAMPED_SNAPSHOT})
    assert "loaded_below_request: GPU layers: requested 7, loaded 6" in text
    assert "- max_tokens: 6100" in text, "the required max_tokens field must survive"
    assert "not a per-call limit" in text


def test_the_engine_contract_states_the_difference_and_keeps_its_required_fields():
    from eli.contracts import runtime_status as rs
    ev = rs.build_live_evidence(runtime_snapshot=CLAMPED_SNAPSHOT, settings=SETTINGS)
    text = rs.build_content(ev, requested_mode="quick", surface="test")
    assert "loaded_below_request: GPU layers: requested 7, loaded 6" in text
    assert "NOT what loaded" in text
    assert rs.has_required_fields(text), "adding the comparison must not drop a required field"
    assert "not a per-call limit" in text


def test_the_engine_contract_still_builds_without_any_comparison_data():
    from eli.contracts import runtime_status as rs
    ev = rs.build_live_evidence(runtime_snapshot={}, settings={})
    text = rs.build_content(ev, requested_mode="quick", surface="test")
    assert rs.has_required_fields(text)
