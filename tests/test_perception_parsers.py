"""Perception file/text parsers — the pure, non-device-bound bits.

extract_equations pulls LaTeX-ish / `x = …` equations out of text; analyze_csv
profiles a CSV (shape, columns, per-column dtype/nulls/numeric stats). Neither needs
a mic/camera/GPU — they're the genuinely-testable slice of eli/perception. Runs in
the normal suite.
"""
from __future__ import annotations

import pytest

from eli.perception.extract_equations import extract_equations, extract_equations_from_text


# --------------------------------------------------------------------------- #
# extract_equations
# --------------------------------------------------------------------------- #
def test_extract_plain_equation():
    eqs = extract_equations("Einstein's E = mc^2 changed physics.")
    assert any("E = mc^2" in e or "E =" in e for e in eqs)


def test_extract_latex_inline():
    eqs = extract_equations_from_text(r"The area is $\pi r^2$ for a circle.")
    assert any("pi r^2" in e or "$\\pi r^2$" in e for e in eqs)


def test_extract_dedupes():
    eqs = extract_equations("x = 1 here, and again x = 1 there.")
    assert eqs.count("x = 1") <= 1


def test_extract_empty_and_none():
    assert extract_equations_from_text("") == []
    assert extract_equations_from_text(None) == []


def test_extract_prose_without_equations():
    assert extract_equations("Just some ordinary prose, nothing mathematical.") == []


# --------------------------------------------------------------------------- #
# analyze_csv
# --------------------------------------------------------------------------- #
@pytest.fixture
def _csv(tmp_path):
    p = tmp_path / "data.csv"
    p.write_text("name,age,score\nalice,30,9.5\nbob,25,7.0\ncara,40,8.25\n", encoding="utf-8")
    return p


def _analyze(csv_path, tmp_path):
    from eli.perception.analyze_csv import analyze_csv_file
    return analyze_csv_file(str(csv_path), str(tmp_path / "out.md"))


def test_csv_missing_file(tmp_path):
    from eli.perception.analyze_csv import analyze_csv_file
    r = analyze_csv_file(str(tmp_path / "nope.csv"), str(tmp_path / "out.md"))
    assert r["ok"] is False and r["error"] == "not_found"


def test_csv_profile_shape_and_columns(_csv, tmp_path):
    r = _analyze(_csv, tmp_path)
    assert r["ok"] is True
    assert r["shape"] == [3, 3]                      # 3 rows, 3 cols
    assert r["columns"] == ["name", "age", "score"]


def test_csv_numeric_summary(_csv, tmp_path):
    r = _analyze(_csv, tmp_path)
    age = r["summary"]["age"]
    assert age["min"] == 25.0 and age["max"] == 40.0
    assert abs(age["mean"] - (30 + 25 + 40) / 3) < 1e-6
    assert age["nulls"] == 0


def test_csv_writes_markdown(_csv, tmp_path):
    out = tmp_path / "out.md"
    _analyze(_csv, tmp_path)
    assert out.exists() and out.stat().st_size > 0
