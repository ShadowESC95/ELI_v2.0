import sys, os, pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["ELI_TEST_MODE"] = "1"
os.environ["ELI_FORCE_CPU"] = "1"

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Redirect ALL artifact writes (documents, runtime snapshots, the scheduled-task
# store) to a throwaway IN-PROJECT dir for the whole test session, so a test run can
# never pollute the real artifacts/ or wipe the user's standing scheduled jobs. This
# is plain config (an in-project path runtime_settings won't strip) — NOT a
# monkeypatch. _artifacts_dir() and _store_path() both honour ELI_ARTIFACTS_DIR.
os.environ["ELI_ARTIFACTS_DIR"] = str(ROOT / "artifacts" / "_pytest")
os.environ.setdefault("ELI_CPU_PREFLIGHT", "0")  # no smoke subprocess in tests
# ELI_ARTIFACTS_DIR alone did NOT isolate the SQLite stores — the user DB path is resolved
# by eli.core.paths.user_db_path(), which honours ELI_USER_DB/ELI_MEMORY_DB FIRST (before
# any dev-tree fallback). So tests that called store_memory()/awareness reflection were
# writing into the REAL artifacts/db/user.sqlite3 and injecting rows ("test store", auto
# reflections) into the user's memory. Pin the user + memory DB to the throwaway _pytest
# tree via the highest-priority override so NO test can pollute the real database — and
# without touching artifacts_dir()/data_dir() (ELI_DATA_DIR would, breaking path tests).
_PYTEST_DB = ROOT / "artifacts" / "_pytest" / "db" / "user.sqlite3"
_PYTEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["ELI_USER_DB"]   = str(_PYTEST_DB)
os.environ["ELI_MEMORY_DB"] = str(_PYTEST_DB)
os.environ["ELI_DB_DIR"]    = str(ROOT / "artifacts" / "_pytest" / "db")
# agent.sqlite3 resolves via ELI_AGENT_DB FIRST (paths.agent_db_path); without it,
# tests that touched the agent bus (dispatch/metrics/observations) were writing into
# the REAL artifacts/db/agent.sqlite3. Pin it to the throwaway tree too so NO test can
# change ANY of ELI's stores — the DB must stay a clean slate for a fresh download.
os.environ["ELI_AGENT_DB"]  = str(ROOT / "artifacts" / "_pytest" / "db" / "agent.sqlite3")

# persona_auto_path()/notebook_dir() had no override at all — a full test run once
# replaced the real persona.auto.txt with fixture content. Pin both to the sandbox.
os.environ["ELI_PERSONA_AUTO_PATH"] = str(ROOT / "artifacts" / "_pytest" / "persona.auto.txt")
os.environ["ELI_NOTEBOOK_DIR"]      = str(ROOT / "artifacts" / "_pytest" / "eli_notebook")

# storage.WORLD_DIR is frozen at import time, so this must be set before that module
# ever loads — a full-suite run once wrote real events into the actual world state.
os.environ["ELI_WORLD_DIR"] = str(ROOT / "artifacts" / "_pytest" / "world")
os.environ["ELI_LAST_TRACE_PATH"] = str(ROOT / "artifacts" / "_pytest" / "last_trace.json")

# Both resolve through db_dir() -> data_dir(), which ELI_DB_DIR doesn't touch, so every
# test turn was appending to the REAL audit chain (fixture rows from a dev run sat in it).
# The HMAC key likewise came from (or was created in) the real config dir.
os.environ["ELI_ORCHESTRATOR_AUDIT_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "orchestrator_audit.sqlite3")
os.environ["ELI_CAPABILITY_STATE_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "capability_state.sqlite3")
os.environ["ELI_AUDIT_HMAC_KEY"] = "eli-pytest-audit-key-not-a-real-secret"
# The document index stores whatever a turn reads and embeds it on a worker thread. Off by
# default here; the tests for it build their own on a tmp path.
os.environ["ELI_DOCUMENT_INDEX_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "documents.sqlite3")
os.environ.setdefault("ELI_DOCUMENT_INDEX", "0")
# The agenda (calendar and reminders) writes a DB and an .ics file and fires desktop notifications.
os.environ["ELI_AGENDA_DB"] = str(ROOT / "artifacts" / "_pytest" / "db" / "agenda.sqlite3")
os.environ["ELI_CALENDAR_FILE"] = str(ROOT / "artifacts" / "_pytest" / "calendar.ics")
os.environ["ELI_AGENDA_NOTIFY"] = "0"

# Hard isolation guard: fail LOUDLY at collection if any canonical store still resolves
# to the real artifacts/db tree. This makes "no test can change memory" an enforced
# invariant, not just configuration that a future refactor could silently break.
def _assert_db_isolated() -> None:
    from eli.core import paths as _p
    _safe = (ROOT / "artifacts" / "_pytest").resolve()
    for _name, _fn in (("user", _p.user_db_path), ("memory", _p.memory_db_path),
                       ("agent", _p.agent_db_path),
                       ("orchestrator audit", _p.orchestrator_audit_db_path),
                       ("capability state", _p.capability_state_db_path)):
        _resolved = Path(_fn()).resolve()
        if _safe not in _resolved.parents:
            raise RuntimeError(
                f"TEST ISOLATION BREACH: {_name} DB resolves to {_resolved}, "
                f"outside the throwaway {_safe}. A test could pollute the real "
                f"database. Check eli.core.paths overrides in conftest.")
    _persona_resolved = Path(_p.persona_auto_path()).resolve()
    if _safe not in _persona_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: persona_auto_path() resolves to "
            f"{_persona_resolved}, outside the throwaway {_safe}. A test could "
            f"overwrite the real persona overlay. Check eli.core.paths overrides "
            f"in conftest.")
    _notebook_resolved = Path(_p.notebook_dir()).resolve()
    if _safe not in _notebook_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: notebook_dir() resolves to "
            f"{_notebook_resolved}, outside the throwaway {_safe}. Check "
            f"eli.core.paths overrides in conftest.")
    # persona.py used to duplicate persona_auto_path()'s resolution, so the check above
    # passed while its own write constant still pointed at the real file. Check it directly.
    from eli.cognition import persona as _persona_mod
    _persona_file_resolved = Path(_persona_mod._PERSONA_AUTO_FILE).resolve()
    if _safe not in _persona_file_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: eli.cognition.persona._PERSONA_AUTO_FILE resolves to "
            f"{_persona_file_resolved}, outside the throwaway {_safe}. A test could "
            f"overwrite the real persona overlay. Check eli.cognition.persona / "
            f"eli.core.paths overrides in conftest.")
    # WORLD_DIR is frozen at import time — check the module constant, not a fresh call.
    from eli.world.persistence import storage as _world_storage_mod
    _world_dir_resolved = Path(_world_storage_mod.WORLD_DIR).resolve()
    if _safe not in _world_dir_resolved.parents:
        raise RuntimeError(
            f"TEST ISOLATION BREACH: eli.world.persistence.storage.WORLD_DIR resolves to "
            f"{_world_dir_resolved}, outside the throwaway {_safe}. A test could write real "
            f"autonomy-engine events into the actual world state. Check ELI_WORLD_DIR is set "
            f"before this module is first imported.")
_assert_db_isolated()

@pytest.fixture(autouse=True, scope="session")
def mock_heavy_imports():
    with patch.dict(sys.modules, {
        "llama_cpp": MagicMock(), "llama_cpp.llama_cpp": MagicMock(),
        # PySide6 not re-stubbed here — root conftest.py already installs a real
        # working stub/real binding; a bare MagicMock() broke `import *` (no Signal).
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


# Production code writes ELI_* variables straight into os.environ (save_settings pins ELI_MODEL_PATH, for
# one), which monkeypatch cannot see, so they outlived the test that caused them and skewed later ones.
@pytest.fixture(autouse=True, scope="function")
def restore_eli_environment():
    before = {k: v for k, v in os.environ.items() if k.startswith("ELI_")}
    yield
    for k in [k for k in os.environ if k.startswith("ELI_") and k not in before]:
        os.environ.pop(k, None)
    for k, v in before.items():
        if os.environ.get(k) != v:
            os.environ[k] = v
    # Path resolvers are lru_cached; a test that pointed them at a temp tree must not decide for the next one.
    try:
        from eli.core import paths as _paths
        for _fn in vars(_paths).values():
            if hasattr(_fn, "cache_clear"):
                _fn.cache_clear()
    except Exception:
        pass


# gguf_inference keeps the loaded model in module globals; a test that runs the real
# load_model() leaves a Mock there for the whole session. Reset it after every test.
@pytest.fixture(autouse=True, scope="function")
def reset_gguf_inference_globals():
    yield
    try:
        import eli.cognition.gguf_inference as _ggi
        _ggi._llm = None
        _ggi._live_runtime_override = None
        _ggi._load_failed = False
        _ggi._last_error = None
        if "_live_runtime_params" in vars(_ggi):
            _ggi._live_runtime_params = None
    except Exception:
        pass


# A test that escapes ELI_ARTIFACTS_DIR can overwrite the real runtime snapshot with
# junk (a MagicMock loads as n_ctx=1), which later runs read as machine state. Restore
# it after the session and name any test that touches it.
_REAL_SNAPSHOT = ROOT / "artifacts" / "runtime_snapshot.json"
_SNAPSHOT_TOUCHED: list = []


def _snapshot_state():
    try:
        return _REAL_SNAPSHOT.read_bytes() if _REAL_SNAPSHOT.exists() else None
    except OSError:
        return None


@pytest.fixture(autouse=True, scope="function")
def guard_real_runtime_snapshot(request):
    before = _snapshot_state()
    yield
    if _snapshot_state() != before:
        _SNAPSHOT_TOUCHED.append(request.node.nodeid)
        try:
            if before is None:
                _REAL_SNAPSHOT.unlink(missing_ok=True)
            else:
                _REAL_SNAPSHOT.write_bytes(before)
        except OSError:
            pass


# ── Auto-updating test-results document ──────────────────────────────────────
# Every pytest run (re)writes artifacts/test_report.md with the live results, so
# the report is dynamic — never stale. ELI's RUN_TESTS action reads/summarises it.
def pytest_sessionfinish(session, exitstatus):
    if _SNAPSHOT_TOUCHED:
        print("\n[conftest] tests that modified the REAL runtime_snapshot.json (restored):", *_SNAPSHOT_TOUCHED[:10], sep="\n  ")
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
        _adir = os.environ.get("ELI_ARTIFACTS_DIR")
        _base = Path(_adir).expanduser() if _adir else (ROOT / "artifacts")
        rep_path = _base / "test_report.md"
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        rep_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    except Exception:
        pass
