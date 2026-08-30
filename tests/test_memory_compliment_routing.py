"""Memory compliment vs internals audit — router must not dump counts on praise."""
from __future__ import annotations

import pytest

from eli.execution.router_enhanced import route


@pytest.mark.parametrize("text", [
    "haha scary how well your memory is working",
    "scary how well your memory is working",
    "your memory is working really well",
    "good job remembering all that",
    "impressive how well you remember things",
])
def test_memory_compliment_stays_chat_not_internals_dump(text):
    out = route(text)
    assert out["action"] != "EXPLAIN_MEMORY_RUNTIME", (
        f"compliment {text!r} must not route to memory internals audit"
    )


@pytest.mark.parametrize("text", [
    "how does your memory work",
    "explain how memory recall and storage works",
    "walk me through your memory pipeline",
    "how many memories do you have",
])
def test_explicit_memory_internals_still_route(text):
    out = route(text)
    assert out["action"] in {
        "EXPLAIN_MEMORY_RUNTIME",
        "PERSONAL_MEMORY_DEEP_EXPLAIN",
        "MEMORY_STATUS",
    }, f"technical query {text!r} should reach memory introspection"


def test_correction_after_data_dump_routes_to_chat():
    out = route("answer properly, i did not ask for a data dump")
    assert out["action"] == "CHAT"
    assert out.get("meta", {}).get("matched_by") == "router.correction_chat"
