"""Weak vector candidates are trimmed relative to each query's own best hit.

An ABSOLUTE similarity threshold is not possible here, and this is measured, not
assumed. Against the real 449-vector index:

    worst real query, best hit   0.5294
    best nonsense query, best hit 0.5377

The bands overlap. Any constant floor that rejects gibberish also rejects genuine
questions, so a fixed threshold would be a relevance check in appearance only.

Within one query there is real structure — the tenth result sits at roughly 0.84
of the first — so the cutoff is relative to that query's own best hit. Sweeping
the real index, 0.94 is the knee: it trims a weak tail where one exists and
leaves a uniform result set alone; 0.96 begins cutting good results.

What this buys is a tighter candidate pool going into rank fusion. It does not
detect nonsense, and nothing at this embedder and corpus size can.
"""
from __future__ import annotations

import pytest

from eli.memory.vector_store import (
    SIM_MIN_KEEP, SIM_RELATIVE_FLOOR, _trim_weak_tail,
)


def _r(*scores):
    return [{"text": f"m{i}", "score": s} for i, s in enumerate(scores)]


def test_a_weak_tail_is_trimmed():
    kept = _trim_weak_tail(_r(1.0, 0.99, 0.97, 0.60, 0.55, 0.51))
    assert [round(r["score"], 2) for r in kept] == [1.0, 0.99, 0.97]


def test_a_uniform_result_set_is_left_alone():
    """If everything is close to the best hit, nothing is a weak tail."""
    scores = (0.60, 0.59, 0.585, 0.58, 0.575)
    assert len(_trim_weak_tail(_r(*scores))) == len(scores)


def test_it_never_starves_the_pool():
    """Recall fuses these with FTS5 by rank. An empty vector side would hand the
    entire answer to keyword matching."""
    kept = _trim_weak_tail(_r(1.0, 0.2, 0.1, 0.05))
    assert len(kept) == SIM_MIN_KEEP
    assert kept[0]["score"] == 1.0, "the best hit must survive"


def test_fewer_results_than_the_floor_are_all_kept():
    assert len(_trim_weak_tail(_r(1.0, 0.1))) == 2


def test_empty_input_is_safe():
    assert _trim_weak_tail([]) == []


def test_a_zero_ratio_disables_trimming():
    scores = (1.0, 0.2, 0.1, 0.05, 0.01)
    assert len(_trim_weak_tail(_r(*scores), min_ratio=0)) == len(scores)


def test_missing_or_bad_scores_do_not_raise():
    assert len(_trim_weak_tail([{"text": "a"}, {"text": "b", "score": None}])) == 2


def test_the_floor_is_relative_not_absolute():
    """The same shape must trim identically at a different absolute magnitude —
    that is the property an absolute threshold cannot have."""
    high = _trim_weak_tail(_r(1.0, 0.98, 0.60))
    low = _trim_weak_tail(_r(0.10, 0.098, 0.06))
    assert len(high) == len(low) == SIM_MIN_KEEP


def test_the_calibrated_floor_is_in_the_measured_band():
    """Below ~0.90 nothing is trimmed on the real index; at 0.96 good results
    start disappearing. Moving this outside that band should be deliberate."""
    assert 0.90 < SIM_RELATIVE_FLOOR < 0.96
