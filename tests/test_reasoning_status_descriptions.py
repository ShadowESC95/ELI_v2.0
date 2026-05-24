from eli.cognition.reasoning_modes import mode_description
from eli.runtime.reasoning_status import current_reasoning_mode_text


MODES = [
    "quick",
    "chain_of_thought",
    "self_consistency",
    "tree_of_thoughts",
    "constitutional_ai",
]


def test_mode_descriptions_exist_and_are_distinct():
    descriptions = {mode: mode_description(mode) for mode in MODES}

    for mode, desc in descriptions.items():
        assert isinstance(desc, str), mode
        assert len(desc) > 80, mode

    assert len(set(descriptions.values())) == len(MODES)


def test_mode_descriptions_capture_core_contract_terms():
    assert "direct" in mode_description("quick").lower()
    assert "scratchpad" in mode_description("chain_of_thought").lower()
    assert "n-sample" in mode_description("self_consistency").lower()
    assert "propose" in mode_description("tree_of_thoughts").lower()
    assert "critique" in mode_description("constitutional_ai").lower()

    for mode in MODES[1:]:
        assert "private" in mode_description(mode).lower()


def test_reasoning_status_uses_mode_specific_description():
    for mode in MODES:
        text = current_reasoning_mode_text(override=mode, explain=True)
        assert "Current reasoning mode:" in text
        assert mode_description(mode) in text
