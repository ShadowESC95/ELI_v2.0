"""One place to turn bytes into the memory/model-size figures ELI reports and compares.

Every size that gets compared against another — a model's file size against free VRAM,
an MoE model's expert weights against available RAM, a model against a friend's — has to
share one base or the comparison is meaningless. VRAM and RAM are physically binary
(what the OS and nvidia-smi report), so that's the base here throughout: GiB = 1024**3
bytes, MiB = 1024**2. Decimal GB (bytes/1e9) reads a bigger number for the same file and
was scattered across a dozen call sites that duplicated the conversion inline — some
binary, some decimal, all labelled "GB" — so the same model loaded from two different
code paths could print two different sizes. Use these helpers instead of writing the
division inline; a second inline copy is how the mismatch happened the first time.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

GIB = 1024 ** 3
MIB = 1024 ** 2


def bytes_to_gib(n: Union[int, float]) -> float:
    return float(n) / GIB


def bytes_to_mib(n: Union[int, float]) -> float:
    return float(n) / MIB


def gib_to_mib(gib: Union[int, float]) -> float:
    return float(gib) * 1024.0


def file_size_gib(path: Union[str, Path]) -> float:
    """A file's size in GiB, or 0.0 if it can't be stat'd."""
    try:
        return bytes_to_gib(Path(path).stat().st_size)
    except OSError:
        return 0.0


def dir_size_gib(path: Union[str, Path]) -> float:
    """Total size in GiB of every regular file under a directory, or 0.0 if unreadable."""
    try:
        root = Path(path)
        if root.is_file():
            return file_size_gib(root)
        return bytes_to_gib(sum(f.stat().st_size for f in root.rglob("*") if f.is_file()))
    except OSError:
        return 0.0
