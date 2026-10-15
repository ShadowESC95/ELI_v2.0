"""Process-wide socket guard — offline must block raw socket.connect, not just helpers."""
from __future__ import annotations

import socket

import pytest

from eli.core.netguard import OfflineError, install_socket_guard


def test_socket_guard_blocks_remote_connect_when_offline(monkeypatch):
    monkeypatch.setenv("ELI_OFFLINE", "1")
    install_socket_guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OfflineError, match="network disabled"):
            sock.connect(("203.0.113.1", 80))
    finally:
        sock.close()


def test_socket_guard_allows_loopback_when_offline(monkeypatch):
    monkeypatch.setenv("ELI_OFFLINE", "1")
    install_socket_guard()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            # Closed port on loopback — connection refused, not OfflineError.
            sock.connect(("127.0.0.1", 1))
    finally:
        sock.close()


# ---- nothing reports to a company --------------------------------------------------------------

def test_reporting_hosts_never_resolve_even_with_the_network_on():
    from eli.core.netguard import allow_network, is_reporting_host
    install_socket_guard()
    assert is_reporting_host("mobile.events.data.microsoft.com")
    assert is_reporting_host("us.i.posthog.com")
    assert not is_reporting_host("huggingface.co") and not is_reporting_host("duckduckgo.com")
    with allow_network("test"):
        with pytest.raises(socket.gaierror, match="only collects telemetry"):
            socket.getaddrinfo("mobile.events.data.microsoft.com", 443)
        assert socket.getaddrinfo("localhost", 80)  # every other name still resolves


def test_importing_eli_switches_library_telemetry_off():
    import os
    import eli  # noqa: F401
    for name, value in (("ORT_DISABLE_TELEMETRY", "1"), ("HF_HUB_DISABLE_TELEMETRY", "1"),
                        ("GRADIO_ANALYTICS_ENABLED", "False"), ("DO_NOT_TRACK", "1")):
        assert os.environ.get(name) == value, name


def test_onnxruntime_keeps_no_telemetry_queue(tmp_path):
    """onnxruntime 1.30+ creates ~/.cache/Microsoft/DeveloperTools/.onnxruntime (a device ID and an
    upload queue for Microsoft's collector) the first time it runs a model, unless switched off. That
    holds for a program ELI starts as well: Piper, the speech voice, carries its own onnxruntime and
    queued Microsoft events whenever ELI spoke, so the switch must reach programs ELI starts."""
    import glob
    import subprocess
    import sys
    from importlib.machinery import PathFinder
    from pathlib import Path
    # the real packages on disk (the test session may stand in for them in sys.modules)
    ort, fw = PathFinder.find_spec("onnxruntime"), PathFinder.find_spec("faster_whisper")
    if ort is None or fw is None or not fw.origin:
        pytest.skip("onnxruntime and faster_whisper are not installed")
    models = sorted(glob.glob(str(Path(fw.origin).parent / "assets" / "*.onnx")))
    if not models:
        pytest.skip("no onnx model shipped with faster_whisper")
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith(("ORT_", "HF_HUB_"))}
    env["HOME"] = str(tmp_path)
    run_model = f"import onnxruntime as ort; ort.InferenceSession({models[0]!r}, providers=['CPUExecutionProvider'])"
    subprocess.run([sys.executable, "-c", "import eli; " + run_model], env=env, check=True, timeout=300)
    assert not (tmp_path / ".cache" / "Microsoft").exists(), "onnxruntime set up its telemetry"
    # a program ELI starts, which never imports eli, run with the environment ELI gives it
    starts_a_program = ("import eli, subprocess, sys; from eli.core.host_env import host_env; "
                        f"subprocess.run([sys.executable, '-c', {run_model!r}], env=host_env(), check=True)")
    subprocess.run([sys.executable, "-c", starts_a_program], env=env, check=True, timeout=300)
    assert not (tmp_path / ".cache" / "Microsoft").exists(), "a program ELI started set up onnxruntime's telemetry"
