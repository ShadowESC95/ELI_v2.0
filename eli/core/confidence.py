"""The one confidence-score to label mapping."""
from __future__ import annotations

_BANDS = ((0.85, "very high"), (0.70, "high"), (0.50, "medium"), (0.30, "low"))


def confidence_label(score: float) -> str:
    s = float(score or 0.0)
    return next((name for floor, name in _BANDS if s >= floor), "very low")
