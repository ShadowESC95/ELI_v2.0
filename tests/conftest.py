import sys
import json
import sqlite3
import importlib
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def pytest_configure(config):
    _install_stubs()


def _install_stubs():
    _llama = MagicMock(name="llama_cpp")
    _llama.Llama = MagicMock(name="Llama")
    _llama.LlamaGrammar = MagicMock(name="LlamaGrammar")
    _llama.LlamaTokenizer = MagicMock(name="LlamaTokenizer")
    _llama.LlamaCache = MagicMock(name="LlamaCache")
    sys.modules["llama_cpp"] = _llama
    sys.modules["llama_cpp.llama"] = _llama
    sys.modules["llama_cpp.llama_grammar"] = _llama

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

    _faiss = MagicMock(name="faiss")
    _faiss.IndexFlatL2 = MagicMock(name="IndexFlatL2")
    _faiss.IndexIDMap = MagicMock(name="IndexIDMap")
    _faiss.IndexHNSWFlat = MagicMock(name="IndexHNSWFlat")
    _faiss.read_index = MagicMock(name="read_index")
    _faiss.write_index = MagicMock(name="write_index")
    _faiss.normalize_L2 = MagicMock(name="normalize_L2")
    sys.modules["faiss"] = _faiss
    sys.modules["faiss.swigfaiss"] = _faiss

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
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    subject   TEXT,
    predicate TEXT,
    object    TEXT
);
"""


@pytest.fixture
def project_root():
    return Path(__file__).parent.parent


@pytest.fixture
def eli_package_path(project_root):
    return project_root / "eli"


@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test_memory.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_MEMORY_SCHEMA)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def populated_db(tmp_db):
    rows = [
        ("My name is Alice",               "user",         "2024-01-01T00:00:00", 1.0, "user",   "identity"),
        ("I love jazz music",               "user",         "2024-01-02T00:00:00", 1.0, "user",   "music"),
        ("My favourite language is Python", "user",         "2024-01-03T00:00:00", 1.0, "user",   "skills,python"),
        ("I prefer dark mode interfaces",   "user",         "2024-01-04T00:00:00", 0.8, "user",   "preferences"),
        ("The project is called ELI",       "user",         "2024-01-05T00:00:00", 0.9, "user",   "work"),
        ("ELI runs on a local GPU",         "user",         "2024-01-06T00:00:00", 0.9, "user",   "work"),
        ("I use Ollama for model serving",  "user",         "2024-01-07T00:00:00", 0.8, "user",   "skills"),
        ("Reflection: session stable",      "reflection",   "2024-01-08T00:00:00", 0.5, "system", ""),
        ("Short",                           "user",         "2024-01-09T00:00:00", 0.3, "user",   ""),
        ("Orchestrator processed entry",    "orchestrator", "2024-01-10T00:00:00", 0.4, "system", ""),
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


@pytest.fixture
def tmp_settings_file(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({}))
    monkeypatch.setenv("ELI_SETTINGS_FILE", str(settings_path))
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    for mod_path in ("eli.core.settings", "eli.core.config", "eli.settings", "eli.config"):
        try:
            mod = importlib.import_module(mod_path)
            for attr in ("SETTINGS_FILE", "CONFIG_PATH", "_SETTINGS_PATH",
                         "SETTINGS_PATH", "CONFIG_FILE", "_CONFIG_PATH"):
                if hasattr(mod, attr):
                    monkeypatch.setattr(mod, attr, settings_path, raising=False)
            for fn_name in ("_get_settings_path", "get_settings_path", "_settings_path"):
                if hasattr(mod, fn_name) and callable(getattr(mod, fn_name)):
                    monkeypatch.setattr(mod, fn_name, lambda: settings_path, raising=False)
        except ImportError:
            pass
    yield settings_path


@pytest.fixture
def mock_config(tmp_settings_file):
    return tmp_settings_file
