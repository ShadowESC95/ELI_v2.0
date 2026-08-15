"""Truncation trim + false-self-denial guard.

Both regressions came from one live transcript: a quick-mode profile report that
shipped ending on a bare "-", and — when the user pushed back — ELI retracting its
own DB-backed recall as "likely a hallucination / I have no access to your data".
"""
import pytest

from eli.cognition.output_governor import _looks_truncated, trim_dangling_fragment, govern_output
from eli.runtime.control_contracts import output_violates_evidence


# ── Dangling-fragment detection ───────────────────────────────────────────────
@pytest.mark.parametrize("tail", ["-", "*", "+", "•", "1.", "2)", "#", "###"])
def test_orphan_list_marker_is_truncation(tail):
    """The observed failure: token cap hit just as the next bullet opened."""
    assert _looks_truncated(f"- Humor: accepted\n- Errors: direct\n{tail}")


def test_complete_answer_is_not_truncation():
    assert not _looks_truncated("Here is the full answer. Nothing is missing.")
    assert not _looks_truncated("- one\n- two\n- three is complete.")


def test_midword_cut_still_detected():
    assert _looks_truncated("This sentence runs on for a good while and then just sto")


def test_empty_is_not_truncation():
    assert not _looks_truncated("")
    assert not _looks_truncated("   ")


# ── Trimming ──────────────────────────────────────────────────────────────────
def test_trim_removes_orphan_marker():
    out = trim_dangling_fragment("- Humor: accepted\n- Errors: direct\n-")
    assert out == "- Humor: accepted\n- Errors: direct"


def test_trim_removes_several_orphans():
    assert trim_dangling_fragment("- real content\n-\n*\n1.") == "- real content"


def test_trim_leaves_complete_text_alone():
    txt = "- one\n- two\n- three."
    assert trim_dangling_fragment(txt) == txt


def test_trim_never_empties_a_bare_marker_only_answer():
    """All-markers input must not become empty — fall back to the original."""
    assert trim_dangling_fragment("-").strip()


def test_govern_output_trims_in_every_mode():
    """govern_output runs on quick too, where the re-generation repair does not."""
    got = govern_output("- Humor: accepted\n- Assumption handling: state uncertainties\n-")
    assert got.splitlines()[-1] == "- Assumption handling: state uncertainties"
    assert not _looks_truncated(got)


# ── False self-denial ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("denial", [
    "I don't have access to your personal files.",
    "It was likely a hallucination.",
    "I have no hidden access to your life.",
    "I only see the text in this window.",
    "I have no memory of previous conversations.",
])
def test_disowning_real_memory_is_a_violation(denial):
    """Retracting DB-backed recall as a hallucination is as bad as inventing one."""
    assert output_violates_evidence(denial, "memory_entries: name=alex")


def test_standing_behind_a_stored_fact_is_allowed():
    assert not output_violates_evidence("Your stored name is alex.", "name=alex")


def test_correcting_one_field_is_allowed():
    assert not output_violates_evidence(
        "The name field says alex — if that's wrong, tell me and I'll update it.",
        "name=alex")
