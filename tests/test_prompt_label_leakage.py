"""Prompt section labels must never be spoken as output.

Live on eli-finetuned-phi3, an entire reply was the two literal lines
"FINAL INSTRUCTION:" / "I am operating as intended." — the label is scaffolding
written into the PROMPT by context_synthesiser, echoed back verbatim, exposing
ELI's internal prompt structure as if it were speech.
"""
import re

import eli.cognition.context_synthesiser as cs
from eli.cognition.output_governor import (
    _PROMPT_SECTION_LABELS,
    _PROMPT_SECTION_LABEL_RX,
)


def test_the_observed_leak_is_stripped():
    out = "FINAL INSTRUCTION:\nI am operating as intended."
    assert _PROMPT_SECTION_LABEL_RX.sub("", out).lstrip() == "I am operating as intended."


def test_every_label_is_covered():
    for label in _PROMPT_SECTION_LABELS:
        assert _PROMPT_SECTION_LABEL_RX.search(f"{label}:\nsomething"), label


def test_ordinary_prose_is_left_alone():
    """The filter must not eat normal sentences that happen to use the words."""
    for keep in ("The final instruction: be brief.",
                 "I checked the grounded facts: all three hold.",
                 "Recent dialogue suggests otherwise."):
        assert _PROMPT_SECTION_LABEL_RX.sub("", keep) == keep, keep


def test_the_list_matches_what_the_synthesiser_actually_writes():
    """If a new section label is added to the prompt, it must be covered here."""
    import inspect
    src = inspect.getsource(cs)
    emitted = set(re.findall(r'"\\n([A-Z][A-Z ]{4,}):', src))
    missing = emitted - set(_PROMPT_SECTION_LABELS)
    assert not missing, f"new prompt labels not covered by the leak filter: {sorted(missing)}"


def test_crlf_text_is_stripped_too():
    """Windows line endings must not smuggle the label through."""
    out = "FINAL INSTRUCTION:\r\nI am operating as intended."
    assert _PROMPT_SECTION_LABEL_RX.sub("", out).lstrip() == "I am operating as intended."
