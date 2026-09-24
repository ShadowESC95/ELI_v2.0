"""Helpers that replaced copy-pasted versions in many modules."""
from pathlib import Path

from eli.core.paths import canonical_root, path_get
from eli.utils.jsonio import read_json_dict, read_jsonl_dicts


def test_canonical_root_prefers_the_real_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_PROJECT_ROOT", str(tmp_path))
    assert canonical_root(Path("/nonexistent/fallback")) == tmp_path.resolve()


def test_canonical_root_falls_back_when_resolution_fails(monkeypatch):
    import eli.core.paths as P
    monkeypatch.setattr(P, "project_root", lambda: (_ for _ in ()).throw(RuntimeError("no root")))
    assert canonical_root(Path("/fallback")) == Path("/fallback")


def test_path_get_reads_dicts_and_objects():
    class Paths:
        user_db = "u.sqlite3"
    assert path_get({"user_db": "d"}, "user_db") == "d"
    assert path_get(Paths(), "user_db") == "u.sqlite3"
    assert path_get(None, "user_db", "x") == "x" and path_get({}, "user_db", "x") == "x"


def test_read_json_dict_is_tolerant(tmp_path):
    good = tmp_path / "g.json"; good.write_text('{"a": 1}')
    assert read_json_dict(good) == {"a": 1}
    for name, body in (("list.json", "[1]"), ("bad.json", "{oops"), ("empty.json", "")):
        p = tmp_path / name; p.write_text(body)
        assert read_json_dict(p) == {}
    assert read_json_dict(tmp_path / "missing.json") == {}


def test_read_jsonl_dicts_skips_blank_and_bad_lines(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text('{"a": 1}\n\nnot json\n[1,2]\n{"b": 2}\n')
    assert read_jsonl_dicts(p) == [{"a": 1}, {"b": 2}]
    assert read_jsonl_dicts(tmp_path / "missing.jsonl") == []
