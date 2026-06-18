"""Light, skippable first-run onboarding — seeds the continuous User Model."""
from eli.onboarding.interview import (
    is_onboarding_active,
    onboarding_intercept,
    clear_onboarding_state,
)

__all__ = ["is_onboarding_active", "onboarding_intercept", "clear_onboarding_state"]
