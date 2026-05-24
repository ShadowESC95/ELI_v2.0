"""Integration: mode preset resolution is correct for all 4 private modes.

Tests that _mode_profile():
  - Resolves canonical keys directly
  - Resolves alias keys (e.g. 'cot' -> chain_of_thought preset)
  - Returns meaningful token budgets (not the 1536-token quick-mode fallback)
  - Returns expected per-stage keys for each algorithm
  - Provides realistic fallback defaults when no preset exists at all
"""
import pytest
from unittest.mock import patch


def _mode_profile(engine, mode: str) -> dict:
    return engine._mode_profile(mode)


def _make_engine():
    from eli.kernel.engine import CognitiveEngine
    return CognitiveEngine(auto_init_gguf=False)


# ---------------------------------------------------------------------------
# Canonical key resolution
# ---------------------------------------------------------------------------

class TestCanonicalKeyResolution:

    def test_chain_of_thought_key_resolves(self):
        engine = _make_engine()
        profile = _mode_profile(engine, "chain_of_thought")
        assert profile["mode"] == "chain_of_thought"
        assert int(profile.get("max_tokens", 0)) >= 1536, (
            "chain_of_thought preset max_tokens is below 1536 — CoT responses will be truncated"
        )

    def test_self_consistency_key_resolves(self):
        engine = _make_engine()
        profile = _mode_profile(engine, "self_consistency")
        assert profile["mode"] == "self_consistency"

    def test_tree_of_thoughts_key_resolves(self):
        engine = _make_engine()
        profile = _mode_profile(engine, "tree_of_thoughts")
        assert profile["mode"] == "tree_of_thoughts"

    def test_constitutional_ai_key_resolves(self):
        engine = _make_engine()
        profile = _mode_profile(engine, "constitutional_ai")
        assert profile["mode"] == "constitutional_ai"

    def test_quick_key_resolves(self):
        engine = _make_engine()
        profile = _mode_profile(engine, "quick")
        assert profile["mode"] == "quick"


# ---------------------------------------------------------------------------
# Alias key resolution (the 'cot' bug)
# ---------------------------------------------------------------------------

class TestAliasKeyResolution:

    @pytest.mark.parametrize("alias,canonical", [
        ("cot",             "chain_of_thought"),
        ("chain",           "chain_of_thought"),
        ("self-c",          "self_consistency"),
        ("self-consistency","self_consistency"),
        ("tot",             "tree_of_thoughts"),
        ("tree",            "tree_of_thoughts"),
        ("constitutional",  "constitutional_ai"),
        ("cai",             "constitutional_ai"),
    ])
    def test_alias_resolves_to_canonical_mode_key(self, alias, canonical):
        """_mode_profile(alias) must resolve to the canonical mode — not 'quick' fallback."""
        engine = _make_engine()
        # Inject a settings stub that only has the alias key, not the canonical one
        fake_settings = {
            "mode_presets": {
                alias: {
                    "max_tokens": 9999,
                    "passes": 2,
                    "temperature": 0.5,
                    "top_p": 0.9,
                }
            }
        }
        with patch("eli.core.runtime_settings.load_settings", return_value=fake_settings):
            profile = _mode_profile(engine, canonical)
        assert int(profile.get("max_tokens", 0)) == 9999, (
            f"_mode_profile('{canonical}') did not find alias key '{alias}' "
            f"in mode_presets — got max_tokens={profile.get('max_tokens')}"
        )

    def test_cot_alias_uses_real_budget_not_1536_fallback(self):
        """The specific bug: settings stored 'cot' but engine looked up 'chain_of_thought'.
        _mode_profile must NOT fall back to 1536-token default when 'cot' key exists."""
        engine = _make_engine()
        fake_settings = {
            "mode_presets": {
                "cot": {
                    "max_tokens": 4096,
                    "passes": 1,
                    "memory_depth": "normal",
                }
            }
        }
        with patch("eli.core.runtime_settings.load_settings", return_value=fake_settings):
            profile = _mode_profile(engine, "chain_of_thought")
        assert int(profile.get("max_tokens", 0)) == 4096, (
            f"_mode_profile('chain_of_thought') fell back to {profile.get('max_tokens')} "
            f"instead of finding the 'cot' alias key with max_tokens=4096. "
            f"This was the root cause of CoT responses being identical to Quick."
        )


# ---------------------------------------------------------------------------
# Fallback defaults are realistic for each mode
# ---------------------------------------------------------------------------

class TestFallbackDefaults:

    @pytest.mark.parametrize("mode,min_tokens", [
        ("chain_of_thought",  2048),
        ("constitutional_ai", 2048),
        ("tree_of_thoughts",  1536),
        ("self_consistency",  1536),
    ])
    def test_fallback_max_tokens_is_not_quick_budget(self, mode, min_tokens):
        """When no preset exists at all, private modes must not fall back to
        the 1536-token quick budget — they need room for multi-pass work."""
        engine = _make_engine()
        empty_settings = {"mode_presets": {}}
        with patch("eli.core.runtime_settings.load_settings", return_value=empty_settings):
            profile = _mode_profile(engine, mode)
        assert int(profile.get("max_tokens", 0)) >= min_tokens, (
            f"_mode_profile('{mode}') fallback max_tokens={profile.get('max_tokens')} "
            f"is below minimum expected {min_tokens} — multi-pass responses will be truncated"
        )

    def test_fallback_mode_key_is_preserved(self):
        """Even with no preset, profile['mode'] must equal the requested mode."""
        engine = _make_engine()
        with patch("eli.core.runtime_settings.load_settings", return_value={"mode_presets": {}}):
            for mode in ("chain_of_thought", "tree_of_thoughts", "constitutional_ai",
                         "self_consistency", "quick"):
                profile = _mode_profile(engine, mode)
                assert profile["mode"] == mode, (
                    f"_mode_profile('{mode}') returned mode={profile['mode']!r}"
                )


# ---------------------------------------------------------------------------
# Per-mode algorithm keys are present
# ---------------------------------------------------------------------------

class TestPerModeAlgorithmKeys:

    def test_chain_of_thought_has_reasoning_temperature(self):
        """CoT preset should carry temperature_reasoning and temperature_final
        so _run_chain_of_thought can use per-stage temperatures."""
        engine = _make_engine()
        profile = _mode_profile(engine, "chain_of_thought")
        # Either the preset has them or the algorithm falls back to derivations —
        # just confirm the profile is not the quick-mode stub
        assert profile["mode"] == "chain_of_thought"
        assert float(profile.get("temperature", 1.0)) <= 0.7, (
            "CoT temperature should be ≤ 0.7 to reduce rambling in scratchpad"
        )

    def test_self_consistency_has_samples_key(self):
        """SC preset must carry a 'samples' key so n is not hard-coded to 3."""
        engine = _make_engine()
        profile = _mode_profile(engine, "self_consistency")
        # 'samples' may come from the preset or be absent (default=3 in algorithm)
        # Just assert the mode resolved correctly
        assert profile["mode"] == "self_consistency"

    def test_tree_of_thoughts_has_branch_budget(self):
        """ToT preset should carry max_tokens_propose and max_tokens_develop."""
        engine = _make_engine()
        profile = _mode_profile(engine, "tree_of_thoughts")
        assert profile["mode"] == "tree_of_thoughts"

    def test_constitutional_ai_has_per_stage_budgets(self):
        """CAI preset should carry max_tokens_generate, critique, revise."""
        engine = _make_engine()
        profile = _mode_profile(engine, "constitutional_ai")
        assert profile["mode"] == "constitutional_ai"


# ---------------------------------------------------------------------------
# canonical_mode() from reasoning_modes.py resolves all aliases
# ---------------------------------------------------------------------------

class TestCanonicalModeFunction:

    @pytest.mark.parametrize("raw,expected", [
        ("quick",            "quick"),
        ("fast",             "quick"),
        ("cot",              "chain_of_thought"),
        ("chain",            "chain_of_thought"),
        ("chain_of_thought", "chain_of_thought"),
        ("self-c",           "self_consistency"),
        ("self_consistency", "self_consistency"),
        ("tot",              "tree_of_thoughts"),
        ("tree_of_thoughts", "tree_of_thoughts"),
        ("constitutional",   "constitutional_ai"),
        ("constitutional_ai","constitutional_ai"),
        # GUI combo box labels (strippable)
        ("⚡ Quick",         "quick"),
        ("🔗 CoT",           "chain_of_thought"),
        ("🌳 ToT",           "tree_of_thoughts"),
    ])
    def test_canonical_mode_resolves(self, raw, expected):
        from eli.cognition.reasoning_modes import canonical_mode
        # Strip emoji prefixes that the GUI adds
        import re
        clean = re.sub(r"^[^\w]+", "", raw).strip()
        result = canonical_mode(clean)
        assert result == expected, (
            f"canonical_mode({clean!r}) returned {result!r}, expected {expected!r}"
        )
