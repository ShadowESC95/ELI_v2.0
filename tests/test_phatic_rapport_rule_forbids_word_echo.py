"""A real session showed Qwen2.5-7B-Instruct opening a phatic reply by directly reusing the
user's own sentence back at them:

    user> Is there any other day? Can't lt the day slip! Just woke up ja;f an hour ago, GOT is
          on in the bckground, and i am just checking in on you
    ELI>  Is there any other day? Pfft, you're still in the morning, technically. Just woke up
          myself an hour ago, GOT is on in the background too, so we're both fresh starts here.

The phatic rapport style rule told the model to "Mirror their energy" two lines above a line
FORBIDDING "empty mirroring" — a self-contradiction a stronger model can resolve (match the mood,
not the words) but a 7B model apparently cannot. The rule now says "match their MOOD" and
explicitly forbids reusing the user's own words/phrases/openings, with no "mirror" language left
to misread literally.
"""
from eli.kernel.engine import _phatic_rapport_style_rule


def test_the_rule_does_not_use_the_word_mirror():
    # "Mirror" was the literal word a weak model could take as "copy their text".
    assert "mirror" not in _phatic_rapport_style_rule().lower()


def test_the_rule_explicitly_forbids_reusing_the_users_own_words():
    rule = _phatic_rapport_style_rule().lower()
    assert "reusing the user's own words" in rule or "reusing the user" in rule


def test_the_rule_still_asks_for_mood_matching_not_word_copying():
    rule = _phatic_rapport_style_rule().lower()
    assert "match their mood" in rule
    assert "not their words" in rule
