"""A test file the size of a model takes no disk on any OS (see tests/_sparse.py)."""
from __future__ import annotations

import os
import pathlib

from tests._sparse import sparse_file

TESTS = pathlib.Path(__file__).resolve().parent


def test_files_are_only_grown_through_the_sparse_helper():
    grow = "." + "truncate("
    offenders = sorted(p.name for p in TESTS.rglob("*.py")
                       if p.name != "_sparse.py" and grow in p.read_text(encoding="utf-8"))
    assert not offenders, f"use tests._sparse.sparse_file: {offenders}"


def test_a_sparse_file_has_its_size_and_its_head_and_no_data(tmp_path):
    size = 3 * 1024 ** 3
    path = sparse_file(tmp_path / "m.gguf", size, b"GGUF")
    assert os.path.getsize(path) == size
    with open(path, "rb") as f:
        assert f.read(4) == b"GGUF"
    blocks = getattr(os.stat(path), "st_blocks", None)
    if blocks is not None:
        assert blocks * 512 < 1024 * 1024
