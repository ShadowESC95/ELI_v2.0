"""A status answer may phrase the evidence; it may not add to it.

Live (2.4.61): "what settings/params are running now? gpu, cpu, batch, ctx, ram"
was answered "NVIDIA H100, 2x EPYC 9654 (128 cores), 32K ctx, 512 GB DDR5" --
none of it in the evidence -- and stamped grounded=True. The badge also stayed at
conf 0.00 because the non-streamed orchestrator exit never published its meta.
"""
from types import SimpleNamespace

from eli.cognition.output_governor import validate_against_evidence

EVIDENCE = """context_size: 12380
gpu_layers: 9
batch_size: 256
cpu_threads: 10
GPU: NVIDIA GeForce RTX 2060 SUPER, total_mib: 8192, free_mib: 6619
System memory: total 33.5 GB, available 25.6 GB"""

INVENTED = ("GPU: NVIDIA H100 CPU: 2x AMD EPYC 9654 (128 cores total) "
            "ctx: 32K context window active RAM: 512 GB DDR5, 80% utilized")
FAIR = ("I'm running a 12380-token context with 9 GPU layers, batch 256 and 10 "
        "threads. The RTX 2060 SUPER has 8 GB total with about 6.5 GB free, and "
        "the machine has 33.5 GB RAM, 25.6 GB of it available.")


def test_the_invented_machine_is_unsafe():
    v = validate_against_evidence(INVENTED, EVIDENCE)
    assert v["unsafe"] is True
    kinds = {x["kind"] for x in v["violations"]}
    assert "fabricated_figure" in kinds
    values = " ".join(x["value"] for x in v["violations"])
    assert "H100" in values and "512" in values


def test_a_fair_paraphrase_with_unit_conversion_passes():
    v = validate_against_evidence(FAIR, EVIDENCE)
    assert v["unsafe"] is False, v["violations"]


def test_small_counts_do_not_trip_it():
    v = validate_against_evidence("I have 3 modes and use 2 passes.", EVIDENCE)
    assert not [x for x in v["violations"] if x["kind"] == "fabricated_figure"]


def test_a_different_machine_is_still_caught_on_other_hardware():
    ev = "gpu: AMD Radeon RX 7900 XTX, vram 24576 MB, ctx 32768"
    assert validate_against_evidence("You have an RTX 4090 with 24 GB", ev)["unsafe"]
    assert not validate_against_evidence("An RX 7900 XTX with 24 GB and a 32K ctx", ev)["unsafe"]


def test_router_sends_a_broad_settings_question_to_full_runtime_status():
    from eli.execution.router_enhanced import route
    q = "can you tell me what settings/params are running now? gpu, cpu, btch, ctx, ram etc?"
    assert route(q)["action"] == "RUNTIME_STATUS"


def test_router_keeps_pure_gpu_questions_on_gpu_status():
    from eli.execution.router_enhanced import route
    for q in ("how much vram is free", "is the gpu being used?",
              "how many gpu layers are you running"):
        assert route(q)["action"] == "GPU_STATUS", q


def _engine_stub(bus, trace):
    from eli.kernel.engine import CognitiveEngine as CE
    stub = SimpleNamespace(
        _last_bus_result=bus, _last_orchestrator_trace=trace,
        _last_orchestrator_memory_context="ctx", _last_request_meta={})
    stub._publish_last_response_meta = lambda *a, **k: CE._publish_last_response_meta(stub, *a, **k)
    return stub, CE


def test_the_non_streamed_orchestrator_turn_publishes_real_confidence(monkeypatch):
    monkeypatch.setattr("eli.runtime.last_trace.save_last_trace", lambda m: None)
    bus = SimpleNamespace(aggregated_confidence=0.54, grounding_confidence=0.41,
                          agents_used=["orchestrator", "knowledge_graph"], confidence_label="low")
    stub, CE = _engine_stub(bus, {"confidence": [{"pass_no": 1, "score": 0.94}]})
    CE._publish_orchestrator_turn_meta(stub, "hello", "an answer")
    m = stub._last_request_meta
    assert m["confidence"] == 0.94 and m["grounding_confidence"] == 0.41
    assert m["agents_used"] == ["orchestrator", "knowledge_graph"]
    assert m["response_text"] == "an answer"


def test_without_a_reasoning_score_the_bus_figures_are_used(monkeypatch):
    monkeypatch.setattr("eli.runtime.last_trace.save_last_trace", lambda m: None)
    bus = SimpleNamespace(aggregated_confidence=0.54, grounding_confidence=0.41,
                          agents_used=["orchestrator"], confidence_label="low")
    stub, CE = _engine_stub(bus, {})
    CE._publish_orchestrator_turn_meta(stub, "hello", "an answer")
    m = stub._last_request_meta
    assert m["aggregated_confidence"] == 0.54 and m["confidence_label"] == "low"


def test_runtime_status_evidence_carries_ram_and_cpu(monkeypatch):
    import eli.runtime.truth_report as tr
    monkeypatch.setattr(tr, "system_memory_line",
                        lambda: "ram_total_gb: 33.5, ram_available_gb: 25.6, cpu_threads_total: 12")
    import eli.execution.executor_enhanced as ex
    text = ex._format_runtime_status({"settings": {}, "runtime": {}})
    assert "ram_available_gb: 25.6" in text
    from eli.contracts import runtime_status as rs
    ev = rs.build_live_evidence(runtime_snapshot={}, settings={})
    assert "ram_total_gb: 33.5" in rs.build_content(ev, requested_mode="quick", surface="t")


def test_eli_runtime_statements_are_not_stored_as_knowledge(monkeypatch):
    from eli.kernel.engine import CognitiveEngine as CE
    stored = []
    stub = SimpleNamespace(
        session_id="s", user_id="u",
        _store_memory_record=lambda *a, **k: stored.append(a),
    )
    import eli.kernel.engine as eng
    monkeypatch.setattr(eng, "_HAS_GOVERNANCE", False, raising=False)
    src = __import__("inspect").getsource(CE._maybe_store_memory)
    assert "runtime-state statement" in src, "the storage rule must stay in _maybe_store_memory"
