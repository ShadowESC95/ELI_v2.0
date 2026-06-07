import sys, os, pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ELI_TEST_MODE"] = "1"
os.environ["ELI_FORCE_CPU"] = "1"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

@pytest.fixture(autouse=True, scope="session")
def mock_heavy_imports():
    with patch.dict(sys.modules, {
        "llama_cpp": MagicMock(), "llama_cpp.llama_cpp": MagicMock(),
        "PySide6": MagicMock(), "PySide6.QtWidgets": MagicMock(),
        "PySide6.QtCore": MagicMock(), "PySide6.QtGui": MagicMock(),
        "faster_whisper": MagicMock(), "sounddevice": MagicMock(),
        "soundfile": MagicMock(), "piper": MagicMock(), "onnxruntime": MagicMock(),
        "faiss": MagicMock(), "torch": MagicMock(), "diffusers": MagicMock(),
        "transformers": MagicMock(), "pydantic": MagicMock(),
    }):
        yield

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_user.sqlite3"
    yield db_path
    if db_path.exists():
        db_path.unlink()

@pytest.fixture
def memory_instance(temp_db):
    from eli.memory import Memory
    return Memory(db_path=temp_db)

@pytest.fixture
def mock_gguf():
    with patch("eli.cognition.gguf_inference") as mock:
        mock.load_model.return_value = MagicMock()
        mock.chat_completion.return_value = {"content": "Mocked GGUF response"}
        mock.generate.return_value = "Mocked generation"
        yield mock

@pytest.fixture
def mock_executor():
    with patch("eli.execution.executor_enhanced.execute") as mock:
        mock.return_value = {"ok": True, "content": "mocked", "response": "mocked"}
        yield mock

@pytest.fixture
def engine_with_mocks(mock_gguf, mock_executor):
    from eli.kernel.engine import CognitiveEngine
    return CognitiveEngine(auto_init_gguf=False)

# FIX: Force persistence gate to allow all memory writes in tests
@pytest.fixture(autouse=True)
def allow_all_persistence():
    with patch("eli.runtime.persistence_gate.should_store_memory_text", return_value=True), \
         patch("eli.runtime.persistence_gate.should_store_conversation_turn", return_value=True):
        yield

# Force persistence gate to allow all memory writes during tests
@pytest.fixture(autouse=True, scope="function")
def force_persistence_gate():
    with patch("eli.memory.memory._eli_should_store_memory_text", None), \
         patch("eli.memory.memory._eli_should_store_conversation_turn", None):
        yield


# ── Auto-updating test-results document ──────────────────────────────────────
# Every pytest run (re)writes artifacts/test_report.md with the live results, so
# the report is dynamic — never stale. ELI's RUN_TESTS action reads/summarises it.
def pytest_sessionfinish(session, exitstatus):
    try:
        import datetime
        from collections import defaultdict
        tr = session.config.pluginmanager.get_plugin("terminalreporter")
        if tr is None:
            return
        stats = tr.stats
        order = ("passed", "failed", "error", "xfailed", "xpassed", "skipped")
        totals = {k: len(stats.get(k, [])) for k in order}
        total = sum(totals.values())
        per_file = defaultdict(lambda: defaultdict(int))
        failures = []
        for outcome in order:
            for rep in stats.get(outcome, []):
                nid = getattr(rep, "nodeid", "?")
                f = nid.split("::", 1)[0]
                per_file[f][outcome] += 1
                per_file[f]["total"] += 1
                if outcome in ("failed", "error"):
                    failures.append(nid)
        out = [
            "# ELI — Test Suite Report (auto-generated)",
            f"\n*Updated {datetime.datetime.now().isoformat(timespec='seconds')} "
            f"on every `pytest` run.*\n",
            "## Totals\n",
            f"- **Total:** {total}",
            f"- **Passed:** {totals['passed']}",
            f"- **Failed:** {totals['failed'] + totals['error']}",
            f"- **xfailed (known gaps):** {totals['xfailed']}",
            f"- **xpassed (gap fixed?):** {totals['xpassed']}",
            f"- **Skipped:** {totals['skipped']}",
            f"\n**Verdict:** {'✅ GREEN' if (totals['failed'] + totals['error']) == 0 else '❌ FAILURES'}\n",
            "## Per-file\n",
            "| Test file | Total | Pass | Fail | xfail | skip |",
            "|---|---|---|---|---|---|",
        ]
        for f in sorted(per_file):
            c = per_file[f]
            out.append(f"| `{f}` | {c['total']} | {c.get('passed',0)} | "
                       f"{c.get('failed',0)+c.get('error',0)} | {c.get('xfailed',0)} | "
                       f"{c.get('skipped',0)} |")
        if failures:
            out.append("\n## Failures\n")
            out += [f"- `{x}`" for x in failures[:200]]
        rep_path = ROOT / "artifacts" / "test_report.md"
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        rep_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        pass


# ── No test may pollute the real artifacts/ (docs, eval, runtime snapshots) ───
# Redirect the executor's canonical artifacts root to a per-test tmp dir. This is
# the safety net behind the doc-gen / runtime-audit / report writers — a test run
# must never leave files in the real artifacts/ folder.
@pytest.fixture(autouse=True)
def _isolate_artifacts_dir(tmp_path, monkeypatch):
    try:
        import eli.execution.executor_enhanced as _EX
        adir = tmp_path / "artifacts"
        adir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(_EX, "_artifacts_dir", lambda: adir, raising=False)
    except Exception:
        pass
    yield
