"""
tests/conftest.py — complete replacement
Fixes all 8 root causes from junit_20260428_170455.xml
"""
import sys
import json
import sqlite3
import importlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ─────────────────────────────────────────────────────────────────────────────
#  pytest_configure — runs BEFORE any module collection or import
#  This is the only hook that fires early enough to beat broken system packages
# ─────────────────────────────────────────────────────────────────────────────

def pytest_configure(config):
    """Install all heavy-dep stubs into sys.modules before anything else loads."""
    _install_stubs()


def _install_stubs():
    # ── A  llama_cpp  ────────────────────────────────────────────────────────
    # The real llama_cpp is installed but broken (no .so compiled).
    # Force-replace it entirely so `from llama_cpp import Llama` works.
    _llama = MagicMock(name="llama_cpp")
    _llama.Llama = MagicMock(name="Llama")
    _llama.LlamaGrammar = MagicMock(name="LlamaGrammar")
    _llama.LlamaTokenizer = MagicMock(name="LlamaTokenizer")
    _llama.LlamaCache = MagicMock(name="LlamaCache")
    sys.modules["llama_cpp"] = _llama
    sys.modules["llama_cpp.llama"] = _llama
    sys.modules["llama_cpp.llama_grammar"] = _llama

    # ── B  Qt  ───────────────────────────────────────────────────────────────
    # qt_compat.py waterfall: PySide6 → PyQt6 → PyQt5
    # All three must expose Qt, QTimer, QThread etc. as real attributes
    # (not just MagicMock attribute access) so `from X.QtCore import Qt` works.
    _QT_ATTRS = [
        "Qt", "QTimer", "QThread", "QObject", "QRunnable", "QThreadPool",
        "pyqtSignal", "pyqtSlot", "Signal", "Slot",
        "QSettings", "QCoreApplication", "QApplication",
        "QMutex", "QMutexLocker", "QAbstractListModel",
        "QModelIndex", "QVariant", "QSize", "QPoint", "QRect",
    ]

    def _make_qtcore():
        m = MagicMock(name="QtCore")
        for a in _QT_ATTRS:
            setattr(m, a, MagicMock(name=a))
        return m

    for _pkg in ("PySide6", "PyQt6", "PyQt5"):
        _core = _make_qtcore()
        _widgets = MagicMock(name=f"{_pkg}.QtWidgets")
        _gui = MagicMock(name=f"{_pkg}.QtGui")
        _mm = MagicMock(name=f"{_pkg}.QtMultimedia")
        _mod = MagicMock(name=_pkg)
        _mod.QtCore = _core
        _mod.QtWidgets = _widgets
        _mod.QtGui = _gui
        _mod.QtMultimedia = _mm
        sys.modules[_pkg] = _mod
        sys.modules[f"{_pkg}.QtCore"] = _core
        sys.modules[f"{_pkg}.QtWidgets"] = _widgets
        sys.modules[f"{_pkg}.QtGui"] = _gui
        sys.modules[f"{_pkg}.QtMultimedia"] = _mm

    # ── C  PIL / Pillow  ─────────────────────────────────────────────────────
    # real PIL is installed but missing compiled parts → force full mock
    _PIL_SUBS = [
        "Image", "ImageDraw", "ImageEnhance", "ImageFilter",
        "ImageFont", "ImageOps", "ImageColor", "ImageChops", "ImageSequence",
    ]
    _pil = MagicMock(name="PIL")
    for _s in _PIL_SUBS:
        _sub = MagicMock(name=f"PIL.{_s}")
        setattr(_pil, _s, _sub)
        sys.modules[f"PIL.{_s}"] = _sub
    sys.modules["PIL"] = _pil

    # ── faiss  ───────────────────────────────────────────────────────────────
    # "partially initialized module faiss has no attribute IndexFlatL2"
    # → real faiss installed but C extension broken; nuke and replace
    _faiss = MagicMock(name="faiss")
    _faiss.IndexFlatL2 = MagicMock(name="IndexFlatL2")
    _faiss.IndexIDMap = MagicMock(name="IndexIDMap")
    _faiss.IndexHNSWFlat = MagicMock(name="IndexHNSWFlat")
    _faiss.read_index = MagicMock(name="read_index")
    _faiss.write_index = MagicMock(name="write_index")
    _faiss.normalize_L2 = MagicMock(name="normalize_L2")
    sys.modules["faiss"] = _faiss
    sys.modules["faiss.swigfaiss"] = _faiss

    # ── Other heavy deps  ────────────────────────────────────────────────────
    _OTHER = [
        "torch", "torchvision", "torchaudio",
        "torch.nn", "torch.nn.functional", "torch.cuda",
        "whisper", "faster_whisper",
        "sounddevice", "soundfile", "pyaudio",
        "sentence_transformers",
        "transformers", "transformers.models",
        "diffusers", "accelerate",
        "ollama",
        "dbus", "dbus.mainloop", "dbus.mainloop.glib",
        "gi", "gi.repository", "gi.repository.Notify",
        "cv2",
        "scipy", "scipy.spatial",
        "sklearn", "sklearn.metrics", "sklearn.metrics.pairwise",
        "pydantic",
        "aiohttp",
        "httpx",
    ]
    for _dep in _OTHER:
        if _dep not in sys.modules:
            sys.modules[_dep] = MagicMock(name=_dep)


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
    return Path(__file__).parent.parent


@pytest.fixture
def eli_package_path(project_root):
    return project_root / "eli"


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
        ("My name is Jason",                  "user",         "2024-01-01T00:00:00", 1.0, "user",   "identity"),
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


# Convenience alias expected by some test files
@pytest.fixture
def mock_config(tmp_settings_file):
    return tmp_settings_file
