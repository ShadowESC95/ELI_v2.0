"""The machine that builds the Linux download decides which systems it runs on.

Built on Ubuntu 24.04 the AppImage needs glibc 2.39: on Ubuntu 22.04 or Debian 12 it fails with
"version `GLIBC_2.38' not found". The workflow built on "ubuntu-latest", which GitHub moves to
a newer Ubuntu from time to time. The image is named now, the floor is measured at build, the
docs state it, and the launcher says it on a system too old.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
BUILD_WORKFLOWS = [p for p in (WORKFLOWS / "release.yml", WORKFLOWS / "gpu-packs.yml") if p.exists()]
FLOOR_TOOL = ROOT / "packaging" / "linux" / "glibc_floor.py"
APPIMAGE_SCRIPT = ROOT / "packaging" / "linux" / "build-appimage-pyinstaller.sh"

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux packaging")


def _linux_images(path: Path) -> list[str]:
    """Every Linux image a workflow's jobs run on, from runs-on and from the os matrix."""
    jobs = yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]
    images: list[str] = []
    for job in jobs.values():
        named = job.get("runs-on")
        if isinstance(named, str) and "${{" not in named:
            images.append(named)
        images.extend(((job.get("strategy") or {}).get("matrix") or {}).get("os") or [])
    return [image for image in images if str(image).startswith("ubuntu")]


def _declared_floor() -> str:
    env = yaml.safe_load((WORKFLOWS / "release.yml").read_text(encoding="utf-8"))["env"]
    return str(env["LINUX_GLIBC_FLOOR"])


def test_the_build_workflows_exist():
    assert (WORKFLOWS / "release.yml") in BUILD_WORKFLOWS


@pytest.mark.parametrize("workflow", BUILD_WORKFLOWS, ids=lambda p: p.name)
def test_what_users_download_is_never_built_on_a_moving_image(workflow):
    images = _linux_images(workflow)
    assert images, f"{workflow.name} builds nothing on Linux?"
    moving = [image for image in images if image.endswith("-latest")]
    assert not moving, (
        f"{workflow.name} builds on {moving}: GitHub repoints that name to a newer Ubuntu, and the "
        "build would then stop starting on the systems it runs on today. Name the image.")


def test_the_app_and_the_gpu_packs_are_built_on_one_image():
    # a pack loads into the app and uses its C++ runtime
    images = {image for workflow in BUILD_WORKFLOWS for image in _linux_images(workflow)}
    assert len(images) == 1, f"Linux builds are spread over {sorted(images)}"


def test_the_floor_is_declared_and_the_build_checks_the_bundle_against_it():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert re.fullmatch(r"\d+\.\d+", _declared_floor())
    check = text.index('glibc_floor.py dist/ELI --max "$LINUX_GLIBC_FLOOR"')
    assert check < text.index("build-appimage-pyinstaller.sh"), "measure before the AppImage is wrapped"


def test_the_documents_state_the_floor_the_build_declares():
    floor = f"glibc {_declared_floor()}"
    for name in ("docs/CROSS_PLATFORM.md", "docs/RELEASE_PIPELINE.md",
                 "blueprints/common_errors_and_fixes.md", "blueprints/installation.md"):
        assert floor in (ROOT / name).read_text(encoding="utf-8"), f"{name} does not say {floor}"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "x86_64.AppImage" in readme:          # a README that offers the download says who it is for
        assert floor in readme, f"README.md offers the AppImage and does not say {floor}"
    assert "any glibc distro" not in readme


def test_the_release_notes_carry_the_floor():
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    notes = text[text.index("Write release notes stub"):]
    assert "needs glibc ${LINUX_GLIBC_FLOOR} or newer" in notes[:1500]



def _run_steps(path: Path):
    for job_name, job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].items():
        for step in job.get("steps") or []:
            if "run" in step:
                yield f"{job_name}: {step.get('name', '?')}", step["run"]


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_no_check_stops_reading_its_pipe_early(workflow):
    # Actions runs bash with pipefail: in `pip list | grep -q x` grep quits at the first match,
    # pip dies on the closed pipe, and the test comes out false exactly when it matched
    early = [name for name, script in _run_steps(workflow)
             if re.search(r"\|\s*grep\s+-[A-Za-z]*q", script)]
    assert not early, f"{workflow.name}: piped grep -q in {early}; read the output into a variable first"


_REPO_FILE = re.compile(r"(?<![\w./-])((?:scripts|packaging|tools)[/\\][\w./\\-]+\.(?:py|sh|ps1|iss|spec|toml))")


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_every_file_a_workflow_runs_is_in_the_repo(workflow):
    # a job that calls a script the repo lost fails only when a release is built
    missing = sorted({path.replace("\\", "/") for _name, script in _run_steps(workflow)
                      for path in _REPO_FILE.findall(script)
                      if not (ROOT / path.replace("\\", "/")).exists()})
    assert not missing, f"{workflow.name} runs files the repo does not have: {missing}"


def test_extras_resolve_torch_from_the_cpu_index_too():
    # an extra pinning its own torch version would take the CUDA build of it from PyPI
    script = next(run for _name, run in _run_steps(WORKFLOWS / "release.yml")
                  if "pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu" in run)
    cpu_index = script.index("export PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu")
    assert cpu_index < script.index('pip install ".[$(echo $REQUIRED_EXTRAS')
    assert cpu_index < script.index("for extra in $OPTIONAL_EXTRAS")


# ── the measuring tool ───────────────────────────────────────────────────────

def _floor(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(FLOOR_TOOL), *args], capture_output=True, text=True)


@pytest.fixture
def a_binary(tmp_path):
    if not shutil.which("readelf"):
        pytest.skip("readelf not installed")
    source = Path(os.path.realpath(sys.executable))
    folder = tmp_path / "bundle"
    folder.mkdir()
    shutil.copy(source, folder / "program")
    (folder / "notes.txt").write_text("not a binary")
    (folder / "link").symlink_to(folder / "program")
    return folder


@linux_only
def test_the_floor_is_read_from_the_binaries(a_binary):
    got = _floor(str(a_binary))
    assert got.returncode == 0, got.stderr
    assert re.fullmatch(r"\d+\.\d+", got.stdout.strip())


@linux_only
def test_a_bundle_needing_more_than_declared_fails_the_build_and_names_the_files(a_binary):
    got = _floor(str(a_binary), "--max", "2.0")
    assert got.returncode == 1
    assert "program" in got.stderr and "declared floor is 2.0" in got.stderr
    assert _floor(str(a_binary), "--max", "99.0").returncode == 0


@linux_only
def test_nothing_to_measure_is_an_error_not_a_pass(tmp_path):
    if not shutil.which("readelf"):
        pytest.skip("readelf not installed")
    (tmp_path / "notes.txt").write_text("no binaries here")
    assert _floor(str(tmp_path)).returncode == 2
    assert _floor(str(tmp_path / "missing")).returncode == 2


def test_versions_compare_as_numbers():
    sys.path.insert(0, str(FLOOR_TOOL.parent))
    try:
        import glibc_floor
    finally:
        sys.path.remove(str(FLOOR_TOOL.parent))
    assert glibc_floor.parse("2.9") < glibc_floor.parse("2.39") < glibc_floor.parse("2.43")


# ── the launcher inside the AppImage ─────────────────────────────────────────

def _apprun() -> str:
    text = APPIMAGE_SCRIPT.read_text(encoding="utf-8")
    start = text.index("cat > \"$APPDIR/AppRun\" <<'EOF'\n") + len("cat > \"$APPDIR/AppRun\" <<'EOF'\n")
    return text[start:text.index("\nEOF\n", start) + 1]


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def appdir(tmp_path):
    """An AppDir with the real launcher and a stand-in for the app."""
    if not shutil.which("bash"):
        pytest.skip("bash not installed")
    root = tmp_path / "ELI.AppDir"
    (root / "usr" / "app").mkdir(parents=True)
    (root / "usr" / "share" / "eli").mkdir(parents=True)
    _executable(root / "AppRun", _apprun())
    _executable(root / "usr" / "app" / "ELI", '#!/bin/bash\necho "APP STARTED $*"\n')
    tools = tmp_path / "tools"
    tools.mkdir()

    def run(*, system: str | None, needs: str | None, args: tuple[str, ...] = ()):
        floor = root / "usr" / "share" / "eli" / "min-glibc"
        if needs is None:
            floor.unlink(missing_ok=True)
        else:
            floor.write_text(needs + "\n")
        # a non-glibc system has no answer
        _executable(tools / "getconf",
                    "#!/bin/bash\n" + (f'echo "glibc {system}"\n' if system else "exit 1\n"))
        for dialog in ("zenity", "kdialog", "notify-send", "xmessage"):
            _executable(tools / dialog, f'#!/bin/bash\necho "$@" > "{tmp_path}/dialog.txt"\n')
        env = dict(os.environ, PATH=f"{tools}{os.pathsep}{os.environ['PATH']}")
        return subprocess.run([str(root / "AppRun"), *args], capture_output=True, text=True,
                              env=env, stdin=subprocess.DEVNULL)

    run.dialog = tmp_path / "dialog.txt"
    return run


@linux_only
@pytest.mark.parametrize("system", ["2.35", "2.36", "2.38", "2.9"])
def test_a_system_too_old_is_told_so_in_a_sentence(appdir, system):
    got = appdir(system=system, needs="2.39")
    assert got.returncode == 1
    assert "APP STARTED" not in got.stdout
    assert "needs glibc 2.39 or newer" in got.stderr and f"has glibc {system}" in got.stderr
    assert "from source" in got.stderr


@linux_only
def test_started_from_a_file_manager_the_sentence_is_shown_in_a_dialog(appdir):
    appdir(system="2.35", needs="2.39")        # stderr is a pipe here, as from a file manager
    assert "needs glibc 2.39 or newer" in appdir.dialog.read_text()


@linux_only
@pytest.mark.parametrize("system", ["2.39", "2.40", "2.43", "3.0"])
def test_a_system_new_enough_starts_the_app_with_its_arguments(appdir, system):
    got = appdir(system=system, needs="2.39", args=("--selftest", "two words"))
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == "APP STARTED --selftest two words"
    assert not appdir.dialog.exists()


@linux_only
def test_the_check_never_blocks_a_start_it_cannot_judge(appdir):
    # no floor in the bundle, or a system that cannot say which glibc it has
    assert appdir(system="2.35", needs=None).stdout.strip() == "APP STARTED"
    assert appdir(system=None, needs="2.39").stdout.strip() == "APP STARTED"


def test_the_appimage_ships_the_floor_it_measured():
    text = APPIMAGE_SCRIPT.read_text(encoding="utf-8")
    assert 'glibc_floor.py" "$APPDIR/usr/app"' in text
    assert text.index("usr/share/eli/min-glibc") < text.index("cat > \"$APPDIR/AppRun\"")
