from __future__ import annotations

NONQUICK_MODES = {
    "constitutional_ai",
    "tree_of_thoughts",
    "self_consistency",
    "cot",
    "chain_of_thought",
}

QUICK_MODES = {"quick", "fast", "raw"}


def mode_name(mode) -> str:
    if mode is None:
        return ""
    if hasattr(mode, "value"):
        return str(mode.value).lower()
    return str(mode).lower()


def is_quick(mode) -> bool:
    return mode_name(mode) in QUICK_MODES


def is_nonquick(mode) -> bool:
    m = mode_name(mode)
    return m in NONQUICK_MODES and not is_quick(m)


def block_raw_fallback_if_nonquick(text: str, mode, cause: str = "raw fallback blocked") -> str:
    if not is_nonquick(mode):
        return text

    m = mode_name(mode) or "unknown"
    return (
        "Internal synthesis-contract fault: this response was blocked because "
        f"`{m}` mode attempted to surface raw fallback text. "
        f"Cause: {cause}. "
        "Non-Quick modes must complete synthesis/governor finalization before user-visible output."
    )
