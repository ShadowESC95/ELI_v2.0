"""Locks on the operator's own settings being tried first, and on answers being
worth the wait they cost.

From a live 2.2.0 session running a 22.28GB / 30B model on a card with 6.5GB
free. Single replies took 57s, 136s, 186s. What came back:

    user> So are you somewhat back to normal? No more spouting nonsense?
    ELI > Yes. I've stopped spouting nonsense.

Three separate causes, none of them the model being slow:

1. THE VOICE SAID BE SHORT. Six places defined ELI as "terse" — persona.txt,
   three prompts in engine.py, context_synthesiser. On a machine where a reply
   costs two minutes, an instruction to be brief is the wrong instruction.
   "No filler" is worth keeping; "terse" is not.

2. THE ANSWER WAS CAPPED FOR NO REASON. quick was pinned to a flat 1024 and
   standard to 3072; engine.py capped the whole budget at min(4096, n_ctx // 3)
   on GPU and n_ctx // 4 on CPU. So a 128k-context model could never answer with
   more than 4k tokens. None of it bought speed: max_tokens is a ceiling, not a
   target, so it only ever bit when the model had more to say.

3. THE USER'S SETTINGS WERE NEVER TRIED. smart-fit ran first and its reduced
   result was queued ahead of "requested", so a config the operator explicitly
   chose in the startup dialog sat at position 2 behind one that always loaded.
   The setting was a suggestion, not a setting.

Nothing here hardcodes a new number — it removes four. The one real constraint,
prompt + generation <= n_ctx, is computed per call from the ACTUAL prompt in
gguf_inference._fit_generation_budget, which is the only place that can know it.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


# ── 1. the voice no longer instructs brevity ───────────────────────────────
VOICE_FILES = [
    "eli/cognition/persona.txt",
    "eli/cognition/context_synthesiser.py",
    "eli/kernel/engine.py",
]


@pytest.mark.parametrize("rel", VOICE_FILES)
def test_the_base_voice_does_not_ask_for_terseness(rel):
    import re
    text = (REPO / rel).read_text(encoding="utf-8")
    # Word-boundary: "terse" as a voice instruction, not a substring of prose.
    assert not re.search(r"\bterse\b", text, re.I), \
        f"{rel} still instructs the model to be terse"


def test_the_character_is_intact():
    """Removing 'terse' must not turn ELI into a cheerful assistant — the point
    was the length instruction, not the personality."""
    persona = (REPO / "eli/cognition/persona.txt").read_text(encoding="utf-8").lower()
    for trait in ("direct", "dry", "no flattery", "no filler"):
        assert trait in persona, f"lost '{trait}' from the persona"


def test_padding_is_still_discouraged():
    """"Say more" must not become "waffle"."""
    persona = (REPO / "eli/cognition/persona.txt").read_text(encoding="utf-8").lower()
    assert "filler" in persona or "padding" in persona


def test_a_scoped_terse_tone_is_still_allowed():
    """The 'exasperated' entry in the emotion palette is a deliberate, temporary
    tone — it is not the base voice and must survive."""
    palette = (REPO / "eli/cognition/emotion_palette.py").read_text(encoding="utf-8")
    assert "terse" in palette.lower(), "the scoped exasperated tone was removed too"


# ── 2. no artificial ceiling on the answer ────────────────────────────────
# These originally asserted a tier-scaled ceiling (1024 small, 4096 frontier).
# That was still a cap, and the question "why is there a cap in the first
# place?" has no good answer: max_tokens is a CEILING, not a target, so a short
# reply is short regardless and the cap only ever bites when the model had more
# to say. It never made anything faster — it made long answers incomplete.
#
# What was removed:
#   engine.py     min(4096, n_ctx // 3)  on GPU, n_ctx // 4 on CPU, and a
#                 policy ceiling of n_ctx // 3 above them
#   optimizer     a flat 1024 (quick) and 3072 (standard)
#
# The real constraint is enforced where it can be known: per call, from the
# actual prompt, in gguf_inference._fit_generation_budget.

def _presets(scale, n_ctx=12192, max_tokens=6000, monkeypatch=None):
    import eli.core.model_tier as MT
    from eli.core.startup_hardware_optimizer import mode_presets
    monkeypatch.setattr(MT, "tier_scale", lambda: scale)
    return mode_presets(n_ctx, max_tokens)


@pytest.mark.parametrize("scale", [1.0, 1.5, 2.5, 4.0])
def test_no_mode_truncates_the_answer_below_the_window(monkeypatch, scale):
    p = _presets(scale, monkeypatch=monkeypatch)
    assert p["quick"]["max_tokens"] == 6000
    assert p["standard"]["max_tokens"] == 6000


def test_quick_is_still_quick_by_doing_less_work(monkeypatch):
    """The mode has to differ SOMEHOW — by passes and retrieval depth, which is
    what actually costs time, not by cutting the answer off."""
    p = _presets(1.0, monkeypatch=monkeypatch)
    assert p["quick"]["passes"] == 1
    assert p["quick"]["memory_depth"] == "minimal"
    assert p["standard"]["memory_depth"] != p["quick"]["memory_depth"]


def test_no_flat_ceiling_remains_in_the_presets():
    src = (REPO / "eli/core/startup_hardware_optimizer.py").read_text(encoding="utf-8")
    start = src.index("def mode_presets(")
    body = src[start:src.index("\ndef ", start + 10)]
    for bad in ("min(max_tokens, 1024)", "min(max_tokens, 3072)", "min(max_tokens, 1536)"):
        assert bad not in body, f"flat ceiling {bad} is back"


def test_engine_no_longer_caps_the_budget_at_a_fraction_of_the_window():
    """Strip comments first: the note explaining WHY these were removed quotes
    them verbatim, and matching that would make this test pass on prose."""
    src = (REPO / "eli/kernel/engine.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    for bad in ("min(4096, n_ctx // 3)", "max(384, n_ctx // 4)"):
        assert bad not in code, f"{bad} is back — a blind guess at the prompt size"


@pytest.mark.parametrize("n_ctx,prompt_tok,at_least", [
    (12192, 5184, 6000),      # the live session: was capped at 4064
    (131072, 8000, 100000),   # a large model: was capped at 4096
    (4096, 3000, 500),        # a small window still gets what is left
])
def test_the_budget_is_whatever_the_window_actually_has_left(n_ctx, prompt_tok, at_least, monkeypatch):
    import eli.cognition.gguf_inference as G

    class FakeLLM:
        def n_ctx(self):
            return n_ctx

    monkeypatch.setattr(G, "_estimate_prompt_tokens", lambda llm, p: len(p) // 4)
    monkeypatch.setattr(G, "_effective_ctx_limit", lambda llm: llm.n_ctx())
    monkeypatch.setattr(G, "_truncate_prompt_to_tokens", lambda llm, p, b: p[: b * 4])

    _, budget = G._fit_generation_budget(FakeLLM(), "x" * (prompt_tok * 4), n_ctx)
    assert budget >= at_least
    assert prompt_tok + budget <= n_ctx


# ── 3. the operator's settings are attempted first ────────────────────────
def test_the_users_own_settings_are_the_first_load_attempt():
    """smart-fit's reduced result used to be queued ahead of them, so a config
    the operator explicitly chose was never tried."""
    src = (REPO / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    requested = src.index('_add_attempt("requested"')
    smartfit = src.index('_add_attempt("smart-fit"')
    assert requested < smartfit, "ELI still overrules the user before the driver does"


def test_the_calculated_fit_is_still_the_fallback():
    """Honouring the setting must not remove the safety net for hardware that
    genuinely cannot take it."""
    src = (REPO / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert '_add_attempt("smart-fit"' in src
    for rung in ('"live-tuner-gpu"', '"lower-batch-half"', '"cpu-fallback"'):
        assert rung in src, f"lost the {rung} fallback"


def test_requested_is_queued_once_not_twice():
    """It moved; the old call site had to go, or the ladder carries a duplicate."""
    src = (REPO / "eli/gui/eli_pro_audio_gui_v2_0.py").read_text(encoding="utf-8")
    assert src.count('_add_attempt("requested"') == 1
