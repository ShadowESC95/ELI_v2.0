"""Hardware settings derive from THIS machine unless the operator chose them.

ELI is redistributed to wildly different hardware. The shipped defaults were a
single fixed set — n_ctx=16384, n_gpu_layers=0, batch_size=512 — handed to a
4 GB laptop and a 24 GB workstation alike; and because the profiler documents
n_ctx/n_gpu_layers/batch_size as "the user's" and never rewrites them, whatever
landed there on first run became an "explicit operator choice" that won attempt
1 of the load ladder for ever, on any machine.

Live consequence: a persisted n_ctx=10384 / n_gpu_layers=99 loaded full offload
on a 6.2 GB card, past the 29 layers the fit measured for that context, and
generation came back "GGUF returned empty response".
"""
from eli.core import runtime_settings as rs


_MACHINE = {"hw_profile_n_ctx": 4096, "hw_profile_n_gpu_layers": 30,
            "hw_profile_batch_size": 128}


def test_unpinned_values_come_from_this_machine():
    s = dict(_MACHINE, n_ctx=10384, n_gpu_layers=99, batch_size=512)
    out = rs._apply_hardware_derived_defaults(dict(s))
    assert (out["n_ctx"], out["n_gpu_layers"], out["batch_size"]) == (4096, 30, 128)


def test_an_operator_choice_is_never_re_derived():
    s = dict(_MACHINE, n_ctx=10384, n_gpu_layers=99, operator_pinned=["n_ctx"])
    out = rs._apply_hardware_derived_defaults(dict(s))
    assert out["n_ctx"] == 10384, "the operator's own setting was overwritten"
    assert out["n_gpu_layers"] == 30, "an unpinned key should still derive"


def test_a_machine_with_no_profile_yet_is_left_alone():
    """First run, before profiling: fall back to defaults, never to zero."""
    s = {"n_ctx": 16384, "n_gpu_layers": 0}
    assert rs._apply_hardware_derived_defaults(dict(s)) == s


def test_update_settings_pins_what_the_operator_sets():
    """update_settings is the operator-facing write path (settings pages, the
    startup dialog, the API) — a hardware key set through it is theirs."""
    import inspect
    src = inspect.getsource(rs.update_settings)
    assert "OPERATOR_PINNED_KEY" in src and "HARDWARE_DERIVED_KEYS" in src


def test_pinned_keys_parse_defensively():
    for junk in (None, "n_ctx", 5, {"n_ctx": True}):
        assert isinstance(rs.operator_pinned_keys({"operator_pinned": junk}), set)


# ── the context ELI asks for is derived from its own budgets ──────────────
def test_the_brief_floor_is_derived_not_a_flat_literal():
    """ELI_CTX_BRIEF_FLOOR defaulted to 12288 — the brief's budget in CHARACTERS,
    spent as TOKENS. Every machine was asked for four times the context the brief
    can occupy, and smart_fit pays for context by shedding GPU layers."""
    from eli.kernel.engine import eli_brief_budget_tokens
    tokens = eli_brief_budget_tokens()
    assert 1024 <= tokens <= 6144, tokens
    assert tokens < 12288, "still demanding the character budget as tokens"


def test_the_brief_budget_tracks_the_assembler():
    """One definition: if the persona or memory budget moves, the context ELI
    requests moves with it, instead of drifting apart."""
    from eli.kernel.engine import (eli_brief_budget_tokens, ELI_BUDGET_MEMORY_CHARS,
                                   ELI_CHARS_PER_TOKEN, CognitiveEngine)
    expected = (CognitiveEngine._PERSONA_MAX_CHARS + ELI_BUDGET_MEMORY_CHARS) // ELI_CHARS_PER_TOKEN
    assert eli_brief_budget_tokens() == max(1024, expected)


def test_a_smaller_context_leaves_more_layers_on_the_gpu():
    """The point of the fix: constrained hardware gains GPU offload it was
    giving away to reserve context nothing would use."""
    from eli.core.hardware_profile import smart_fit_config as fit
    for free_mb in (3000, 4000, 6328):
        _, old_layers, _ = fit(model_size_gb=4.68, free_vram_mb=free_mb,
                               user_ctx=16384, user_batch=128, kv_quantized=True)
        _, new_layers, _ = fit(model_size_gb=4.68, free_vram_mb=free_mb,
                               user_ctx=8192, user_batch=128, kv_quantized=True)
        assert new_layers > old_layers, f"{free_mb}MB: {old_layers} -> {new_layers}"


def test_the_requested_context_still_holds_the_brief():
    from eli.kernel.engine import eli_brief_budget_tokens
    need = eli_brief_budget_tokens() + 4096          # brief + generation reserve
    requested = -(-need // 2048) * 2048              # grain rounds UP
    assert requested >= need, "the grain gave back part of the reserve"
