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


def test_a_named_eli_file_is_the_one_in_force_not_one_in_the_program_folder(tmp_path, monkeypatch):
    """A packaged install keeps the persona overlay and the settings in its config folder; the router
    looked for them only beside the code, never found them there, and the question fell to CHAT."""
    overlay = tmp_path / "config" / "persona.auto.txt"
    settings = tmp_path / "config" / "settings.json"
    overlay.parent.mkdir()
    overlay.write_text("# overlay\n", encoding="utf-8")
    settings.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ELI_PERSONA_AUTO_PATH", str(overlay))
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings))

    assert route("is your persona.auto.txt up to date? read it")["args"]["path"] == str(overlay)
    assert route("what's in your settings file")["args"]["path"] == str(settings)
