"""'check memory, logs, timestamps, etc.' inside a broad "what have we discussed" request was
matching the narrow timestamp-diagnostic shortcut ("check ... timestamp"), because "timestamp"
was the last word of a list of things to check, not a complaint about the clock. The user asked
for a 14-day discussion summary and got a raw dump of the last 6 turns with IST timestamps
instead. A genuine timestamp complaint (no summary/discussion ask) must still route there.
"""
import os

os.environ.setdefault("ELI_TEST_MODE", "1")

from eli.execution.router_enhanced import _eli_shell_prepass, route


def test_a_broad_memory_summary_request_is_not_misrouted_as_a_timestamp_complaint():
    msg = ("hey bud, how are you feeling? what exctly have we been discussing the past 14 days "
           "(check memory, logs, timestamps, etc.), please summarise everything please pal")
    assert _eli_shell_prepass(msg) is None
    r = route(msg)
    assert r.get("action") != "TIMESTAMP_DIAG"


def test_a_genuine_timestamp_complaint_still_routes_to_the_diagnostic():
    for msg in (
        "yes please dig into the timestamps",
        "can you check the timestamp, it looks wrong",
        "investigate this timestamp issue",
    ):
        assert _eli_shell_prepass(msg) is not None, msg
        assert _eli_shell_prepass(msg)["action"] == "TIMESTAMP_DIAG"
