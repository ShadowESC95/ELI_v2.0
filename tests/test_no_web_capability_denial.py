"""Locks against ELI disowning its own web access.

Observed live: a WEB_SEARCH executed successfully — five results, `web_grounded:
True`, grounding 0.98 — and the reply generated from it opened with

    "I don't have internet access. I am a local, private AI running on this
     machine, with no external connectivity or web search capabilities."

Two causes, both fixed here. The verified-self-facts block listed version,
databases, capability count, components and upgrade path but said *nothing* about
network reach, and that silence was not neutral: told only that it is a local,
private assistant, the model inferred it therefore had no internet. And the
self-description repair guard only checked paths and upgrade scripts, so a false
denial passed through untouched.

Disowning a real capability is the same class of defect as inventing one, and
worse in practice — it teaches the user not to ask again.
"""
import re

import pytest

from eli.runtime import self_facts
from eli.runtime.self_facts import (
    get_self_facts,
    render_self_facts_block,
    repair_self_description,
)

# The exact reply from the transcript.
LIVE_FAILURE = (
    "Yes. Here's why.\n\nI don't have internet access. I am a local, private AI "
    "running on this machine, with no external connectivity or web search "
    "capabilities. My knowledge is derived from the data stored in my SQLite "
    "databases and vector index — nothing more."
)
EARLIER_FAILURE = (
    "I am a local AI with no internet access, so checking the web is not an option. "
    "My memory consists of SQLite stores, vector index, and knowledge graph."
)


# ── the fact must exist, and be read from the live policy ───────────────────
def test_network_reach_is_a_verified_self_fact():
    assert get_self_facts().get("network"), (
        "the brief must state ELI's network reach; its absence is what the model "
        "filled in with 'no internet access'"
    )


def test_network_fact_reaches_the_persona_brief():
    """get_self_facts() carrying it is not enough — the renderer has an explicit
    key list, and a fact it does not render never reaches the model."""
    block = render_self_facts_block(include_canon=False)
    assert re.search(r"web access is currently (ON|OFF)", block)


@pytest.mark.parametrize("blocked,expect", [(True, "OFF"), (False, "ON")])
def test_network_fact_follows_the_live_netguard_state(monkeypatch, blocked, expect):
    monkeypatch.setattr("eli.core.netguard.should_block_network", lambda: blocked)
    fact = self_facts._network_reach()
    assert expect in fact
    # Even switched off, it must not read as "ELI cannot do this at all".
    assert "CAN search the web" in fact or "can search the web" in fact


# ── and the denial must be repaired if it is emitted anyway ─────────────────
@pytest.mark.parametrize("bad", [LIVE_FAILURE, EARLIER_FAILURE])
def test_web_denial_is_corrected(bad):
    out, corrections = repair_self_description(bad)

    assert corrections, "a denial of web access must be corrected"
    assert not re.search(r"(?i)(?:do\s*n[o']t|don'?t)\s+have\s+internet", out)
    assert "no external connectivity" not in out.lower()


def test_repair_leaves_no_sentence_fragments():
    """Substituting inside a sentence produced wreckage like '…egress ledger
    access.' — the denial is rarely one contiguous span."""
    out, _ = repair_self_description(LIVE_FAILURE)

    for sentence in [s.strip() for s in out.split(".") if s.strip()]:
        assert not sentence.lower().startswith(("access", "connectivity", "capabilities"))


def test_surrounding_content_survives_the_repair():
    """The reply still has to answer what it was answering."""
    out, _ = repair_self_description(LIVE_FAILURE)
    assert "SQLite" in out


# ── a TRUTHFUL statement about being offline must not be rewritten ──────────
def test_truthful_offline_statement_is_left_alone():
    """When the Net toggle really is off, saying so is correct — the guard targets
    the absolute denial, not an accurate report of current state."""
    honest = ("Web access is currently off, so I did not search. Turn the Net "
              "toggle on and ask me again.")

    out, corrections = repair_self_description(honest)

    assert out == honest
    assert not corrections


def test_unrelated_replies_are_untouched():
    plain = "Your databases live under artifacts/db and hold your preferences."
    out, corrections = repair_self_description(plain)
    assert out == plain and not corrections


def test_guard_is_cheap_on_ordinary_replies():
    """It sits on every reply, so it must bail out before building the fact set."""
    out, corrections = repair_self_description("Playing that on Spotify now.")
    assert out == "Playing that on Spotify now." and not corrections
