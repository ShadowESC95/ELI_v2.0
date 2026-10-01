"""Regression: "evaluate this document" on a non-PDF attachment came back as
a generic summary. Root cause was in the router, not the summarizer —
SUMMARIZE_FILE's dispatch only ever sent {"path": ...}, dropping the user's
actual instruction entirely (ANALYZE_PDF's dispatch, right next to it, always
included "instruction": raw). _summarize_long_text already falls back to a
hardcoded "Summarize the following file content." whenever instruction is
empty, so every non-PDF attachment got that fallback regardless of what was
actually asked.
"""
from eli.execution.router_enhanced import route


def test_evaluate_request_on_a_docx_keeps_the_real_instruction(tmp_path):
    f = tmp_path / "answers.docx"
    f.write_bytes(b"not a real docx, just needs to exist")
    text = f"evaluate {f}"

    result = route(text)

    assert result["action"] == "SUMMARIZE_FILE"
    assert result["args"].get("instruction") == text, (
        "the raw request must reach the summarizer, not get silently dropped"
    )


def test_known_eli_file_lookup_also_keeps_the_instruction(monkeypatch):
    import eli.execution.router_enhanced as rr
    monkeypatch.setattr(rr, "_eli_resolve_known_eli_file", lambda low: "/fake/persona.auto.txt")

    text = "is your persona.auto.txt up to date? read it"
    result = route(text)

    assert result["action"] == "SUMMARIZE_FILE"
    assert result["args"].get("instruction") == text
