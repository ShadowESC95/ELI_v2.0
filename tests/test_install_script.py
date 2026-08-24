"""Install script regressions — catch fresh-clone failures before users hit them."""
from __future__ import annotations

from pathlib import Path


def test_install_sh_does_not_use_set_e_unsafe_wheel_lookup():
    text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    assert "WHEEL=$(ls" not in text, (
        "install.sh must not use WHEEL=$(ls ...) under set -e — ls fails when no wheel exists and aborts the installer"
    )
    assert 'install -e ".[full]"' in text or "install -e '.[full]'" in text


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
    root = Path(__file__).resolve().parents[1]
    return sorted(p for p in root.rglob("*.ps1")
                  if not (_PS1_SKIP_DIRS & set(p.parts)))


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


def test_windows_installer_detects_more_than_nvidia():
    """nvidia-smi was the only detector, so AMD and Intel Arc machines were
    told they had no GPU at all and silently got a CPU-only build."""
    text = _ps1_text()
    assert "Win32_VideoController" in text, "no vendor-neutral GPU enumeration"
    for vendor in ("amd|radeon", "intel|arc"):
        assert vendor in text, f"installer never recognises {vendor}"


def test_windows_installer_cannot_fall_into_a_source_build():
    """--prefer-binary lets pip build from source when no wheel matches. That
    needs MSVC, and its failure aborted the installer right after the GPU
    accelerator step."""
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


def test_windows_installer_explains_the_fallback():
    """A silent downgrade to CPU is how 0 GPU layers became a mystery."""
    text = _ps1_text()
    assert "No prebuilt CUDA" in text
    assert "-InstallCuda" in text and "cu124" in text, "no remedy offered"


# ── the CUDA wheel index is stale; installers must not silently take it ────
def _sh_text() -> str:
    return (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")


LLAMA_MIN_FOR_MODERN_GGUF = "0.3.30"


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


def test_linux_nvidia_build_finds_nvcc_off_path():
    """The CUDA toolkit is routinely installed without being on PATH."""
    text = _sh_text()
    nvidia = text[text.index("# NVIDIA."):]
    assert "/usr/local/cuda" in nvidia, "does not look for nvcc where the toolkit installs it"
    assert "CUDACXX" in nvidia


def test_windows_cuda_wheel_is_version_bounded():
    text = _ps1_text()
    llama = text[text.index("llama-cpp-python (CUDA"):]
    assert f"llama-cpp-python>={LLAMA_MIN_FOR_MODERN_GGUF}" in llama, \
        "Windows still accepts any CUDA wheel version"


def test_ddgs_replaces_the_deprecated_package_name():
    """duckduckgo-search was renamed; the old name installs a shim that warns on
    every search and will stop being published."""
    root = Path(__file__).resolve().parents[1]
    for name in ("requirements.txt", "requirements-full.txt",
                 "requirements-macos.txt", "requirements-windows.txt"):
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
