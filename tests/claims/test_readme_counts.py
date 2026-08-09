"""CLAIM: the numbers README.md advertises still match the repository.

The README said "215 capabilities" in two places while the manifest carried 216.
Nothing tied the prose to the artifact, so the only way that drift surfaced was
somebody auditing the marketing copy by hand.

Scope is deliberately narrow — this checks the numbers that have a machine-
readable source of truth, not every sentence. Two conventions matter:

  * A flat number ("215 capabilities") is a precise claim and must be exact.
  * A "+" number ("8,100+ tests across 245+ files") is a floor, and is correct
    for as long as the real count is at or above it. Those are asserted as
    lower bounds, not equalities, so ordinary growth never fails the build.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from . import _helpers as H

REPO_ROOT = Path(__file__).resolve().parents[2]
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _capability_total() -> int:
    """The same figure tests/claims/test_capability_manifest.py enforces."""
    return int(H.manifest().get("total") or len(H.capabilities()))


def _test_file_count() -> int:
    return len([p for p in (REPO_ROOT / "tests").rglob("test_*.py")])


# ── exact claims ────────────────────────────────────────────────────────────
def test_readme_capability_count_is_exact():
    stated = {int(n) for n in re.findall(r"\*?\*?(\d{3})\*?\*? capabilities", README)}
    assert stated, "README no longer states a capability count — update this test"
    assert stated == {_capability_total()}, (
        f"README claims {sorted(stated)} capabilities, manifest total is "
        f"{_capability_total()}. Update README.md (it appears more than once)."
    )


def test_capability_count_is_stated_consistently():
    """It appears in the intro and again in the breadth table; they drifted apart
    once and both must move together."""
    occurrences = re.findall(r"\*?\*?(\d{3})\*?\*? capabilities", README)
    assert len(set(occurrences)) == 1, f"README states conflicting counts: {occurrences}"


# ── floor claims ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("pattern,actual,label", [
    (r"([\d,]+)\+\s*tests", None, "tests"),
    (r"([\d,]+)\+\s*files", _test_file_count, "test files"),
])
def test_plus_claims_are_floors_not_ceilings(pattern, actual, label):
    m = re.search(pattern, README)
    if not m:
        pytest.skip(f"README no longer states a '{label}' floor")
    claimed = int(m.group(1).replace(",", ""))
    if actual is None:
        # The test total is only known by running the suite; assert the floor is
        # merely sane so a typo like "81,000+" cannot slip through.
        assert 0 < claimed <= 100_000, f"implausible {label} floor: {claimed}"
        return
    assert actual() >= claimed, (
        f"README claims {claimed}+ {label} but the repo has {actual()} — "
        f"the floor is no longer true."
    )


def test_readme_does_not_claim_formats_the_reader_cannot_open():
    """.odt and .epub were advertised while falling through to the binary
    text branch. If a format is named as readable, it must be dispatched."""
    from eli.plugins.document_reader.plugin import DocumentReaderPlugin

    src = Path(
        REPO_ROOT / "eli" / "plugins" / "document_reader" / "plugin.py"
    ).read_text(encoding="utf-8")
    described = DocumentReaderPlugin.description.lower()

    for fmt in ("pdf", "docx", "odt", "epub"):
        if fmt in described:
            assert f'".{fmt}"' in src, f"{fmt} is advertised but never dispatched"
