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
    assert imported <= {"__future__", "glob", "json", "os", "shutil", "subprocess", "sys", "typing"}


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


# ── making the environment ───────────────────────────────────────────────────
# Debian and Ubuntu ship Python without venv; the installer stopped at its first step.

def test_an_environment_is_made_with_pip_in_it(tmp_path):
    got = eli_env.create(str(tmp_path))
    assert got["ok"], got
    assert eli_env.status(str(tmp_path))["ok"]
    assert subprocess.run([eli_env.venv_python(str(tmp_path)), "-m", "pip", "--version"],
                          capture_output=True).returncode == 0


def test_without_venv_support_the_user_is_told_the_command_and_nothing_is_left_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(eli_env, "_can_make_environments", lambda python: False)
    monkeypatch.setattr(eli_env, "_as_root", lambda command, quiet=False: False)        # needs a password
    monkeypatch.setattr(eli_env.shutil, "which", lambda name: "/usr/bin/" + name if name == "apt-get" else None)
    got = eli_env.create(str(tmp_path))
    assert not got["ok"]
    assert "sudo apt-get install -y python%d.%d-venv" % HERE in got["fix"]
    assert "installer again" in got["fix"]
    assert not (tmp_path / ".venv").exists()


def test_venv_support_is_added_when_that_takes_no_password(tmp_path, monkeypatch):
    ran, made = [], []
    monkeypatch.setattr(eli_env, "_can_make_environments", lambda python: bool(ran))
    monkeypatch.setattr(eli_env, "_as_root", lambda command, quiet=False: ran.append(command) or True)
    monkeypatch.setattr(eli_env, "_make", lambda python, target: made.append(target) or True)
    monkeypatch.setattr(eli_env.shutil, "which", lambda name: "/usr/bin/" + name if name == "apt-get" else None)
    assert eli_env.create(str(tmp_path))["ok"]
    assert ran == [["apt-get", "install", "-y", "python%d.%d-venv" % HERE]]
    assert made == [eli_env.venv_dir(str(tmp_path))]


def test_a_system_with_no_package_lists_yet_refreshes_them_once(tmp_path, monkeypatch):
    ran = []

    def as_root(command, quiet=False):
        ran.append(command[1])
        return ran != ["install"]            # the first install fails: nothing is known about the package

    monkeypatch.setattr(eli_env, "_can_make_environments", lambda python: ran[-2:] == ["update", "install"])
    monkeypatch.setattr(eli_env, "_as_root", as_root)
    monkeypatch.setattr(eli_env, "_make", lambda python, target: True)
    monkeypatch.setattr(eli_env.shutil, "which", lambda name: "/usr/bin/" + name if name == "apt-get" else None)
    assert eli_env.create(str(tmp_path))["ok"]
    assert ran == ["install", "update", "install"]


def test_a_system_whose_package_manager_is_unknown_is_still_told_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(eli_env, "_can_make_environments", lambda python: False)
    monkeypatch.setattr(eli_env.shutil, "which", lambda name: None)
    got = eli_env.create(str(tmp_path))
    assert not got["ok"] and "venv" in got["fix"] and "installer again" in got["fix"]


def test_an_environment_that_could_not_be_made_is_not_left_half_made(tmp_path, monkeypatch):
    def half(python, target):
        os.makedirs(os.path.join(target, "bin"))
        return False

    monkeypatch.setattr(eli_env, "_can_make_environments", lambda python: True)
    monkeypatch.setattr(eli_env, "_make", half)
    assert not eli_env.create(str(tmp_path))["ok"]
    assert not (tmp_path / ".venv").exists()


def test_create_reports_by_exit_status(tmp_path):
    made = subprocess.run([sys.executable, str(HELPER), "create", str(tmp_path)], capture_output=True, text=True)
    assert made.returncode == 0, made.stderr
    assert "Python environment created" in made.stdout


@pytest.mark.parametrize("script", ["install.sh", "scripts/eli_setup.sh", "scripts/safe_install_linux.sh"])
def test_the_installers_make_their_environment_through_the_helper(script):
    text = (ROOT / script).read_text(encoding="utf-8")
    assert 'scripts/eli_env.py" create ' in text
    assert not [line for line in text.splitlines()
                if "-m venv" in line and not line.lstrip().startswith("#")], f"{script} calls venv directly"


# ── filling it, and saying what is in it ─────────────────────────────────────
# pip installs a requirement file all or nothing: one package that would not compile and
# none went in, while the installer's check passed by importing ELI from the source folder.

def test_requirements_are_read_one_to_a_line_without_comments_or_pip_options(tmp_path):
    listing = tmp_path / "requirements.txt"
    listing.write_text(
        "# a heading\n"
        "\n"
        "requests>=2.33\n"
        "llama-cpp-python>=0.3.30  # older ones cannot read some models\n"
        "                          # (a note that runs on)\n"
        "-r another.txt\n"
        "--extra-index-url https://example.invalid/simple\n"
        'audioop-lts>=0.2.1; python_version >= "3.13"\n', encoding="utf-8")
    assert eli_env.requirement_lines(str(listing)) == [
        "requests>=2.33", "llama-cpp-python>=0.3.30", 'audioop-lts>=0.2.1; python_version >= "3.13"']


def test_one_requirement_that_cannot_be_installed_costs_only_itself(tmp_path, monkeypatch):
    listing = tmp_path / "requirements.txt"
    listing.write_text("requests>=2.33\nPyAudio>=0.2\nPySide6>=6.11\n", encoding="utf-8")
    calls = []

    class Done:
        def __init__(self, code):
            self.returncode = code

    def pip(command, **_):
        calls.append(command)
        return Done(1 if command[-1].startswith("PyAudio") else 0)

    monkeypatch.setattr(eli_env.subprocess, "run", pip)
    monkeypatch.setattr(eli_env, "_installed_version", lambda python, requirement: None)
    got = eli_env.install_each(str(tmp_path), str(listing), ["--find-links", "wheels"])
    assert got == {"installed": ["requests>=2.33", "PySide6>=6.11"], "failed": ["PyAudio>=0.2"], "older": {}}
    assert all(c[0] == eli_env.venv_python(str(tmp_path)) and c[1:4] == ["-m", "pip", "install"] for c in calls)
    assert all("--find-links" in c for c in calls)


def test_a_requirement_with_no_build_for_this_python_is_not_called_missing_when_an_older_one_is_there(tmp_path, monkeypatch):
    """On Python 3.10 nothing satisfies onnxruntime>=1.25, but 1.23.2 is installed."""
    listing = tmp_path / "requirements.txt"
    listing.write_text("onnxruntime>=1.25\nPyAudio>=0.2\n", encoding="utf-8")

    class Failed:
        returncode = 1

    monkeypatch.setattr(eli_env.subprocess, "run", lambda command, **_: Failed())
    monkeypatch.setattr(eli_env, "_installed_version",
                        lambda python, requirement: "1.23.2" if requirement.startswith("onnxruntime") else None)
    got = eli_env.install_each(str(tmp_path), str(listing))
    assert got["older"] == {"onnxruntime>=1.25": "1.23.2"}
    assert got["failed"] == ["PyAudio>=0.2"]


def test_the_version_in_the_environment_is_read_by_package_name(install):
    python = eli_env.venv_python(str(install))
    _dist(install, "some-package", [])
    for written in ("some-package>=9", "some-package[extra]>=9", 'some-package >= 9; python_version >= "3.11"', "some-package"):
        assert eli_env._installed_version(python, written) == "1.0", written
    assert eli_env._installed_version(python, "never-installed>=1") is None


@pytest.mark.parametrize("name", ["requirements-full.txt", "requirements-macos.txt", "requirements-windows.txt"])
def test_the_ranged_requirements_can_be_met_on_the_oldest_python_eli_supports(name):
    """onnxruntime>=1.25 and networkx>=3.6 have no Python 3.10 build; the set failed there."""
    lines = eli_env.requirement_lines(str(ROOT / name))
    for package, newest_for_310 in (("onnxruntime", (1, 23)), ("networkx", (3, 4))):
        mine = [line for line in lines if line.split(">=")[0].split(";")[0].strip() == package]
        if not mine:
            continue
        on_310 = [line for line in mine if 'python_version < "3.11"' in line]
        assert on_310, f"{name}: {package} has no requirement a Python 3.10 can meet"
        floor = tuple(int(part) for part in on_310[0].split(">=")[1].split(";")[0].strip().split(".")[:2])
        assert floor <= newest_for_310
        assert all("python_version" in line for line in mine), f"{name}: an unmarked {package} line still applies to 3.10"


def _dist(root: Path, name: str, requires: list) -> None:
    """Put a package's installed-metadata folder into the environment, as pip would."""
    found = subprocess.run([eli_env.venv_python(str(root)), "-c",
                            "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                           capture_output=True, text=True, check=True).stdout.strip()
    info = Path(found) / f"{name.replace('-', '_').replace('.', '_')}-1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: %s\nVersion: 1.0\n%s" % (name, "".join("Requires-Dist: %s\n" % r for r in requires)),
        encoding="utf-8")


@pytest.fixture()
def project(install):
    (install / "pyproject.toml").write_text('[build-system]\nname = "not-this"\n\n[project]\nname = "eli-test.0"\n',
                                            encoding="utf-8")
    return install


def test_the_project_name_is_read_from_its_own_table(project):
    assert eli_env.project_name(str(project)) == "eli-test.0"


def test_a_folder_holding_the_source_is_not_an_installation(project):
    (project / "eli").mkdir()
    (project / "eli" / "__init__.py").write_text("", encoding="utf-8")     # importable from here, installed nowhere
    got = eli_env.verify(str(project))
    assert not got["ok"] and "is not installed" in got["say"]


def test_a_package_eli_cannot_run_without_is_named_when_it_is_missing(project):
    _dist(project, "eli-test.0", ["surely-not-installed-anywhere>=1", 'only-for-a-feature>=1; extra == "full"'])
    got = eli_env.verify(str(project))
    assert not got["ok"]
    assert got["missing"] == ["surely-not-installed-anywhere"]          # the optional one is not an error


def test_an_environment_with_eli_and_what_it_needs_passes(project):
    _dist(project, "eli-test.0", ["the-one-it-needs>=1", 'only-for-a-feature>=1; extra == "full"'])
    _dist(project, "the-one-it-needs", [])
    assert eli_env.verify(str(project))["ok"]


def test_verify_reports_by_exit_status(project):
    assert subprocess.run([sys.executable, str(HELPER), "verify", str(project)], capture_output=True).returncode == 7
    _dist(project, "eli-test.0", [])
    assert subprocess.run([sys.executable, str(HELPER), "verify", str(project)], capture_output=True).returncode == 0


def test_the_installer_installs_what_it_builds_with_first_and_ends_on_what_it_found():
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    body = text[text.index("\nattempt_build_prereqs\n"):]                  # from the call on
    assert body.index("attempt_build_prereqs") < body.index('eli_env.py" create ')
    assert body.index('eli_env.py" create ') < body.index('install -e ".[full]"')
    assert 'install -e . --no-deps' in body                               # ELI itself, whatever else fails
    assert 'eli_env.py" install-each "$SCRIPT_DIR" "$RANGES"' in body      # then one at a time, by range
    assert 'eli_env.py" verify "$SCRIPT_DIR"' in body
    assert '"$PYTHON_VENV" -c "import eli"' not in text                    # the check the folder could satisfy
    assert text.rstrip().endswith('[ "$VERIFY_OK" -eq 1 ] || exit 1')
    # the summary does not report an inference engine that failed to build
    summary = text[text.index('section "Summary"'):]
    assert summary.index('import llama_cpp') < summary.index('ok "Build ') < summary.index('llama-cpp NOT installed')


@pytest.mark.skipif(not POSIX or not __import__("shutil").which("bash"), reason="runs the installer's own shell function")
@pytest.mark.parametrize("root,can_add", [(False, False), (True, True)])
def test_a_system_without_what_the_install_builds_with(tmp_path, root, can_add):
    """An ordinary user gets the one command and the install stops; root gets them added."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    start = text.index("attempt_build_prereqs() {")
    function = text[start:text.index("\n}\n", start) + 3]
    tools = tmp_path / "tools"
    tools.mkdir()

    def tool(name, body):
        path = tools / name
        path.write_text("#!/bin/bash\n" + body, encoding="utf-8")
        path.chmod(0o755)

    added = tmp_path / "added"
    # no venv and no headers until the system packages are there
    tool("python-here", f'case "$2" in *version_info*) echo 3.10 ;; *) [ -e "{added}" ] ;; esac\n')
    tool("apt-get", f'echo "apt-get $*" >> "{tmp_path}/ran"; [ "$1" = install ] && touch "{added}"; exit 0\n')
    tool("sudo", "exit 1\n")                                  # would ask for a password
    tool("id", "echo %d\n" % (0 if root else 1000))
    script = (f'set -euo pipefail\nOS=Linux\nPYTHON="{tools}/python-here"\n'
              'info(){ echo "[..] $*"; }; ok(){ echo "[OK] $*"; }; warn(){ echo "[WARN] $*"; }\n'
              + function + '\nattempt_build_prereqs\necho CARRIED-ON\n')
    got = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         env=dict(os.environ, PATH=f"{tools}{os.pathsep}{os.environ['PATH']}"))
    if can_add:
        assert got.returncode == 0 and "CARRIED-ON" in got.stdout, got.stdout + got.stderr
        ran = (tmp_path / "ran").read_text()
        assert "python3.10-venv" in ran and "python3.10-dev" in ran and "libgl1" in ran and "libegl1" in ran
    else:
        assert got.returncode == 1 and "CARRIED-ON" not in got.stdout
        assert "sudo apt-get install -y" in got.stdout and "python3.10-venv" in got.stdout and "python3.10-dev" in got.stdout
        assert "libgl1" in got.stdout
        assert not (tmp_path / "ran").exists()


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


# ── system libraries ELI cannot carry ────────────────────────────────────────
# On a system without libGL the window failed with "Please install PySide6". The graphics
# libraries belong to the GPU driver, so they are named and installed, not bundled.

def _only(monkeypatch, pc, *tools):
    """A system that has just these package tools."""
    monkeypatch.setattr(pc.shutil, "which", lambda name: "/usr/bin/" + name if name in tools else None)


@pytest.mark.parametrize("tool,asks_for", [
    ("apt-get", "sudo apt-get install -y libgl1"),                 # Debian names the package after the library
    ("dnf", "sudo dnf install -y 'libGL.so.1()(64bit)'"),          # rpm installs by library name
    ("zypper", "sudo zypper install 'libGL.so.1()(64bit)'"),
    ("apk", "sudo apk add so:libGL.so.1"),                         # so does Alpine
    ("pacman", "sudo pacman -S --needed libglvnd"),                # Arch does not: listed
])
def test_a_missing_system_library_is_named_with_the_command_that_installs_it(monkeypatch, tool, asks_for):
    from eli.utils import platform_compat as pc
    _only(monkeypatch, pc, tool)
    said = pc.missing_library_hint(ImportError("libGL.so.1: cannot open shared object file: No such file or directory"))
    assert "libGL.so.1" in said and said.endswith(asks_for)


@pytest.mark.parametrize("library,package", [
    ("libGL.so.1", "libgl1"), ("libEGL.so.1", "libegl1"), ("libfontconfig.so.1", "libfontconfig1"),
    ("libdbus-1.so.3", "libdbus-1-3"), ("libxkbcommon-x11.so.0", "libxkbcommon-x11-0"),
    ("libxcb-render-util.so.0", "libxcb-render-util0"), ("libX11-xcb.so.1", "libx11-xcb1"),
    ("libgssapi_krb5.so.2", "libgssapi-krb5-2"), ("libportaudio.so.2", "libportaudio2"),
    ("libglib-2.0.so.0", "libglib2.0-0"), ("libgthread-2.0.so.0", "libglib2.0-0"), ("libharfbuzz.so.0", "libharfbuzz0b"),
])
def test_debian_names_a_package_after_its_library(monkeypatch, library, package):
    from eli.utils import platform_compat as pc
    _only(monkeypatch, pc, "apt-get")
    assert pc._debian_package(library) == package


def test_a_package_apt_has_never_heard_of_is_not_suggested(monkeypatch):
    from eli.utils import platform_compat as pc
    _only(monkeypatch, pc, "apt-get", "apt-cache")

    class Known:
        def __init__(self, yes):
            self.returncode = 0 if yes else 100

    monkeypatch.setattr(pc.subprocess, "run", lambda command, **_: Known(command[-1] == "libgl1"))
    command, unknown = pc.install_command(["libGL.so.1", "libsomething-odd.so.12"])
    assert command == "sudo apt-get install -y libgl1" and unknown == ["libsomething-odd.so.12"]
    said = pc.explain_missing_libraries(["libGL.so.1", "libsomething-odd.so.12"])
    assert "For libsomething-odd.so.12, install the package that provides it" in said


def test_several_missing_libraries_come_as_one_command(monkeypatch):
    from eli.utils import platform_compat as pc
    _only(monkeypatch, pc, "apt-get")
    said = pc.explain_missing_libraries(["libGL.so.1", "libfontconfig.so.1", "libgthread-2.0.so.0", "libglib-2.0.so.0"])
    assert said.endswith("sudo apt-get install -y libgl1 libfontconfig1 libglib2.0-0")       # one package, once
    assert "system libraries" in said and "Install them" in said


def test_a_system_with_no_known_package_tool_is_still_told_which_library(monkeypatch):
    from eli.utils import platform_compat as pc
    _only(monkeypatch, pc)
    said = pc.missing_library_hint(OSError("libGL.so.1: cannot open shared object file"))
    assert "libGL.so.1" in said and "package that provides it" in said and "sudo" not in said


@pytest.mark.parametrize("error", ["No module named 'PySide6'", "DLL load failed while importing QtCore", ""])
def test_an_error_that_is_not_a_missing_library_gets_no_hint(error):
    from eli.utils.platform_compat import missing_library_hint
    assert missing_library_hint(ImportError(error)) is None


def test_every_library_qt_lacks_is_found_at_once(monkeypatch, tmp_path):
    """An import stops at the first missing library: libGL, then libfontconfig, then the next."""
    from eli.utils import platform_compat as pc
    qt = tmp_path / "PySide6" / "Qt" / "lib"
    qt.mkdir(parents=True)
    for name in ("libQt6Core.so.6", "libQt6Gui.so.6"):
        (qt / name).write_text("")
    monkeypatch.setattr(pc, "LINUX", True)
    monkeypatch.setattr(pc.shutil, "which", lambda name: "/usr/bin/" + name)

    class Spec:
        submodule_search_locations = [str(tmp_path / "PySide6")]

    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: Spec())
    listing = {"libQt6Core.so.6": "\tlibglib-2.0.so.0 => not found\n\tlibc.so.6 => /lib/libc.so.6 (0x1)\n",
               "libQt6Gui.so.6": "\tlibGL.so.1 => not found\n\tlibfontconfig.so.1 => not found\n"
                                 "\tlibglib-2.0.so.0 => not found\n\tlibQt6Core.so.6 => not found\n"}

    class Out:
        def __init__(self, text):
            self.stdout = text

    monkeypatch.setattr(pc.subprocess, "run", lambda command, **_: Out(listing[Path(command[-1]).name]))
    assert pc.missing_qt_libraries() == ["libglib-2.0.so.0", "libGL.so.1", "libfontconfig.so.1"]


_BROKEN_QT = """
import importlib.abc, sys
class Broken(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        top = name.split(".")[0]
        if top == "PySide6":
            raise %s
        if top in ("PyQt6", "PyQt5"):
            raise ModuleNotFoundError("No module named " + repr(top), name=top)
sys.meta_path.insert(0, Broken())
import eli.gui.eli_pro_audio_gui_v2_0
"""


@pytest.mark.parametrize("failure,says,never", [
    ('ImportError("libGL.so.1: cannot open shared object file: No such file or directory")', "libGL.so.1", "not installed"),
    ('ModuleNotFoundError("No module named \'PySide6\'", name="PySide6")', "is not installed", "libGL"),
    ('ImportError("something else went wrong inside Qt")', "installed but did not load: something else went wrong", "not installed."),
])
def test_the_window_says_why_its_toolkit_did_not_load(failure, says, never):
    got = subprocess.run([sys.executable, "-c", _BROKEN_QT % failure], capture_output=True, text=True, cwd=str(ROOT),
                         env=dict(os.environ, ELI_OFFLINE="1", QT_QPA_PLATFORM="offscreen"))
    assert got.returncode == 1
    last = [line for line in got.stdout.splitlines() if line.strip()][-1]
    assert "window cannot start" in last and says in last and never not in last
    assert "Please install PySide6" not in got.stdout


def test_the_reason_reaches_a_console_that_cannot_print_the_symbol():
    """On Windows (cp1252) the cross symbol raised UnicodeEncodeError and the reason was lost."""
    failure = 'ModuleNotFoundError("No module named \'PySide6\'", name="PySide6")'
    got = subprocess.run([sys.executable, "-c", _BROKEN_QT % failure], capture_output=True, cwd=str(ROOT),
                         env=dict(os.environ, ELI_OFFLINE="1", QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="cp1252"))
    assert got.returncode == 1
    assert b"window cannot start" in got.stdout and b"is not installed" in got.stdout
    assert b"UnicodeEncodeError" not in got.stderr


def test_the_debian_package_depends_on_what_the_install_builds_with_and_the_window_loads():
    text = (ROOT / "packaging" / "debian" / "build-deb.sh").read_text(encoding="utf-8")
    depends = [line for line in text.splitlines() if line.startswith("Depends:")][0]
    for package in ("python3-venv", "python3-dev", "build-essential", "portaudio19-dev", "libgl1", "libegl1", "libxcb-cursor0"):
        assert package in depends, package


@pytest.mark.skipif(not POSIX, reason="a script whose interpreter is gone is a POSIX case")
def test_a_piper_whose_python_has_gone_is_passed_over_without_a_traceback(tmp_path, caplog):
    """An old environment's piper names a Python that is gone. That is what the check is for,
    and it printed a traceback at every start."""
    from eli.perception import tts_router
    stale = tmp_path / "piper"
    stale.write_text("#!/nonexistent/python3\nprint('never runs')\n")
    stale.chmod(0o755)
    tts_router._PIPER_RUNS.pop(str(stale), None)
    with caplog.at_level("DEBUG"):
        assert tts_router._piper_runs(str(stale)) is False
    assert "passed over" in caplog.text
    assert "Traceback" not in caplog.text and not any(r.exc_info for r in caplog.records)


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
