"""The longitudinal memory benchmark gates every memory change: no scenario may regress."""
import pytest

from eli.runtime.persistence_gate import is_chatter, should_store_memory_text  # real ones, bound before any test stubs them
from tools.eval import memory_bench


@pytest.mark.parametrize("name", list(memory_bench.SCENARIOS))
def test_scenario(name):
    result = memory_bench.run([name])[name]
    assert result["passed"], result["note"]


@pytest.mark.parametrize("text", ["haha", "lol that is funny", "hello there", "ok cool got it"])
def test_chatter_never_becomes_durable_knowledge(text):
    assert is_chatter(text) and should_store_memory_text(text) is False


@pytest.mark.parametrize("text", ["I work nights now", "my dog is called Max", "The meeting is at 5 tomorrow", "No, Tuesday not Wednesday"])
def test_short_meaningful_statements_survive(text):
    assert not is_chatter(text)
