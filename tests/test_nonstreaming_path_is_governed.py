"""The non-streaming reply path must be governed too.

The streaming path had its own choke point; this loop did not. It served
roughly a third of live turns straight out of _get_chat_response, so every
output guard -- invented health, invented runtime state, invented internals,
leaked prompt labels -- was simply absent from those replies. Live at 2.3.27
"I'm still running on fumes" reached the user this way, while the MEMORY side
correctly refused to store the same sentence: the asymmetry was the clue.

The call cannot live inside _get_chat_response, which also produces private
reasoning and internal summaries -- those are not speech and must not be
governed as if they were.
"""
import re
from pathlib import Path


def _loop_source():
    import eli.cognition.output_governor as og
    root = Path(og.__file__).resolve().parents[2]
    for rel in ("eli/kernel/engine.py", "eli/kernel/stages/reasoning_modes.py"):
        f = root / rel
        if f.is_file():
            t = f.read_text(encoding="utf-8")
            if "_score_response_confidence" in t and "chat_pass_" in t:
                return t
    raise AssertionError("reasoning loop not found under %s" % root)


def test_the_loop_governs_before_scoring():
    src = _loop_source()
    i_gov = src.index("response = govern_output(")
    # Search FORWARD from the governor: there are other scoring sites earlier
    # in the file, and searching backwards found one of those instead.
    i_score = src.index("score = self._score_response_confidence(", i_gov)
    assert i_score - i_gov < 1200, (
        "the response is scored before it is governed; confidence would "
        "describe text the user never receives")


def test_the_governor_is_actually_importable_there():
    """A missing import would be swallowed by the guard's own except clause."""
    src = _loop_source()
    assert "from eli.cognition.output_governor import govern_output" in src, (
        "govern_output is not imported in the module that calls it - the "
        "NameError would be caught and governing would silently never run")


def test_it_is_not_pushed_into_the_shared_helper():
    """_get_chat_response also produces private reasoning; it must stay raw."""
    src = _loop_source()
    m = re.search(r"def _get_chat_response\(.*?(?=\n    def )", src, re.S)
    if m:
        assert "govern_output" not in m.group(0), (
            "the shared helper governs its own output, which would also "
            "rewrite private reasoning and internal summaries")
