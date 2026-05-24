def test_recent_updates_routes_to_grounded_self_report():
    from eli.execution.router_enhanced import route

    r = route("Tell me about yourself, eli. What updates and checks have been performed as of late?")

    assert r["action"] == "SELF_REPORT"
    assert r["args"]["self_report_scope"] == "recent_updates"
    assert r["meta"]["grounded_required"] is True
    assert r["meta"]["forbid_chat_fallback"] is True


def test_recent_updates_executor_surface_is_grounded():
    from eli.execution.executor_enhanced import execute

    out = execute(
        "SELF_REPORT",
        {
            "question": "Tell me about yourself, eli. What updates and checks have been performed as of late?",
            "self_report_scope": "recent_updates",
        },
    )

    txt = out["content"]

    assert out["evidence_source"] == "self_report_recent_updates_git_runtime"
    assert "Grounded ELI self-report / recent update evidence:" in txt
    assert "Recent Git updates:" in txt
    assert "Runtime snapshot:" in txt
    assert "Grounding rule:" in txt

    forbidden = [
        # Personal profile data that must never appear in ELI's self-report:
        "Spotify once",
        "3 rewired",
        "usual nutty self",
        "digital hoarder",
        # Note: technical filenames (e.g. "user_profile.json") are permitted
        # because they may appear in grounded git commit messages.
    ]
    for bad in forbidden:
        assert bad not in txt
