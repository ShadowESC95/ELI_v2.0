"""Locks on the 2.1.81 live session (18:55–18:57).

Mid-conversation about Oblivion and Fallout, "what have you been doing?" was
answered with the raw grounded self-report evidence block — git/runtime fields,
and then this, verbatim, as ELI's reply to a friend making conversation:

    Grounding rule: if an update/check is not listed above, ELI must not claim
    it happened.

Three separate defects in one answer:

1. **Routing.** "what have you been doing" was an unconditional match for the
   recent-updates contract at confidence 0.995 with ``forbid_chat_fallback``.
   The phrase is genuinely ambiguous — it is the maintenance question when the
   subject is the code, and small talk otherwise.

2. **The instruction leaked.** The grounding rule is written FOR the model. It
   was appended to ``content``, which is returned as ``response``, so it could
   only ever reach the user.

3. **The report read the wrong root.** ``Path(__file__).parents[2]`` resolves
   inside the read-only AppImage mount, so every runtime field printed None
   ("model_name: None, loaded: None") in a session whose log shows the model
   loaded and the snapshot written to ~/.local/share/ELI_v2/artifacts/ — and a
   failed ``git status --short`` in a directory that is not a repository was
   rendered as the positive claim "clean according to git status --short".
"""
import pytest

from eli.execution.router_enhanced import route
from eli.execution.executor_enhanced import execute


# ── 1. the same words, two different questions ──────────────────────────────
@pytest.mark.parametrize("asked", [
    "what have you been doing?",
    "what have you been doing",
    "so what have you been doing lately",
    "what have you been up to?",
    "what have you been working on today?",
    "what you been up to",
])
def test_conversational_activity_question_stays_in_chat(asked):
    assert route(asked)["action"] == "CHAT", asked


@pytest.mark.parametrize("asked", [
    "what have you been doing to the code?",
    "what have you been working on in the repo since the last commit?",
    "what have you checked recently?",
    "what have you updated?",
    "what recent updates have you made, eli?",
    "Tell me about yourself, eli. What updates and checks have been performed as of late?",
])
def test_maintenance_question_still_reaches_the_grounded_report(asked):
    r = route(asked)
    assert r["action"] == "SELF_REPORT", asked
    assert r["args"]["self_report_scope"] == "recent_updates"
    assert r["meta"]["forbid_chat_fallback"] is True


# ── 2. the model-facing instruction is not the answer ───────────────────────
def _report():
    return execute("SELF_REPORT", {
        "question": "what have you been doing to the code?",
        "self_report_scope": "recent_updates",
    })


def test_grounding_instruction_never_appears_in_the_visible_reply():
    out = _report()
    for surface in (out["content"], out["response"]):
        assert "Grounding rule:" not in surface
        assert "must not claim it happened" not in surface


def test_grounding_rule_survives_where_the_model_can_use_it():
    assert "must not claim it happened" in _report()["report"]["policy"]["grounding_rule"]


def test_the_visible_reply_is_still_the_evidence():
    """Trimming the instruction must not gut the report itself."""
    txt = _report()["content"]
    assert "Grounded ELI self-report / recent update evidence:" in txt
    assert "Recent Git updates:" in txt
    assert "Runtime snapshot:" in txt
    assert "Working tree status:" in txt


# ── 3. the report reads the canonical root, and never claims "clean" blind ──
def test_runtime_snapshot_is_read_from_the_canonical_artifacts_dir(tmp_path, monkeypatch):
    """The snapshot the loader writes must be the snapshot the report reads."""
    import json
    from eli.core.paths import get_paths

    artifacts = get_paths().artifacts_dir
    artifacts.mkdir(parents=True, exist_ok=True)
    snap = artifacts / "runtime_snapshot.json"
    original = snap.read_text(encoding="utf-8") if snap.exists() else None
    snap.write_text(json.dumps({
        "model_name": "sentinel-model.gguf",
        "loaded": True,
        "effective": {"n_ctx": 4321, "n_gpu_layers": 7, "n_threads": 3, "n_batch": 64},
    }), encoding="utf-8")
    try:
        txt = _report()["content"]
        assert "sentinel-model.gguf" in txt
        assert "ctx=4321" in txt
        assert "model_name: None" not in txt
    finally:
        if original is None:
            snap.unlink(missing_ok=True)
        else:
            snap.write_text(original, encoding="utf-8")


def test_missing_git_is_reported_as_missing_not_as_clean(monkeypatch):
    """A packaged build has no repo; "clean" would be a claim about a tree that
    isn't there."""
    import eli.execution.executor_enhanced as ex

    real_run = ex.subprocess.run

    def _no_git(cmd, *a, **kw):
        if cmd and cmd[0] == "git":
            class _P:
                returncode = 128
                stdout = ""
                stderr = "fatal: not a git repository"
            return _P()
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(ex.subprocess, "run", _no_git)
    txt = _report()["content"]
    assert "clean according to git status --short" not in txt
    assert "no git repository in this build" in txt
    assert "packaged build" in txt
