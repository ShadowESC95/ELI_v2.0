"""ELI keeps working when the computer's Python changes underneath it.

A virtual environment is tied to the interpreter it was made with. An operating-system
upgrade that replaces that interpreter (Ubuntu 24.04 -> 26.04 swaps Python 3.12 for 3.14)
left ELI's environment starting as the new version and unable to see one package, so every
launch died with "No module named ...". The same happens on Windows and macOS when the
Python an environment was built from is removed.

scripts/eli_env.py is the one place that knows which interpreter a new install should use,
whether an existing environment still works, and how to mend it. It is standard library
only, because it runs exactly when the environment cannot. The installers and every
launcher call it; these tests run on Linux, macOS and Windows.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "eli_env.py"
_spec = importlib.util.spec_from_file_location("eli_env_under_test", HELPER)
eli_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eli_env)

HERE = (sys.version_info[0], sys.version_info[1])
POSIX = os.name != "nt"
BASE_PYTHON = os.path.realpath(getattr(sys, "_base_executable", "") or sys.executable)


@pytest.fixture()
def install(tmp_path):
    """A stand-in for an ELI folder with a real environment in it."""
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(tmp_path / ".venv")], check=True)
    return tmp_path


def _packages_dir(root: Path) -> Path:
    return root / ".venv" / "lib" / ("python%d.%d" % HERE)


# ── which Python a new install uses ──────────────────────────────────────────

@pytest.mark.parametrize("on_offer,chosen", [
    ([(3, 14), (3, 12)], (3, 12)),          # ready-made packages for the inference engine
    ([(3, 14), (3, 11), (3, 10)], (3, 11)),
    ([(3, 13), (3, 14)], (3, 13)),          # newer than that still installs, building one package
    ([(3, 14)], (3, 14)),                   # the only one there is: use it, do not refuse
    ([(3, 15)], (3, 15)),                   # a version this file has never heard of
    ([(3, 9), (2, 7)], None),               # too old to run ELI
    ([], None),
])
def test_a_new_install_takes_the_python_that_installs_fastest_and_never_refuses_a_new_one(on_offer, chosen):
    assert eli_env.prefer(on_offer) == chosen


def test_the_python_picked_on_this_machine_exists_and_is_new_enough():
    python = eli_env.pick_python()
    assert python and os.path.isfile(python)
    assert eli_env._version_of(python) >= eli_env.MINIMUM


def test_an_interpreter_that_does_not_run_has_no_version(tmp_path):
    assert eli_env._version_of(str(tmp_path / "not-a-python")) is None


# ── whether an environment still works ───────────────────────────────────────

def test_a_fresh_environment_is_fine(install):
    got = eli_env.status(str(install))
    assert got["ok"] is True and got["running"] == HERE


def test_a_folder_with_no_environment_says_so(tmp_path):
    got = eli_env.status(str(tmp_path))
    assert got["ok"] is False and got["why"] == "missing"


@pytest.mark.skipif(not POSIX, reason="the versioned lib/pythonX.Y directory is the POSIX layout")
def test_an_environment_built_for_another_python_is_recognised_and_explained(install, monkeypatch):
    """What an operating-system upgrade leaves behind: the interpreter starts, as a version
    the packages were not installed for."""
    _packages_dir(install).rename(install / ".venv" / "lib" / "python3.99")
    got = eli_env.status(str(install))
    assert got["ok"] is False and got["why"] == "version_changed" and got["built_for"] == (3, 99)
    assert "changed from 3.99 to %d.%d" % HERE in got["say"]
    monkeypatch.setattr(eli_env, "find_python", lambda minor: None)        # no 3.99 anywhere
    mended = eli_env.repair(str(install))
    assert mended["ok"] is False and mended["repaired"] is False
    assert "install.sh" in mended["fix"] and "not touched" in mended["fix"]


@pytest.mark.skipif(not POSIX, reason="on Windows the environment's python.exe is a launcher, not a link")
def test_an_environment_whose_python_has_gone_is_pointed_at_one_of_the_same_version(install, monkeypatch):
    bin_dir = install / ".venv" / "bin"
    for link in bin_dir.iterdir():
        if link.name.startswith("python"):
            link.unlink()
            link.symlink_to(install / "gone" / "python")                   # where the interpreter used to be
    broken = eli_env.status(str(install))
    assert broken["ok"] is False and broken["why"] == "dead_interpreter"
    monkeypatch.setattr(eli_env, "find_python", lambda minor: BASE_PYTHON if minor == HERE else None)
    mended = eli_env.repair(str(install))
    assert mended["ok"] is True and mended["repaired"] is True and "Nothing was reinstalled" in mended["say"]
    assert eli_env.status(str(install))["ok"] is True
    ran = subprocess.run([str(bin_dir / "python"), "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True)
    assert os.path.realpath(ran.stdout.strip()) == os.path.realpath(str(install / ".venv"))


def test_repairing_a_working_environment_changes_nothing(install):
    before = (install / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8")
    got = eli_env.repair(str(install))
    assert got["ok"] is True and got["repaired"] is False
    assert (install / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8") == before


@pytest.mark.skipif(not POSIX, reason="looks an interpreter up by its python3.X name on PATH")
def test_a_python_of_one_version_is_found_by_name(tmp_path, monkeypatch):
    (tmp_path / ("python%d.%d" % HERE)).symlink_to(BASE_PYTHON)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path / "nobody"))
    assert eli_env.find_python(HERE) == str(tmp_path / ("python%d.%d" % HERE))
    assert eli_env.find_python((3, 99)) is None


# ── the command the launchers and installers run ─────────────────────────────

def test_the_command_reports_by_exit_status(install, tmp_path_factory):
    fine = subprocess.run([sys.executable, str(HELPER), "status", str(install)], capture_output=True, text=True)
    assert fine.returncode == 0 and "fine" in fine.stdout
    empty = tmp_path_factory.mktemp("no_install")
    missing = subprocess.run([sys.executable, str(HELPER), "status", str(empty)], capture_output=True, text=True)
    assert missing.returncode == 3
    picked = subprocess.run([sys.executable, str(HELPER), "pick"], capture_output=True, text=True)
    assert picked.returncode == 0 and os.path.isfile(picked.stdout.strip())


def test_the_helper_needs_nothing_but_the_standard_library():
    """It is run by whatever Python can be found, with ELI's own packages out of reach."""
    import ast
    tree = ast.parse(HELPER.read_text(encoding="utf-8"))
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"__future__", "glob", "os", "shutil", "subprocess", "sys", "typing"}


@pytest.mark.skipif(not POSIX, reason="the shell launchers")
def test_a_launcher_starts_a_working_environment_and_explains_a_broken_one(install):
    check = 'source "%s/scripts/eli_isolate_env.sh"; eli_env_ready "$1"' % ROOT
    fine = subprocess.run(["bash", "-c", check, "_", str(install)], capture_output=True, text=True)
    assert fine.returncode == 0 and fine.stdout.strip() == ""               # nothing to say when all is well
    _packages_dir(install).rename(install / ".venv" / "lib" / "python3.99")
    broken = subprocess.run(["bash", "-c", check, "_", str(install)], capture_output=True, text=True,
                            env=dict(os.environ, ELI_ENV_HELPER=str(HELPER)))
    said = broken.stdout + broken.stderr
    assert broken.returncode != 0 and "built for 3.99" in said and "install.sh" in said
    assert "Traceback" not in said and "ModuleNotFoundError" not in said


@pytest.mark.parametrize("script", ["eli.sh", "scripts/eli_launch.sh", "scripts/eli_serve.sh",
                                    "scripts/eli_startup.sh", "scripts/run_eli_repo_venv.sh"])
def test_every_shell_launcher_checks_the_environment_before_starting(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    assert "eli_env_ready" in text, "%s starts ELI without checking its environment" % script


def test_the_windows_launchers_check_the_environment_before_starting():
    assert "eli_env.py" in (ROOT / "eli.bat").read_text(encoding="utf-8")
    assert "eli_env.py" in (ROOT / "scripts" / "eli_serve.ps1").read_text(encoding="utf-8")


def test_the_installers_choose_their_python_and_rebuild_an_environment_that_no_longer_matches():
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    ps = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "eli_env.py" in sh and " pick" in sh
    assert "eli_env.py" in ps and "pick" in ps
    assert "eli_env.py\" status" in sh or "eli_env.py status" in sh
    assert "status" in ps


# ── the voice engine is ELI's own, and it has to run ─────────────────────────

def _fake_tool(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.skipif(not POSIX, reason="uses shell scripts as stand-in programs")
def test_a_piper_that_does_not_run_or_is_another_program_is_passed_over(tmp_path, monkeypatch):
    """Some Linux distributions ship an unrelated `piper` (it configures gaming mice), and a
    `piper` installed for a Python that has since gone still sits on PATH."""
    from eli.perception import tts_router as tts
    other = tmp_path / "other"; stale = tmp_path / "stale"; own = tmp_path / "own"
    for d in (other, stale, own):
        d.mkdir()
    _fake_tool(other / "piper", 'echo "usage: piper [--version]  configure your mouse"')
    _fake_tool(stale / "piper", 'echo "ModuleNotFoundError: No module named piper" >&2; exit 1')
    real = _fake_tool(own / "piper", 'echo "usage: piper --model MODEL --output_file FILE"')
    monkeypatch.setattr(tts, "_packaged_piper_binary_candidates", lambda: [])
    monkeypatch.delenv("ELI_PIPER_BINARY", raising=False)
    monkeypatch.delenv("ELI_PIPER_BIN", raising=False)
    tts._PIPER_RUNS.clear()
    monkeypatch.setattr(tts, "_own_piper_candidates", lambda: [])
    monkeypatch.setenv("PATH", os.pathsep.join([str(other), str(stale)]))
    monkeypatch.setenv("HOME", str(tmp_path / "nobody"))
    assert tts._find_piper_bin() is None                                    # neither is the speech engine
    monkeypatch.setenv("PATH", os.pathsep.join([str(other), str(stale), str(own)]))
    assert tts._find_piper_bin() == str(real)


@pytest.mark.skipif(not POSIX, reason="uses shell scripts as stand-in programs")
def test_elis_own_piper_is_used_before_whatever_is_on_the_path(tmp_path, monkeypatch):
    from eli.perception import tts_router as tts
    mine = tmp_path / "env_bin"; theirs = tmp_path / "path_bin"
    mine.mkdir(); theirs.mkdir()
    own = _fake_tool(mine / "piper", 'echo "usage: piper --model MODEL"')
    _fake_tool(theirs / "piper", 'echo "usage: piper --model MODEL"')
    monkeypatch.setattr(tts, "_packaged_piper_binary_candidates", lambda: [])
    monkeypatch.setattr(tts, "_own_piper_candidates", lambda: [own])
    monkeypatch.delenv("ELI_PIPER_BINARY", raising=False)
    monkeypatch.delenv("ELI_PIPER_BIN", raising=False)
    tts._PIPER_RUNS.clear()
    monkeypatch.setenv("PATH", str(theirs))
    assert tts._find_piper_bin() == str(own)


def test_elis_own_piper_is_looked_for_beside_the_python_that_is_running():
    from eli.perception import tts_router as tts
    beside = {os.path.normcase(str(Path(p).parent)) for p in tts._own_piper_candidates()}
    assert os.path.normcase(str(Path(sys.executable).parent)) in beside
