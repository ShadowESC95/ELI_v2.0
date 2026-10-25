"""Root conftest: session isolation and the shared fixtures (see tests/conftest.py for the rest)."""
import importlib
import json
import sqlite3
import pytest
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  pytest_configure — runs BEFORE any module collection or import
# ─────────────────────────────────────────────────────────────────────────────

def pytest_configure(config):
    """Test-run isolation. The real libraries are used: replacing the model runtime, FAISS, PyTorch,
    Qt and others with mocks let tests pass against code that could not run, and hid a crash
    (a closed embedder used again) that only a real llama.cpp shows."""
    # Test isolation: never write generated artifacts into the user's LIVE
    # artifacts/ tree. Several tests exercise GENERATE_SCRIPT (supernova,
    # quantum-decoherence, ton_618, relative_time) whose deterministic writers
    # save to ELI_ARTIFACTS_DIR (default: PROJECT_ROOT/artifacts/scripts). Without
    # this redirect, every test run overwrote those real scripts and bumped their
    # mtimes — making them look "just generated" in the morning report. Redirect
    # artifact + data writes to a throwaway temp dir for the whole test session.
    import os as _os
    # Must be INSIDE the project root: _eli_runtime_clear_stale_env_paths()
    # strips ELI_ARTIFACTS_DIR if it points outside the install (portability
    # guard), which would silently send writes back to the real artifacts/scripts.
    _test_root = _os.path.join(_os.path.dirname(__file__), ".pytest_artifacts")
    _os.makedirs(_test_root, exist_ok=True)
    _os.environ["ELI_ARTIFACTS_DIR"] = _test_root
    # Deterministic network baseline: tests must not depend on the user's live
    # Net toggle (config/settings.json network_enabled). Force offline so e.g.
    # search routing is stable (offline → OPEN_BROWSER); tests that need network
    # mock network_allowed() directly.
    _os.environ.setdefault("ELI_OFFLINE", "1")
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ─────────────────────────────────────────────────────────────────────────────
#  MEMORY SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

_MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT    NOT NULL,
    kind       TEXT    DEFAULT 'user',
    timestamp  TEXT,
    importance REAL    DEFAULT 1.0,
    source     TEXT    DEFAULT 'user',
    tags       TEXT    DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(text, content=memories, content_rowid=id);
CREATE TABLE IF NOT EXISTS habits (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern  TEXT,
    action   TEXT,
    count    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS knowledge (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    predicate TEXT,
    object  TEXT
);
"""


# ─────────────────────────────────────────────────────────────────────────────
#  FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def project_root():
    return Path(__file__).parent


# G + F  tmp_db  — pathlib.Path, schema initialised
@pytest.fixture
def tmp_db(tmp_path):
    """Isolated SQLite DB with full ELI memory schema. Returns pathlib.Path."""
    db_path = tmp_path / "test_memory.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_MEMORY_SCHEMA)
    conn.commit()
    conn.close()
    return db_path          # <── pathlib.Path, NOT str


# E  populated_db  — tmp_db pre-filled with representative rows
@pytest.fixture
def populated_db(tmp_db):
    """tmp_db with 10 varied memory rows covering all filter/recall scenarios."""
    rows = [
        ("My name is Alex",                    "user",         "2024-01-01T00:00:00", 1.0, "user",   "identity"),
        ("I love jazz music",                  "user",         "2024-01-02T00:00:00", 1.0, "user",   "music"),
        ("My favourite language is Python",    "user",         "2024-01-03T00:00:00", 1.0, "user",   "skills,python"),
        ("I prefer dark mode interfaces",      "user",         "2024-01-04T00:00:00", 0.8, "user",   "preferences"),
        ("The project is called ELI",          "user",         "2024-01-05T00:00:00", 0.9, "user",   "work"),
        ("ELI runs on a local GPU",            "user",         "2024-01-06T00:00:00", 0.9, "user",   "work"),
        ("I use Ollama for model serving",     "user",         "2024-01-07T00:00:00", 0.8, "user",   "skills"),
        ("Reflection: session stable",         "reflection",   "2024-01-08T00:00:00", 0.5, "system", ""),
        ("Short",                              "user",         "2024-01-09T00:00:00", 0.3, "user",   ""),
        ("Orchestrator processed this entry",  "orchestrator", "2024-01-10T00:00:00", 0.4, "system", ""),
    ]
    conn = sqlite3.connect(str(tmp_db))
    conn.executemany(
        "INSERT INTO memories (text, kind, timestamp, importance, source, tags) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return tmp_db


# D  tmp_settings_file  — isolated JSON settings with module monkey-patch
@pytest.fixture
def tmp_settings_file(tmp_path, monkeypatch):
    """
    Isolated settings JSON file. Patches eli.core.settings (and aliases)
    to read/write it instead of the real config directory.
    """
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}))

    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings_path))
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))

    for mod_path in ("eli.core.settings", "eli.core.config", "eli.settings", "eli.config"):
        try:
            mod = importlib.import_module(mod_path)
            for attr in (
                "SETTINGS_FILE", "CONFIG_PATH", "_SETTINGS_PATH",
                "SETTINGS_PATH", "CONFIG_FILE", "_CONFIG_PATH",
            ):
                if hasattr(mod, attr):
                    monkeypatch.setattr(mod, attr, settings_path, raising=False)
            # Also patch any Path-returning functions that resolve the settings path
            for fn_name in ("_get_settings_path", "get_settings_path", "_settings_path"):
                if hasattr(mod, fn_name) and callable(getattr(mod, fn_name)):
                    monkeypatch.setattr(mod, fn_name, lambda: settings_path, raising=False)
        except ImportError:
            pass

    yield settings_path
