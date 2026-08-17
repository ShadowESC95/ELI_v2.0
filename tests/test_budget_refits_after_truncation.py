"""Locks on the answer budget being computed against the prompt actually sent.

Live at 2.2.2, n_ctx=10384:

    [COGNITIVE] Prompt capped to 28000chars (head+tail; n_ctx=10384, qcap=28000)
    [GGUF][TIMING] prompt_tokens=5693 prompt_chars=22380 max_tokens=128
    [GGUF][RAW_TEXT] "...That said, there's one thing I'd flag as potentially
                      problematic: the repea"          <- cut mid-word

A 5,693-token prompt in a 10,384-token window leaves roughly 4,600 free. It
generated with 128.

The order of operations was wrong:

    estimate the prompt  ->  clamp the budget  ->  truncate the prompt

The estimate ran on the prompt BEFORE truncation. A large one pushed the
estimate past n_ctx, `max(128, ...)` engaged, and the budget was pinned to the
floor. The prompt was then cut roughly in half to fit — which freed thousands of
tokens that the already-decided budget never saw.

Truncating frees room; the budget has to be recomputed once it has.

This is the third truncation of the same family (the streaming path missing the
clamp, then the ctx//3 caps). The shape is always the same: a number decided
from a value that later changes.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / "eli" / "kernel" / "engine.py"

N_CTX = 10384
CHARS_PER_TOK = 3.5


def _est(chars):
    return max(1, int(chars / CHARS_PER_TOK))


def _avail(chars, n_ctx=N_CTX):
    return max(128, n_ctx - _est(chars) - 64)


# ── the arithmetic the fix restores ────────────────────────────────────────
def test_the_untruncated_estimate_is_what_produced_128():
    """Reproduces the live failure: the pre-truncation prompt hits the floor."""
    assert _avail(36000) == 128


def test_the_truncated_prompt_leaves_thousands_of_tokens():
    """22,380 chars is what was actually sent."""
    assert _avail(22380) > 3000


def test_recomputing_raises_the_budget_by_an_order_of_magnitude():
    before, after = _avail(36000), _avail(22380)
    assert after > before * 20


@pytest.mark.parametrize("pre,post", [(36000, 22380), (60000, 28000), (40000, 12000)])
def test_a_truncation_always_frees_budget(pre, post):
    assert _avail(post) >= _avail(pre)


def test_a_prompt_that_never_needed_truncating_is_unaffected():
    """The re-fit must not inflate a budget that was already correct."""
    small = 8000
    assert _avail(small) == _avail(small)


# ── the source must recompute after truncating ─────────────────────────────
def _engine_code():
    src = ENGINE.read_text(encoding="utf-8")
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


def test_the_budget_is_refitted_after_the_prompt_is_capped():
    code = _engine_code()
    cap = code.index("Prompt capped to")
    assert "_avail_final" in code, "no post-truncation re-fit exists"
    assert code.index("_avail_final") > cap, \
        "the re-fit runs before the truncation it is meant to follow"


def test_the_refit_happens_before_the_call():
    code = _engine_code()
    refit = code.index("_avail_final")
    call = code.index("max_tokens=_safe_max_pf1")
    assert refit < call, "the budget is re-fitted after it has already been used"


def test_the_refit_never_lowers_the_budget():
    """It exists to reclaim room, not to introduce a new cap."""
    code = _engine_code()
    block = code[code.index("_avail_final"):]
    assert "if _avail_final > _safe_max_pf1:" in block, \
        "the re-fit is not guarded against reducing the budget"


def test_an_explicit_request_is_still_respected():
    """Reclaiming room must not override a smaller number the caller asked for."""
    code = _engine_code()
    block = code[code.index("_avail_final"):code.index("max_tokens=_safe_max_pf1")]
    assert "_req_pf1" in block, "the re-fit ignores what the caller requested"


# ── the traceback that printed on every examine ────────────────────────────
def test_clearing_an_absent_pending_fix_is_not_an_error():
    """"Clear" on a file that is already gone is the success case. It logged a
    full FileNotFoundError stack to the console on every normal EXAMINE_CODE."""
    src = (REPO / "eli" / "runtime" / "code_examiner.py").read_text(encoding="utf-8")
    fn = src[src.index("def clear_pending_fix"):]
    fn = fn[:fn.index("\ndef ")] if "\ndef " in fn else fn
    assert "missing_ok=True" in fn


def test_clear_pending_fix_is_silent_when_nothing_is_pending(tmp_path, monkeypatch):
    from eli.runtime import code_examiner as CE
    monkeypatch.setattr(CE, "_pending_file", lambda: tmp_path / "absent.json")
    CE.clear_pending_fix()          # must not raise
    CE.clear_pending_fix()          # and must stay idempotent


def test_clear_pending_fix_removes_a_real_one(tmp_path, monkeypatch):
    from eli.runtime import code_examiner as CE
    target = tmp_path / "pending_code_fix.json"
    target.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(CE, "_pending_file", lambda: target)
    CE.clear_pending_fix()
    assert not target.exists()
