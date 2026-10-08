"""Every name and window method the GUI code uses exists when it runs, and the window builds.

The Labs tabs take their imports from a shared _common.py with `import *`, so an import that looks
unused there is used by them, and pyflakes cannot follow `import *`. Removing such imports left a
window unable to start (NameError on `deque`) while every test passed, because nothing built it.
tests/_gui_runtime_checks.py looks each name pyflakes cannot resolve up on the module as imported,
and builds the window offscreen.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WINDOW_MODULE = "eli.gui.eli_pro_audio_gui_v2_0"


def _run(what: str, tmp_path, timeout: int = 300) -> dict:
    env = dict(os.environ)
    for key in ("HOME", "USERPROFILE", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
        env[key] = str(tmp_path / "home")
    env.update(ELI_DATA_DIR=str(tmp_path / "data"), ELI_CONFIG_DIR=str(tmp_path / "config"),
               ELI_PERSONA_AUTO_PATH=str(tmp_path / "persona.auto.txt"),
               ELI_WORLD_DIR=str(tmp_path / "world"), ELI_NOTEBOOK_DIR=str(tmp_path / "notebook"),
               ELI_OFFLINE="1", ELI_FORCE_CPU="1", QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([sys.executable, "-m", "tests._gui_runtime_checks", what, WINDOW_MODULE],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert lines, f"exit {proc.returncode}\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    result = json.loads(lines[-1][len("RESULT "):])
    if "skip" in result:
        pytest.skip(result["skip"])
    return result


def test_every_name_resolves_when_the_module_runs(tmp_path):
    missing = _run("names", tmp_path)["missing"]
    assert not missing, "names that do not exist at runtime:\n" + "\n".join(missing)


def test_every_method_the_window_calls_on_itself_exists(tmp_path):
    missing = _run("methods", tmp_path)["missing"]
    assert not missing, "the window calls what it does not have:\n" + "\n".join(missing)


def test_the_window_builds_with_every_tab(tmp_path):
    built = _run("window", tmp_path)
    assert not built["failed"], "tabs that fell back to 'unavailable':\n" + "\n".join(built["failed"])
    assert any("Chat" in t for t in built["tabs"]) and any("Settings" in t for t in built["tabs"])
