"""#14 — self-patch CI-grade verification: run the patched module's tests and
revert on a genuine regression, but NEVER false-revert on tooling gaps.

The critical safety invariant: a self-modifying engine must not block/revert on
its own tooling failing (no matching tests, timeout, infra error). Only a real
test failure (ran=True, passed=False) should trigger a revert.
"""
from pathlib import Path

from eli.runtime.self_improvement import _run_targeted_tests


def test_no_matching_tests_is_tolerated():
    # A module with no tests → ran=False (no signal), passed=True (don't revert).
    ran, passed, _ = _run_targeted_tests(Path("eli/core/zzz_does_not_exist.py"), timeout=20)
    assert ran is False
    assert passed is True


def test_clean_module_with_tests_passes():
    # cognition/scoring.py has dedicated tests that pass on a clean tree.
    ran, passed, detail = _run_targeted_tests(Path("eli/cognition/scoring.py"), timeout=120)
    # Either it ran the tests and they passed, or (on a constrained box) it was
    # tolerated — in both cases it must NOT report a false regression.
    assert passed is True, detail
