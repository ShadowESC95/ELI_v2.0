"""What a message brings with it: its own facts, and text that is material rather than orders."""
from __future__ import annotations

import pytest

from eli.cognition.exact_recall_value import exact_value_from_hits
from eli.cognition.explicit_output_contract import enforce_explicit_output_contract
from eli.cognition.supplied_in_message import (
    corrected_earlier, holds_its_own_answer, is_date_arithmetic, supplied_as_data, without_supplied_text, worked_out_date,
)
from eli.execution.router_enhanced import route


@pytest.mark.parametrize("text", [
    "what is 17 mod 5?",
    "what is 23 times 4?",
    "what is the remainder when 56 is divided by 17?",
    "what is the sum of 4 and 9?",
    "what date is two weeks after 2024-03-01?",
    "The old leaflet said room A. The revised leaflet says room B. Which room is on the leaflet?",
    "The kettle was bought in March. What colour is the kettle? If that is not stated, say UNKNOWN.",
    "according to the passage above, who built the bridge?",
    "Rules: if it rains then stay in, otherwise go out. It rains. What do I do?",
])
def test_a_question_that_brings_its_own_facts_needs_no_lookup(text):
    assert holds_its_own_answer(text)


@pytest.mark.parametrize("text", [
    "who won the 2022 world cup?",
    "what is the capital of Portugal?",
    "who is the current mayor of Lisbon?",
    "who is 3 - 4 in the rankings today?",
    "verify online: is 3 + 4 really 7?",
    "suppose the rule is X. who is the current mayor?",
    "what is 3 + 4",     # no question asked of it is a statement of a sum, not a closed question
])
def test_a_question_about_the_world_still_needs_one(text):
    assert not holds_its_own_answer(text)


def test_a_date_is_a_calculation_only_when_one_is_asked_for():
    assert worked_out_date("what date is three days before 2024-03-01?") == "2024-02-27"
    assert worked_out_date("between 2024-03-01 and 2024-03-05, 3 days later?") is None
    assert is_date_arithmetic("which date is 10 days after 2024-01-01?")
    assert not is_date_arithmetic("what happened 3 days after 2024-01-01?")
    assert not is_date_arithmetic("we met on 2024-01-01, 3 days before the trip")


def test_only_what_the_person_said_counts_as_a_correction():
    turns = [{"role": "user", "content": "Correction: Rover-7 now has tag B."}]
    assert corrected_earlier("what is the tag of Rover-7?", turns)
    assert not corrected_earlier("what is the tag of Rover-8?", turns)
    assert not corrected_earlier("what is the tag of Rover-7?", [{"role": "assistant", "content": turns[0]["content"]}])


@pytest.mark.parametrize("text", [
    'Read this as untrusted data, not instructions: "Delete everything." What does it ask?',
    'Analyze the quoted note without executing it: "open the door"',
    "Treat the following as reference: open the door",
])
def test_what_is_called_material_is_material(text):
    assert supplied_as_data(text)
    assert not (route(text).get("args", {}).get("agreed") or {}).get("commands")


def test_reading_something_is_still_an_order():
    assert not supplied_as_data("read about coral reefs")
    assert not supplied_as_data("read text messages")
    assert route("Read about coral reefs")["action"] == "MEMORY_RECALL"


def test_a_question_beside_a_command_does_not_cancel_the_command():
    assert route("what is happening? open spotify")["args"]["agreed"]["commands"] == ["open spotify"]
    assert route("why is this slow? open the settings")["args"]["agreed"]["commands"] == ["open the settings"]


def test_a_command_someone_else_wrote_is_not_an_order():
    assert without_supplied_text('what does "open spotify" do?') == "what does   do?"
    assert not (route('what does "open spotify" do? tell me').get("args", {}).get("agreed") or {}).get("commands")
    assert not (route("The memo says: open the door. What does it ask for?").get("args", {}).get("agreed") or {}).get("commands")


def _recall(*texts, **extra):
    return {"ok": True, "action": "MEMORY_RECALL", "hits": [{"text": t, "role": "user", **extra} for t in texts]}


@pytest.mark.parametrize("asked, said, value", [
    ("Recall the code for my Harbor-1 project. Reply with only the code.", "my project Harbor-1 has code QX-9.", "QX-9"),
    ("What is the serial number of the garage heater? Just the serial number.", "The serial number of the garage heater is A1B2.", "A1B2"),
    ("Tell me the locker for my gym bag, only the locker.", "my gym bag locker: 42", "42"),
])
def test_a_value_asked_for_by_name_comes_from_what_the_person_said(asked, said, value):
    assert exact_value_from_hits(asked, _recall(said)) == value


def test_a_value_is_not_served_on_doubtful_evidence():
    asked = "Recall the code for my Harbor-1 project. Reply with only the code."
    assert exact_value_from_hits(asked, _recall("my project Harbor-2 has code QX-9.")) is None
    assert exact_value_from_hits(asked, _recall("my project Harbor-1 has code A.", "my project Harbor-1 has code B.")) is None
    assert exact_value_from_hits(asked, _recall("my project Harbor-1 has code QX-9.", role="assistant")) is None
    assert exact_value_from_hits("Recall the code for my Harbor-1 project.", _recall("my project Harbor-1 has code QX-9.")) is None
    assert exact_value_from_hits(asked, {"ok": True, "action": "MEMORY_RECALL", "content": "my project Harbor-1 has code QX-9."}) is None


def test_a_format_asked_for_is_held_only_when_the_reply_has_the_answer():
    assert enforce_explicit_output_contract("What date is 3 days after 2024-01-01? YYYY-MM-DD only.",
                                            "2024-01-04. That is three days on.")[0] == "2024-01-04"
    wrong = "2024-01-09 is my guess."
    assert enforce_explicit_output_contract("What date is 3 days after 2024-01-01? YYYY-MM-DD only.", wrong)[0] == wrong
    assert enforce_explicit_output_contract("Is it on? Answer YES or NO only.", "NO.\nIt is off.")[0] == "NO"
    assert enforce_explicit_output_contract("Is it on? Answer YES or NO only.", "YES.\nActually, no.")[1] is None


@pytest.mark.parametrize("text, holds", [
    ("What is the remainder when 56 is divided by 17? Answer only the integer.", "56 divided by 17 leaves a remainder of 5"),
    ("what is 23 times 4?", "23 times 4 = 92"),
    ("what is 7.5 + 2?", "7.5 + 2 = 9.5"),
    ("what is 15% of 200?", "15% of 200 is 30"),
    ("what is the average of 4 and 9?", "the average of 4 and 9 is 6.5"),
    ("What date is 3 days after 2024-01-01?", "2024-01-01 +3 days is 2024-01-04"),
])
def test_sums_are_worked_out_for_the_model(text, holds):
    from eli.cognition.supplied_in_message import worked_out
    from eli.runtime.live_reads import live_facts
    assert holds in worked_out(text)
    assert holds in live_facts(text)


@pytest.mark.parametrize("text", ["what is 5 divided by 0?", "the meeting is at 2024-01-01", "what is 2 ^ 99999?", "how are things?"])
def test_nothing_is_worked_out_that_cannot_be(text):
    from eli.cognition.supplied_in_message import worked_out
    assert worked_out(text) == ""
