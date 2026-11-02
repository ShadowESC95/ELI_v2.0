"""The llama-cpp-python source every release and GPU pack is built from.

Upstream's newest release (0.3.36) carries a llama.cpp from before several model families existed;
loading one fails with "unknown model architecture". So this takes upstream's release, swaps in a
newer llama.cpp and updates the bindings for what changed in its C structures. A wrong field offset
here is a crash, so a change that no longer applies stops the build.

The version comes from llama_cpp_constraints.txt and has to differ from upstream's. A pack and the
bundled runtime share native library names and two builds in one process crash, and that check goes
by version: under upstream's number an installed 0.3.36 pack would look current.

Standard library only: it runs before anything is installed, on every system.

usage: python packaging/llama_source.py [folder]     (prints the folder to give to pip)
"""
from __future__ import annotations

import hashlib
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN = HERE / "llama_cpp_constraints.txt"

# release v0.3.36, then llama.cpp v0.8.0. A moved tag or a changed archive stops the build.
BINDINGS = ("https://github.com/abetlen/llama-cpp-python/archive/1652066e0af45f2313b339670ef9555e8a54e545.tar.gz",
            "232bf52f8219c82271de139a9134863fcd34b58d0c8c2c5da571225e1159b987")
LLAMA_CPP = ("https://github.com/ggml-org/llama.cpp/archive/8642541b255bfb5dc39cd351a178be09013a55d6.tar.gz",
             "1688a167a8edd9499cdd0c19b8bd044f0fa184b466981977bbf2222d884953a4")

# (file, text upstream has, text llama.cpp v0.8.0 needs): what include/llama.h and tools/mtmd/mtmd.h changed
BINDING_CHANGES = (
    ("llama_cpp/llama_cpp.py", "LLAMA_SESSION_VERSION = 10\n", "LLAMA_SESSION_VERSION = 11\n"),
    ("llama_cpp/llama_cpp.py", "LLAMA_STATE_SEQ_VERSION = 3\n", "LLAMA_STATE_SEQ_VERSION = 4\n"),
    ("llama_cpp/llama_cpp.py",
     '        ("type_v", ctypes.c_int),\n        ("abort_callback", ggml_abort_callback),\n',
     '        ("type_v", ctypes.c_int),\n        ("moe_cache_size", ctypes.c_size_t),\n'
     '        ("abort_callback", ggml_abort_callback),\n'),
    ("llama_cpp/llama_cpp.py",
     '        ("n_reused", ctypes.c_int32),\n    ]\n',
     '        ("n_reused", ctypes.c_int32),\n        ("n_reallocs_same", ctypes.c_int32),\n'
     '        ("n_reallocs_diff", ctypes.c_int32),\n    ]\n'),
    ("llama_cpp/mtmd_cpp.py",
     '        ("inp_vision", c_bool),\n        ("inp_audio", c_bool),\n    ]\n',
     '        ("inp_vision", c_bool),\n        ("inp_audio", c_bool),\n        ("gen_audio", c_bool),\n    ]\n'),
)


def pinned_version() -> str:
    pins = re.findall(r"^llama-cpp-python==(\S+)\s*$", PIN.read_text(encoding="utf-8"), re.M)
    if len(pins) != 1:
        raise SystemExit(f"{PIN.name}: expected one llama-cpp-python pin, found {pins}")
    return pins[0]


def _fetch(source: tuple, into: Path) -> None:
    url, sha256 = source
    into.parent.mkdir(parents=True, exist_ok=True)
    archive = into.parent / (sha256 + ".tar.gz")
    with urllib.request.urlopen(url, timeout=300) as reply, open(archive, "wb") as out:
        shutil.copyfileobj(reply, out)
    found = hashlib.sha256(archive.read_bytes()).hexdigest()
    if found != sha256:
        raise SystemExit(f"{url}: sha256 is {found}, expected {sha256}")
    unpacked = into.parent / (sha256 + ".src")
    with tarfile.open(archive) as tar:
        tar.extractall(unpacked, filter="data")
    # an archive holds one folder, named after the repository and commit
    (top,) = unpacked.iterdir()
    top.rename(into)
    shutil.rmtree(unpacked)
    archive.unlink()


def apply_binding_changes(root: Path) -> None:
    for name, old, new in BINDING_CHANGES:
        path = root / name
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise SystemExit(f"{name}: expected this once, found it {text.count(old)} times:\n{old}")
        path.write_text(text.replace(old, new), encoding="utf-8")


def stamp_version(root: Path, version: str) -> None:
    path = root / "llama_cpp" / "__init__.py"
    text, n = re.subn(r'__version__ = "[^"]+"', f'__version__ = "{version}"', path.read_text(encoding="utf-8"))
    if n != 1:
        raise SystemExit(f"{path}: no __version__ line")
    path.write_text(text, encoding="utf-8")


def prepare(dest: Path) -> Path:
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} is not empty")
    dest.mkdir(parents=True, exist_ok=True)
    root = dest / "llama-cpp-python"
    _fetch(BINDINGS, root)
    vendor = root / "vendor" / "llama.cpp"
    if vendor.exists():
        shutil.rmtree(vendor)  # an empty submodule folder in the archive
    _fetch(LLAMA_CPP, vendor)
    apply_binding_changes(root)
    stamp_version(root, pinned_version())
    return root


if __name__ == "__main__":
    print(prepare(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="llama-source-"))))
