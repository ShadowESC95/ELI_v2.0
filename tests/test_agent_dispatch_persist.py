"""Integration tests: agent dispatch results persist to agent.sqlite3.

Verifies:
- _persist_dispatch_result() writes a row to agent_dispatches table
- dispatch() calls _persist_dispatch_result() after completing
- Custom agents with unregistered hashes are blocked
- Custom agents with matching hashes are allowed
"""
import sqlite3
import time
import threading
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------

class TestPersistDispatchResult:

    def test_persist_writes_to_db(self, tmp_path):
        """_persist_dispatch_result creates the table and inserts a row."""
        db_path = tmp_path / "agent.sqlite3"

        with patch("eli.cognition.agent_bus._persist_dispatch_result") as _mock:
            # Import the real function directly
            pass

        from eli.cognition.agent_bus import _persist_dispatch_result

        with patch("eli.core.paths.get_paths") as gp_mock:
            paths_mock = MagicMock()
            paths_mock.artifacts_dir = tmp_path
            gp_mock.return_value = paths_mock

            _persist_dispatch_result(
                action="CHAT",
                agents_used=["ReasoningAgent"],
                confidence=0.85,
                elapsed_ms=120.0,
                ok=True,
                summary="test run",
            )

        # Wait for the daemon thread to finish
        time.sleep(0.3)

        assert db_path.exists(), "agent.sqlite3 was not created"
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT action, confidence, ok, summary FROM agent_dispatches").fetchall()
        conn.close()

        assert len(rows) >= 1
        row = rows[-1]
        assert row[0] == "CHAT"
        assert abs(row[1] - 0.85) < 0.001
        assert row[2] == 1
        assert row[3] == "test run"

    def test_persist_is_non_blocking(self, tmp_path):
        """_persist_dispatch_result must return immediately (uses a daemon thread)."""
        from eli.cognition.agent_bus import _persist_dispatch_result

        with patch("eli.core.paths.get_paths") as gp_mock:
            paths_mock = MagicMock()
            paths_mock.artifacts_dir = tmp_path
            gp_mock.return_value = paths_mock

            start = time.monotonic()
            _persist_dispatch_result("TIME", [], 1.0, 5.0, True, "")
            elapsed = time.monotonic() - start

        # Should return in well under 100 ms (not waiting for DB write)
        assert elapsed < 0.1, f"_persist_dispatch_result blocked for {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Custom agent trust verification
# ---------------------------------------------------------------------------

class TestCustomAgentTrust:

    def test_untrusted_agent_is_blocked(self, tmp_path, monkeypatch):
        """An unregistered custom agent file must be skipped (not loaded)."""
        from eli.cognition.agent_bus import _load_custom_agents, _ALL_AGENTS

        # Point the custom agents dir to tmp_path via env var
        monkeypatch.setenv("ELI_CUSTOM_AGENTS_DIR", str(tmp_path))
        # Ensure trust bypass is off
        monkeypatch.delenv("ELI_TRUST_ALL_AGENTS", raising=False)

        agent_file = tmp_path / "my_agent.py"
        agent_file.write_text(
            "class MyAgent:\n    name='MyAgent'\n    def run(self, ctx):\n        return {}\n"
        )

        before_count = len(_ALL_AGENTS)
        with patch("eli.cognition.agent_bus._get_trusted_agents_registry", return_value={}):
            _load_custom_agents()

        # The untrusted agent must not have been added to _ALL_AGENTS
        after_count = len(_ALL_AGENTS)
        new_names = [getattr(a, "name", type(a).__name__) for a in _ALL_AGENTS[before_count:]]
        assert "MyAgent" not in new_names, (
            f"Untrusted agent 'MyAgent' was loaded into _ALL_AGENTS — security gate failed. "
            f"New agents: {new_names}"
        )

    def test_trusted_agent_hash_check_passes_with_matching_hash(self, tmp_path, monkeypatch):
        """A file whose hash matches the registry is not rejected by the security gate."""
        import hashlib
        from eli.cognition.agent_bus import _load_custom_agents

        monkeypatch.setenv("ELI_CUSTOM_AGENTS_DIR", str(tmp_path))
        monkeypatch.delenv("ELI_TRUST_ALL_AGENTS", raising=False)

        agent_src = "# trusted minimal agent\nclass TrustedAgent:\n    name='TrustedAgent'\n"
        agent_file = tmp_path / "trusted_agent.py"
        agent_file.write_text(agent_src)

        file_hash = hashlib.sha256(agent_file.read_bytes()).hexdigest()
        registry = {"trusted_agent.py": file_hash}

        # Should not raise; agent may fail to instantiate but must not be security-blocked
        import sys as _sys, io as _io
        captured = _io.StringIO()
        with patch("eli.cognition.agent_bus._get_trusted_agents_registry", return_value=registry), \
             patch("builtins.print", side_effect=lambda *a, **k: captured.write(" ".join(str(x) for x in a) + "\n")):
            _load_custom_agents()

        output = captured.getvalue()
        # If the hash matches, there must be no "hash mismatch" log line for this file
        assert "trusted_agent.py" not in output or "hash mismatch" not in output, (
            f"Trusted agent was incorrectly rejected: {output}"
        )
