"""Install script regressions — catch fresh-clone failures before users hit them."""
from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_install_sh_does_not_use_set_e_unsafe_wheel_lookup():
    text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    assert "WHEEL=$(ls" not in text, (
        "install.sh must not use WHEEL=$(ls ...) under set -e — ls fails when no wheel exists and aborts the installer"
    )
    assert 'install -e ".[full]"' in text or "install -e '.[full]'" in text


def _wheel_lookup_line() -> str:
    text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.startswith("WHEEL=") and "$(" in line]
    assert len(lines) == 1, lines
    return lines[0]


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="runs the installer's own shell line")
def test_a_clone_with_no_built_wheel_gets_past_the_wheel_lookup(tmp_path):
    """The guard above looks for one spelling; the line was rewritten with quotes and every
    clone install ended there, exit 2, no message. Run the line itself under set -euo pipefail."""
    script = "set -euo pipefail\nSCRIPT_DIR=%s\n%s\necho \"wheel=[$WHEEL]\"\n"
    empty = subprocess.run(["bash", "-c", script % (shlex.quote(str(tmp_path)), _wheel_lookup_line())],
                           capture_output=True, text=True)
    assert empty.returncode == 0, "the installer would stop here on a fresh clone"
    assert empty.stdout.strip() == "wheel=[]"

    dist = tmp_path / "dist"
    dist.mkdir()
    name = _wheel_lookup_line().split("/dist/", 1)[1].split("*", 1)[0]      # the wheel's name stem
    for version in ("2.9.0", "2.10.0"):
        (dist / f"{name}{version}-py3-none-any.whl").write_text("")
    found = subprocess.run(["bash", "-c", script % (shlex.quote(str(tmp_path)), _wheel_lookup_line())],
                           capture_output=True, text=True)
    assert found.stdout.strip().endswith("2.10.0-py3-none-any.whl]"), found.stdout     # newest, not first


# ── shipped shell scripts must run on the bash every Mac has (3.2) ─────────
def _sh_code():
    """(file, line number, line) for every code line of every shipped shell script."""
    root = Path(__file__).resolve().parents[1]
    try:
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "*.sh"],
                                capture_output=True, text=True, timeout=30)
        names = listed.stdout.split() if listed.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        names = []
    files = ([root / n for n in names] if names else
             sorted(p for p in root.rglob("*.sh") if not (_PS1_SKIP_DIRS & set(p.relative_to(root).parts))))
    assert files, "no shell scripts found"
    for path in files:
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if not line.lstrip().startswith("#"):
                yield path.relative_to(root).as_posix(), number, line


def test_shell_scripts_expand_arrays_the_way_the_bash_on_a_mac_accepts():
    """macOS ships bash 3.2, which under `set -u` reads "${ARR[@]}" of an empty array as an unset
    variable. install.sh stopped at its first pip call on every Mac ("_PIP_LINKS[@]: unbound
    variable") and the launcher stopped when started with no arguments. ${ARR[@]+"${ARR[@]}"}
    is the same expansion, accepted empty; ${ARR[*]-} likewise inside a string."""
    plain = re.compile(r'(?<!\+)"\$\{[A-Za-z_][A-Za-z0-9_]*\[@\]\}"|\$\{[A-Za-z_][A-Za-z0-9_]*\[\*\]\}')
    bad = [f"{name}:{number}" for name, number, line in _sh_code() if plain.search(line)]
    assert not bad, f"array expansions bash 3.2 rejects when the array is empty: {bad}"
    assert plain.search('pip install "${LINKS[@]}" x') and plain.search('echo "all: ${LINKS[*]}"')
    assert not plain.search('pip install ${LINKS[@]+"${LINKS[@]}"} x') and not plain.search('"${LINKS[*]-}"')


def test_shell_scripts_use_nothing_newer_than_the_bash_on_a_mac():
    newer = re.compile(r"\b(mapfile|readarray|coproc)\b|\b(declare|local|typeset)\s+-[a-zA-Z]*A\b"
                       r"|\$\{[A-Za-z_][A-Za-z0-9_]*(,,|\^\^)|\|&|&>>|;;&")
    bad = [f"{name}:{number}" for name, number, line in _sh_code() if newer.search(line)]
    assert not bad, f"bash 4 constructs in shipped shell scripts: {bad}"


def test_install_ps1_uses_editable_dot_full_not_scriptdir_subscript():
    text = (Path(__file__).resolve().parents[1] / "install.ps1").read_text(encoding="utf-8")
    assert '$ScriptDir[full]' not in text, "PowerShell treats $ScriptDir[full] as indexing, not pip extras syntax"
    assert '.[full]' in text


# ── shipped PowerShell must survive Windows PowerShell 5.1 ─────────────────
# Directories that are not the shipped tree: virtualenvs, build output, and
# the per-session git worktrees under .claude/ that other agents work in.
_PS1_SKIP_DIRS = {".venv", "venv", "build", "dist", ".git", ".claude",
                  "node_modules", "__pycache__"}


def _ps1_files():
    # by the path inside the tree: a checkout that is itself under .claude/ (a worktree) found none
    root = Path(__file__).resolve().parents[1]
    files = sorted(p for p in root.rglob("*.ps1")
                   if not (_PS1_SKIP_DIRS & set(p.relative_to(root).parts)))
    assert files, "no PowerShell scripts found"
    return files


def test_shipped_ps1_is_pure_ascii():
    """PS5.1 reads a BOM-less file as the system ANSI codepage, which turns a
    UTF-8 em-dash into a smart quote that closes the enclosing string and
    breaks the script at parse time."""
    bad = {}
    for p in _ps1_files():
        raw = p.read_bytes()
        body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        offenders = sorted({b for b in body if b > 0x7E or (b < 0x09 and b != 0x00)})
        if offenders:
            bad[p.name] = [hex(b) for b in offenders[:8]]
    assert not bad, f"non-ASCII bytes in shipped PowerShell: {bad}"


def test_shipped_ps1_has_utf8_bom():
    missing = [p.name for p in _ps1_files() if not p.read_bytes().startswith(b"\xef\xbb\xbf")]
    assert not missing, f"PowerShell files missing the UTF-8 BOM: {missing}"


def test_shipped_ps1_uses_crlf_throughout():
    mixed = {}
    for p in _ps1_files():
        raw = p.read_bytes()
        # Counted outside the f-string on purpose: a backslash inside an
        # f-string expression is a SyntaxError before Python 3.12 (PEP 701),
        # and this project still supports 3.10.
        lf, crlf = raw.count(b"\n"), raw.count(b"\r\n")
        if lf != crlf:
            mixed[p.name] = f"{lf} LF vs {crlf} CRLF"
    assert not mixed, f"PowerShell files with mixed line endings: {mixed}"


# ── a print never ends a run ───────────────────────────────────────────────
def test_printing_never_stops_the_program_on_a_stream_that_is_not_unicode():
    """On Windows any redirected or piped output uses the legacy code page, which has no arrow:
    the installer's shortcut step printed one and died with UnicodeEncodeError whenever its
    output was being read (the graphical installer, a build job). Importing ELI makes the
    streams write "?" for what they cannot show."""
    root = Path(__file__).resolve().parents[1]
    code = "import eli; print('ready \u2192 \u2713 \U0001F680'); import sys; print('still here', file=sys.stderr)"
    env = dict(__import__("os").environ, PYTHONIOENCODING="cp1252", PYTHONPATH=str(root))
    env.pop("PYTHONUTF8", None)
    ran = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, cwd=str(root))
    assert ran.returncode == 0, ran.stderr.decode("cp1252", "replace")
    assert ran.stdout.decode("cp1252").strip() == "ready ? ? ?"
    without = subprocess.run([sys.executable, "-c", code.replace("import eli; ", "")],
                             capture_output=True, env=env, cwd=str(root))
    assert without.returncode != 0, "the check proves nothing if this stream took the arrow anyway"


def test_the_windows_installer_reports_its_own_result_not_its_last_optional_step_s():
    code = _ps1_code().rstrip()
    assert code.endswith("exit 0"), "a completed install ended with the shortcut step's exit code"
    after_shortcuts = code.split("install_desktop_apps.ps1\"", 1)[1]
    assert after_shortcuts.lstrip().startswith("if ($LASTEXITCODE -ne 0)"), "a failed shortcut step is said, not passed on"


def test_on_windows_pip_is_run_as_a_module_never_as_pip_exe():
    """pip.exe cannot replace itself while it runs, and says so with an error. "Upgrading pip"
    was the installer's first step: it ended there on every Windows Python that came with a pip
    older than the newest one."""
    code = _ps1_code()
    assert "pip.exe" not in code and "$Pip " not in code
    assert "& $PythonVenv -m pip @Arguments" in code


# Windows PowerShell 5.1 turns each line a program writes to a redirected stderr (2>$null, 2>&1,
# *>$null) into an error record, and under $ErrorActionPreference = "Stop" the first one ends the
# script though the program succeeded. One function relaxes the preference for its own call and is
# the only place a program's streams are redirected while "Stop" is in force.
_NATIVE_HELPER = ("eli_native.ps1", "Invoke-Native")
_STREAM_REDIRECT = re.compile(r"(?<![\w$])[2*]>(?:>|&1)?")
_STOP = re.compile(r"""^\s*\$ErrorActionPreference\s*=\s*["']Stop["']""", re.M | re.I)
_DOT_SOURCED = re.compile(r"""^\s*\.\s+.*?([\w.-]+\.ps1)\b""", re.M)


def _ps1_statements(path):
    """(line number, code) for each line of a PowerShell file, without comments, here-strings and
    single-quoted strings: a redirect written in a message or a comment is not one."""
    ends = None
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if ends:
            if not line.startswith(ends) and ends != "#>":
                continue
            if ends == "#>":
                if "#>" not in line:
                    continue
                line = line.split("#>", 1)[1]
            else:
                line = line[len(ends):]
            ends = None
        code = re.sub(r"'(?:[^']|'')*'", "''", line)
        if "<#" in code:
            code, ends = code.split("<#", 1)[0], "#>"
        code = re.split(r"(?:^|\s)#", code, maxsplit=1)[0]
        if code.rstrip().endswith(("@'", '@"')):
            ends = code.rstrip()[-1] + "@"
        if code.strip():
            yield number, code


def _redirects_under_stop():
    files = _ps1_files()
    stop = {p for p in files if _STOP.search(p.read_text(encoding="utf-8-sig"))}
    # a file dot-sourced by one of them runs under its preference
    sourced = {name for p in stop for name in _DOT_SOURCED.findall(p.read_text(encoding="utf-8-sig"))}
    stop |= {p for p in files if p.name in sourced}
    found = []
    for path in sorted(stop):
        helper_body = False
        for number, code in _ps1_statements(path):
            if path.name == _NATIVE_HELPER[0] and re.match(rf"function\s+{_NATIVE_HELPER[1]}\b", code):
                helper_body = True
            elif helper_body and code.rstrip() == "}":
                helper_body = False
            elif not helper_body and _STREAM_REDIRECT.search(code):
                found.append(f"{path.name}:{number}: {code.strip()}")
    return stop, found


def test_no_powershell_probe_redirects_a_program_s_stderr_while_stop_is_in_force():
    """install.ps1 dropped stderr with 2>$null on `import eli`, the Qt check, nvidia-smi and winget, and
    eli_serve.ps1 on its Python and voice checks: on Windows PowerShell 5.1 a warning printed there
    stopped the script. They go through Invoke-Native, which relaxes the preference for its call."""
    for bad in ('& $Py -c "import sys" 2>$null | Out-Null', "winget install --id $id --silent 2>$null",
                "& nvidia-smi --query-gpu=name 2>&1", "& $PythonVenv -c $Code *> $null", "x 2>>log.txt"):
        assert _STREAM_REDIRECT.search(bad), bad
    for fine in ("& $Py -m pip install x | Out-Null", "$n -ge 2", "Get-Item x -ErrorAction SilentlyContinue",
                 "@(& $Py $EnvHelper versions)[0]"):
        assert not _STREAM_REDIRECT.search(fine), fine
    stop, found = _redirects_under_stop()
    assert {"install.ps1", "eli_serve.ps1"} <= {p.name for p in stop}
    assert not found, f"a program's stderr redirected while Stop is in force, outside {_NATIVE_HELPER[1]}: {found}"

    helper = next(p for p in _ps1_files() if p.name == _NATIVE_HELPER[0])
    body = helper.read_text(encoding="utf-8-sig")
    body = body[body.index(f"function {_NATIVE_HELPER[1]}"):]
    body = body[:body.index("\n}")]
    assert body.index('$ErrorActionPreference = "Continue"') < body.index("2>&1"), "the helper does not relax Stop"
    assert "$LASTEXITCODE" in body and "catch" in body
    for script in ("install.ps1", "eli_serve.ps1"):
        text = next(p for p in _ps1_files() if p.name == script).read_text(encoding="utf-8-sig")
        assert re.search(r'^\. \(Join-Path \$\w+ "scripts\\eli_native\.ps1"\)', text, re.M), f"{script} does not load the helper"


def test_no_powershell_script_escapes_a_quote_with_a_backslash():
    """PowerShell has no backslash escape: \\" ends a double-quoted string. The capability step
    handed Python half a line of code and failed on every Windows install, unseen, because the
    shipped manifest was used in its place."""
    bad = []
    for path in _ps1_files():
        for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if not line.lstrip().startswith("#") and re.search(r'-c\s+".*\\"', line):
                bad.append(f"{path.name}:{number}")
    assert not bad, bad


def test_both_installers_install_eli_within_the_lock_and_fall_back_the_same_way():
    """The newest of everything was installed first and the lock replaced it: every fresh
    install kept the newest Qt's add-on packages beside the locked Qt. And on Windows a lock
    that could not be met ended the installer, where install.sh went on to the ranges."""
    sh = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    assert '_LOCKED=(-c "$REQ")' in sh
    assert sh.index('_LOCKED=(-c "$REQ")') < sh.index('_pip install -e ".[full]"') < sh.index("--ignore-installed")
    ps = _ps1_code()
    assert '$Locked = @("-c", $RequirementsFile)' in ps and "@EliTarget @Locked" in ps
    assert ps.index("@EliTarget @Locked") < ps.index("-r $RequirementsFile --quiet")
    for installer in (sh, ps):
        assert "install-each" in installer and "one at a time" in installer


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="runs the installer's own shell function")
def test_the_dependency_install_keeps_the_inference_engine_built_for_this_gpu(tmp_path):
    """requirements.txt (--latest) and requirements-macos.txt list llama-cpp-python, and the set is
    installed over what is there (--ignore-installed): pip put a plain PyPI build, made again without
    the GPU flags, over the one the installer had just built for this machine's GPU."""
    sh = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    start = sh.index("_ENGINE_LINE=")
    end = sh.index("\n}\n", sh.index("_requirements_but_the_installed_engine() {")) + 3
    req = tmp_path / "requirements.txt"
    req.write_text("PySide6>=6.5\nllama-cpp-python>=0.3.35  # the engine\nLlama_CPP_Python==0.3.36\n"
                   "llama-cpp-python-extras\nnumpy\n", encoding="utf-8")
    pythons = {}
    for name, code in (("with-engine", 0), ("without-engine", 1)):
        pythons[name] = tmp_path / name
        pythons[name].write_text("#!/bin/sh\nexit %d\n" % code, encoding="utf-8")
        pythons[name].chmod(0o755)
    script = 'set -euo pipefail\nPYTHON_VENV="$1"\n%s\n_requirements_but_the_installed_engine "$2"\n' % sh[start:end]

    def install_from(python):
        ran = subprocess.run(["bash", "-c", script, "_", str(python), str(req)], capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
        return Path(ran.stdout.strip())

    copy = install_from(pythons["with-engine"])
    assert copy != req and copy.parent == req.parent              # beside it: its -r/-c lines still read
    assert copy.read_text(encoding="utf-8").splitlines() == ["PySide6>=6.5", "llama-cpp-python-extras", "numpy"]
    assert install_from(pythons["without-engine"]) == req          # no engine yet: the file as it is
    assert '-r "$REQ_INSTALL" --quiet --ignore-installed' in sh and 'rm -f "$REQ_INSTALL"' in sh


# ── the Windows GPU path ───────────────────────────────────────────────────
def _ps1_text() -> str:
    return (Path(__file__).resolve().parents[1] / "install.ps1").read_text(encoding="utf-8-sig")


def _ps1_code() -> str:
    """install.ps1 with whole-line comments removed.

    Structural checks must read code, not the comments explaining which flag
    used to be wrong -- those legitimately name the old broken value.
    """
    return "\n".join(line for line in _ps1_text().splitlines()
                      if not line.strip().startswith("#"))


def test_declining_the_model_prompt_on_windows_skips_only_the_chat_model():
    """Answering "n" set -NoModel, and -NoModel also skips the embedder memory and recall need;
    install.sh's answer skips the chat model alone."""
    code = _ps1_code()
    prompt = code[code.index("Choose model(s) to download now?"):]
    answer = prompt[:prompt.index("\n    }")]
    assert "$NoModel" not in answer, "the model prompt's answer still turns on -NoModel"
    assert "$ChooseModel = -not ($m -match '^[Nn]')" in answer
    embedder = code[code.index("eli.core.model_download --aux") - 300:code.index("eli.core.model_download --aux")]
    assert "if (-not $NoModel)" in embedder and "ChooseModel" not in embedder


def test_windows_installer_detects_more_than_nvidia():
    """nvidia-smi was the only detector, so AMD and Intel Arc machines were
    told they had no GPU at all and silently got a CPU-only build."""
    text = _ps1_text()
    assert "Win32_VideoController" in text, "no vendor-neutral GPU enumeration"
    for vendor in ("amd|radeon", "intel|arc"):
        assert vendor in text, f"installer never recognises {vendor}"


def test_windows_installer_cannot_fall_into_a_source_build():
    """--prefer-binary lets pip build from source when no wheel matches, unannounced. That
    needs MSVC, and its failure aborted the installer right after the GPU
    accelerator step. The CUDA step takes a wheel or nothing; the build that follows
    is said first and does not end the install (the test after the next)."""
    code = _ps1_code()
    llama = code[code.index("llama-cpp-python (CUDA"):]
    assert "--only-binary=:all:" in llama, "source build is still reachable"
    assert "--prefer-binary" not in llama, "--prefer-binary re-enables the source build"


def test_windows_installer_falls_back_to_cpu_wheel():
    llama = _ps1_code()
    llama = llama[llama.index("llama-cpp-python (CUDA"):]
    assert "$llamaCudaOk" in llama, "no fallback path when the CUDA wheel is missing"
    # After falling back it must stop claiming a GPU build.
    assert "$CpuOnly = $true" in llama, "fallback does not correct the build label"


def test_with_no_ready_made_engine_the_windows_installer_builds_one_and_goes_on():
    """PyPI publishes llama-cpp-python as source only. When the CUDA index had nothing new enough,
    install.ps1 fell back to --only-binary from PyPI, which cannot succeed, and Invoke-Pip's error
    ended the installer; the CPU path and the older-CPU repair counted on a PyPI wheel the same way."""
    code = _ps1_code()
    llama = code[code.index("Eli-Progress -Phase llama"):code.index("Eli-Progress -Phase eli")]
    for call in re.findall(r"Invoke-Pip[^\n]*", llama):
        assert "--extra-index-url" in call, f"a pip step that can only fail stops the installer: {call}"
    build = llama[llama.index("function Build-LlamaHere"):]
    build = build[:build.index("\n}\n")]
    assert "--no-binary llama-cpp-python" in build and "Invoke-Pip" not in build and "throw" not in build
    assert "BuildTools" in build, "a failed build does not say what it needs"
    # the CPU path, the CUDA wheel missing, the older-CPU repair and the -InstallCuda rebuild
    assert llama.count("Build-LlamaHere -Reason") == 4
    assert '-CmakeArgs "-DGGML_NATIVE=ON"' in llama, "the repair is not built for this CPU"
    # a check of an engine that may be missing never goes through PowerShell's error stream: each one
    # is Test-VenvPython, which runs it through Invoke-Native
    probes = [line for line in llama.splitlines() if "$PythonVenv -c" in line]
    assert probes == [], probes
    check = code[code.index("function Test-VenvPython"):]
    assert 'return ((Invoke-Native $PythonVenv @("-c", $Code)).ExitCode -eq 0)' in check[:check.index("\n}\n")]
    assert code.index("function Test-VenvPython") < code.index("Test-VenvPython \"import sys, torch"), \
        "the PyTorch check runs before the function is defined"
    assert "if ($BuildWarn)" in code and "llama-cpp $BuildLabel" in code


def test_windows_installer_explains_the_fallback():
    """A silent downgrade to CPU is how 0 GPU layers became a mystery."""
    text = _ps1_text()
    assert "No prebuilt CUDA" in text
    assert "-InstallCuda" in text and "cu124" in text, "no remedy offered"


# ── the CUDA wheel index is stale; installers must not silently take it ────
def _sh_text() -> str:
    return (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")


LLAMA_MIN_FOR_MODERN_GGUF = "0.3.35"   # hybrid GGUFs need 0.3.30; load planning needs 0.3.35


def test_requirements_demand_a_runtime_that_reads_current_ggufs():
    """Below 0.3.30 a hybrid attention+SSM GGUF (qwen35, nemotron-h) fails with
    a missing ssm_conv1d tensor, which surfaced to the user as a bogus 'llama
    sampler' error."""
    root = Path(__file__).resolve().parents[1]
    seen = 0
    for name in ("requirements-full.txt", "requirements-macos.txt", "requirements-windows.txt"):
        p = root / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        if "llama-cpp-python" not in text:
            continue
        seen += 1
        assert LLAMA_MIN_FOR_MODERN_GGUF in text, f"{name} allows a runtime too old for current GGUFs"
    assert seen, "no requirements file pins llama-cpp-python at all"


def test_linux_nvidia_path_does_not_take_a_stale_cuda_wheel():
    """The abetlen CUDA index stops at 0.3.19 for cp312. Installing from it with
    --prefer-binary is what left NVIDIA users unable to load modern models."""
    text = _sh_text()
    nvidia = text[text.index("# NVIDIA."):]
    assert LLAMA_MIN_FOR_MODERN_GGUF in nvidia, "no minimum enforced on the CUDA path"
    assert "--prefer-binary \\\n        --extra-index-url" not in nvidia, \
        "the unbounded --prefer-binary CUDA install is back"
    assert "GGML_CUDA=on" in nvidia, "no CUDA source-build fallback when no wheel qualifies"


def _choose_build(**given):
    """install.sh's build decision, run by itself: (CPU_ONLY, BUILD_LABEL) for this hardware and these flags."""
    text = _sh_text()
    start = text.index("_choose_build() {")
    body = text[start:text.index("\n}\n", start) + 3]
    names = dict(BUILD_FLAG="", CPU_ONLY=0, FORCE_GPU=0, HAS_NVIDIA=0, HAS_AMD=0, HAS_INTEL_IGPU=0,
                 HAS_INTEL_ARC=0, HAS_QUALCOMM_IGPU=0, OS="Linux", ASSUME_YES=0, _RAMGB=32)
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("ELI_INSTALL_CPU_ONLY", "ELI_FORCE_GPU")}
    for name in ("ELI_INSTALL_CPU_ONLY", "ELI_FORCE_GPU"):
        if name in given:
            env[name] = str(given.pop(name))
    names.update(given)
    script = ("set -euo pipefail\n" + "".join(f"{k}={shlex.quote(str(v))}\n" for k, v in names.items())
              + body + '_choose_build >/dev/null\necho "$CPU_ONLY|$BUILD_LABEL"\n')
    ran = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert ran.returncode == 0, ran.stderr
    cpu, label = ran.stdout.strip().split("|")
    return int(cpu), label


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="runs the installer's own shell function")
def test_asking_for_the_gpu_build_gets_it_where_the_cpu_build_would_be_chosen():
    """--gpu set CPU_ONLY=0, which it already was, so it changed nothing: with no GPU found, on an
    Intel iGPU laptop or a low-RAM non-interactive install the build was the CPU one all the same."""
    assert "--gpu)         BUILD_FLAG=gpu ;;" in _sh_text()
    assert _choose_build() == (1, "CPU-only")                                  # nothing found
    assert _choose_build(BUILD_FLAG="gpu") == (0, "GPU (CUDA)")                # as -Gpu on Windows
    assert _choose_build(ELI_FORCE_GPU=1) == (0, "GPU (CUDA)")
    igpu = dict(HAS_INTEL_IGPU=1, ASSUME_YES=1)
    assert _choose_build(**igpu) == (1, "CPU-only (Intel iGPU laptop)")
    assert _choose_build(BUILD_FLAG="gpu", **igpu) == (0, "GPU (Intel Vulkan)")
    small = dict(HAS_QUALCOMM_IGPU=1, ASSUME_YES=1, _RAMGB=8)
    assert _choose_build(**small) == (1, "CPU-only (low RAM)")
    assert _choose_build(BUILD_FLAG="gpu", **small) == (0, "GPU (Qualcomm Vulkan)")
    # The CPU build is still the CPU build, however it is asked for, and the line beats the environment.
    assert _choose_build(BUILD_FLAG="cpu", HAS_NVIDIA=1) == (1, "CPU-only")
    assert _choose_build(ELI_INSTALL_CPU_ONLY=1, HAS_NVIDIA=1) == (1, "CPU-only")
    assert _choose_build(ELI_INSTALL_CPU_ONLY=1, ELI_FORCE_GPU=1) == (1, "CPU-only")   # as the hardware policy
    assert _choose_build(BUILD_FLAG="gpu", ELI_INSTALL_CPU_ONLY=1) == (0, "GPU (CUDA)")
    assert _choose_build(HAS_NVIDIA=1) == (0, "GPU (CUDA)")
    assert _choose_build(OS="Darwin") == (0, "GPU (Metal)")


def _setup_hands_install_sh(**given):
    """What scripts/eli_setup.sh (ELI_Setup.sh) exports for install.sh after its hardware-policy step,
    with these variables in its environment; the policy itself answers "gpu" here."""
    text = (Path(__file__).resolve().parents[1] / "scripts" / "eli_setup.sh").read_text(encoding="utf-8")
    start = text.index("_eli_apply_hw_policy() {")
    body = text[start:text.index("\n}\n", start) + 3]
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("ELI_INSTALL_CPU_ONLY", "ELI_FORCE_GPU")}
    env.update({k: str(v) for k, v in given.items()})
    script = ("set -euo pipefail\npython3() { echo gpu; }\n" + body
              + '_eli_apply_hw_policy\necho "${ELI_INSTALL_CPU_ONLY:-}|${ELI_FORCE_GPU:-}"\n')
    ran = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)
    assert ran.returncode == 0, ran.stderr
    cpu, gpu = ran.stdout.strip().split("|")
    return {name: value for name, value in (("ELI_INSTALL_CPU_ONLY", cpu), ("ELI_FORCE_GPU", gpu)) if value}


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="runs the installers' own shell functions")
def test_the_documented_gpu_override_for_eli_setup_builds_for_the_gpu():
    """`ELI_INSTALL_CPU_ONLY=0 ./ELI_Setup.sh` is the documented way to ask for the GPU build, and on an
    Intel iGPU laptop or a low-RAM machine install.sh built for the CPU all the same: only --gpu and
    ELI_FORCE_GPU=1 reach its switch. ELI_Setup.sh hands the 0 on as ELI_FORCE_GPU=1."""
    igpu = dict(HAS_INTEL_IGPU=1, ASSUME_YES=1)
    small = dict(HAS_QUALCOMM_IGPU=1, ASSUME_YES=1, _RAMGB=8)
    asked = _setup_hands_install_sh(ELI_INSTALL_CPU_ONLY=0)
    assert asked == {"ELI_INSTALL_CPU_ONLY": "0", "ELI_FORCE_GPU": "1"}
    assert _choose_build(**asked, **igpu) == (0, "GPU (Intel Vulkan)")
    assert _choose_build(**asked, **small) == (0, "GPU (Qualcomm Vulkan)")
    assert _choose_build(BUILD_FLAG="cpu", **asked, **igpu) == (1, "CPU-only")   # its CPU retry still is one
    # The policy's own answer is not an override: install.sh still prefers the CPU build there.
    decided = _setup_hands_install_sh()
    assert decided == {"ELI_INSTALL_CPU_ONLY": "0"}
    assert _choose_build(**decided, **igpu) == (1, "CPU-only (Intel iGPU laptop)")
    for value in ("1", "yes"):
        cpu = _setup_hands_install_sh(ELI_INSTALL_CPU_ONLY=value)
        assert cpu == {"ELI_INSTALL_CPU_ONLY": "1"} and _choose_build(**cpu, HAS_NVIDIA=1) == (1, "CPU-only")
    assert _setup_hands_install_sh(ELI_FORCE_GPU=1) == {"ELI_INSTALL_CPU_ONLY": "0", "ELI_FORCE_GPU": "1"}


def test_linux_nvidia_build_finds_nvcc_off_path():
    """The CUDA toolkit is routinely installed without being on PATH."""
    text = _sh_text()
    nvidia = text[text.index("# NVIDIA."):]
    assert "/usr/local/cuda" in nvidia, "does not look for nvcc where the toolkit installs it"
    assert "CUDACXX" in nvidia


def test_the_pytorch_build_is_read_from_the_machine_and_never_decides_the_engine_build():
    """cu121 and rocm6.2 were fixed in both installers; neither has a build past Python 3.12. On 3.13
    and later an NVIDIA machine got CPU PyTorch, blamed on the network, and on Linux CPU_ONLY=1 then
    built the inference engine without CUDA as well. Intel Arc was sent CUDA PyTorch."""
    sh, ps = _sh_text(), _ps1_code()
    assert "torch-index" in sh and "torch-index" in ps
    for text in (sh, ps):
        assert "pytorch.org/whl/cu121" not in text and "pytorch.org/whl/rocm6.2" not in text, "a fixed PyTorch build is back"
    gpu = sh[sh.index("_install_pytorch_gpu() {"):]
    gpu = gpu[:gpu.index("\n}\n")]
    assert "CPU_ONLY" not in gpu and "SKIP_TORCH" not in gpu
    assert "_torch_runs_on" in gpu, "a build that installs is not proof it runs on this GPU"
    assert '[ "$SKIP_TORCH" -eq 0 ] && [ "$CPU_ONLY" -eq 0 ]' not in sh, "the engine's GPU check waits on PyTorch"
    assert "_TORCH_KIND=xpu" in sh


def test_no_installer_advises_a_python_version_for_ready_made_engine_builds():
    """\"PYTHON=python3.12 installs faster\" and \"use Python 3.11\": no Python has a ready-made
    llama-cpp-python new enough for current GGUFs, and which Python installs fastest is measured."""
    sh, ps = _sh_text(), _ps1_code()
    assert "PYTHON=python3." not in sh
    assert "sys.version_info[:2] <= (3, 12)" not in sh
    assert "use Python 3." not in ps


def test_windows_cuda_wheel_is_version_bounded():
    text = _ps1_text()
    llama = text[text.index("llama-cpp-python (CUDA"):]
    assert f"llama-cpp-python>={LLAMA_MIN_FOR_MODERN_GGUF}" in llama, \
        "Windows still accepts any CUDA wheel version"


def test_ddgs_replaces_the_deprecated_package_name():
    """duckduckgo-search was renamed; the old name installs a shim that warns on
    every search and will stop being published. pyproject's web extra is what the
    release bundles, and it still had the old name."""
    root = Path(__file__).resolve().parents[1]
    for name in ("requirements.txt", "requirements-full.txt",
                 "requirements-macos.txt", "requirements-windows.txt", "pyproject.toml"):
        p = root / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        assert "duckduckgo-search>=" not in text, f"{name} still pins the renamed package"
        if "ddgs" in text:
            assert "ddgs>=" in text


def test_yt_dlp_is_declared():
    """Undeclared, so a fresh install had no direct YouTube playback on any OS."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "yt-dlp" in text, "yt-dlp is still undeclared; playback would be browser-only"


def test_linux_installer_smoke_tests_llama_runtime_not_just_import():
    """CUDA wheels import fine then SIGILL in ggml_cpu_init on CPUs without VNNI."""
    text = _sh_text()
    assert "_llama_runtime_smoke" in text
    assert "llama_backend_init" in text
    assert "_llama_rebuild_for_this_cpu" in text
    assert "_cpu_trusts_prebuilt_llama_wheel" in text
    assert "x86-64-v3" in text


# Invented flag sets: one CPU with AVX2, one with AVX but no AVX2 / FMA / F16C / BMI2, one with neither.
_CPU_AVX2 = ("fpu tsc msr pae cx8 apic sep cmov clflush mmx fxsr sse sse2 syscall nx lm pni pclmulqdq ssse3 fma "
             "cx16 sse4_1 sse4_2 movbe popcnt aes xsave avx f16c lahf_lm abm bmi1 avx2 bmi2")
_CPU_AVX = ("fpu tsc msr pae cx8 apic sep cmov clflush mmx fxsr sse sse2 syscall nx lm pni pclmulqdq ssse3 "
            "cx16 sse4_1 sse4_2 popcnt aes xsave avx lahf_lm")
_CPU_SSSE3 = "fpu tsc msr pae cx8 apic sep cmov clflush mmx fxsr sse sse2 syscall nx lm pni ssse3 cx16 lahf_lm"


def _cpuinfo(*cores: str) -> str:
    return "".join(f"processor\t: {n}\nmodel name\t: Example CPU\nflags\t\t: {flags}\n\n" for n, flags in enumerate(cores))


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="runs the installer's own shell function")
def test_a_cpu_build_holds_no_instruction_set_the_cpu_lacks(tmp_path, monkeypatch):
    """With native tuning off, ggml compiles SSE4.2, AVX, AVX2, BMI2, FMA and F16C into its CPU backend by
    default (llama.cpp's ggml/CMakeLists.txt: GGML_NATIVE=OFF turns INS_ENB on), whatever -march says, so
    the "CPU-safe" build for a CPU without AVX2 still held AVX2 code and died on it. Each one the CPU's
    flags lack is now switched off, and eli.core.llama_cpu_compat gives the same flags."""
    import eli.core.llama_cpu_compat as lcc
    sh = _sh_text()
    start = sh.index("_cpu_has_flag() {")
    end = sh.index("\n}\n", sh.index("_llama_safe_cpu_cmake_flags() {")) + 3
    expect = {
        (_CPU_AVX2,): "-march=x86-64-v3",
        (_CPU_AVX,): "-march=x86-64-v2 -DGGML_AVX2=OFF -DGGML_BMI2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF",
        (_CPU_SSSE3,): "-march=x86-64 -DGGML_SSE42=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_BMI2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF",
        (_CPU_AVX2, _CPU_AVX): "-march=x86-64-v2 -DGGML_AVX2=OFF -DGGML_BMI2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF",  # on every core
    }
    for cores, tail in expect.items():
        info = tmp_path / "cpuinfo"
        info.write_text(_cpuinfo(*cores), encoding="utf-8")
        body = sh[start:end].replace("/proc/cpuinfo", str(info))
        script = 'set -euo pipefail\nuname() { case "$1" in -m) echo x86_64 ;; *) echo Linux ;; esac; }\n' + body + "_llama_safe_cpu_cmake_flags\n"
        ran = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
        march, _, off = tail.partition(" ")
        flags = f"-DGGML_NATIVE=OFF -DCMAKE_C_FLAGS={march} -DCMAKE_CXX_FLAGS={march}" + (f" {off}" if off else "")
        assert ran.stdout.strip() == flags, (cores, ran.stdout)

        class _Info:
            def read_text(self, **_kw):
                return _cpuinfo(*cores)
        monkeypatch.setattr(lcc, "Path", lambda *_a, **_k: _Info())
        monkeypatch.setattr(lcc.platform, "machine", lambda: "x86_64")
        monkeypatch.setattr(lcc.sys, "platform", "linux")
        assert lcc.safe_source_cmake_flags() == flags, cores
    assert [opt for opt, _flag in lcc.GGML_X86_DEFAULT_ISA] == ["SSE42", "AVX", "AVX2", "BMI2", "FMA", "F16C"]
    assert sh.count('_GGML_X86_DEFAULT_ISA="SSE42:sse4_2 AVX:avx AVX2:avx2 BMI2:bmi2 FMA:fma F16C:f16c"') == 1


def test_install_sh_emits_gui_progress_markers():
    text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    assert "eli_progress()" in text
    assert "[ELI-PROGRESS]" in text
    assert 'eli_progress finish 100' in text


def test_install_backend_parses_progress_lines():
    from eli.setup.install_backend import parse_install_line
    p = parse_install_line("[ELI-PROGRESS] phase=venv pct=12 msg=Virtual environment ready")
    assert p is not None
    assert p.phase == "venv"
    assert p.percent == 12
    assert "Virtual" in p.message
    hint = parse_install_line("[..] Installing PyTorch (CUDA 12.1)...")
    assert hint is not None
    assert hint.phase == "torch"


def test_install_messages_have_all_phases():
    from eli.setup.install_messages import INSTALL_MESSAGES, messages_for_phase
    for phase in ("welcome", "system", "venv", "torch", "llama", "eli", "finish", "android"):
        assert phase in INSTALL_MESSAGES
        assert messages_for_phase(phase)


def test_install_backend_routes_android_profile(monkeypatch, tmp_path):
    from eli.setup import install_backend as ib
    script = tmp_path / "scripts" / "install_android.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(ib, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        "eli.setup.platform_profile.is_android_headless",
        lambda: True,
    )
    assert ib.install_script_path() == script
    assert ib.build_install_command()[0] == "bash"


def test_appimage_syncs_when_bundled_version_changes():
    text = (Path(__file__).resolve().parents[1]
            / "packaging" / "linux" / "build-appimage.sh").read_text(encoding="utf-8")
    apprun = text[text.index("cat > \"$APPDIR/AppRun\" <<'APPRUN_EOF'"):]
    assert "_bundle_version" in apprun
    assert "_installed_version" in apprun
    assert 'printf \'%s\\n\' "$_BUNDLE_VER" >"$MARKER"' in apprun
    assert "touch \"$MARKER\"" not in apprun, "marker must store version, not just exist"
