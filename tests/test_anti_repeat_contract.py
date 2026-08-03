"""ELI must be told, in the prompt, not to repeat what it has already said.

Three live loops, three different phrasings — "still glitchy, still running on the same
old code", then "post-breakfast haze and Rick and Morty on repeat" — each re-asking
"How are you?" after the user had answered, and continuing even after being told to
stop. Purging the text doesn't help: the mechanism just latches onto a new phrase.

The output-side echo guard cannot fire on the streaming path (it lives in finalize,
which streaming never reaches), so the contract has to be stated in the prompt, where
it applies to every path. This tests the block the engine appends after chat history.
"""
from __future__ import annotations

LOOP = ("I'm standing by, still got that post-breakfast haze and Rick and Morty "
        "on repeat. Everything's fine. How are you?")


def _build_contract(conversations):
    """Mirror of the engine's anti-repeat block (kernel/engine.py, chat-history build)."""
    said = [str(t.get("content") or "").strip()
            for t in conversations
            if str(t.get("role") or "").lower() in ("assistant", "eli")
            and str(t.get("content") or "").strip()]
    if not said:
        return ""
    quoted = "\n".join(f"  - {s[:220]}" for s in said[:3])
    return ("YOU HAVE ALREADY SAID THE FOLLOWING — do not repeat any of it, and do not "
            "re-ask a question the user has already answered:\n" + quoted +
            "\nRespond to what the user just said. If you have already described your own "
            "state or mood, do not describe it again unless they ask.")


def test_contract_is_emitted_when_eli_has_spoken():
    convo = [{"role": "assistant", "content": LOOP}, {"role": "user", "content": "yo"}]
    c = _build_contract(convo)
    assert "ALREADY SAID" in c
    assert "post-breakfast haze" in c          # the exact line is quoted back
    assert "re-ask a question" in c            # covers the repeated "How are you?"


def test_contract_absent_on_a_fresh_conversation():
    assert _build_contract([{"role": "user", "content": "yo"}]) == ""
    assert _build_contract([]) == ""


def test_contract_quotes_at_most_three_and_truncates():
    convo = [{"role": "assistant", "content": f"{LOOP} #{i}"} for i in range(6)]
    c = _build_contract(convo)
    assert c.count("  - ") == 3               # bounded, so it can't bloat the prompt
    for line in [l for l in c.splitlines() if l.startswith("  - ")]:
        assert len(line) <= 226


def test_user_turns_are_not_quoted_back_as_elis_own():
    convo = [{"role": "user", "content": "I am tired and had breakfast"},
             {"role": "assistant", "content": LOOP}]
    c = _build_contract(convo)
    assert "I am tired" not in c
