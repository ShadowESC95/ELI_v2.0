"""ELI's runtime status lines are not steps it offered to take.

Live: after the status dump, "provider: gguf" was stored as the offer a "yes" would run.
"""
from eli.runtime import pending_proposal as pp

DUMP = """Runtime status evidence:

Identity:
- name: ELI / Enhanced Learning Interface

Effective runtime:
- provider: gguf
- model_name: Qwen2.5-7B-Instruct-Q4_K_M.gguf
- context_size: 16128

Requested vs loaded:
- loaded_below_request: GPU layers: requested 28, loaded 26
"""


def test_a_status_dump_offers_nothing():
    assert pp.actionable_items(DUMP) == []


def test_a_list_of_steps_still_does():
    steps = "Here's what I can do:\n1. Check your calendar for tomorrow\n2. Pause the music\n"
    assert [i.get("action") for i in pp.actionable_items(steps)] == ["LIST_EVENTS", "MEDIA_CONTROL"]


def test_the_status_report_itself_is_never_an_offer():
    assert not pp._offerable("RUNTIME_STATUS")
