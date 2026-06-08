"""Integration tests: shell command security gate in executor_enhanced.

Verifies:
- RUN_CMD rejects commands matching _BLOCKED_PATTERNS (shell -c, python -c, etc.)
- RUN_CMD rejects executables in _DENIED_EXECUTABLES
- RUN_CMD allows safe commands like 'ls', 'echo', 'cat'
- Blocked commands return ok=False with an error message (no subprocess spawned)
"""
import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _full_control_off(monkeypatch):
    """These tests verify the safety FLOOR, so they must run with ELI Full Control off
    regardless of the ambient environment (Full Control deliberately lifts this gate)."""
    monkeypatch.setenv("ELI_FULL_CONTROL", "0")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_cmd(command: str, timeout: int = 5):
    """Call the RUN_CMD path in executor_enhanced directly."""
    from eli.execution.executor_enhanced import execute
    return execute("RUN_CMD", {"command": command, "timeout": timeout})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestShellSecurityGate:

    # ── Blocked pattern tests ────────────────────────────────────────────────

    def test_bash_minus_c_blocked(self):
        result = _run_cmd("bash -c 'rm -rf /'")
        assert result.get("ok") is False
        assert "block" in str(result).lower() or "deny" in str(result).lower() \
               or "secur" in str(result).lower() or "not allowed" in str(result).lower()

    def test_python_minus_c_blocked(self):
        result = _run_cmd("python3 -c 'import os; os.system(\"id\")'")
        assert result.get("ok") is False

    def test_sh_minus_c_blocked(self):
        result = _run_cmd("sh -c whoami")
        assert result.get("ok") is False

    def test_perl_minus_e_blocked(self):
        result = _run_cmd("perl -e 'print 1'")
        assert result.get("ok") is False

    def test_redirect_to_etc_blocked(self):
        result = _run_cmd("echo evil > /etc/passwd")
        assert result.get("ok") is False

    def test_chpasswd_blocked(self):
        result = _run_cmd("echo root:pwned | chpasswd")
        assert result.get("ok") is False

    def test_crontab_edit_blocked(self):
        result = _run_cmd("crontab -e")
        assert result.get("ok") is False

    # ── Denied executable tests ─────────────────────────────────────────────

    def test_rm_executable_blocked(self):
        result = _run_cmd("rm -rf /tmp/test")
        assert result.get("ok") is False

    def test_dd_blocked(self):
        result = _run_cmd("dd if=/dev/zero of=/tmp/x bs=1M count=1")
        assert result.get("ok") is False

    def test_nc_blocked(self):
        result = _run_cmd("nc -lvp 4444")
        assert result.get("ok") is False

    def test_iptables_blocked(self):
        result = _run_cmd("iptables -F")
        assert result.get("ok") is False

    # ── Allowed commands ────────────────────────────────────────────────────

    def test_ls_allowed(self):
        """ls /tmp should not be blocked by the security gate."""
        # We mock subprocess.run to avoid actually running it in the test suite
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "file1\nfile2\n"
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc) as _sp:
            result = _run_cmd("ls /tmp")
        # If the gate passed, subprocess.run was called (not blocked)
        assert result.get("ok") is not False or _sp.called, (
            "ls /tmp was incorrectly blocked by the security gate"
        )

    def test_echo_allowed(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "hello\n"
        mock_proc.stderr = ""

        with patch("subprocess.run", return_value=mock_proc):
            result = _run_cmd("echo hello")
        assert result.get("ok") is not False


class TestSecurityGateNoSubprocess:
    """Ensure blocked commands never reach subprocess.run."""

    def test_blocked_command_never_spawns_process(self):
        with patch("subprocess.run") as sp_mock:
            _run_cmd("bash -c 'id'")
        sp_mock.assert_not_called()

    def test_denied_executable_never_spawns_process(self):
        with patch("subprocess.run") as sp_mock:
            _run_cmd("rm /etc/hosts")
        sp_mock.assert_not_called()
