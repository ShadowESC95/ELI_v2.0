"""Live session report (2026-10-02): "why the fuck is my LAN server not working" — uvicorn's
WebSocket support needs websockets>=14 (the ServerProtocol class), but websockets was never a
pinned dependency of its own anywhere in the requirements files; uvicorn>=0.27 was listed
unpinned, so whatever websockets happened to already be on the system (here, an old
dist-packages copy) silently won and broke the import uvicorn needs for WS support.

Fixed two ways: (1) requirements files now pin websockets>=14.0 explicitly so a fresh install
never hits this; (2) the server-start code self-heals a machine that already has the broken
state installed, rather than leaving "failed to bind" as the only thing a user sees.

Qt-coupled GUI module, not directly executable in CI — verified at the source-text level,
matching this file's established pattern (see test_moe_gpu_layer_print_matches_what_loads.py).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py"

REQUIREMENTS_FILES = [
    "requirements.txt",
    "requirements-windows.txt",
    "requirements-macos.txt",
    "requirements-full.txt",
    "requirements-android.txt",
    "requirements-test.txt",
]


def test_every_requirements_file_pins_websockets_explicitly():
    for name in REQUIREMENTS_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "websockets>=14.0" in text, f"{name} missing an explicit websockets pin"


def test_pyproject_server_and_test_extras_pin_websockets():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert text.count("websockets>=14.0") >= 2


def test_server_start_detects_an_old_websockets_before_importing_uvicorn():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("from websockets.server import ServerProtocol")
    j = src.index("import uvicorn", i)
    around = src[i:j]
    assert "from websockets.server import ServerProtocol" in around
    assert "ImportError" in around


def test_server_start_self_heal_upgrades_in_place_and_cannot_crash_the_start():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("from websockets.server import ServerProtocol")
    j = src.index("import uvicorn", i)
    block = src[i:j]
    assert "pip" in block and "install" in block and "websockets>=14.0" in block
    assert "importlib.reload" in block
    # The self-heal's own failure (offline machine, read-only env, pip missing)
    # must not take down the server-start attempt that follows it.
    assert "except Exception as _ws_fix_err" in block


def test_server_start_self_heal_handles_externally_managed_environments():
    """Live verification (2026-10-02): on a bare system interpreter (no venv — the
    project's own .venv is what normally avoids this), modern Debian/Ubuntu's pip
    refuses even a --user install with 'externally-managed-environment' (PEP 668).
    Reproduced directly in this sandbox: a plain `pip install --upgrade websockets`
    failed with that exact error, and only a `--break-system-packages` retry actually
    upgraded the package and made `from websockets.server import ServerProtocol`
    importable. Without this retry the self-heal silently no-ops on exactly the
    machines most likely to have a stray system websockets in the first place."""
    src = GUI.read_text(encoding="utf-8")
    i = src.index("from websockets.server import ServerProtocol")
    j = src.index("import uvicorn", i)
    block = src[i:j]
    assert "externally-managed-environment" in block
    assert "--break-system-packages" in block
    assert "CalledProcessError" in block
