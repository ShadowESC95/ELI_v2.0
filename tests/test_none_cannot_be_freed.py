"""An extension that drops references to None cannot abort ELI.

PySide6 6.12.0 on Python 3.11 takes one reference to None away on every Qt call that returns nothing;
the window died with "Fatal Python error: none_dealloc: deallocating None" about twenty minutes in.
"""
import pathlib
import shutil
import subprocess
import sys

import pytest

from eli.core import singleton_refs as sr

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_nothing_to_do_where_none_is_immortal():
    if sys.version_info >= (3, 12):
        assert not sr.applies() and sr.pin_singletons() is False
        assert sr.none_refs_lost_per_qt_call() == 0.0


@pytest.mark.skipif(not shutil.which("python3.11"), reason="needs a Python 3.11 interpreter")
def test_before_312_none_gets_a_reserve():
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from eli.core import singleton_refs as sr\n"
            "b = sys.getrefcount(None); sr.pin_singletons()\n"
            "print(sys.getrefcount(None) - b > sr._RESERVE // 2, sr.pin_singletons())" % str(ROOT))
    out = subprocess.run([shutil.which("python3.11"), "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.split() == ["True", "False"], out.stderr   # applied once, not twice


def test_the_frozen_app_is_built_on_a_python_where_none_cannot_be_freed():
    """The bundle was on 3.11, where it can; the GPU packs load into it, so they build on the same one."""
    import re
    versions = [re.search(r'^\s*PYTHON_VERSION:\s*"(\d+)\.(\d+)"', (ROOT / ".github/workflows" / name).read_text(
        encoding="utf-8"), re.M) for name in ("release.yml", "gpu-packs.yml")]
    release, packs = [(int(m.group(1)), int(m.group(2))) for m in versions]
    assert release == packs and release >= (3, 12)


def test_the_frozen_app_reserves_first_and_its_selftest_measures_qt():
    entry = (ROOT / "packaging/pyinstaller/eli_entry.py").read_text(encoding="utf-8")
    assert entry.index("_pin_singletons()") < entry.index("_install_host_env()")
    selftest = entry[entry.index("def _selftest"):entry.index("def _user_root")]
    assert "none_refs_lost_per_qt_call()" in selftest and "raise RuntimeError" in selftest


def test_the_leaking_qt_is_not_installed_before_312():
    py = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "PySide6>=6.5,!=6.12.0; python_version < '3.12'" in py
