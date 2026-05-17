from __future__ import annotations


def test_hybrid_memory_question_classifies_as_personal_deep_explain():
    from eli.execution.route_contracts import classify_precedence_route

    r = classify_precedence_route(
        "Explain exactly how your memory system works internally — which files, "
        "which DB tables, which functions and what you actually remember about me. "
        "We are not in quick mode."
    )

    assert r is not None
    assert r["action"] == "PERSONAL_MEMORY_DEEP_EXPLAIN"
    assert r["meta"]["task_family"] == "personal_memory"


def test_pure_memory_internals_not_stolen_by_personal_deep_contract():
    from eli.execution.route_contracts import classify_precedence_route

    r = classify_precedence_route(
        "Explain exactly how your memory system works internally — which files, which DB tables, which functions."
    )

    assert r is None


def test_pure_personal_memory_not_stolen_by_hybrid_contract():
    from eli.execution.route_contracts import classify_precedence_route

    r = classify_precedence_route(
        "What do you know about me from memory? Give me everything."
    )

    assert r is None
