"""Small talk is where ELI invents things, because nothing was watching it.

All four defects below come from one live evening conversation on 2.3.19 --
a conversation with no task in it at all. Every existing guard fires on TASK
turns, where an action routes and evidence is gathered. Casual turns route to
CHAT with no evidence, so they were the one ungoverned surface.

  1. ELI opened with "all systems nominal - no glitches detected in the last
     12 hours". There is no twelve-hour glitch check; nothing ran. The user's
     next message was "well that is not entirely true, we just sorted out an
     issue with your gpu acceleration".
  2. It then told the user to "run the full acceleration diagnostics again,
     and I'll flag any lingering hiccups" -- ELI owns RUNTIME_AUDIT,
     SELF_TEST and SELF_ANALYZE. It asked the operator to do its job.
  3. It ran RUNTIME_AUDIT anyway, the audit found a REAL defect (a duplicate
     top-level _first_sentence in engine.py), and the follow-through gate
     suppressed the whole thing. The promise to flag hiccups was broken by
     the machinery that found one.
  4. Asked what it was doing that evening it answered "the plan for the
     evening is to chill out, get some weed, and maybe play Fallout 4" --
     the USER's life, read back out of memory in the first person. Two turns
     later it said "I'm not planning anything", contradicting itself.

The persona is deliberately NOT the target here. ELI joking, teasing and
having opinions all survive; only claims that are factually false for a piece
of software are removed.
"""
from pathlib import Path

import pytest

from eli.cognition import output_governor as og
from eli.kernel.engine import _ft_summarise_findings, _first_sentence


# ── 1. invented self-status ────────────────────────────────────────────────
REAL_OPENING = ("evening, jason. all systems nominal - no glitches detected in "
                "the last 12 hours. how's your day shaping up?")


@pytest.mark.parametrize("claim", [
    "all systems nominal",
    "no glitches detected in the last 12 hours",
    "everything is running fine",
    "diagnostics show no problems",
    "no errors in the last 24 hours",
    "all subsystems are green",
])
def test_self_status_claims_are_detected(claim):
    assert og.claims_unverified_self_status(claim) is True


def test_the_real_opening_line_loses_its_invented_status():
    out = og.drop_unverified_self_status(REAL_OPENING, is_grounded=False)
    assert "nominal" not in out and "12 hours" not in out
    assert "evening, jason" in out, "the greeting was destroyed with the claim"
    assert "how's your day" in out


def test_a_grounded_turn_keeps_its_status_report():
    """The point is not to forbid ELI reporting health, only inventing it."""
    text = "All systems nominal. 15 agents registered."
    assert og.drop_unverified_self_status(text, is_grounded=True) == text


@pytest.mark.parametrize("ordinary", [
    "Playing the third world by immortal technique on Spotify.",
    "You're stuck in a loop of pain and pop culture, buddy.",
    "The model failed to load because a tensor is missing.",
])
def test_ordinary_replies_are_untouched(ordinary):
    assert og.drop_unverified_self_status(ordinary, is_grounded=False) == ordinary


def test_a_reply_that_is_only_a_status_claim_is_not_emptied():
    """Silence is a worse failure than an over-claim."""
    only = "All systems nominal."
    assert og.drop_unverified_self_status(only, is_grounded=False) == only


# ── 2. handing its own diagnostic to the user ──────────────────────────────
@pytest.mark.parametrize("deflection", [
    "run the full acceleration diagnostics again, and I'll flag any lingering hiccups",
    "you should run a self test",
    "could you run the runtime audit",
    "try running a health check",
])
def test_self_diagnostic_deflection_is_detected(deflection):
    assert og.defers_own_diagnostic_to_user(deflection) is True


@pytest.mark.parametrize("legitimate", [
    "run the installer again and it will rebuild the venv",
    "you could run that script yourself if you want",
    "I'll run the tests now.",
])
def test_other_run_instructions_are_left_alone(legitimate):
    assert og.defers_own_diagnostic_to_user(legitimate) is False


# ── 3. a promised check must report what it found ──────────────────────────
REAL_AUDIT = """FAIL /home/jay/.local/share/ELI_v2/eli/kernel/engine.py
  - line 3561 [duplicate_top_level_symbol] _first_sentence also defined at lines [3508, 3561]
PASS /home/jay/.local/share/ELI_v2/eli/cognition/gguf_inference.py
PASS /home/jay/.local/share/ELI_v2/eli/memory/memory.py

Live health probes:
  ✅ plugin_manager: OK - 10 plugin(s) installed
  ❌ recent_failures: 5 recent live failure(s): missing app name (×1)"""


def test_findings_survive_but_the_dump_does_not():
    out = _ft_summarise_findings(REAL_AUDIT)
    assert "duplicate_top_level_symbol" in out, "the real defect is still hidden"
    assert "recent_failures" in out
    assert "PASS" not in out, "this is the data dump the suppression exists to prevent"
    assert "plugin_manager" not in out, "healthy probes are not 'hiccups'"


def test_a_clean_run_says_nothing():
    """No manufactured reassurance -- the other half of the same rule."""
    assert _ft_summarise_findings("PASS a.py\nPASS b.py\n  ✅ memory: ok") == ""
    assert _ft_summarise_findings("") == ""


def test_the_gate_still_suppresses_unpromised_dumps():
    src = Path("eli/kernel/engine.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    assert "_ft_promised" in code, "promise detection is gone"
    assert "suppressed status/dump action" in code, \
        "the unrequested-dump suppression was removed along with the fix"


# ── 4. ELI claiming the user's life as its own ─────────────────────────────
REAL_EVENING_REPLY = (
    "Well, the plan for the evening is to chill out, get some weed, and maybe "
    "play Fallout 4 while watching The Walking Dead. I'll be around, just "
    "don't expect me to do anything too complicated."
)


def test_the_users_evening_is_not_elis_plan():
    out = og.repair_embodied_self_claims(REAL_EVENING_REPLY)
    assert "get some weed" not in out, "ELI still claims to be acquiring weed"
    assert "I'll be around" in out, "the rest of the reply was destroyed"


@pytest.mark.parametrize("claim", [
    "I'm going to get some weed later",
    "my plan for the evening is to eat and sleep",
    "I'll probably just crash out after this",
])
def test_embodied_plans_are_detected(claim):
    assert og.claims_embodied_activity(claim) is True


@pytest.mark.parametrize("persona", [
    "You're stuck in a loop of pain and pop culture, buddy.",
    "I'll play some music if you want.",            # PLAY_MEDIA is real
    "I'll keep the vibe low and quiet for you.",
    "I'm not planning anything - yet.",
    "I'll open Fallout for you if you like.",       # OPEN_APP is real
])
def test_the_voice_survives(persona):
    """The persona is not the bug. Only false claims are."""
    assert og.repair_embodied_self_claims(persona) == persona


# ── the defect ELI's own audit found ───────────────────────────────────────
def test_first_sentence_is_defined_once():
    src = Path("eli/kernel/engine.py").read_text(encoding="utf-8")
    assert src.count("\ndef _first_sentence(") == 1, \
        "the duplicate definition is back; the later one silently wins"


def test_first_sentence_understands_ellipses_and_quotes():
    """The dead definition was the one that used _SENTENCE_SPLIT_RE, so the
    anti-echo test had been running on the weaker splitter."""
    assert _first_sentence("Trailing... more here.") == "Trailing..."
    assert _first_sentence("Hello there. Second one.") == "Hello there."
    assert _first_sentence("") == ""
    assert _first_sentence("no punctuation") == "no punctuation"


def test_governor_applies_all_casual_guards():
    import inspect
    src = inspect.getsource(og.govern_output)
    for fn in ("drop_repeated_clarification", "drop_unverified_self_status",
               "repair_embodied_self_claims"):
        assert fn in src, f"{fn} is not wired into the choke point"
