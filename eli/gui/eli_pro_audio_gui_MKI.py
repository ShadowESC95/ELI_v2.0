

#!/usr/bin/env python3
"""
ELI MKXI - Modern Comprehensive GUI
100% Local Operation with Qwen2.5-32B GGUF

Features:
- Modern dark/light theme
- Multi-panel dockable interface
- Integrated memory management
- Proactive suggestions panel
- IDE with syntax highlighting
- Document viewer
- File browser
- Habits management
- 100% local - NO external APIs
"""

from __future__ import annotations

import os
import sys

import json
import time
import threading
import traceback
import gc
import subprocess
import urllib.request
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from queue import Empty
from datetime import datetime
import re
import shutil
from collections import deque

from eli.utils.log import get_logger
log = get_logger(__name__)

# Direct script launches (`python eli/gui/eli_pro_audio_gui_MKI.py`) do not put
# the project root on sys.path. Bootstrap it early so `import eli.*` succeeds.
_BOOT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOT_PROJECT_ROOT))

def _eli_path_get(obj, key, default=None):
    """
    Compatibility helper for ELI path containers.
    Accepts both dict-style path maps and object/namespace-style path maps.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)

# Qt imports — PySide6-first policy for licensing portability.
# PySide6 (LGPLv3) is the canonical binding because LGPL allows dynamic
# linking from proprietary code, while PyQt6 is GPLv3 which would force
# the whole binary to be GPL. PyQt6/PyQt5 fallbacks remain available so
# users who already have those installed can run ELI without adding a
# second Qt binding, but the shipped requirements pin PySide6 only.
try:
    from PySide6.QtWidgets import *
    from PySide6.QtCore import *
    from PySide6.QtGui import *
    pyqtSignal = Signal
    pyqtSlot = Slot
    QT_VERSION = 6
    QT_API = "PySide6"
except ImportError:
    try:
        from PyQt6.QtWidgets import *
        from PyQt6.QtCore import *
        from PyQt6.QtGui import *
        QT_VERSION = 6
        QT_API = "PyQt6"
    except ImportError:
        try:
            from PyQt5.QtWidgets import *
            from PyQt5.QtCore import *
            from PyQt5.QtGui import *
            QT_VERSION = 5
            QT_API = "PyQt5"
        except ImportError:
            print("❌ Please install PySide6 (recommended), PyQt6, or PyQt5")
            sys.exit(1)

# Try to import syntax highlighter.
# QScintilla has no PySide6 binding (Riverbank ships Qsci for PyQt only).
# On PySide6 the IDE editor falls back to QTextEdit with basic styling.
try:
    if QT_API == "PyQt6":
        from PyQt6.Qsci import QsciScintilla, QsciLexerPython
        QSCI_AVAILABLE = True
    elif QT_API == "PyQt5":
        from PyQt5.Qsci import QsciScintilla, QsciLexerPython
        QSCI_AVAILABLE = True
    else:
        QSCI_AVAILABLE = False
except ImportError:
    QSCI_AVAILABLE = False

if not QSCI_AVAILABLE:
    print("⚠️  QScintilla not available. IDE will use basic editor.")

# --- Central ELI imports ---
try:
    from eli.core import config
    from eli.core.paths import get_paths
    from eli.memory import get_memory, Memory
    from eli.cognition import gguf_inference
    from eli.planning.proactive_daemon import start_daemon
    CENTRAL_IMPORTS_AVAILABLE = True
    print("✅ Central ELI modules loaded.")
except ImportError as e:
    CENTRAL_IMPORTS_AVAILABLE = False
    print(f"⚠️  Central ELI modules not available – GUI will operate with limited functionality. Error: {e}")
    config = None
    get_paths = None
    get_memory = None
    gguf_inference = None
    Memory = None
    start_daemon = None

# ============================================================
# Adapter for central Memory to match GUI's expected interface
# ============================================================


def _eli_gui_visible_text(result):
    from eli.runtime.visible_text import to_user_visible_text
    return to_user_visible_text(result)


class CentralMemoryAdapter:
    def __init__(self, mem_instance):
        self._mem = mem_instance

    def store(self, text: str, tags: List[str] = None, kind: str = "note",
              source: str = "user", confidence: float = 0.8) -> bool:
        try:
            result = self._mem.store_memory(
                text=text,
                tags=tags or [],
                source=source,
                kind=kind,
                confidence=confidence
            )
            return result.get("ok", False)
        except Exception as e:
            print(f"Memory store error: {e}")
            return False

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            results = self._mem.recall_memory(query, limit=limit)
            out = []
            for r in results:
                out.append({
                    "timestamp": r.get("ts") or r.get("timestamp") or "",
                    "kind": r.get("kind", "note"),
                    "text": r.get("text", ""),
                    "tags": r.get("tags", ""),
                })
            return out
        except Exception as e:
            print(f"Memory search error: {e}")
            return []

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            if hasattr(self._mem, "get_recent_memories"):
                results = self._mem.get_recent_memories(limit=limit)
            else:
                results = self._mem.recall_memory("", limit=limit)
            out = []
            for r in results:
                out.append({
                    "timestamp": r.get("ts") or r.get("timestamp") or "",
                    "kind": r.get("kind", "note"),
                    "text": r.get("text", ""),
                    "tags": r.get("tags", ""),
                })
            return out
        except Exception as e:
            print(f"Memory get_recent error: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        try:
            if hasattr(self._mem, "get_stats"):
                return self._mem.get_stats()
            else:
                return {"total": 0, "by_kind": {}}
        except Exception as e:
            print(f"Memory stats error: {e}")
            return {"total": 0, "by_kind": {}}

    def get_recent_memories(self, limit: int = 10) -> list:
        try:
            return self._mem.get_recent_memories(limit=limit)
        except Exception:
            return []

    def log_event(self, event_type: str, description: str, metadata: Dict = None):
        try:
            self._mem.log_habit_event(event_type, {"description": description, **(metadata or {})})
        except Exception as e:
            print(f"Event log error: {e}")

    # --- Habit methods (direct pass-through) ---
    def get_habit_rules(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        return self._mem.get_habit_rules(enabled_only)

    def add_habit_rule(self, name: str, command: str, hour: int, minute: int, days: list = None) -> int:
        return self._mem.add_habit_rule(name, command, hour, minute, days)

    def delete_habit_rule(self, rule_id: int) -> None:
        conn = self._mem._get_connection()
        try:
            conn.execute("DELETE FROM habit_rules WHERE id = ?", (rule_id,))
            conn.commit()
        finally:
            conn.close()

    def toggle_habit_rule(self, rule_id: int, enabled: bool) -> None:
        conn = self._mem._get_connection()
        try:
            conn.execute("UPDATE habit_rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id))
            conn.commit()
        finally:
            conn.close()

# ============================================================
# CONSTANTS & CONFIGURATION
# ============================================================

APP_NAME = "ELI Pro"
APP_VERSION = "7.0.7"

PROJECT_ROOT = _BOOT_PROJECT_ROOT

# Settings file: prefer eli.core.paths config_dir, fall back to PROJECT_ROOT/config
try:
    from eli.core.paths import config_dir as _config_dir
    APP_DIR = Path(_config_dir())
except Exception:
    APP_DIR = PROJECT_ROOT / "config"
SETTINGS_FILE = APP_DIR / "settings.json"

if CENTRAL_IMPORTS_AVAILABLE and get_paths:
    _paths = get_paths()
    MEMORY_DB = _eli_path_get(_paths, "memory_db")
    CONVERSATIONS_DIR = _paths.conversations_dir
    ARTIFACTS_DIR = _paths.artifacts_dir
    # No model filename is hardcoded — scan models/ for any .gguf at startup.
    # Returns "" when nothing is found so the heal loop doesn't fire on a stale
    # baked-in default and the GUI/startup-picker can prompt the user instead.
    def _eli_pick_any_bundled_model() -> str:
        try:
            root = PROJECT_ROOT / "models"
            if root.exists():
                for p in sorted(root.rglob("*.gguf")):
                    if p.is_file():
                        return str(p)
        except Exception:
            pass
        return ""
    DEFAULT_MODEL_PATH = str(_paths.model) if _paths.model and _paths.model.exists() else _eli_pick_any_bundled_model()
    BUNDLED_MODEL_DIR = PROJECT_ROOT / "models"
    CUSTOM_MODELS_DIR = APP_DIR / "models"
else:
    MEMORY_DB = PROJECT_ROOT / "artifacts" / "eli_memory.sqlite3"
    CONVERSATIONS_DIR = PROJECT_ROOT / "artifacts" / "conversations"
    ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
    def _eli_pick_any_bundled_model() -> str:
        try:
            root = PROJECT_ROOT / "models"
            if root.exists():
                for p in sorted(root.rglob("*.gguf")):
                    if p.is_file():
                        return str(p)
        except Exception:
            pass
        return ""
    DEFAULT_MODEL_PATH = _eli_pick_any_bundled_model()
    BUNDLED_MODEL_DIR = PROJECT_ROOT / "models"
    CUSTOM_MODELS_DIR = APP_DIR / "models"

if CENTRAL_IMPORTS_AVAILABLE and config:
    ELI_SYSTEM_PROMPT = config.get_eli_persona()
else:
    def _load_eli_persona() -> str:
        for p in [
            PROJECT_ROOT / "eli" / "brain" / "persona" / "persona.txt",
            PROJECT_ROOT / "eli" / "brain" / "cognition" / "persona.txt",
            PROJECT_ROOT / "config" / "persona.txt",
        ]:
            if p.exists():
                return p.read_text().strip()
        return "You are ELI, a helpful local AI assistant."
    ELI_SYSTEM_PROMPT = _load_eli_persona()
    # Strip any "prove it" remnants from dynamically loaded prompt
    ELI_SYSTEM_PROMPT = ELI_SYSTEM_PROMPT.replace('- "Now prove it." is your catchphrase.\n', '')
    ELI_SYSTEM_PROMPT = ELI_SYSTEM_PROMPT.replace('"Now prove it." is your catchphrase.\n', '')

MODEL_PROVIDER_LABELS = {
    "bundled_gguf": "Bundled GGUF",
    "custom_gguf": "Custom GGUF",
    "ollama": "Ollama",
}

if CENTRAL_IMPORTS_AVAILABLE and get_memory:
    _central_mem = get_memory()
    memory_system = CentralMemoryAdapter(_central_mem)
else:
    # Fallback local MemorySystem
    class MemorySystem:
        def __init__(self, db_path: Path = MEMORY_DB):
            self.db_path = db_path
            self._init_db()
        def _init_db(self):
            import sqlite3
            conn = sqlite3.connect(str(self.db_path))
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'note',
                    text TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    source TEXT DEFAULT 'user',
                    confidence REAL DEFAULT 0.8
                );
                CREATE INDEX IF NOT EXISTS idx_memories_timestamp ON memories(timestamp);
                CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
            """)
            conn.commit()
            conn.close()
        def store(self, text: str, tags: List[str] = None, kind: str = "note",
                  source: str = "user", confidence: float = 0.8) -> bool:
            import sqlite3
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                tags_str = ",".join(tags) if tags else ""
                timestamp = now_timestamp()
                cursor.execute("""
                    INSERT INTO memories (timestamp, kind, text, tags, source, confidence)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (timestamp, kind, text, tags_str, source, confidence))
                conn.commit()
                conn.close()
                return True
            except Exception as e:
                print(f"❌ Memory store error: {e}")
                return False
        def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
            import sqlite3
            try:
                conn = sqlite3.connect(str(self.db_path))
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM memories
                    WHERE text LIKE ? OR tags LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", limit))
                results = [dict(row) for row in cursor.fetchall()]
                conn.close()
                return results
            except Exception as e:
                print(f"❌ Memory search error: {e}")
                return []
        def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
            import sqlite3
            try:
                conn = sqlite3.connect(str(self.db_path))
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM memories
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))
                results = [dict(row) for row in cursor.fetchall()]
                conn.close()
                return results
            except Exception as e:
                print(f"❌ Memory get recent error: {e}")
                return []
        def get_stats(self) -> Dict[str, Any]:
            import sqlite3
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM memories")
                _row = cursor.fetchone(); total = _row[0] if _row else 0
                cursor.execute("SELECT kind, COUNT(*) FROM memories GROUP BY kind")
                by_kind = dict(cursor.fetchall())
                conn.close()
                return {"total": total, "by_kind": by_kind}
            except Exception as e:
                print(f"❌ Memory stats error: {e}")
                return {"total": 0, "by_kind": {}}
        def log_event(self, event_type: str, description: str, metadata: Dict = None):
            import sqlite3, json
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                timestamp = now_timestamp()
                meta_str = json.dumps(metadata or {})
                cursor.execute("""
                    INSERT INTO events (timestamp, event_type, description, metadata)
                    VALUES (?, ?, ?, ?)
                """, (timestamp, event_type, description, meta_str))
                conn.commit()
                conn.close()
            except Exception as e:
                print(f"❌ Event log error: {e}")
        # Minimal habit methods for fallback
        def get_habit_rules(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
            return []
        def add_habit_rule(self, name: str, command: str, hour: int, minute: int, days: list = None) -> int:
            return -1
        def delete_habit_rule(self, rule_id: int):
            pass
        def toggle_habit_rule(self, rule_id: int, enabled: bool):
            pass
    memory_system = MemorySystem()

# ============================================================
# UTILITIES (unchanged from previous version)
# ============================================================
def ensure_dirs():
    for d in [APP_DIR, CONVERSATIONS_DIR, ARTIFACTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)

def now_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")

def format_gb(n: float) -> str:
    return f"{n:.1f} GB"

def classify_gguf_source(path: str) -> str:
    """Classify GGUF source for UI labels.

    - `bundled`: models shipped in `models/gguf/base`
    - `custom`: user-added models (including project-root `models/*.gguf`)
    """
    try:
        p = Path(str(path or "")).expanduser().resolve()
        bundled_root = BUNDLED_MODEL_DIR.expanduser().resolve()
        bundled_base = (BUNDLED_MODEL_DIR / "gguf" / "base").expanduser().resolve()
        custom_root = CUSTOM_MODELS_DIR.expanduser().resolve()

        if custom_root in p.parents:
            return "custom"
        if bundled_base in p.parents:
            return "bundled"
        if bundled_root in p.parents:
            # Models dropped directly into project `models/` are user-managed.
            return "custom"
    except Exception:
        pass
    return "custom"

def recommend_model_setup(models, sysinfo, ollama_models=None):
    ollama_models = list(ollama_models or [])
    models = list(models or [])

    def _source_for_path(path: str) -> str:
        return "bundled_gguf" if classify_gguf_source(path) == "bundled" else "custom_gguf"

    if models:
        try:
            from eli.core.hardware_profile import detect_hardware as _hp_detect
            from eli.core.hardware_profile import recommend as _hp_recommend
            normalized = []
            for m in models:
                path_s = str(m.get("path") or "").strip()
                if not path_s:
                    continue
                p = Path(path_s).expanduser()
                if not p.exists():
                    continue
                try:
                    size_bytes = int(m.get("size_bytes") or p.stat().st_size)
                except Exception:
                    size_bytes = int(p.stat().st_size)
                size_gb = float(m.get("size_gb") or (size_bytes / 1e9))
                normalized.append({
                    "name": str(m.get("name") or p.name),
                    "path": str(p.resolve()),
                    "size_bytes": size_bytes,
                    "size_gb": size_gb,
                })

            if normalized:
                rec = _hp_recommend(_hp_detect(), normalized)
                chosen_path = str(rec.model_path or normalized[0]["path"])
                provider = _source_for_path(chosen_path)
                return {
                    "provider": provider,
                    "path": chosen_path,
                    "reason": (
                        f"Recommended {Path(chosen_path).name} "
                        f"(ctx={int(rec.n_ctx)}, gpu_layers={int(rec.n_gpu_layers)}, "
                        f"threads={int(rec.n_threads)}, batch={int(rec.batch_size)})"
                    ),
                }
        except Exception as e:
            log.debug(f"[SETTINGS] hardware-profile recommendation failed: {e}")

        # Fallback: smallest bundled model first, then smallest custom model.
        try:
            by_size = sorted(models, key=lambda m: float(m.get("size_gb") or 0.0))
            if by_size:
                chosen = by_size[0]
                chosen_path = str(chosen.get("path") or "")
                provider = _source_for_path(chosen_path)
                return {
                    "provider": provider,
                    "path": chosen_path,
                    "reason": f"Fallback selection: {Path(chosen_path).name}",
                }
        except Exception:
            pass

    if ollama_models:
        return {
            "provider": "ollama",
            "ollama_model": ollama_models[0],
            "reason": f"No local GGUF detected. Recommended Ollama model: {ollama_models[0]}",
        }

    return {
        "provider": "custom_gguf",
        "path": DEFAULT_MODEL_PATH,
        "reason": "No automatic recommendation available. Using configured model path.",
    }


def discover_gguf_models(base_dirs: Optional[List[Path]] = None) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    seen: set[str] = set()
    base_dirs = base_dirs or [BUNDLED_MODEL_DIR, CUSTOM_MODELS_DIR]
    for base in base_dirs:
        try:
            base = Path(base).expanduser()
            if not base.exists():
                continue
            for path in sorted(base.rglob('*.gguf')):
                key = str(path.resolve())
                if key in seen:
                    continue
                seen.add(key)
                try:
                    size_gb = path.stat().st_size / (1024 ** 3)
                except Exception:
                    size_gb = 0.0
                family = 'unknown'
                name_low = path.name.lower()
                if 'mistral' in name_low:
                    family = 'mistral'
                elif 'qwen' in name_low:
                    family = 'qwen'
                elif 'phi' in name_low:
                    family = 'phi'
                results.append({
                    'name': path.name,
                    'path': str(path),
                    'size_gb': size_gb,
                    'family': family,
                    'source': classify_gguf_source(str(path)),
                })
        except Exception:
            continue
    results.sort(key=lambda x: (x['source'] != 'bundled', x['size_gb'], x['name'].lower()))
    return results

def detect_system_capabilities() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        'platform': sys.platform,
        'cpu_count': os.cpu_count() or 1,
        'total_ram_gb': 0.0,
        'available_ram_gb': 0.0,
        'ollama_cli': False,
        'has_gpu': False,
        'gpu_name': '',
        'vram_mb': 0,
        'vram_total_mb': 0,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        info['total_ram_gb'] = vm.total / (1024 ** 3)
        info['available_ram_gb'] = vm.available / (1024 ** 3)
    except Exception:
        pass
    try:
        import shutil
        info['ollama_cli'] = shutil.which('ollama') is not None
        if shutil.which('nvidia-smi'):
            out = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.free,memory.total,name",
                    "--format=csv,noheader,nounits",
                ],
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).decode().strip().splitlines()
            if out:
                parts = [p.strip() for p in out[0].split(",")]
                info['vram_mb'] = int(float(parts[0]))
                info['vram_total_mb'] = int(float(parts[1]))
                info['gpu_name'] = parts[2] if len(parts) > 2 else "NVIDIA GPU"
                info['has_gpu'] = True
        elif shutil.which('rocm-smi'):
            info['has_gpu'] = True
            info['gpu_name'] = "ROCm GPU"
    except Exception:
        pass
    return info

def recommend_optimal_settings(sysinfo: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-detect sensible defaults from the current machine's hardware.

    Project-wide baseline is ctx=16384 and max_tokens=4096 unless the machine
    is genuinely too small to support it comfortably.
    """
    ram_gb    = float(sysinfo.get('total_ram_gb', 8) or 8)
    vram_mb   = int(sysinfo.get('vram_mb', 0) or 0)
    cpu_count = int(sysinfo.get('cpu_count', 4) or 4)
    has_gpu   = bool(sysinfo.get('has_gpu', False))

    # Context window: preserve the 16k project baseline on normal machines.
    if ram_gb >= 12:
        n_ctx = 16384
    elif ram_gb >= 8:
        n_ctx = 8192
    else:
        n_ctx = 4096

    # GPU layers: fit as much as VRAM allows.
    if not has_gpu or vram_mb <= 0:
        n_gpu_layers = 0
    elif vram_mb >= 8000:
        n_gpu_layers = 99
    elif vram_mb >= 6000:
        n_gpu_layers = 40
    elif vram_mb >= 4000:
        n_gpu_layers = 24
    elif vram_mb >= 2000:
        n_gpu_layers = 12
    else:
        n_gpu_layers = 4

    n_threads  = max(1, cpu_count - 2)
    batch_size = 512 if vram_mb >= 6000 else (384 if vram_mb >= 4000 else 256)
    max_tokens = min(4096, max(1024, int(n_ctx // 4)))

    return {
        'n_ctx':        n_ctx,
        'n_gpu_layers': n_gpu_layers,
        'n_threads':    n_threads,
        'batch_size':   batch_size,
        'temperature':  0.7,
        'max_tokens':   max_tokens,
    }

# ============================================================
# LLAMA.CPP MODEL MANAGER (unchanged)
# ============================================================
def resolve_model_path(model_path: str) -> Path:
    p = Path(model_path).expanduser()
    if p.is_absolute():
        return p
    try:
        base = PROJECT_ROOT
    except NameError:
        base = Path(__file__).resolve().parents[3]
    return (base / p).resolve()

def _sanitize_identity_drift(text: str) -> str:
    return text

def _policy_identity_memory_response(user_text: str, model_text: str) -> str:
    return model_text

class LocalModelManager:
    provider_name = "gguf"
    def __init__(self):
        self.model = None
        self.model_path = None
        self.is_loaded = False
        self.load_error = None
    def _write_shared_runtime_snapshot(
        self,
        model_path: str,
        n_ctx: int,
        n_threads: int,
        n_gpu_layers: int,
        *,
        requested_n_gpu_layers: Optional[int] = None,
        gpu_offload_supported: Optional[bool] = None,
    ):
        try:
            from eli.core.paths import get_paths
            snap_path = Path(get_paths().artifacts_dir) / 'runtime_snapshot.json'
            effective_n_gpu_layers = int(n_gpu_layers or 0)
            requested_layers = int(
                requested_n_gpu_layers
                if requested_n_gpu_layers is not None
                else effective_n_gpu_layers
            )
            payload = {
                'provider': 'gguf',
                'model_path': str(model_path),
                'model_name': Path(model_path).name if model_path else '',
                'n_ctx': int(n_ctx or 0),
                'n_gpu_layers': effective_n_gpu_layers,
                'n_threads': int(n_threads or 0),
                'n_batch': int(getattr(self, 'n_batch', 0) or 0),
                'requested_n_gpu_layers': requested_layers,
                'gpu_offload_supported': gpu_offload_supported,
                'load_mode': 'GPU' if effective_n_gpu_layers > 0 else 'CPU',
                'requested': {
                    'n_ctx': int(n_ctx or 0),
                    'n_gpu_layers': requested_layers,
                    'n_threads': int(n_threads or 0),
                    'n_batch': int(getattr(self, 'n_batch', 0) or 0),
                },
                'effective': {
                    'n_ctx': int(n_ctx or 0),
                    'n_gpu_layers': effective_n_gpu_layers,
                    'n_threads': int(n_threads or 0),
                    'n_batch': int(getattr(self, 'n_batch', 0) or 0),
                },
                'loaded': bool(getattr(self, 'is_loaded', False)),
                'pid': __import__('os').getpid(),
                'ts': time.time(),
            }
            snap_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
            print(f'✅ shared runtime snapshot written: {snap_path}')
        except Exception as e:
            log.debug(f'[GUI] shared runtime snapshot write failed: {e}')

    def load_model(
        self,
        model_path: str,
        n_ctx: int = 16384,
        n_threads: int = 8,
        n_gpu_layers: int = 0,
        n_batch: int = 512,
        cache_type_k: str = "",
        cache_type_v: str = "",
        use_mmap: bool = True,
        use_mlock: bool = False,
    ) -> bool:
        try:
            from llama_cpp import Llama
            from llama_cpp import llama_cpp as _llama_native
            path_obj = resolve_model_path(model_path)
            self.model_path = str(path_obj)
            if not path_obj.exists():
                self.load_error = f"Model not found: {path_obj}"
                return False
            print(f"🔄 Loading model: {path_obj.name}")
            print(f"   Size: {path_obj.stat().st_size / (1024**3):.2f} GB")
            # ELI HARDWARE PROFILE AUTHORITY v1
            # Startup hardware scan is authoritative across tablets, CPU-only machines,
            # single GPU rigs, multi-GPU rigs, and workstations.
            try:
                import json as _eli_hw_json
                from pathlib import Path as _EliHwPath
                from eli.core.paths import get_paths as _eli_get_paths
                _eli_profile_path = _EliHwPath(_eli_get_paths().artifacts_dir) / "runtime_hardware_profile.json"
                if _eli_profile_path.exists():
                    _eli_profile = _eli_hw_json.loads(_eli_profile_path.read_text(encoding="utf-8"))
                    n_ctx = int(_eli_profile.get("n_ctx", n_ctx))
                    n_gpu_layers = int(_eli_profile.get("n_gpu_layers", n_gpu_layers))
                    n_batch = int(_eli_profile.get("batch_size", n_batch))
                    log.debug(
                        f"[GUI][HW_AUTHORITY] using startup profile "
                        f"ctx={n_ctx} gpu_layers={n_gpu_layers} batch={n_batch}"
                    )
            except Exception as _eli_hw_err:
                log.debug(f"[GUI][HW_AUTHORITY] profile read failed: {_eli_hw_err}")

            print(f"   GPU-layer load parameter: {n_gpu_layers}")
            print(f"   Batch size: {n_batch}")
            if cache_type_k or cache_type_v:
                print(f"   KV cache: K={cache_type_k or 'default'} V={cache_type_v or 'default'}")
            requested_n_gpu_layers = int(n_gpu_layers)
            gpu_offload_supported = None
            try:
                _supports_fn = getattr(_llama_native, "llama_supports_gpu_offload", None)
                if callable(_supports_fn):
                    gpu_offload_supported = bool(_supports_fn())
            except Exception:
                gpu_offload_supported = None
            effective_n_gpu_layers = int(n_gpu_layers)
            if requested_n_gpu_layers > 0 and gpu_offload_supported is False:
                log.debug(
                    "[GUI][GPU] GPU offload unsupported by current runtime "
                    "(driver/CUDA/backend unavailable). Forcing CPU mode.",
                )
                effective_n_gpu_layers = 0
            effective_n_batch = int(n_batch)
            if int(effective_n_gpu_layers) <= 0 and int(effective_n_batch) > 128:
                log.debug(
                    f"[GUI][CPU] Clamping batch size {effective_n_batch} -> 128 for CPU-only mode.",
                )
                effective_n_batch = 128
            log.debug(
                f"[GUI][GPU] requested_layers={requested_n_gpu_layers} "
                f"effective_layers={effective_n_gpu_layers} "
                f"offload_supported={gpu_offload_supported}",
            )
            self.n_ctx = int(n_ctx)
            self.n_threads = int(n_threads)
            self.n_gpu_layers = int(effective_n_gpu_layers)
            self.n_batch = int(effective_n_batch)
            self.requested_n_gpu_layers = int(requested_n_gpu_layers)
            self.gpu_offload_supported = gpu_offload_supported
            _seen: set[Tuple[int, int, int]] = set()
            _attempts: List[Dict[str, Any]] = []

            def _add_attempt(label: str, ctx: int, layers: int, batch: int):
                _ctx = max(1024, int(ctx))
                _layers = max(0, int(layers))
                _batch = max(32, int(batch))
                if gpu_offload_supported is False:
                    _layers = 0
                key = (_ctx, _layers, _batch)
                if key in _seen:
                    return
                _seen.add(key)
                _attempts.append({
                    "label": str(label),
                    "n_ctx": _ctx,
                    "n_gpu_layers": _layers,
                    "n_batch": _batch,
                })

            _base_ctx = int(n_ctx)
            _base_layers = int(effective_n_gpu_layers)
            _base_batch = int(effective_n_batch)
            _add_attempt("requested", _base_ctx, _base_layers, _base_batch)

            if _base_layers > 0:
                _add_attempt("lower-batch-256", _base_ctx, _base_layers, min(_base_batch, 256))
                _add_attempt("lower-batch-128", _base_ctx, _base_layers, min(_base_batch, 128))
                _add_attempt("ctx12k-batch128", min(_base_ctx, 12288), _base_layers, min(_base_batch, 128))
                _add_attempt("ctx8k-half-gpu", min(_base_ctx, 8192), max(1, _base_layers // 2), min(_base_batch, 128))
                _add_attempt("ctx6k-half-gpu", min(_base_ctx, 6144), max(1, _base_layers // 2), min(_base_batch, 96))
                _add_attempt("ctx4k-third-gpu", min(_base_ctx, 4096), max(1, _base_layers // 3), min(_base_batch, 64))
                # Live-tuner: re-run allocate() with current GPU free VRAM.
                # Finds the best ctx/layers/batch the hardware can actually support
                # right now, without relying on the (possibly stale) startup profile.
                try:
                    import os as _os
                    from eli.core.startup_hardware_optimizer import (
                        detect_nvidia_gpus as _dng, select_gpu as _sg,
                        allocate as _hw_alloc, find_model as _fm,
                        load_settings as _hls, size_gb as _sgb,
                        detect_ram_gb as _drg,
                    )
                    _lt_gpus = _dng()
                    _lt_gpu = _sg(_lt_gpus)
                    if _lt_gpu and _lt_gpu.free_mb > 0:
                        _lt_settings = _hls()
                        _lt_model = _fm(_lt_settings)
                        _lt_model_gb = _sgb(_lt_model) if _lt_model else 0.0
                        _lt_ram = _drg()
                        if _lt_model_gb > 0:
                            _lt_ctx, _lt_layers, _lt_batch, _, _, _ = _hw_alloc(
                                _lt_model, _lt_model_gb, _lt_ram, _lt_gpu
                            )
                            if _lt_layers > 0:
                                _add_attempt("live-tuner-gpu", _lt_ctx, _lt_layers, _lt_batch)
                            # CPU path at live-tuner ctx (better than the 4096 floor)
                            _add_attempt("live-tuner-cpu", _lt_ctx, 0, min(_lt_batch, 96))
                except Exception:
                    pass
                # Dynamic CPU ctx floor: derive from RAM capacity, never a hardcoded int.
                # ELI_MIN_CTX env var overrides if set.
                try:
                    import os as _os2
                    _env_min = _os2.environ.get("ELI_MIN_CTX", "").strip()
                    if _env_min:
                        _cpu_ctx_floor = int(_env_min)
                    else:
                        from eli.core.startup_hardware_optimizer import (
                            ram_ctx_cap as _rcc, detect_ram_gb as _drg2
                        )
                        _cpu_ctx_floor = _rcc(_drg2(), 0)
                    _cpu_ctx_floor = min(_cpu_ctx_floor, _base_ctx)
                except Exception:
                    _cpu_ctx_floor = _base_ctx
                _add_attempt("cpu-fallback", _cpu_ctx_floor, 0, min(_base_batch, 96))
                _add_attempt("cpu-fallback-half-ctx", max(1024, _cpu_ctx_floor // 2), 0, min(_base_batch, 64))
            else:
                # CPU-only path: derive context steps from RAM capacity + ELI_MIN_CTX.
                # No hardcoded ctx floors — all values are calculated dynamically.
                try:
                    import os as _os3
                    _env_min_cpu = _os3.environ.get("ELI_MIN_CTX", "").strip()
                    if _env_min_cpu:
                        _cpu_base_ctx = min(int(_env_min_cpu), _base_ctx)
                    else:
                        from eli.core.startup_hardware_optimizer import (
                            ram_ctx_cap as _rcc2, detect_ram_gb as _drg3
                        )
                        _cpu_base_ctx = min(_rcc2(_drg3(), 0), _base_ctx)
                except Exception:
                    _cpu_base_ctx = _base_ctx
                _add_attempt("cpu-batch-96", _base_ctx, 0, min(_base_batch, 96))
                _add_attempt("cpu-ctx-ram-cap", _cpu_base_ctx, 0, min(_base_batch, 96))
                _add_attempt("cpu-ctx-half-ram-cap", max(1024, _cpu_base_ctx // 2), 0, min(_base_batch, 64))
                _add_attempt("cpu-ctx-quarter-ram-cap", max(1024, _cpu_base_ctx // 4), 0, min(_base_batch, 32))

            _applied = None
            _last_error = ""
            for i, _cand in enumerate(_attempts, start=1):
                log.debug(
                    f"[GUI][LOAD] attempt {i}/{len(_attempts)}: {_cand['label']} "
                    f"(ctx={_cand['n_ctx']} gpu_layers={_cand['n_gpu_layers']} batch={_cand['n_batch']})",
                )
                llama_kwargs: Dict[str, Any] = dict(
                    model_path=str(path_obj),
                    n_ctx=int(_cand["n_ctx"]),
                    n_threads=int(n_threads),
                    n_gpu_layers=int(_cand["n_gpu_layers"]),
                    n_batch=int(_cand["n_batch"]),
                    use_mmap=bool(use_mmap),
                    use_mlock=bool(use_mlock),
                    chat_format="chatml",
                    verbose=False,
                )
                if cache_type_k:
                    llama_kwargs["cache_type_k"] = str(cache_type_k)
                if cache_type_v:
                    llama_kwargs["cache_type_v"] = str(cache_type_v)
                try:
                    try:
                        self.model = Llama(**llama_kwargs)
                    except TypeError:
                        llama_kwargs.pop("cache_type_k", None)
                        llama_kwargs.pop("cache_type_v", None)
                        self.model = Llama(**llama_kwargs)
                    _applied = dict(_cand)
                    break
                except Exception as _attempt_err:
                    _last_error = str(_attempt_err)
                    log.debug(f"[GUI][LOAD] attempt failed: {_last_error}")
                    self.model = None
                    gc.collect()
                    continue

            if self.model is None or _applied is None:
                raise RuntimeError(
                    "Failed to create llama_context after adaptive load attempts. "
                    f"Last error: {_last_error or 'unknown'}"
                )

            applied_n_ctx = int(_applied["n_ctx"])
            applied_n_gpu_layers = int(_applied["n_gpu_layers"])
            applied_n_batch = int(_applied["n_batch"])
            log.debug(
                f"[GUI][LOAD] selected={_applied['label']} "
                f"(ctx={applied_n_ctx} gpu_layers={applied_n_gpu_layers} batch={applied_n_batch})",
            )

            setattr(self.model, "n_ctx", int(applied_n_ctx))
            setattr(self.model, "n_threads", int(n_threads))
            setattr(self.model, "n_gpu_layers", int(applied_n_gpu_layers))
            setattr(self.model, "n_batch", int(applied_n_batch))
            self.n_ctx = int(applied_n_ctx)
            self.n_threads = int(n_threads)
            self.n_gpu_layers = int(applied_n_gpu_layers)
            self.n_batch = int(applied_n_batch)
            try:
                from eli.cognition import gguf_inference as _gg
                _gg._llm = self.model
            except Exception as _wire_err:
                log.debug(f"[GUI] gguf runtime handoff failed: {_wire_err}")
            self.is_loaded = True
            self.n_ctx = int(self.n_ctx or 0)
            self.n_threads = int(self.n_threads or 0)
            self.n_gpu_layers = int(self.n_gpu_layers or 0)
            self.n_batch = int(getattr(self.model, 'n_batch', 0) or 0)
            try:
                from eli.cognition import gguf_inference as _ggi
                _ggi._llm = self.model
                _ggi.set_live_runtime_override({
                    "provider": "gguf",
                    "loaded": True,
                    "model_path": str(path_obj),
                    "model_name": path_obj.name,
                    "n_ctx": int(self.n_ctx),
                    "n_gpu_layers": int(self.n_gpu_layers),
                    "n_threads": int(self.n_threads),
                    "n_batch": int(self.n_batch),
                    "requested_n_gpu_layers": int(requested_n_gpu_layers),
                    "gpu_offload_supported": gpu_offload_supported,
                    "load_mode": "GPU" if int(self.n_gpu_layers) > 0 else "CPU",
                })
                print("✅ gguf_inference live runtime override published")
            except Exception as e:
                log.debug(f"[GUI] live runtime override publish failed: {e}")
            self.load_error = None
            print(f"✅ Model loaded successfully")
            self._write_shared_runtime_snapshot(
                str(path_obj),
                self.n_ctx,
                n_threads,
                self.n_gpu_layers,
                requested_n_gpu_layers=requested_n_gpu_layers,
                gpu_offload_supported=gpu_offload_supported,
            )
            return True
        except Exception as e:
            self.load_error = f"Failed to load model: {str(e)}"
            print(f"❌ {self.load_error}")
            self.model = None
            self.is_loaded = False
            gc.collect()
            return False
    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 2048,
             temperature: float = 0.7) -> str:
        if not self.is_loaded or not self.model:
            return "❌ Model not loaded"
        try:
            response = self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.9,
            )
            return response['choices'][0]['message']['content'].strip()
        except Exception as e:
            return f"❌ Chat error: {str(e)}"
    def generate(self, prompt: str, max_tokens: int = 2048,
                temperature: float = 0.7) -> str:
        messages = [
            {'role': 'system', 'content': ELI_SYSTEM_PROMPT},
            {'role': 'user',   'content': prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature)
    def chat_stream(self, messages, max_tokens=4096, temperature=0.7):
        if not self.is_loaded or not self.model:
            yield "❌ Model not loaded"
            return
        try:
            stream = self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=0.9,
                stream=True,
            )
            for chunk in stream:
                delta = chunk['choices'][0].get('delta', {})
                token = delta.get('content', '')
                if token:
                    yield token
        except Exception as e:
            yield f"\n❌ Stream error: {e}"
    def unload(self):
        self.model = None
        self.is_loaded = False
        gc.collect()
        print("🔄 Model unloaded")

class OllamaModelManager:
    provider_name = "ollama"
    def __init__(self):
        self.host = "http://localhost:11434"
        self.model_name = ""
        self.is_loaded = False
        self.load_error = None
    def _normalize_host(self, host: str) -> str:
        host = (host or "http://localhost:11434").strip().rstrip('/')
        if not host.startswith('http://') and not host.startswith('https://'):
            host = 'http://' + host
        return host
    def list_models(self, host: Optional[str] = None) -> List[str]:
        host = self._normalize_host(host or self.host)
        url = host + '/api/tags'
        req = urllib.request.Request(url, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='replace'))
        return [m.get('name', '') for m in data.get('models', []) if m.get('name')]
    def load_model(self, host: str, model_name: str) -> bool:
        try:
            self.host = self._normalize_host(host)
            self.model_name = (model_name or '').strip()
            if not self.model_name:
                self.load_error = 'No Ollama model selected.'
                self.is_loaded = False
                return False
            models = self.list_models(self.host)
            if models and self.model_name not in models:
                log.debug(f"[OLLAMA] model not in /api/tags yet, continuing anyway: {self.model_name}")
            self.load_error = None
            self.is_loaded = True
            return True
        except Exception as e:
            self.load_error = f"Failed to connect to Ollama: {e}"
            self.is_loaded = False
            return False
    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 2048,
             temperature: float = 0.7) -> str:
        if not self.is_loaded:
            return "❌ Ollama model not loaded"
        url = self.host + '/api/chat'
        payload = {
            'model': self.model_name,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens,
            }
        }
        body = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode('utf-8', errors='replace'))
        msg = data.get('message') or {}
        return (msg.get('content') or '').strip()
    def generate(self, prompt: str, max_tokens: int = 2048,
                temperature: float = 0.7) -> str:
        messages = [
            {'role': 'system', 'content': ELI_SYSTEM_PROMPT},
            {'role': 'user',   'content': prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature)
    def chat_stream(self, messages, max_tokens=4096, temperature=0.7):
        if not self.is_loaded:
            yield "❌ Ollama not loaded"
            return
        import json, urllib.request
        url = self.host + '/api/chat'
        payload = {
            'model': self.model_name,
            'messages': messages,
            'stream': True,
            'options': {'temperature': temperature, 'num_predict': max_tokens},
        }
        body = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for line in resp:
                    line = line.decode('utf-8', errors='replace').strip()
                    if not line:
                        continue
                    try:
                        j = json.loads(line)
                        token = (j.get('message') or {}).get('content', '')
                        if token:
                            yield token
                        if j.get('done'):
                            break
                    except Exception:
                        continue
        except Exception as e:
            yield f"\n❌ Ollama stream error: {e}"
    def unload(self):
        self.is_loaded = False

model_manager = LocalModelManager()

# ============================================================
# EXECUTOR INTEGRATION (unchanged)
# ============================================================
class ExecutorBridge:
    def __init__(self):
        self.executor_module = None
        self.router_module = None
        self.import_notes: List[str] = []
        self._load_modules()
    def _candidate_roots(self) -> List[Path]:
        here = Path(__file__).resolve()
        candidates = [
            here.parent,
            here.parent.parent,
            here.parent.parent.parent,
            here.parent.parent.parent.parent,
            PROJECT_ROOT,
            Path.cwd(),
            Path(__file__).resolve().parents[2],
        ]
        seen = set()
        out: List[Path] = []
        for c in candidates:
            try:
                r = c.resolve()
            except Exception:
                r = c
            key = str(r)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out
    def _prepare_sys_path(self) -> None:
        import sys as _sys
        for root in self._candidate_roots():
            root_str = str(root)
            if root_str not in _sys.path:
                _sys.path.insert(0, root_str)
    def _import_first(self, module_names: List[str]):
        self._prepare_sys_path()
        last_err = None
        for name in module_names:
            try:
                module = __import__(name, fromlist=['*'])
                self.import_notes.append(f"loaded:{name}")
                return module
            except Exception as e:
                last_err = e
                self.import_notes.append(f"failed:{name}:{e}")
        if last_err:
            raise last_err
        raise ImportError('No module names supplied')
    def _load_modules(self):
        executor_candidates = [
            'eli.execution.executor_enhanced',
            'eli.tools.executor_enhanced',
            'eli.execution.executor_enhanced',
        ]
        router_candidates = [
            'eli.execution.router_enhanced',
            'eli.tools.router_enhanced',
            'eli.execution.router_enhanced',
        ]
        try:
            self.executor_module = self._import_first(executor_candidates)
            print(f"✅ Executor module loaded: {getattr(self.executor_module, '__name__', self.executor_module)}")
        except Exception as e:
            print(f"⚠️  Executor module not found: {e}")
        try:
            self.router_module = self._import_first(router_candidates)
            print(f"✅ Router module loaded: {getattr(self.router_module, '__name__', self.router_module)}")
        except Exception as e:
            print(f"⚠️  Router module not found: {e}")
    def route_command(self, text: str) -> Dict[str, Any]:
        if self.router_module:
            try:
                if hasattr(self.router_module, 'route'):
                    return self.router_module.route(text)
                if hasattr(self.router_module, 'route_command'):
                    return self.router_module.route_command(text)
            except Exception as e:
                print(f"⚠️  Router error: {e}")
        return self._simple_route(text)
    def _simple_route(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower().strip()
        if 'time' in text_lower or 'what time' in text_lower:
            return {'action': 'TIME', 'args': {}}
        if (
            text_lower == 'date'
            or 'what date' in text_lower
            or 'current date' in text_lower
            or 'what is the date' in text_lower
            or "what's the date" in text_lower
            or text_lower == 'today'
            or 'what day' in text_lower
        ):
            return {'action': 'DATE', 'args': {}}
        if 'remember' in text_lower or 'store memory' in text_lower:
            return {'action': 'MEMORY_STORE', 'args': {'text': text}}
        if 'recall' in text_lower or 'search memory' in text_lower:
            return {'action': 'MEMORY_RECALL', 'args': {'query': text, 'limit': 10}}
        return {'action': 'CHAT', 'args': {'message': text}}
    def execute_action(self, action: str, args: Dict[str, Any]) -> str:
        if self.executor_module:
            try:
                if hasattr(self.executor_module, 'execute'):
                    result = self.executor_module.execute(action, args)
                    return self._coerce_result(result)
                if hasattr(self.executor_module, 'execute_action'):
                    result = self.executor_module.execute_action(action, args)
                    return self._coerce_result(result)
            except Exception as e:
                return f"❌ Execution error: {str(e)}"
        return self._simple_execute(action, args)
    def _coerce_result(self, result: Any) -> str:
        if isinstance(result, dict):
            return str(result.get('content') or result.get('response') or result.get('message') or result)
        return str(result)
    def _simple_execute(self, action: str, args: Dict[str, Any]) -> str:
        if action == 'TIME':
            return f"Current time: {now_timestamp()}"
        if action == 'DATE':
            return datetime.now().strftime("%A, %Y-%m-%d")
        if action == 'MEMORY_STORE':
            text = args.get('text', '')
            if memory_system.store(text):
                return '✅ Memory stored'
            return '❌ Failed to store memory'
        if action == 'MEMORY_RECALL':
            query = args.get('query', '')
            limit = args.get('limit', 10)
            results = memory_system.search(query, limit)
            if results:
                return f"Found {len(results)} memories:\n" + "\n".join(
                    f"- {r['text']}" for r in results[:5]
                )
            return 'No memories found'
        try:
            from eli.execution.executor_enhanced import execute as execute_enhanced
            result = execute_enhanced(action, args or {})
            if isinstance(result, dict):
                return result.get("response") or result.get("content") or str(result)
            return str(result)
        except Exception:
            return f"Action {action} not implemented in fallback mode"

executor_bridge = ExecutorBridge()

# ============================================================
# STARTUP MODEL + HARDWARE TUNING UI  (extracted → eli/gui/panels/startup.py)
# ============================================================
from eli.gui.panels.startup import HardwareTuningDock  # noqa: E402


from eli.gui.panels.startup import StartupModelSelectionDialog, FirstBootWizard  # noqa: E402
# ============================================================
# ============================================================
# AGENT EDIT DIALOG  (extracted → eli/gui/panels/agent_wizard.py)
# ============================================================
from eli.gui.panels.agent_wizard import AgentEditDialog  # noqa: E402
# ============================================================
# QUICK ACTIONS — helper classes
# ============================================================

class _FlowLayout(QLayout):
    """Wrapping flow layout — items fill left-to-right then wrap."""

    def __init__(self, parent=None, h_spacing: int = 8, v_spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self._h = h_spacing
        self._v = v_spacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        return self._layout(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._layout(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        sz = QSize()
        for it in self._items:
            sz = sz.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return sz + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, dry: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = eff.x(), eff.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._h
            if nx - self._h > eff.right() and row_h > 0:
                x, y = eff.x(), y + row_h + self._v
                nx = x + hint.width() + self._h
                row_h = 0
            if not dry:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x, row_h = nx, max(row_h, hint.height())
        return y + row_h - rect.y() + m.bottom()


class _CapabilityList(QListWidget):
    """Draggable list that emits the capability name via MIME text/plain."""

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if not item:
            return
        drag = QDrag(self)
        mime = QMimeData()
        # Store only the raw action name (strip description suffix)
        mime.setText(item.data(Qt.ItemDataRole.UserRole) or item.text().split()[0])
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class _QABoard(QWidget):
    """
    Drop target that holds quick-action button cards.
    Each card: action label + ▶ Run button + ✕ remove.
    """
    changed = pyqtSignal()  # emitted whenever cards are added/removed

    _NO_ARG_ACTIONS = frozenset({
        # Time / date
        "TIME", "DATE", "GET_DATE", "GET_TIME",
        # System info
        "SCREENSHOT", "HARDWARE_PROFILE", "LIST_DIR",
        "RUNTIME_AUDIT", "IMPORT_AUDIT", "RESOLVE_RUNTIME_PATHS",
        "GUI_RUNTIME_AUDIT", "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME",
        "RUNTIME_STATUS", "REASONING_MODE_STATUS", "MEMORY_STATUS", "COGNITION_STATUS",
        # Memory
        "MEMORY_STATS", "AWARENESS_STATUS", "PERSONAL_MEMORY_SUMMARY",
        "PERSONAL_MEMORY_DEEP_EXPLAIN", "ROUTING_FAULT_EXPLAIN", "NAME_SOURCE_AUDIT",
        # Help & capabilities
        "HELP", "LIST_CAPABILITIES",
        # Self-awareness / improvement
        "SELF_TEST", "SELF_ANALYZE", "SELF_IMPROVE", "SELF_PATCH", "SELF_UPGRADE",
        "MORNING_REPORT", "CODE_CHANGES",
        # Proactive daemon
        "PROACTIVE_START", "PROACTIVE_STOP", "PROACTIVE_STATUS", "HABIT_STATUS",
        # Clipboard (get)
        "GET_CLIPBOARD",
        # Plugins
        "PLUGIN_LIST", "PLUGIN_STATUS",
        # News (default fetch all)
        "NEWS_FETCH",
        # Misc
        "GET_STATUS", "SHOW_DIFF", "LIST_EVENTS",
        # Media control (no args needed to pause/stop/next/prev)
        "STOP_MEDIA", "PAUSE_MEDIA", "PLAY_MEDIA", "NEXT_MEDIA",
        "PREVIOUS_MEDIA", "SHUFFLE_MEDIA", "REPEAT_MEDIA",
        # Chronal / system
        "CHECK_CHRONAL_ALIGNMENT",
        # File system / OS launchers
        "OPEN_FILE_SYSTEM", "OPEN_AUDIO_SETTINGS", "OPEN_BROWSER",
        "OPEN_COMMUNICATION_HUB", "OPEN_MEDIA_HUB", "OPEN_NETWORK_BROWSER",
        "OPEN_SYSTEM_SETTINGS", "OPEN_POWER_SETTINGS", "OPEN_IDE",
        # Persona
        "PERSONA_LOCK_STATUS", "PERSONA_LOCK_CLEAR",
        # System stats (no args)
        "CPU_USAGE", "RAM_USAGE", "SYSTEM_STATS",
        # Notes / Pomodoro no-arg variants
        "LIST_NOTES", "POMODORO_STATUS", "POMODORO_STOP",
    })

    def __init__(self, execute_fn, parent=None):
        super().__init__(parent)
        self._execute_fn = execute_fn   # callable(action_name, args)
        self._cards: dict[str, QWidget] = {}
        self._flow = _FlowLayout(self, h_spacing=10, v_spacing=10)
        self.setLayout(self._flow)
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)

    # ── Drop handling ────────────────────────────────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasText():
            action = event.mimeData().text().strip()
            if action:
                self.add_card(action)
                event.acceptProposedAction()

    # ── Card management ──────────────────────────────────────────────────────
    def add_card(self, action_name: str) -> bool:
        """Add a card for action_name. Returns False if already present."""
        if action_name in self._cards:
            return False

        card = QFrame()
        card.setFixedSize(148, 88)
        card.setStyleSheet(
            "QFrame{background:#1e2230;border:1px solid #3b4060;"
            "border-radius:8px;}"
            "QLabel{background:transparent;color:#c8d0e0;}"
            "QPushButton{border-radius:4px;padding:3px 6px;font-size:10px;}"
        )
        vl = QVBoxLayout(card)
        vl.setContentsMargins(8, 6, 8, 6)
        vl.setSpacing(4)

        # Top row: label + close
        top = QHBoxLayout()
        lbl = QLabel(action_name)
        lbl.setStyleSheet("font-size:10px;font-weight:bold;color:#88c0d0;")
        lbl.setWordWrap(True)
        top.addWidget(lbl, 1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(18, 18)
        close_btn.setStyleSheet(
            "QPushButton{background:#3b1f1f;color:#bf616a;border:none;font-size:9px;}"
            "QPushButton:hover{background:#bf616a;color:#fff;}"
        )
        close_btn.clicked.connect(lambda: self.remove_card(action_name))
        top.addWidget(close_btn)
        vl.addLayout(top)

        # Run button
        run_btn = QPushButton("▶  Run")
        run_btn.setStyleSheet(
            "QPushButton{background:#2d4a3e;color:#a3be8c;border:1px solid #3d6b56;}"
            "QPushButton:hover{background:#3d6b56;}"
            "QPushButton:pressed{background:#2a5c48;}"
        )
        run_btn.clicked.connect(lambda: self._fire(action_name))
        vl.addWidget(run_btn)

        self._flow.addWidget(card)
        self._cards[action_name] = card
        self.update()
        self.changed.emit()
        return True

    def remove_card(self, action_name: str):
        card = self._cards.pop(action_name, None)
        if card:
            self._flow.removeWidget(card)
            card.deleteLater()
            self.update()
            self.changed.emit()

    def clear_all(self):
        for name in list(self._cards.keys()):
            self.remove_card(name)

    def action_names(self) -> list:
        return list(self._cards.keys())

    # ── Action execution ─────────────────────────────────────────────────────
    def _fire(self, action_name: str):
        # Pass empty args — _qa_run_action on EliMainWindow handles all
        # arg prompting using _QA_ACTION_ARGS metadata (specific prompts
        # per action with the correct arg key).  No-arg actions just run.
        self._execute_fn(action_name, {})


# ============================================================
# ZOOMABLE SETTINGS VIEW  (Ctrl+Scroll to zoom in/out)
# ============================================================
class _ZoomableSettingsView(QGraphicsView):
    """
    Wraps a widget in a QGraphicsView that supports Ctrl+Scroll zoom.
    The embedded widget auto-sizes to the viewport width at the current zoom.
    """
    def __init__(self, widget: QWidget, parent=None):
        super().__init__(parent)
        self._inner = widget
        self._zoom = 1.0

        scene = QGraphicsScene(self)
        self._proxy = QGraphicsProxyWidget()
        self._proxy.setWidget(widget)
        scene.addItem(self._proxy)
        self.setScene(scene)

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QBrush(QColor("#1a1d23")))
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_inner()

    def _fit_inner(self):
        vw = max(100, self.viewport().width())
        target_w = max(100, int(vw / self._zoom))
        self._inner.setFixedWidth(target_w)
        self.setSceneRect(0, 0, vw / self._zoom,
                          max(self._proxy.boundingRect().height(),
                              self.viewport().height() / self._zoom))

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.08 if delta > 0 else (1.0 / 1.08)
            new_zoom = max(0.55, min(2.0, self._zoom * factor))
            if abs(new_zoom - self._zoom) > 0.001:
                change = new_zoom / self._zoom
                self._zoom = new_zoom
                self.scale(change, change)
                self._fit_inner()
            event.accept()
        else:
            super().wheelEvent(event)

    def zoom_reset(self):
        self.resetTransform()
        self._zoom = 1.0
        self._fit_inner()

    def zoom_in(self):
        new_zoom = min(2.0, self._zoom * 1.08)
        if abs(new_zoom - self._zoom) > 0.001:
            change = new_zoom / self._zoom
            self._zoom = new_zoom
            self.scale(change, change)
            self._fit_inner()

    def zoom_out(self):
        new_zoom = max(0.55, self._zoom / 1.08)
        if abs(new_zoom - self._zoom) > 0.001:
            change = new_zoom / self._zoom
            self._zoom = new_zoom
            self.scale(change, change)
            self._fit_inner()


class _MiniTelemetryGraph(QWidget):
    """Small sparkline-style history graph for live runtime telemetry."""

    def __init__(self, accent: str = "#88c0d0", parent=None):
        super().__init__(parent)
        self._values: list[float] = []
        self._accent = QColor(accent)
        self.setMinimumHeight(72)

    def set_values(self, values: List[float]):
        self._values = [max(0.0, min(100.0, float(v))) for v in values]
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = self.rect().adjusted(1, 1, -1, -1)
        if rect.width() <= 0 or rect.height() <= 0:
            return

        p.setPen(QPen(QColor("#283142"), 1))
        p.setBrush(QColor("#11151d"))
        p.drawRoundedRect(rect, 6, 6)

        if len(self._values) < 2:
            p.setPen(QColor("#5f6f86"))
            p.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "Waiting for samples...")
            return

        path = QPainterPath()
        area = QPainterPath()
        x_step = rect.width() / max(1, len(self._values) - 1)
        bottom = rect.bottom()

        points: list[QPointF] = []
        for idx, value in enumerate(self._values):
            x = rect.left() + (idx * x_step)
            y = rect.bottom() - ((value / 100.0) * rect.height())
            points.append(QPointF(x, y))

        path.moveTo(points[0])
        for pt in points[1:]:
            path.lineTo(pt)

        area.moveTo(rect.left(), bottom)
        for pt in points:
            area.lineTo(pt)
        area.lineTo(rect.right(), bottom)
        area.closeSubpath()

        fill = QColor(self._accent)
        fill.setAlpha(58)
        p.setPen(QPen(self._accent, 2))
        p.setBrush(fill)
        p.drawPath(area)
        p.drawPath(path)


class _ZoomableImagePreview(QScrollArea):
    """Scrollable image preview with Ctrl+wheel and button-driven zoom."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._zoom = 1.0
        self._pixmap = QPixmap()
        self._label = QLabel("Generate an image to preview it here.")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color:#73839a;font-size:13px;padding:30px;")
        self._label.setMinimumSize(420, 320)
        self.setWidget(self._label)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QScrollArea{background:#10141d;border:1px solid #283142;border-radius:10px;}"
        )

    def set_image_path(self, path: str | Path):
        pix = QPixmap(str(path))
        if pix.isNull():
            self._label.setText(f"Unable to load preview:\n{path}")
            self._pixmap = QPixmap()
            return False
        self._pixmap = pix
        self._zoom = 1.0
        self._render()
        return True

    def _render(self):
        if self._pixmap.isNull():
            return
        target = self._pixmap.size() * self._zoom
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)
        self._label.resize(scaled.size())

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def zoom_in(self):
        self._zoom = min(6.0, self._zoom * 1.12)
        self._render()

    def zoom_out(self):
        self._zoom = max(0.2, self._zoom / 1.12)
        self._render()

    def zoom_reset(self):
        self._zoom = 1.0
        self._render()


# ============================================================
# ============================================================
# ADVANCED SETTINGS DIALOG  (extracted → eli/gui/panels/settings.py)
# ============================================================
from eli.gui.panels.settings import AdvancedSettingsDialog  # noqa: E402
# ENGINE ADAPTER — feeds the AgentOrchestrator without a second model load
# ============================================================
class _GUIEngineAdapter:
    """
    Thin adapter that satisfies the AgentOrchestrator's engine interface
    using the GUI's already-loaded GGUF backend.

    Every method the orchestrator calls goes through this adapter so the
    full 11-stage blueprint pipeline runs with zero extra model loads.
    """

    def __init__(self, backend, memory, max_tokens: int,
                 temperature: float, n_ctx: int, inference_lock,
                 cognitive_engine=None):
        self._backend       = backend
        self.memory         = memory          # raw Memory instance
        self._max_tokens    = max_tokens
        self._temperature   = temperature
        self._n_ctx         = n_ctx
        self._lock          = inference_lock  # class-level GUI lock (thread-safe)
        self._ce            = cognitive_engine
        self._in_orchestrator = False
        self.document_rag   = None            # optional RAG — not wired yet
        self.session_id     = f"gui-{int(time.time())}"
        self.user_id        = self._load_user_id()

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _load_user_id() -> str:
        try:
            from eli.core.paths import get_paths as _gp
            uid_file = _gp().config_dir / "user_id"
            if uid_file.exists():
                return uid_file.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            pass
        return "local-user"

    def _compact_persona(self) -> str:
        """Return persona trimmed to ≤900 chars for small context windows."""
        p = ELI_SYSTEM_PROMPT or ""
        return p[:900].rstrip() if len(p) > 900 else p

    def _build_persona_handoff_once(self, user_input: str, memory_context: str = "",
                                    bus_result=None, recent_turns=None, working_memory=None) -> str:
        if self._ce is None or not hasattr(self._ce, "_build_persona_handoff_once"):
            return ""
        return self._ce._build_persona_handoff_once(
            user_input=user_input,
            memory_context=memory_context,
            bus_result=bus_result,
            recent_turns=recent_turns,
            working_memory=working_memory,
        )

    # ── AgentOrchestrator interface ───────────────────────────────────────
    # ---- PATH2 COMPATIBILITY SURFACE ----
    # These methods are intentionally retained because the AgentOrchestrator
    # fallback path still calls them through the GUI adapter.
    # Main runtime path is CognitiveEngine-first.
    # Do NOT rename/remove these until orchestrator.py is migrated off them.
    def parse_intent(self, user_input: str, context: list) -> dict:
        try:
            if self._ce is not None and hasattr(self._ce, "parse_intent"):
                return self._ce.parse_intent(user_input, context)
        except Exception as _ce_delegate_err:
            log.debug(f"[GUI] parse_intent CE delegation failed: {_ce_delegate_err}")

        try:
            from eli.execution.router_enhanced import route
            return route(user_input)
        except Exception as e:
            log.debug(f"[ENGINE-ADAPTER] parse_intent fallback: {e}")
            return {"action": "CHAT", "args": {"message": user_input},
                    "confidence": 0.7, "meta": {}}

    def verify_persona_lock(self) -> bool:
        """Delegate to CognitiveEngine when available; fall back to True."""
        try:
            if self._ce is not None and hasattr(self._ce, "verify_persona_lock"):
                return self._ce.verify_persona_lock()
        except Exception as _vpl_err:
            log.debug(f"[GUI] verify_persona_lock CE delegation failed: {_vpl_err}")
        return True

    def repair_persona_lock(self):
        """Delegate to CognitiveEngine when available."""
        try:
            if self._ce is not None and hasattr(self._ce, "repair_persona_lock"):
                self._ce.repair_persona_lock()
        except Exception as _rpl_err:
            log.debug(f"[GUI] repair_persona_lock CE delegation failed: {_rpl_err}")

    def recall_memory_query(self, query: str, limit: int = 12) -> list:
        if self.memory is None:
            return []
        try:
            return self.memory.recall_memory(query, limit=limit) or []
        except Exception:
            return []

    def _dispatch_agent_bus(self, user_input: str, intent: dict) -> str:
        """
        Dispatch the 13-agent AgentBus concurrently.  All agents are pure
        SQLite/filesystem evidence-gatherers (no LLM calls) so this is safe
        to run outside the inference lock.  Returns a compact context block.
        """
        try:
            from eli.cognition.agent_bus import get_bus
            dr = get_bus().dispatch(
                user_input, intent,
                session_id=self.session_id,
                user_id=self.user_id,
            )
            ctx = (dr.memory_context or "").strip()
            log.debug(f"[ENGINE-ADAPTER] AgentBus: agents_used={dr.agents_used} "
                  f"conf={dr.aggregated_confidence:.2f} ctx_chars={len(ctx)}")
            return ctx
        except Exception as e:
            log.debug(f"[ENGINE-ADAPTER] AgentBus dispatch failed: {e}")
            return ""

    def assemble_precise_context(self, user_input: str, working_memory,
                                 short_term_memory, intent: dict,
                                 reasoning_mode: str = None) -> tuple:
        """
        Build (assembled_context, final_prompt) from the orchestrator's
        populated WorkingMemory.  assembled_context becomes the system prompt;
        final_prompt is the raw user query.
        """
        try:
            if self._ce is not None and hasattr(self._ce, "assemble_precise_context"):
                return self._ce.assemble_precise_context(
                    user_input,
                    working_memory=working_memory,
                    short_term_memory=short_term_memory,
                    intent=intent,
                    reasoning_mode=reasoning_mode,
                )
        except Exception as _ce_delegate_err:
            log.debug(f"[GUI] assemble_precise_context CE delegation failed: {_ce_delegate_err}")

        import time as _t

        # Token budget: leave enough room for response + safety margin
        _char_budget = max(3000, self._n_ctx * 3 - self._max_tokens * 5)

        # 1. Persona — compact for small models, full for 7B+
        _use_compact = self._n_ctx <= 8192
        persona = self._compact_persona() if _use_compact else (ELI_SYSTEM_PROMPT or "")

        # 2. User profile
        _user_block = ""
        try:
            from eli.kernel.state import get_user_profile_text as _gup
            _user_block = _gup().strip()
        except Exception:
            pass
        if not _user_block:
            try:
                from eli.kernel.state import get_user_name as _gun
                _n = _gun().strip()
                if _n:
                    _user_block = f"Name: {_n}"
            except Exception:
                pass

        # 3. Retrieved + reranked memory hits (most valuable context)
        hit_lines = []
        for hit in (working_memory.reranked_hits or [])[:8]:
            txt = (hit.get("text") or "").strip()[:260]
            if txt:
                src = hit.get("source", "memory")
                hit_lines.append(f"[{src}] {txt}")

        # 4. Recent conversation turns (short-term memory)
        conv_lines = []
        for turn in (short_term_memory.recent_turns or [])[-8:]:
            role    = turn.get("role", "user")
            content = (turn.get("content") or "").strip()[:280]
            if content:
                conv_lines.append(f"[{role.upper()}]: {content}")

        # 5. Reasoning-mode instruction — private strategy, final answer only.
        try:
            from eli.cognition.reasoning_modes import gui_prompt_prefix_for_mode as _rm_gui_prefix
            _mode_instr = _rm_gui_prefix(reasoning_mode)
        except Exception:
            _mode_instr = ""

        _now  = _t.strftime("%H:%M:%S %Z", _t.localtime())
        _date = _t.strftime("%A %d %B %Y", _t.localtime())

        # ── AgentBus — 13 specialist agents in parallel (no LLM, pure SQLite) ──
        _bus_ctx = ""  # orchestrator already gathered evidence; avoid duplicate AgentBus dispatch

        # Assemble — persona first, then user profile, history, context, rules
        parts = [persona]
        if _user_block:
            parts.append(f"\nUSER PROFILE (personalise every response using this):\n{_user_block}")
        if _mode_instr:
            parts.append(_mode_instr)
        if conv_lines:
            parts.append(
                "\n--- CONVERSATION HISTORY ---\n"
                + "\n".join(conv_lines)
                + "\n--- END HISTORY ---"
            )
        if hit_lines:
            parts.append(
                "\n--- RETRIEVED CONTEXT (memory + knowledge base) ---\n"
                + "\n".join(hit_lines)
                + "\n--- END CONTEXT ---"
            )
        if _bus_ctx:
            # Trim bus context to stay within budget (agents can return verbose data)
            _bus_trimmed = _bus_ctx[:1200] if len(_bus_ctx) > 1200 else _bus_ctx
            parts.append(
                "\n--- AGENT INTELLIGENCE (system state + habits + knowledge graph) ---\n"
                + _bus_trimmed
                + "\n--- END AGENT INTELLIGENCE ---"
            )
        parts.append(
            f"\nCURRENT TIME: {_now}  DATE: {_date}."
            "\n\nRESPONSE DISCIPLINE — obey every reply:"
            "\n- Answer ONLY what was asked. Nothing more."
            "\n- NEVER echo or paraphrase the user's message as your opening."
            "\n- NEVER include unsolicited Memory System / Cognition Pipeline sections."
            "\n- NEVER pad with system internals, file paths, or architecture unless asked."
            "\n- Personal/philosophical questions: answer directly as ELI."
            "\n- Begin your reply with ELI's own voice. Direct. Dry. Accurate."
        )

        assembled = "\n".join(parts)

        # Hard budget guard — truncate oldest history if over budget
        if len(assembled) > _char_budget:
            overshoot = len(assembled) - _char_budget
            if conv_lines:
                conv_lines = conv_lines[1:]     # drop oldest turn
                parts_rebuild = [p for p in parts
                                 if "CONVERSATION HISTORY" not in p]
                if conv_lines:
                    parts_rebuild.insert(-1,
                        "\n--- CONVERSATION HISTORY ---\n"
                        + "\n".join(conv_lines)
                        + "\n--- END HISTORY ---"
                    )
                assembled = "\n".join(parts_rebuild)

        return assembled, user_input

    def generate_from_assembled_prompt(self, prompt: str,
                                       working_memory=None,
                                       reasoning_mode: str = None,
                                       raw_direct: bool = False) -> str:
        """
        Non-streaming inference.  Used by HyDE (raw_direct=True, tiny budget)
        and occasionally for grounded action results.
        """
        try:
            if self._ce is not None and hasattr(self._ce, "generate_from_assembled_prompt"):
                return self._ce.generate_from_assembled_prompt(
                    prompt,
                    working_memory=working_memory,
                    reasoning_mode=reasoning_mode,
                )
        except Exception as _ce_delegate_err:
            log.debug(f"[GUI] generate_from_assembled_prompt CE delegation failed: {_ce_delegate_err}")

        if raw_direct:
            # HyDE hypothetical-doc generation — minimal system, tiny token budget
            system = (
                "You are a knowledge assistant. Write a short factual answer "
                "(2-3 sentences, no roleplay, no filler)."
            )
            max_tok = 72
        else:
            system   = (working_memory.assembled_context
                        if working_memory and working_memory.assembled_context
                        else ELI_SYSTEM_PROMPT)
            max_tok  = self._max_tokens

        messages = [{"role": "system", "content": system},
                    {"role": "user",   "content": prompt}]
        try:
            with self._lock:
                if hasattr(self._backend, "chat"):
                    return self._backend.chat(
                        messages=messages,
                        max_tokens=max_tok,
                        temperature=self._temperature,
                    )
        except Exception as e:
            log.debug(f"[ENGINE-ADAPTER] generate_from_assembled_prompt: {e}")
        return ""

    def generate_stream_from_assembled_prompt(self, prompt: str,
                                              working_memory=None,
                                              reasoning_mode: str = None):
        """
        True streaming inference — yields tokens one at a time.
        Stage 11 of the blueprint pipeline.
        """
        try:
            if self._ce is not None and hasattr(self._ce, "generate_stream_from_assembled_prompt"):
                yield from self._ce.generate_stream_from_assembled_prompt(
                    prompt,
                    working_memory=working_memory,
                    reasoning_mode=reasoning_mode,
                )
                return
        except Exception as _ce_delegate_err:
            log.debug(f"[GUI] generate_stream_from_assembled_prompt CE delegation failed: {_ce_delegate_err}")

        system = (working_memory.assembled_context
                  if working_memory and working_memory.assembled_context
                  else ELI_SYSTEM_PROMPT)
        messages = [{"role": "system", "content": system},
                    {"role": "user",   "content": prompt}]
        try:
            with self._lock:
                if hasattr(self._backend, "chat_stream"):
                    for token in self._backend.chat_stream(
                        messages,
                        max_tokens=self._max_tokens,
                        temperature=self._temperature,
                    ):
                        yield token
                    return
                # Fallback: non-streaming, chunk for display
                response = self._backend.chat(
                    messages=messages,
                    max_tokens=self._max_tokens,
                    temperature=self._temperature,
                )
                for i in range(0, len(response), 8):
                    yield response[i:i + 8]
        except Exception as e:
            log.debug(f"[ENGINE-ADAPTER] generate_stream_from_assembled_prompt: {e}")
            yield f"[Error: {e}]"

    def enqueue_post_response_storage(self, user_input: str, response: str,
                                      intent: dict, command: bool = False,
                                      working_memory=None):
        """
        Blueprint Post-Response: store turns + occasional weight decay.
        """
        if not response or self.memory is None:
            return
        try:
            # Canonical persistence lives in CognitiveEngine.
            # GUI layer must not duplicate chat-turn writes.
            pass
        except Exception as e:
            log.debug(f"[ENGINE-ADAPTER] post_storage failed: {e}")
        # Weight decay — 1 % of responses (amortised cost)
        try:
            import random as _rnd
            if _rnd.random() < 0.01 and hasattr(self.memory, "apply_weight_decay"):
                decayed = self.memory.apply_weight_decay()
                if decayed:
                    log.debug(f"[MEMORY] Weight decay: {decayed} entries aged")
        except Exception:
            pass


# ============================================================
# GLOBAL CTRL+SCROLL ZOOM — application-level event filter
# ============================================================
class _GlobalScrollZoom(QObject):
    """Intercepts Ctrl+Wheel app-wide and zooms the application font.

    Scaling the QApplication font cascades to every widget that hasn't
    locked its own point size, so the whole UI grows/shrinks consistently
    instead of relying on per-widget zoomIn/zoomOut (which only QTextEdit
    and a handful of others support and which previously left half the
    GUI unscaled).
    """

    _MIN_POINT = 7
    _MAX_POINT = 28

    def eventFilter(self, obj, event):
        try:
            if event.type() != QEvent.Type.Wheel:
                return False
            mods = event.modifiers()
            if not (mods & Qt.KeyboardModifier.ControlModifier):
                return False

            angle = event.angleDelta().y() if hasattr(event, "angleDelta") else 0
            if angle == 0 and hasattr(event, "pixelDelta"):
                angle = event.pixelDelta().y()
            if angle == 0:
                return False
            step = 1 if angle > 0 else -1

            app = QApplication.instance()
            if app is not None:
                f = app.font()
                cur = f.pointSize() if f.pointSize() > 0 else 9
                new_size = max(self._MIN_POINT, min(self._MAX_POINT, cur + step))
                if new_size != cur:
                    f.setPointSize(new_size)
                    app.setFont(f)
                    # Force every top-level widget to repolish so children pick up
                    # the new application font (some Qt styles cache the old size).
                    for w in app.topLevelWidgets():
                        try:
                            w.setFont(f)
                            for child in w.findChildren(QWidget):
                                if child.font().pointSize() == cur or child.font().pointSize() <= 0:
                                    cf = child.font()
                                    cf.setPointSize(new_size)
                                    child.setFont(cf)
                        except Exception:
                            pass
            event.accept()
            return True
        except Exception:
            pass
        return False


# ============================================================
# MAIN GUI APPLICATION
# ============================================================
class EliMainWindow(QMainWindow):
    stt_transcript = pyqtSignal(str)
    _inference_lock = __import__('threading').Lock()  # llama_cpp is NOT thread-safe
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    chat_response_signal = pyqtSignal(str)
    proactive_update_signal = pyqtSignal(dict)
    self_improve_failures_signal = pyqtSignal(str)
    self_improve_improvements_signal = pyqtSignal(str)

    # NEW signals for proactive sub‑tabs (thread‑safe updates)
    proactive_suggestions_signal = pyqtSignal(str)
    proactive_summary_signal = pyqtSignal(str)
    proactive_insights_signal = pyqtSignal(str)
    image_generation_done_signal = pyqtSignal(object, dict)
    image_generation_failed_signal = pyqtSignal(str)
    chat_image_generation_done_signal = pyqtSignal(object, dict, str)
    chat_image_generation_failed_signal = pyqtSignal(str)
    # Wizard signal — emits wizard question text to main thread
    wizard_say_signal = pyqtSignal(str)
    # Thread-safe memory stats refresh
    _mem_refresh_sig = pyqtSignal()
    # Screen control: capture result (path or "ERROR:...")
    _sc_capture_sig  = pyqtSignal(str)
    # Quick Actions: result from worker thread → main thread
    _qa_result_sig   = pyqtSignal(str)
    # Image chat: ELI response from worker thread → main thread
    _image_chat_sig  = pyqtSignal(str)
    # Generated artifacts: open saved scripts/docs in the GUI from worker threads
    _generated_artifact_open_sig = pyqtSignal(object)
    # Confidence/grounding badge update signal (worker → main thread)
    _conf_meta_update_sig = pyqtSignal()

    def __init__(self):
        super().__init__()
        app = QApplication.instance()
        if app:
            _f = app.font()
            _f.setPointSize(9)
            app.setFont(_f)
            self._global_zoom_filter = _GlobalScrollZoom(self)
            app.installEventFilter(self._global_zoom_filter)
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - 100% Local")
        screen = QApplication.primaryScreen().availableGeometry()
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(400, 300)
        self.setGeometry(screen.x() + 20, screen.y() + 20, screen.width() - 40, screen.height() - 40)
        self.is_generating = False
        self._model_loading = False
        self.conversation_history = []
        self.current_theme = "dark"
        self._user_text_color = "#a3be8c"  # user message colour (changeable via picker)
        # Agent wizard state
        self._agent_wizard_state: Optional[dict] = None
        self.ollama_manager = OllamaModelManager()
        self.active_backend = model_manager
        self.detected_system_info: Dict[str, Any] = {}
        self._startup_model_prompt_done = False
        self._show_startup_model_picker = True
        self._hardware_tuning_dock = None
        self._runtime_stat_history = {
            "cpu": deque(maxlen=60),
            "ram": deque(maxlen=60),
            "vram": deque(maxlen=60),
        }
        self._runtime_stats_timer = None
        # Phase 7: live-data sync timers — memory counts every 30 s,
        # proactive daemon status every 5 s. Without these the panels
        # only updated via manual Refresh buttons.
        self._memory_stats_timer = None
        self._proactive_status_timer = None
        self._central_memory = None
        if CENTRAL_IMPORTS_AVAILABLE and get_memory:
            self._central_memory = get_memory()

        # Streaming VoiceWorker — interruptible TTS with thread-safe interrupt()
        try:
            from eli.perception.voice_worker_streaming import VoiceWorker as _StreamingVW
            self._voice_worker = _StreamingVW()
        except Exception:
            self._voice_worker = None

        self.log_signal.connect(self._append_log)
        self.status_signal.connect(self._update_status, Qt.ConnectionType.QueuedConnection)
        self.chat_response_signal.connect(self._append_chat_response, Qt.ConnectionType.QueuedConnection)
        self.proactive_update_signal.connect(self._update_proactive, Qt.ConnectionType.QueuedConnection)
        self.stt_transcript.connect(self._on_stt_transcript)
        self.self_improve_failures_signal.connect(self._update_failures_display, Qt.ConnectionType.QueuedConnection)
        self.self_improve_improvements_signal.connect(self._update_improvements_display, Qt.ConnectionType.QueuedConnection)

        # Connect new proactive signals
        self.proactive_suggestions_signal.connect(self._update_suggestions_display, Qt.ConnectionType.QueuedConnection)
        self.proactive_summary_signal.connect(self._update_summary_display, Qt.ConnectionType.QueuedConnection)
        self.proactive_insights_signal.connect(self._update_insights_display, Qt.ConnectionType.QueuedConnection)
        self.image_generation_done_signal.connect(self._image_generation_done, Qt.ConnectionType.QueuedConnection)
        self.image_generation_failed_signal.connect(self._image_generation_failed, Qt.ConnectionType.QueuedConnection)
        self.chat_image_generation_done_signal.connect(self._chat_image_generation_done, Qt.ConnectionType.QueuedConnection)
        self.chat_image_generation_failed_signal.connect(self._chat_image_generation_failed, Qt.ConnectionType.QueuedConnection)
        self.wizard_say_signal.connect(self._wizard_display_message, Qt.ConnectionType.QueuedConnection)
        self._mem_refresh_sig.connect(self.refresh_memory_stats, Qt.ConnectionType.QueuedConnection)
        self._conf_meta_update_sig.connect(self._update_confidence_meta_label, Qt.ConnectionType.QueuedConnection)
        self._image_chat_sig.connect(self._on_image_chat_response, Qt.ConnectionType.QueuedConnection)
        self._generated_artifact_open_sig.connect(
            self._open_generated_artifact_from_result,
            Qt.ConnectionType.QueuedConnection,
        )

        ensure_dirs()
        self.init_ui()
        self._ensure_hardware_tuning_dock()
        self._start_runtime_monitoring()
        self._start_live_data_monitoring()
        self.load_settings()
        self.refresh_model_sources()
        self.apply_theme()
        # If the launcher pre-loaded a model into this module, wire it directly
        # into model_manager so the GUI doesn't re-load (or load the wrong one).
        _pre = getattr(__import__('eli.gui.eli_pro_audio_gui_MKI',
                                  fromlist=['_PRELOADED_MODEL']),
                       '_PRELOADED_MODEL', None)
        _pre_path = getattr(__import__('eli.gui.eli_pro_audio_gui_MKI',
                                       fromlist=['_PRELOADED_MODEL_PATH']),
                            '_PRELOADED_MODEL_PATH', None)
        if _pre is not None:
            def _pre_int(attr_name, fallback=0):
                _v = getattr(_pre, attr_name, None)
                try:
                    if callable(_v):
                        _v = _v()
                except Exception:
                    _v = None
                if _v in (None, "", 0):
                    _v = fallback
                try:
                    return int(_v or 0)
                except Exception:
                    try:
                        return int(float(_v))
                    except Exception:
                        return int(fallback or 0)
            model_manager.model      = _pre
            model_manager.is_loaded  = True
            model_manager.load_error = None
            model_manager.model_path = _pre_path or getattr(_pre, 'model_path', '')

            _pre_snap = {}
            try:
                from eli.cognition import gguf_inference as _ggi
                try:
                    _pre_snap = _ggi.get_runtime_snapshot() or {}
                except Exception:
                    _pre_snap = {}

                model_manager.n_ctx = _pre_int('n_ctx', _pre_snap.get('n_ctx', 0))
                model_manager.n_threads = _pre_int('n_threads', _pre_snap.get('n_threads', 0))
                model_manager.n_gpu_layers = _pre_int('n_gpu_layers', _pre_snap.get('n_gpu_layers', 0))
                model_manager.n_batch = _pre_int('n_batch', _pre_snap.get('n_batch', 0))

                _ggi._llm = _pre
                _ggi.set_live_runtime_override({
                    "provider": "gguf",
                    "loaded": True,
                    "model_path": str(model_manager.model_path or ""),
                    "model_name": Path(model_manager.model_path).name if model_manager.model_path else "",
                    "n_ctx": int(model_manager.n_ctx or 0),
                    "n_gpu_layers": int(model_manager.n_gpu_layers or 0),
                    "n_threads": int(model_manager.n_threads or 0),
                    "n_batch": int(model_manager.n_batch or 0),
                })
                if "_eli_runtime_publish" not in locals() or not isinstance(_eli_runtime_publish, dict):
                    _eli_runtime_publish = {}
                    for _src in (locals().get("params"), locals()):
                        if isinstance(_src, dict):
                            for _k in (
                                "provider",
                                "model_path",
                                "model_name",
                                "selected_model",
                                "n_ctx",
                                "n_gpu_layers",
                                "gpu_layers",
                                "n_threads",
                                "batch_size",
                                "temperature",
                                "max_tokens",
                            ):
                                _v = _src.get(_k)
                                if _v is not None and _k not in _eli_runtime_publish:
                                    _eli_runtime_publish[_k] = _v
                    if "provider" not in _eli_runtime_publish:
                        _eli_runtime_publish["provider"] = "gguf"
                    if "gpu_layers" not in _eli_runtime_publish and "n_gpu_layers" in _eli_runtime_publish:
                        _eli_runtime_publish["gpu_layers"] = _eli_runtime_publish["n_gpu_layers"]
                _ggi.set_runtime_override(_eli_runtime_publish)
                try:
                    _ggi._write_shared_runtime_snapshot(dict(_eli_runtime_publish))
                except Exception as _gg_snap_err:
                    log.debug(f"[GUI] gguf preloaded snapshot write failed: {_gg_snap_err}")
                print("✅ gguf_inference preloaded runtime override published")
            except Exception as _pre_wire_err:
                model_manager.n_ctx = _pre_int('n_ctx', 0)
                model_manager.n_threads = _pre_int('n_threads', 0)
                model_manager.n_gpu_layers = _pre_int('n_gpu_layers', 0)
                model_manager.n_batch = _pre_int('n_batch', 0)
                log.debug(f"[GUI] preloaded runtime handoff failed: {_pre_wire_err}")

            try:
                model_manager._write_shared_runtime_snapshot(
                    model_manager.model_path,
                    model_manager.n_ctx,
                    model_manager.n_threads,
                    model_manager.n_gpu_layers,
                )
            except Exception as _pre_snap_err:
                log.debug(f"[GUI] preloaded runtime snapshot write failed: {_pre_snap_err}")

            self.active_backend = model_manager
            self.status_signal.emit(
                f"🟢 Model ready: {Path(model_manager.model_path).name}"
            )
        # Runtime handoff from launcher/model picker. Portable: no absolute source paths.
        _PRELOADED_PARAMS = globals().get("_PRELOADED_PARAMS", {})
        if not isinstance(_PRELOADED_PARAMS, dict):
            _PRELOADED_PARAMS = {}
        _pre_params = dict(_PRELOADED_PARAMS)
        _runtime_handoff = {}

        for _src in (_pre_params, locals()):
            if isinstance(_src, dict):
                for _key in (
                    "provider",
                    "model_path",
                    "model_name",
                    "n_ctx",
                    "n_gpu_layers",
                    "n_threads",
                    "n_batch",
                    "batch_size",
                    "max_tokens",
                    "temperature",
                    "top_p",
                ):
                    _value = _src.get(_key)
                    if _value is not None and _key not in _runtime_handoff:
                        _runtime_handoff[_key] = _value

        def _apply_preloaded_runtime_params():
            if not _runtime_handoff:
                return {}
            try:
                from eli.cognition import gguf_inference as _gguf_runtime
                for _fn_name in (
                    "set_live_runtime_params",
                    "set_runtime_override",
                    "apply_runtime_override",
                    "configure_runtime",
                ):
                    _fn = getattr(_gguf_runtime, _fn_name, None)
                    if callable(_fn):
                        try:
                            _fn(dict(_runtime_handoff))
                            return dict(_runtime_handoff)
                        except TypeError:
                            continue
                setattr(_gguf_runtime, "_live_runtime_override", dict(_runtime_handoff))
                setattr(_gguf_runtime, "_live_runtime_params", dict(_runtime_handoff))
            except Exception as _handoff_err:
                log.debug(f"[GUI] preloaded runtime handoff failed: {_handoff_err}")
            return dict(_runtime_handoff)

        try:
            QTimer.singleShot(600, _apply_preloaded_runtime_params)
        except Exception:
            _apply_preloaded_runtime_params()

        QTimer.singleShot(600, self.maybe_run_first_time_setup)

        # ---------- START PROACTIVE DAEMON ----------
        self._proactive_daemon = None
        self._proactive_dock = None
        self._operator_console_dock = None
        self._proactive_event_count = 0
        if start_daemon:
            try:
                from eli.planning.proactive_daemon import start_daemon as _start_pd
                self._proactive_daemon = _start_pd()
                log.debug(f"[GUI] Proactive daemon started — USER DB: {self._proactive_daemon.user_mem.db_path}")
                log.debug(f"[GUI] Proactive daemon started — AGENT DB: {self._proactive_daemon.agent_mem.db_path}")
                # Attach ProactiveDock so proactive output has a dedicated panel
                try:
                    from eli.gui.docks.proactive_dock import ProactiveDock
                    self._proactive_dock = ProactiveDock(self)
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._proactive_dock)
                    self._proactive_dock.hide()  # hidden by default — user opens it explicitly
                    log.debug("[GUI] ProactiveDock attached (hidden until opened)")
                except Exception as _dock_err:
                    log.debug(f"[GUI] ProactiveDock unavailable (non-fatal): {_dock_err}")
                # Attach OperatorConsoleDock — hidden by default, toggled via View menu
                try:
                    from eli.gui.docks.operator_console_dock import OperatorConsoleDock
                    self._operator_console_dock = OperatorConsoleDock(self)
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._operator_console_dock)
                    self._operator_console_dock.hide()
                    log.debug("[GUI] OperatorConsoleDock attached (hidden until opened)")
                except Exception as _ocd_err:
                    log.debug(f"[GUI] OperatorConsoleDock unavailable (non-fatal): {_ocd_err}")
                    self._operator_console_dock = None
                # Consume daemon suggestion_queue → proactive tab (thread-safe)
                threading.Thread(
                    target=self._daemon_queue_consumer, daemon=True,
                    name="eli-daemon-queue").start()
                # Refresh status label now that daemon is set (init_ui ran before daemon started)
                QTimer.singleShot(200, self._update_proactive_status_label)
            except Exception as e:
                log.debug(f"[GUI] Failed to start proactive daemon: {e}")
        else:
            log.debug("[GUI] Proactive daemon not available (import failed)")

        # ---------- COGNITIVE ENGINE SINGLETON ----------
        self._cognitive_engine = None
        try:
            from eli.kernel.engine import CognitiveEngine
            self._cognitive_engine = CognitiveEngine(
                auto_init_gguf=False,
                enforce_hardware_authority=False,
            )
            log.debug("[GUI] CognitiveEngine singleton ready (reflection/habit/awareness active)")
        except Exception as _ce_init_err:
            log.debug(f"[GUI] CognitiveEngine init skipped (non-fatal): {_ce_init_err}")

    # ── Daemon queue consumer ──────────────────────────────────────────────
    def _daemon_queue_consumer(self):
        """
        Reads (kind, data) tuples from the proactive daemon's suggestion_queue
        and emits them as GUI signals so the proactive tab stays live.
        Runs in its own daemon thread.
        """
        import queue as _q
        daemon = self._proactive_daemon
        if daemon is None:
            return
        while True:
            try:
                kind, data = daemon.suggestion_queue.get(timeout=5)
            except _q.Empty:
                continue
            except Exception:
                import time as _t; _t.sleep(5); continue
            try:
                if kind == "pattern":
                    stype = data.get("type", "pattern")
                    sugg  = data.get("suggestion", "")
                    line  = f"<b>[{stype}]</b> {sugg}"
                    log.debug(f"[PROACTIVE] {stype}: {sugg}")
                    self.proactive_suggestions_signal.emit(line)
                elif kind == "improvement":
                    cat  = data.get("category", "code")
                    det  = data.get("detail", "") or data.get("description", "") or data.get("suggestion", "")
                    log.debug(f"[PROACTIVE] code insight [{cat}]: {det[:120]}")
                    self.proactive_insights_signal.emit(
                        f"<b>[{cat}]</b> {det[:200]}")
                elif kind in ("habit", "habit_result"):
                    name = data.get("name", "")
                    sugg = data.get("suggestion", "")
                    ok   = data.get("ok", None)
                    icon = ("✓" if ok else "✗") if ok is not None else "⏰"
                    log.debug(f"[PROACTIVE] habit {icon} '{name}': {sugg}")
                    self.proactive_suggestions_signal.emit(
                        f"<b>[habit {icon}]</b> {name}: {sugg}")
                elif kind == "morning_report":
                    report_text = data.get("suggestion", "")
                    log.debug(f"[PROACTIVE] morning report ready")
                    # Route to summaries tab
                    self.proactive_summary_signal.emit(
                        f"<pre style='white-space:pre-wrap'>{report_text}</pre>")
                else:
                    sugg = data.get("suggestion", str(data)[:200]) if isinstance(data, dict) else str(data)[:200]
                    log.debug(f"[PROACTIVE] [{kind}]: {sugg[:120]}")
                    self.proactive_suggestions_signal.emit(
                        f"<b>[{kind}]</b> {sugg[:200]}")
                # NOTE: do NOT touch _proactive_dock widgets from this thread —
                # dock forwarding is handled by _update_suggestions_display on the GUI thread.
            except Exception as _sig_err:
                log.debug(f"[GUI] daemon queue signal failed: {_sig_err}")

    # ---------- Advanced memory retrieval ----------
    def _retrieve_relevant_memories(self, query: str, limit: int = 20) -> str:
        if not self._central_memory:
            return ""

        context_parts = []

        # 1. Always include identity/preference memories
        try:
            identity_mems = self._central_memory.recall_memory("identity preference name", limit=10)
            if identity_mems:
                lines = []
                for m in identity_mems:
                    txt_ = (m.get("text") or m.get("content") or "").strip()
                    if txt_:
                        lines.append(f"- {txt_}")
                if lines:
                    context_parts.append("Known facts about the user:\n" + "\n".join(lines))
        except Exception:
            pass

        # 2. Semantic search for the query
        lowered = query.lower()
        commandish = bool(re.match(r"^(open|access|initiate|fabricate|check|run|execute|type|press|pause|resume|play|next|previous|stop|mute|unmute|read|list|show|write|add)\b", lowered))
        if query and not commandish:
            try:
                results = self._central_memory.recall_memory(query=query, limit=limit)
                if results:
                    lines = []
                    for mem in results[:5]:
                        text = (mem.get("text") or "").replace("\n", " ")[:200]
                        tags = mem.get("tags", [])
                        if isinstance(tags, list):
                            tags = ", ".join(tags)
                        lines.append(f"- {text} [{tags}]")
                    if lines:
                        context_parts.append("Relevant stored knowledge:\n" + "\n".join(lines))
            except Exception as e:
                print(f"Memory recall failed: {e}")

        # 3. Pull recent conversation turns from user.sqlite3
        try:
            import sqlite3 as _sq3
            from eli.core.paths import user_db_path as _udp3
            con = _sq3.connect(str(_udp3()))
            rows = con.execute(
                "SELECT role, content FROM conversation_turns WHERE lower(role) = 'user' ORDER BY id DESC LIMIT 20"
            ).fetchall()
            con.close()
            if rows:
                lines = []
                for role, content in reversed(rows):
                    snippet = (content or '')[:120].replace('\n', ' ')
                    lines.append(f"  [{role}]: {snippet}")
                context_parts.append("Recent conversation history:\n" + "\n".join(lines))
        except Exception:
            pass

        return "\n\n".join(context_parts)

    # ---------- TTS / STT ----------
    def _speak_response(self, text: str):
        import re as _re, threading, unicodedata
        if not text or not isinstance(text, str): return
        printable = sum(1 for c in text if unicodedata.category(c)[0] != 'C')
        if printable / max(len(text), 1) < 0.8: return
        try:
            from eli.cognition.reasoning_modes import apply_final_reasoning_contract as _rm_final
            text = _rm_final(text)
        except Exception:
            pass
        clean = _re.sub(r'[*_`#>|\[\]~]', '', text)
        clean = _re.sub(r'\s+', ' ', clean).strip()
        try:
            max_chars = int(os.environ.get("ELI_TTS_MAX_RESPONSE_CHARS", "12000") or "12000")
        except Exception:
            max_chars = 12000
        if max_chars > 0 and len(clean) > max_chars:
            clean = clean[:max_chars].rsplit(" ", 1)[0].rstrip() or clean[:max_chars].rstrip()
        if not clean: return
        if self._voice_worker is not None:
            self._voice_worker.speak(clean)
            return
        def _run():
            try:
                from eli.perception.tts_router import speak as _tts_speak, get_active_voice
                _tts_speak(clean, voice_name=get_active_voice())
            except Exception as e:
                log.debug(f'[TTS] {e}')
        threading.Thread(target=_run, daemon=True).start()

    def _interrupt_speech(self):
        """Interrupt any in-progress TTS via streaming VoiceWorker."""
        if self._voice_worker is not None:
            self._voice_worker.interrupt()

    def _speak_last_response(self):
        self._speak_response(getattr(self, '_last_eli_response', ''))

    def _on_auto_speak_toggled(self, checked: bool):
        self._tts_auto = checked
        try: self.auto_speak_btn.setText('🔊 Auto-Speak: ON' if checked else '🔇 Auto-Speak: OFF')
        except Exception: pass

    def _on_voice_changed(self, name: str):
        if not name or name == "(no voices)":
            return
        try:
            from eli.perception.tts_router import set_active_voice
            set_active_voice(name)
            # Mirror to the Settings tab selector if present
            sel = getattr(self, "_voice_selector", None)
            if sel is not None and sel.findText(name) >= 0:
                sel.blockSignals(True)
                sel.setCurrentText(name)
                sel.blockSignals(False)
        except Exception as ex:
            log.debug(f"[GUI] voice change failed: {ex}")

    def _on_stt_transcript(self, text: str):
        text = text.strip()
        if not text:
            return
        log.debug(f"[STT→GUI] {text}")
        # Existing-router/executor fast path for deterministic voice commands.
        # This avoids CognitiveEngine/LLM latency for safe actions.
        try:
            _voice_text = text  # function parameter — no need to search locals

            from eli.execution import router_enhanced as _eli_voice_router
            from eli.execution import executor_enhanced as _eli_voice_executor

            # Stage-0 instant dispatch: exact-match quick commands bypass the
            # full router pipeline entirely. Saves ~30-60ms per command and
            # ensures media controls fire as fast as possible.
            _INSTANT_DISPATCH = {
                "pause":          ("PAUSE_MEDIA",    {}),
                "play":           ("PLAY_MEDIA",     {}),
                "resume":         ("PLAY_MEDIA",     {}),
                "stop":           ("STOP_MEDIA",     {}),
                "next":           ("NEXT_MEDIA",     {}),
                "next song":      ("NEXT_MEDIA",     {}),
                "next track":     ("NEXT_MEDIA",     {}),
                "skip":           ("NEXT_MEDIA",     {}),
                "previous":       ("PREVIOUS_MEDIA", {}),
                "previous song":  ("PREVIOUS_MEDIA", {}),
                "previous track": ("PREVIOUS_MEDIA", {}),
                "back":           ("PREVIOUS_MEDIA", {}),
                "volume up":      ("VOLUME", {"direction": "up",   "delta": 15}),
                "volume down":    ("VOLUME", {"direction": "down", "delta": 15}),
                "louder":         ("VOLUME", {"direction": "up",   "delta": 15}),
                "quieter":        ("VOLUME", {"direction": "down", "delta": 15}),
                "mute":           ("VOLUME", {"direction": "mute"}),
                "unmute":         ("VOLUME", {"direction": "unmute"}),
            }
            _vt_lower = _voice_text.lower().strip()
            if _vt_lower in _INSTANT_DISPATCH:
                _action, _args = _INSTANT_DISPATCH[_vt_lower]
                _route = {"action": _action, "args": _args,
                          "confidence": 1.0,
                          "meta": {"matched_by": "gui.instant_dispatch"}}
            else:
                _route = _eli_voice_router.route(_voice_text)
                _action = str((_route or {}).get("action") or "").upper()
                _args = (_route or {}).get("args") or {}
        
            _direct_actions = {
                "NOOP",
                "TIME", "DATE",
                "PAUSE_MEDIA", "PLAY_MEDIA", "STOP_MEDIA",
                "NEXT_MEDIA", "PREVIOUS_MEDIA",
                "MEDIA_CONTROL",
                "VOLUME", "VOLUME_UP", "VOLUME_DOWN",
                "SCREENSHOT", "LIST_DIR", "READ_FILE",
                "GET_WEATHER", "SET_TIMER", "SET_ALARM",
                "PROACTIVE_STATUS", "HABIT_STATUS", "LIST_CAPABILITIES",
                # ELI_GUI_TILE_DIRECT_EXEC_FIX_20260505
                "TILE_WINDOWS", "MINIMISE_ALL", "RESTORE_WINDOWS",
                "OPEN_APP", "CLOSE_APP",
            }
        
            if _action in _direct_actions:
                _user_voice_text = str(_voice_text or text or "").strip()
                _session_id = "gui-direct"
                _user_id = "local-user"
                try:
                    _ce = getattr(self, "_cognitive_engine", None)
                    _session_id = str(getattr(_ce, "session_id", "") or _session_id)
                    _user_id = str(getattr(_ce, "user_id", "") or _user_id)
                except Exception:
                    pass
                try:
                    if _user_voice_text:
                        _uc = getattr(self, '_user_text_color', '#a3be8c')
                        if hasattr(self, "chat_display"):
                            self.chat_display.append(
                                f'\n<b><span style="color:{_uc};">🧑 You [{now_hms()}]:</span></b>'
                                f'<br>{_user_voice_text}<br>'
                            )
                        if hasattr(self, "conversation_history"):
                            self.conversation_history.append({'role': 'user', 'content': _user_voice_text})
                        try:
                            if getattr(self, "_central_memory", None):
                                self._central_memory.add_conversation_turn(
                                    "user", _user_voice_text, session_id=_session_id, user_id=_user_id)
                        except Exception as _mem_user_e:
                            log.debug(f"[GUI_DIRECT_EXEC][MEM_USER_FAIL] {_mem_user_e}")
                        log.debug(f"[GUI_DIRECT_EXEC][USER_APPEND] {_user_voice_text}")
                except Exception as _user_ui_e:
                    log.debug(f"[GUI_DIRECT_EXEC][USER_APPEND_FAIL] {_user_ui_e}")

                log.debug(f"[GUI_DIRECT_EXEC] route={_route}")
                _res = _eli_voice_executor.execute_action(_action, _args)
                _ok = bool((_res or {}).get("ok", True)) if isinstance(_res, dict) else True
        
                if isinstance(_res, dict):
                    _reply = str(_res.get("response") or _res.get("content") or _res.get("message") or _res)
                else:
                    _reply = str(_res)
        
                log.debug(f"[GUI_DIRECT_EXEC] {_reply}")
                try:
                    if getattr(self, "_central_memory", None):
                        if _reply:
                            self._central_memory.add_conversation_turn(
                                "assistant", _reply, session_id=_session_id, user_id=_user_id)
                        self._central_memory.log_learning_event(
                            "gui_direct_command",
                            input_text=_user_voice_text,
                            output_text=_reply,
                            action=_action,
                            outcome="ok" if _ok else "failed",
                            reward=1.0 if _ok else -1.0,
                            metadata={
                                "args": _args,
                                "matched_by": (_route.get("meta") or {}).get("matched_by") if isinstance(_route, dict) else "",
                                "source": "gui_direct_exec",
                            },
                        )
                        self._central_memory.log_habit_event(
                            "command_result",
                            {
                                "action": _action,
                                "args": _args,
                                "ok": _ok,
                                "source": "gui_direct_exec",
                            },
                        )
                        if _action == "OPEN_APP" and _ok:
                            _app_name = str(
                                _args.get("name") or _args.get("target") or _args.get("app") or ""
                            ).strip()
                            if _app_name:
                                _cmd = (_res.get("cmd") or _res.get("command") or _app_name) if isinstance(_res, dict) else _app_name
                                _method = (_res.get("method") if isinstance(_res, dict) else "") or "gui_direct_exec"
                                self._central_memory.store_app_cmd(_app_name, _cmd, _method)
                                self._central_memory.log_habit_event(
                                    "app_launch",
                                    {"app": _app_name, "cmd": _cmd, "method": _method, "success": True},
                                )
                        elif _action in {"LIST_DIR", "READ_FILE"} and _ok:
                            _path = str(_args.get("path") or "").strip()
                            if _path:
                                self._central_memory.log_habit_event(
                                    _action.lower(),
                                    {"path": _path, "success": True, "source": "gui_direct_exec"},
                                )
                except Exception as _mem_result_e:
                    log.debug(f"[GUI_DIRECT_EXEC][MEM_RESULT_FAIL] {_mem_result_e}")
                # Honour the Auto-Speak toggle: only emit TTS when the user
                # has it enabled. Voice-initiated commands also opt in via
                # the _last_input_was_voice flag — direct-exec replies to
                # text typed in the chat box should stay silent unless
                # auto-speak is on.
                _tts_auto_on = bool(getattr(self, "_tts_auto", False))
                _speak_text = str(_reply or "").strip()
                if _tts_auto_on and _speak_text:
                    try:
                        from eli.perception.tts_router import speak_text as _eli_gui_direct_speak
                        _eli_gui_direct_speak(_speak_text)
                        log.debug(f"[GUI_DIRECT_EXEC][TTS] {_speak_text}")
                    except Exception as _tts_e:
                        log.debug(f"[GUI_DIRECT_EXEC][TTS_FAIL] {_tts_e}")
                elif _speak_text:
                    log.debug(f"[GUI_DIRECT_EXEC][TTS_SKIPPED] auto-speak off")
        
                # Best-effort GUI append. Execution must not depend on UI method names.
                try:
                    if hasattr(self, "append_assistant_message"):
                        self.append_assistant_message(_reply)
                    elif hasattr(self, "add_assistant_message"):
                        self.add_assistant_message(_reply)
                    elif hasattr(self, "_append_assistant_message"):
                        self._append_assistant_message(_reply)
                    elif hasattr(self, "chat_display"):
                        self.chat_display.append(f"🤖 ELI:\n{_reply}")
                except Exception as _ui_e:
                    log.debug(f"[GUI_DIRECT_EXEC][UI_APPEND_FAIL] {_ui_e}")
        
                return
        except Exception as _direct_e:
            log.debug(f"[GUI_DIRECT_EXEC][FALLBACK] {type(_direct_e).__name__}: {_direct_e}")
        self.chat_input.setPlainText(text)
        self.send_message()

    def _populate_mic_device_combo(self, restore: bool = False):
        """Populate mic selector with ALSA devices + PulseAudio/PipeWire BT sources."""
        import os as _os
        prev = self.mic_device_combo.currentData() if restore else None
        self.mic_device_combo.blockSignals(True)
        self.mic_device_combo.clear()

        # Default / system choice
        self.mic_device_combo.addItem("System default", ("alsa", None))

        # ALSA devices via SpeechRecognition
        try:
            import speech_recognition as _sr
            for idx, name in enumerate(_sr.Microphone.list_microphone_names()):
                if any(skip in name.lower() for skip in ("monitor", "iec958", "spdif", "a52",
                                                          "speex", "upmix", "vdownmix", "samplerate",
                                                          "lavrate", "hdmi", "nvidia")):
                    continue
                self.mic_device_combo.addItem(f"{name}", ("alsa", idx))
        except Exception:
            pass

        # PulseAudio / PipeWire sources (catches BT headsets)
        try:
            import subprocess as _sp
            _out = _sp.check_output(["pactl", "list", "sources", "short"],
                                    text=True, timeout=3)
            for line in _out.strip().splitlines():
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                src_name = parts[1].strip()
                # Skip monitors and virtual sinks
                if ".monitor" in src_name:
                    continue
                label = src_name
                # Make BT sources human-readable
                if src_name.startswith("bluez_input"):
                    label = f"Bluetooth: {src_name.split('.')[1].replace('_', ':')}"
                elif "alsa_input" in src_name:
                    continue  # already covered by ALSA list above
                self.mic_device_combo.addItem(label, ("pulse", src_name))
        except Exception:
            pass

        self.mic_device_combo.blockSignals(False)

        # Restore previous selection or load from settings
        saved = prev or getattr(self, "_saved_mic_device", None)
        if saved:
            for i in range(self.mic_device_combo.count()):
                if self.mic_device_combo.itemData(i) == saved:
                    self.mic_device_combo.setCurrentIndex(i)
                    break

    def _apply_stt_sensitivity(self):
        """Push energy threshold / dynamic flag into the live recognizer and env."""
        import os as _os
        dynamic = self.dynamic_energy_checkbox.isChecked()
        threshold = self.energy_threshold_input.value()
        _os.environ["ELI_STT_DYNAMIC_ENERGY"] = "1" if dynamic else "0"
        _os.environ["ELI_STT_ENERGY_THRESHOLD"] = str(threshold)
        # Apply to live recognizer if STT is running
        try:
            from eli.perception.audio_stt import _get_recognizer
            rec = _get_recognizer()
            if rec is not None:
                rec.dynamic_energy_threshold = dynamic
                if not dynamic:
                    rec.energy_threshold = float(threshold)
        except Exception:
            pass
        if getattr(self, "_first_run_complete", False):
            self.save_settings(silent=True)

    def _on_mic_device_changed(self, _save: bool = True):
        """Apply mic device selection to env vars immediately."""
        import os as _os
        data = self.mic_device_combo.currentData()
        if not data:
            return
        kind, value = data
        if kind == "alsa":
            if value is None:
                _os.environ.pop("ELI_MIC_DEVICE_INDEX", None)
                _os.environ.pop("PULSE_SOURCE", None)
            else:
                _os.environ["ELI_MIC_DEVICE_INDEX"] = str(value)
                _os.environ.pop("PULSE_SOURCE", None)
        elif kind == "pulse":
            _os.environ["ELI_MIC_DEVICE_INDEX"] = "14"
            _os.environ["PULSE_SOURCE"] = value
        self._saved_mic_device = data
        # Don't save during load_settings — caller sets _save=False to avoid
        # triggering a model reload cycle on startup.
        if _save and getattr(self, "_first_run_complete", False):
            self.save_settings(silent=True)

    def _apply_direct_chat_env(self):
        """Sync ELI_STT_ALLOW_DIRECT_CHAT env var from the checkbox — takes effect immediately."""
        import os as _os
        val = "1" if self.allow_direct_chat_checkbox.isChecked() else "0"
        _os.environ["ELI_STT_ALLOW_DIRECT_CHAT"] = val
        # Keep wake word button in sync with the settings-page checkbox
        if hasattr(self, "wake_word_btn"):
            self.wake_word_btn.blockSignals(True)
            self.wake_word_btn.setChecked(not self.allow_direct_chat_checkbox.isChecked())
            self.wake_word_btn.setText("Wake: ON" if self.wake_word_btn.isChecked() else "Wake: OFF")
            self.wake_word_btn.blockSignals(False)
        self.save_settings(silent=True)

    def _on_wake_word_toggled(self, wake_on: bool):
        """Wake word button in the chat toolbar — mirrors the Audio settings checkbox."""
        import os as _os
        # wake_on=True → wake word required → direct chat disabled
        _os.environ["ELI_STT_ALLOW_DIRECT_CHAT"] = "0" if wake_on else "1"
        self.wake_word_btn.setText("Wake: ON" if wake_on else "Wake: OFF")
        log.debug(
            f"[WAKE] {'ON — say \"computer\" before commands' if wake_on else 'OFF — all speech dispatched (≥2 words)'}",
        )
        # Keep settings-page checkbox in sync
        if hasattr(self, "allow_direct_chat_checkbox"):
            self.allow_direct_chat_checkbox.blockSignals(True)
            self.allow_direct_chat_checkbox.setChecked(not wake_on)
            self.allow_direct_chat_checkbox.blockSignals(False)
        self.save_settings(silent=True)

    def _stt_toggle(self, checked: bool):
        if checked:
            self.stt_btn.setText("🔴 Mic: ON")
            def _cb(text):
                text = (text or "").strip()
                if text:
                    log.debug(f"[STT] emitting: {text}")
                    self.stt_transcript.emit(text)
            try:
                from eli.perception.audio_stt import start_audio_listening, stop_audio_listening
                start_audio_listening(callback=_cb)
                self._stt_stop_ref = stop_audio_listening
                log.debug("[STT] listening started — say: computer, <command>")
            except Exception as e:
                log.debug(f"[STT] start failed: {e}")
                self.stt_btn.setChecked(False)
                self.stt_btn.setText("🎤 Mic: OFF")
        else:
            self.stt_btn.setText("🎤 Mic: OFF")
            try:
                fn = getattr(self, "_stt_stop_ref", None)
                if fn:
                    fn()
                log.debug("[STT] listening stopped")
            except Exception as e:
                log.debug(f"[STT] stop failed: {e}")

    # Map both the long and the slim bottom-row labels to canonical mode ids.
    _REASONING_MODE_LABELS = {
        "⚡ Quick": "quick",
        "🔗 Chain of Thought": "chain_of_thought",
        "🔄 Self-Consistency": "self_consistency",
        "🌳 Tree of Thoughts": "tree_of_thoughts",
        "⚖️ Constitutional AI": "constitutional_ai",
        # slim labels used in the new compact bottom-row combobox
        "🔗 CoT": "chain_of_thought",
        "🔄 Self-C": "self_consistency",
        "🌳 ToT": "tree_of_thoughts",
        "⚖️ Const AI": "constitutional_ai",
    }

    def change_reasoning_mode(self, label: str = 'quick'):
        self._reasoning_mode = self._REASONING_MODE_LABELS.get(label, "quick")
        try:
            self.chat_display.append(
                f'<span style="color:#88c0d0;font-size:11px;">⚙️ Mode: {label}</span><br>'
            )
        except Exception:
            pass

    def _on_auto_mode_toggled(self, checked: bool):
        self._auto_reasoning_mode = bool(checked)
        try:
            self.auto_mode_btn.setText("🤖 Auto-Mode" if checked else "🧊 Manual")
            note = "auto-selecting reasoning mode from prompt keywords" if checked \
                   else "manual reasoning mode (auto-detect off)"
            self.chat_display.append(
                f'<span style="color:#88c0d0;font-size:11px;">⚙️ {note}</span><br>'
            )
        except Exception:
            pass

    # ─── Keyword → reasoning mode auto-detection ─────────────────────────
    # Tuples of (canonical_mode_id, list of regex patterns). First match wins.
    _AUTO_MODE_PATTERNS = (
        ("constitutional_ai", [
            r"\bconstitutional\b", r"\bcritique[- ]then[- ]revise\b",
            r"\bself[- ]critique\b", r"\bdraft.*then.*revise\b",
            r"\bethic(?:s|al)\b.*\b(check|review)\b",
        ]),
        ("tree_of_thoughts", [
            r"\btree[- ]of[- ]thoughts?\b", r"\b(?:explore|enumerate)\s+(?:multiple\s+)?branches?\b",
            r"\bbranch(?:es)?\s+and\s+(?:prune|evaluate)\b",
            r"\bcompare\s+(?:multiple|several)\s+(?:options|approaches|paths)\b",
        ]),
        ("self_consistency", [
            r"\bself[- ]consistenc(?:y|t)\b", r"\bmajority\s+vote\b",
            r"\b(?:three|3|five|5)\s+independent\s+(?:reasoning\s+paths?|attempts?)\b",
            r"\bcross[- ]check\s+(?:multiple|several)\s+approaches\b",
        ]),
        ("chain_of_thought", [
            r"\bchain[- ]of[- ]thought\b", r"\bstep[- ]by[- ]step\b",
            r"\bshow\s+(?:your|the)\s+(?:work|reasoning)\b",
            r"\bthink\s+(?:through|carefully)\b", r"\bderive\b",
            r"\bprove\b", r"\bproof\b",
            r"\bwalk\s+me\s+through\b",
        ]),
    )

    def _auto_detect_reasoning_mode(self, text: str) -> Optional[str]:
        """Return the canonical reasoning-mode id implied by `text`, or None."""
        if not text:
            return None
        low = text.lower()
        for mode, patterns in self._AUTO_MODE_PATTERNS:
            for pat in patterns:
                if re.search(pat, low):
                    return mode
        return None

    def _maybe_auto_select_reasoning_mode(self, user_text: str) -> None:
        """If auto-mode is on, pick a reasoning mode from `user_text` keywords."""
        if not getattr(self, "_auto_reasoning_mode", False):
            return
        detected = self._auto_detect_reasoning_mode(user_text)
        if not detected:
            return
        if detected == getattr(self, "_reasoning_mode", "quick"):
            return
        # Find a label in the combo that maps to `detected`
        for i in range(self.reasoning_mode_combo.count()):
            label = self.reasoning_mode_combo.itemText(i)
            if self._REASONING_MODE_LABELS.get(label) == detected:
                self.reasoning_mode_combo.blockSignals(True)
                self.reasoning_mode_combo.setCurrentIndex(i)
                self.reasoning_mode_combo.blockSignals(False)
                self._reasoning_mode = detected
                try:
                    self.chat_display.append(
                        f'<span style="color:#88c0d0;font-size:11px;">'
                        f'🤖 Auto-mode → {label}</span><br>'
                    )
                except Exception:
                    pass
                break

    def _get_mode_prefix(self) -> str:
        """Return private reasoning strategy prompt prefix for backend handoff.

        This must never request visible chain-of-thought, branches,
        self-consistency samples, or constitutional critique passes.
        """
        try:
            from eli.cognition.reasoning_modes import gui_prompt_prefix_for_mode
            return gui_prompt_prefix_for_mode(getattr(self, "_reasoning_mode", "quick"))
        except Exception:
            return ""


    def _pick_user_color(self):
        """Open a colour picker so the user can customise their message colour."""
        color = QColorDialog.getColor(
            QColor(getattr(self, '_user_text_color', '#a3be8c')), self,
            "Pick your message colour"
        )
        if color.isValid():
            self._user_text_color = color.name()
            self.save_settings(silent=True)

    def _noop(): pass

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        main_layout.addWidget(self.tabs)
        self.create_chat_tab()
        self.create_proactive_tab()
        self.create_image_tab()
        self.create_quick_actions_tab()
        self.create_screen_control_tab()
        self.create_files_tab()
        self.create_labs_tab()
        self.create_experimental_tab()
        self.create_eli_world_tab()
        self.create_settings_tab()
        self.create_top_toolbar()
        self.status_bar = self.statusBar()
        self.status_label = QLabel("🔴 Model not loaded")
        self.status_bar.addWidget(self.status_label)
        # Confidence / grounding metadata badge — updated after each response
        self._confidence_meta_label = QLabel("")
        self._confidence_meta_label.setStyleSheet(
            "color:#7a9cbf;font-size:10px;padding:0 6px;"
        )
        self.status_bar.addWidget(self._confidence_meta_label)
        # Proactive daemon status indicator (right side of status bar)
        self._proactive_status_label = QLabel()
        self.status_bar.addPermanentWidget(self._proactive_status_label)
        self._update_proactive_status_label()
        self.create_menu_bar()

    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&File")
        new_conv = QAction("New Conversation", self)
        new_conv.setShortcut("Ctrl+N")
        new_conv.triggered.connect(self.new_conversation)
        file_menu.addAction(new_conv)
        save_conv = QAction("Save Conversation", self)
        save_conv.setShortcut("Ctrl+S")
        save_conv.triggered.connect(self.save_conversation)
        file_menu.addAction(save_conv)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        model_menu = menubar.addMenu("&Model")
        load_model = QAction("Load Model...", self)
        load_model.triggered.connect(self.load_model_dialog)
        model_menu.addAction(load_model)
        startup_picker = QAction("Startup Model Picker…", self)
        startup_picker.triggered.connect(self.prompt_load_model)
        model_menu.addAction(startup_picker)
        unload_model = QAction("Unload Model", self)
        unload_model.triggered.connect(self.unload_model)
        model_menu.addAction(unload_model)
        view_menu = menubar.addMenu("&View")
        open_settings = QAction("Open Settings", self)
        open_settings.setShortcut("Ctrl+,")
        open_settings.triggered.connect(self.open_settings_tab)
        view_menu.addAction(open_settings)
        open_images = QAction("Open Image Studio", self)
        open_images.setShortcut("Ctrl+Shift+I")
        open_images.triggered.connect(self.open_image_studio_tab)
        view_menu.addAction(open_images)
        view_menu.addSeparator()
        zoom_in = QAction("Zoom In", self)
        zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        zoom_in.triggered.connect(lambda: self.adjust_active_zoom(1))
        view_menu.addAction(zoom_in)
        zoom_out = QAction("Zoom Out", self)
        zoom_out.setShortcuts([QKeySequence("Ctrl+-"), QKeySequence("Ctrl+_")])
        zoom_out.triggered.connect(lambda: self.adjust_active_zoom(-1))
        view_menu.addAction(zoom_out)
        zoom_reset = QAction("Reset Zoom", self)
        zoom_reset.setShortcut("Ctrl+0")
        zoom_reset.triggered.connect(self.reset_active_zoom)
        view_menu.addAction(zoom_reset)
        view_menu.addSeparator()
        toggle_theme = QAction("Toggle Theme", self)
        toggle_theme.setShortcut("Ctrl+T")
        toggle_theme.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme)
        # Proactive dock toggle — the dock is created hidden; expose it
        # explicitly here so users can find it.
        view_menu.addSeparator()
        toggle_proactive = QAction("Proactive Dock", self)
        toggle_proactive.setCheckable(True)
        toggle_proactive.setShortcut("Ctrl+Shift+P")
        toggle_proactive.triggered.connect(self._toggle_proactive_dock)
        self._toggle_proactive_action = toggle_proactive
        view_menu.addAction(toggle_proactive)
        toggle_hw = QAction("Hardware Tuning Dock", self)
        toggle_hw.setCheckable(True)
        toggle_hw.setShortcut("Ctrl+Shift+H")
        toggle_hw.triggered.connect(self._toggle_hardware_tuning_dock)
        self._toggle_hardware_dock_action = toggle_hw
        view_menu.addAction(toggle_hw)
        toggle_op = QAction("Operator Console", self)
        toggle_op.setCheckable(True)
        toggle_op.setShortcut("Ctrl+Shift+O")
        toggle_op.triggered.connect(self._toggle_operator_console_dock)
        self._toggle_operator_console_action = toggle_op
        view_menu.addAction(toggle_op)
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_top_toolbar(self):
        toolbar = QToolBar("View")
        toolbar.setObjectName("workspaceToolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

        detect_action = QAction("Auto Detect", self)
        detect_action.triggered.connect(self.detect_optimal_settings)
        toolbar.addAction(detect_action)

        theme_action = QAction("Theme", self)
        theme_action.triggered.connect(self.toggle_theme)
        toolbar.addAction(theme_action)

    def open_settings_tab(self):
        try:
            idx = self.tabs.indexOf(self._settings_root)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        except Exception:
            pass

    def open_image_studio_tab(self):
        try:
            idx = self.tabs.indexOf(self.image_tab_widget)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        except Exception:
            pass

    def _toggle_proactive_dock(self, checked: bool = None):
        """Show or hide the Proactive Dock. Wired to View → Proactive Dock
        (Ctrl+Shift+P)."""
        try:
            dock = getattr(self, "_proactive_dock", None)
            if dock is None:
                # Lazy-attach if it failed at startup.
                try:
                    from eli.gui.docks.proactive_dock import ProactiveDock
                    dock = ProactiveDock(self)
                    self._proactive_dock = dock
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                except Exception as _err:
                    log.debug(f"[GUI] ProactiveDock attach failed: {_err}")
                    return
            if checked is None:
                checked = not dock.isVisible()
            dock.setVisible(bool(checked))
            if checked:
                dock.raise_()
            try:
                self._toggle_proactive_action.setChecked(bool(checked))
            except Exception:
                pass
        except Exception as _e:
            log.debug(f"[GUI] toggle proactive dock failed: {_e}")

    def _toggle_operator_console_dock(self, checked: bool = None):
        """Show or hide the Operator Console dock. Wired to View → Operator Console
        (Ctrl+Shift+O)."""
        try:
            dock = getattr(self, "_operator_console_dock", None)
            if dock is None:
                try:
                    from eli.gui.docks.operator_console_dock import OperatorConsoleDock
                    dock = OperatorConsoleDock(self)
                    self._operator_console_dock = dock
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
                except Exception as _err:
                    log.debug(f"[GUI] OperatorConsoleDock attach failed: {_err}")
                    return
            if checked is None:
                checked = not dock.isVisible()
            dock.setVisible(bool(checked))
            if checked:
                dock.raise_()
            try:
                self._toggle_operator_console_action.setChecked(bool(checked))
            except Exception:
                pass
        except Exception as _e:
            log.debug(f"[GUI] toggle operator console dock failed: {_e}")

    def _ensure_hardware_tuning_dock(self):
        dock = getattr(self, "_hardware_tuning_dock", None)
        if dock is not None:
            return dock
        try:
            dock = HardwareTuningDock(self)
            self._hardware_tuning_dock = dock
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            dock.hide()
            return dock
        except Exception as e:
            log.debug(f"[GUI] hardware tuning dock attach failed: {e}")
            self._hardware_tuning_dock = None
            return None

    def _toggle_hardware_tuning_dock(self, checked: bool = None):
        dock = self._ensure_hardware_tuning_dock()
        if dock is None:
            return
        if checked is None:
            checked = not dock.isVisible()
        dock.setVisible(bool(checked))
        if checked:
            dock.raise_()
        try:
            self._toggle_hardware_dock_action.setChecked(bool(checked))
        except Exception:
            pass

    def _hardware_tuning_log(self, text: str):
        dock = self._ensure_hardware_tuning_dock()
        if dock is not None:
            dock.append_log(text)

    def _extract_image_prompt_from_chat(self, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        patterns = [
            r"^(?:please\s+)?(?:create|generate|make|draw|paint|render|design)\s+(?:me\s+)?(?:an?\s+)?image(?:\s+of|\s+showing|\s+with|\s+for)?\s+(.+)$",
            r"^(?:please\s+)?(?:create|generate|make|draw|paint|render|design)\s+(?:an?\s+)?(?:portrait|logo|poster|wallpaper|icon|illustration|artwork|cover)\s+(?:of|for)?\s+(.+)$",
            r"^(?:an?\s+)?image\s+of\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.match(pattern, raw, re.I)
            if match:
                prompt = match.group(1).strip(" .")
                prompt = re.sub(r"^(?:an?\s+image\s+of\s+)", "", prompt, flags=re.I)
                if prompt:
                    return prompt
        return ""

    def _start_chat_image_request(self, prompt: str, *, source_text: str = ""):
        if not prompt:
            return
        backend_choice = self.image_backend_combo.currentText().strip() if hasattr(self, "image_backend_combo") else "auto"
        if backend_choice == "diffusion" and not self._selected_image_model_path():
            self.chat_response_signal.emit(
                "❌ Diffusion backend selected, but no image model path is configured. Set one in Image Studio or Settings → Identity."
            )
            return
        if hasattr(self, "image_generate_btn") and not self.image_generate_btn.isEnabled():
            self.chat_response_signal.emit("🖼️ Image generation is already running. Wait for it to finish, then send the next prompt.")
            return

        self._chat_image_prompt = prompt
        self._chat_image_source_text = source_text or prompt
        self.open_image_studio_tab()
        if hasattr(self, "image_prompt_input"):
            self.image_prompt_input.setPlainText(prompt)
        if hasattr(self, "image_prompt_context_display"):
            self.image_prompt_context_display.setPlainText("Chat request received. Generating a subject-focused image now…")
        if hasattr(self, "image_summary_display"):
            self.image_summary_display.setPlainText("Generating image from chat request…")
        if hasattr(self, "image_generate_btn"):
            self.image_generate_btn.setEnabled(False)
            self.image_generate_btn.setText("Generating...")

        self.chat_response_signal.emit(f"🖼️ Generating an image for: {prompt}")
        self.status_signal.emit("🖼️ Generating image from chat request…")

        def worker():
            try:
                from eli.tools.image_engine import ImageGenerationRequest, generate_images

                settings = self._image_settings_snapshot()
                proactive_ground = {}
                if hasattr(self, "image_proactive_context_checkbox") and self.image_proactive_context_checkbox.isChecked():
                    proactive_ground = self._build_proactive_ground_truth(query=prompt)

                width = int(getattr(self, "image_width_input", None).value()) if hasattr(self, "image_width_input") else 1408
                height = int(getattr(self, "image_height_input", None).value()) if hasattr(self, "image_height_input") else 896
                req = ImageGenerationRequest(
                    prompt=prompt,
                    project=self.image_project_input.text().strip() if hasattr(self, "image_project_input") else "",
                    preset=self.image_preset_combo.currentText().strip() if hasattr(self, "image_preset_combo") else "",
                    scene_type="auto",
                    style=self.image_style_combo.currentText().strip() if hasattr(self, "image_style_combo") else "auto",
                    palette=self.image_palette_combo.currentText().strip() if hasattr(self, "image_palette_combo") else "auto",
                    backend=self.image_backend_combo.currentText().strip() if hasattr(self, "image_backend_combo") else "auto",
                    model=self._selected_image_model_path() if hasattr(self, "image_model_combo") else "",
                    device=self.image_device_combo.currentText().strip() if hasattr(self, "image_device_combo") else "auto",
                    steps=int(self.image_steps_input.value()) if hasattr(self, "image_steps_input") else 36,
                    guidance=float(self.image_guidance_input.value()) if hasattr(self, "image_guidance_input") else 7.2,
                    negative=self.image_negative_input.toPlainText().strip() if hasattr(self, "image_negative_input") else "",
                    count=1,
                    width=width,
                    height=height,
                    seed=int(self.image_seed_input.value()) if hasattr(self, "image_seed_input") else 77,
                    prefix="eli_chat",
                    sheet=False,
                    manifest=False,
                    save_specs=True,
                    use_chat_context=False,
                    use_proactive_context=bool(getattr(self, "image_proactive_context_checkbox", None).isChecked()) if hasattr(self, "image_proactive_context_checkbox") else False,
                    auto_personalize=bool(getattr(self, "image_personalize_checkbox", None).isChecked()) if hasattr(self, "image_personalize_checkbox") else True,
                )
                result = generate_images(
                    req,
                    settings,
                    proactive_ground=proactive_ground,
                    conversation_history=[],
                )
                self.chat_image_generation_done_signal.emit(result, settings, prompt)
            except Exception as e:
                self.chat_image_generation_failed_signal.emit(str(e))

        threading.Thread(target=worker, daemon=True, name="image-chat-generate").start()

    def _chat_image_generation_done(self, result, settings: Dict[str, Any], prompt: str):
        self._image_generation_done(result, settings)
        message = f"🖼️ Generated {len(result.saved_paths)} image(s) for: {prompt}"
        if result.saved_paths:
            message += f"\nSaved: {result.saved_paths[0]}"
        self.conversation_history.append({"role": "assistant", "content": message})
        self.chat_response_signal.emit(message)
        self._chat_image_prompt = ""
        self._chat_image_source_text = ""

    def _chat_image_generation_failed(self, error_text: str):
        self._image_generation_failed(error_text)
        message = f"❌ Image generation failed: {error_text}"
        self.conversation_history.append({"role": "assistant", "content": message})
        self.chat_response_signal.emit(message)
        self._chat_image_prompt = ""
        self._chat_image_source_text = ""

    def adjust_active_zoom(self, direction: int):
        widget = self.tabs.currentWidget()
        if widget is getattr(self, "_settings_root", None):
            if direction > 0:
                self._settings_zoom_view.zoom_in()
            else:
                self._settings_zoom_view.zoom_out()
            return
        if widget is getattr(self, "image_tab_widget", None):
            if direction > 0:
                self._image_zoom_view.zoom_in()
            else:
                self._image_zoom_view.zoom_out()
            return

        focus = QApplication.focusWidget()
        if hasattr(focus, "zoomIn") and hasattr(focus, "zoomOut"):
            if direction > 0:
                focus.zoomIn(1)
            else:
                focus.zoomOut(1)
            return
        if hasattr(self, "chat_display"):
            if direction > 0:
                self.chat_display.zoomIn(1)
            else:
                self.chat_display.zoomOut(1)

    def reset_active_zoom(self):
        widget = self.tabs.currentWidget()
        if widget is getattr(self, "_settings_root", None):
            self._settings_zoom_view.zoom_reset()
            return
        if widget is getattr(self, "image_tab_widget", None):
            self._image_zoom_view.zoom_reset()

    def create_chat_tab(self):
        chat_widget = QWidget()
        layout = QVBoxLayout(chat_widget)
        header = QLabel(f"💬 {APP_NAME} - Local AI Assistant")
        header.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px;")
        layout.addWidget(header)
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        info_layout = QHBoxLayout(info_frame)
        self.model_info_label = QLabel("🔴 Model: Not loaded")
        info_layout.addWidget(self.model_info_label)
        info_layout.addStretch()
        self.isolation_label = QLabel("🔒 100% LOCAL - No external connections")
        self.isolation_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        info_layout.addWidget(self.isolation_label)
        layout.addWidget(info_frame)
        class ZoomableTextEdit(QTextEdit):
            def wheelEvent(self, event):
                if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    if event.angleDelta().y() > 0:
                        self.zoomIn(1)
                    else:
                        self.zoomOut(1)
                    event.accept()
                else:
                    super().wheelEvent(event)

        _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
        _TEXT_EXTS  = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
                       ".toml", ".csv", ".log", ".sh", ".html", ".css", ".xml", ".rst"}

        class DropAwareTextEdit(QTextEdit):
            """Chat input box that accepts dropped files and images."""
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.setAcceptDrops(True)
                self._dropped_paths: list = []

            def dragEnterEvent(self, event):
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                else:
                    super().dragEnterEvent(event)

            def dragMoveEvent(self, event):
                if event.mimeData().hasUrls():
                    event.acceptProposedAction()
                else:
                    super().dragMoveEvent(event)

            def dropEvent(self, event):
                if not event.mimeData().hasUrls():
                    super().dropEvent(event)
                    return
                event.acceptProposedAction()
                for url in event.mimeData().urls():
                    path = url.toLocalFile()
                    if not path:
                        continue
                    from pathlib import Path as _P
                    p = _P(path)
                    if not p.exists():
                        continue
                    suffix = p.suffix.lower()
                    if suffix in _IMAGE_EXTS:
                        tag = f"[Image: {path}]"
                        self._dropped_paths.append(("image", path))
                    elif suffix in _TEXT_EXTS:
                        tag = f"[File: {path}]"
                        self._dropped_paths.append(("text", path))
                    elif suffix == ".pdf":
                        tag = f"[PDF: {path}]"
                        self._dropped_paths.append(("pdf", path))
                    else:
                        tag = f"[File: {path}]"
                        self._dropped_paths.append(("file", path))
                    cur = self.toPlainText().rstrip()
                    self.setPlainText((cur + "\n" + tag).strip())

        self.chat_display = ZoomableTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlaceholderText("Conversation will appear here...")
        layout.addWidget(self.chat_display, stretch=7)
        input_group = QGroupBox("Your Message")
        input_layout = QVBoxLayout(input_group)
        self.chat_input = DropAwareTextEdit()
        self.chat_input.setPlaceholderText(
            "Type your message here… or drag & drop files/images  (Enter to send, Shift+Enter for newline)"
        )
        self.chat_input.setMaximumHeight(120)
        self.chat_input.installEventFilter(self)
        input_layout.addWidget(self.chat_input)
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)
        # Compact bottom-row stylesheet shared by all chat controls.
        _BTN_BASE = (
            "QPushButton { color:white; font-weight:600; border-radius:4px;"
            " padding:3px 8px; min-height:24px; max-height:26px; font-size:11px; }"
        )
        _COMBO_BASE = (
            "QComboBox { background:#1e2535; color:#88c0d0;"
            " border:1px solid #88c0d0; border-radius:4px;"
            " padding:2px 6px; min-height:24px; max-height:26px; font-size:11px; }"
            "QComboBox QAbstractItemView { background:#1e2535; color:#ccc;"
            " selection-background-color:#3e3e3e; }"
        )

        self.send_btn = QPushButton("Send")
        self.send_btn.setStyleSheet(
            _BTN_BASE +
            "QPushButton { background-color:#4CAF50; }"
            "QPushButton:hover { background-color:#45a049; }"
            "QPushButton:disabled { background-color:#5b6470; color:#cfd6e2; }"
        )
        self.send_btn.clicked.connect(self.send_message)
        btn_layout.addWidget(self.send_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(
            _BTN_BASE + "QPushButton { background-color:#5a6373; }"
            "QPushButton:hover { background-color:#6a7484; }"
        )
        clear_btn.clicked.connect(self.clear_chat)
        btn_layout.addWidget(clear_btn)

        self.wake_word_btn = QPushButton("Wake: ON")
        self.wake_word_btn.setCheckable(True)
        self.wake_word_btn.setChecked(True)
        self.wake_word_btn.setToolTip(
            "Toggle wake word requirement.\n"
            "ON = say 'computer' before commands.\n"
            "OFF = all speech is treated as a command (direct listen mode)."
        )
        self.wake_word_btn.setStyleSheet(
            _BTN_BASE
            + "QPushButton:checked { background-color:#4CAF50; }"
            "QPushButton:!checked { background-color:#F44336; }"
            "QPushButton:checked:hover { background-color:#388E3C; }"
            "QPushButton:!checked:hover { background-color:#C62828; }"
        )
        self.wake_word_btn.toggled.connect(self._on_wake_word_toggled)
        btn_layout.addWidget(self.wake_word_btn)

        self.auto_speak_btn = QPushButton("🔇 Auto")
        self.auto_speak_btn.setCheckable(True)
        self.auto_speak_btn.setToolTip("Auto-speak every ELI response")
        self.auto_speak_btn.setStyleSheet(
            _BTN_BASE + "QPushButton { background-color:#607D8B; }"
            "QPushButton:checked { background-color:#2196F3; }"
            "QPushButton:hover { background-color:#455A64; }"
        )
        self.auto_speak_btn.toggled.connect(self._on_auto_speak_toggled)
        btn_layout.addWidget(self.auto_speak_btn)

        # Voice selector — visible in chat row so the user doesn't dig into Settings.
        self.voice_combo = QComboBox()
        self.voice_combo.setMinimumWidth(120)
        self.voice_combo.setMaximumWidth(150)
        self.voice_combo.setToolTip("Select ELI's voice (Piper)")
        self.voice_combo.setStyleSheet(_COMBO_BASE)
        try:
            from eli.perception.tts_router import (
                list_voices as _lv, get_active_voice as _gav,
            )
            for v in (_lv() or []):
                self.voice_combo.addItem(v)
            cur = _gav()
            if cur and self.voice_combo.findText(cur) >= 0:
                self.voice_combo.setCurrentText(cur)
        except Exception as _ve:
            self.voice_combo.addItem("(no voices)")
            self.voice_combo.setEnabled(False)
            log.debug(f"[GUI] voice list unavailable: {_ve}")
        self.voice_combo.currentTextChanged.connect(self._on_voice_changed)
        btn_layout.addWidget(self.voice_combo)

        self.stt_btn = QPushButton("🎤 Mic")
        self.stt_btn.setCheckable(True)
        self.stt_btn.setToolTip("Toggle voice input on/off")
        self.stt_btn.setStyleSheet(
            _BTN_BASE + "QPushButton { background-color:#607D8B; }"
            "QPushButton:checked { background-color:#FF5722; }"
            "QPushButton:hover { background-color:#455A64; }"
        )
        self.stt_btn.toggled.connect(self._stt_toggle)
        btn_layout.addWidget(self.stt_btn)

        self.reasoning_mode_combo = QComboBox()
        self.reasoning_mode_combo.addItems(['⚡ Quick','🔗 CoT','🔄 Self-C','🌳 ToT','⚖️ Const AI'])
        self.reasoning_mode_combo.setMinimumWidth(110)
        self.reasoning_mode_combo.setMaximumWidth(140)
        self.reasoning_mode_combo.setToolTip('Reasoning mode')
        self.reasoning_mode_combo.setStyleSheet(_COMBO_BASE)
        btn_layout.addWidget(self.reasoning_mode_combo)
        self.reasoning_mode_combo.currentTextChanged.connect(self.change_reasoning_mode)

        # Auto reasoning-mode toggle — when on, prompt keywords switch the
        # combobox automatically before the message is dispatched.
        self.auto_mode_btn = QPushButton("🤖 Auto-Mode")
        self.auto_mode_btn.setCheckable(True)
        self.auto_mode_btn.setChecked(True)
        self.auto_mode_btn.setToolTip(
            "When enabled, the reasoning mode is auto-selected from prompt keywords "
            "(e.g. 'prove', 'step by step', 'explore branches', 'critique then revise')."
        )
        self.auto_mode_btn.setStyleSheet(
            _BTN_BASE + "QPushButton { background-color:#3a4f7a; }"
            "QPushButton:checked { background-color:#5a8de0; color:#0f1424; }"
            "QPushButton:hover { background-color:#4a6394; }"
        )
        self.auto_mode_btn.toggled.connect(self._on_auto_mode_toggled)
        self._auto_reasoning_mode = True
        btn_layout.addWidget(self.auto_mode_btn)

        user_color_btn = QPushButton("🎨")
        user_color_btn.setMaximumWidth(34)
        user_color_btn.setToolTip("Pick colour for your messages")
        user_color_btn.setStyleSheet(
            _BTN_BASE + "QPushButton { background-color:#4a5160; padding:2px 4px; }"
            "QPushButton:hover { background-color:#5a6373; }"
        )
        user_color_btn.clicked.connect(self._pick_user_color)
        btn_layout.addWidget(user_color_btn)
        btn_layout.addStretch()
        input_layout.addLayout(btn_layout)
        layout.addWidget(input_group, stretch=2)
        self.tabs.addTab(chat_widget, "💬 Chat")

    # ========== HABITS TAB (FIXED) ==========
    def _build_habits_panel(self) -> QWidget:
        """Habits management panel used inside the proactive workspace."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        header = QLabel("⏰ Habits Scheduler")
        header.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px;")
        layout.addWidget(header)

        # Toolbar
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.refresh_habit_list)
        toolbar.addWidget(refresh_btn)

        add_btn = QPushButton("➕ Add Habit")
        add_btn.clicked.connect(self.add_habit_rule)
        toolbar.addWidget(add_btn)

        delete_btn = QPushButton("🗑️ Delete Selected")
        delete_btn.clicked.connect(self.delete_habit_rule)
        toolbar.addWidget(delete_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table of habits
        self.habit_table = QTableWidget()
        self.habit_table.setColumnCount(6)
        self.habit_table.setHorizontalHeaderLabels(["ID", "Name", "Command", "Time", "Days", "Enabled"])
        self.habit_table.horizontalHeader().setStretchLastSection(True)
        # Set selection behavior (Qt version safe)
        select_rows = getattr(
            getattr(QAbstractItemView, "SelectionBehavior", QAbstractItemView),
            "SelectRows",
        )
        self.habit_table.setSelectionBehavior(select_rows)
        self.habit_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.habit_table)

        # Info label
        self.habit_info = QLabel("")
        layout.addWidget(self.habit_info)

        self.refresh_habit_list()
        return widget

    def create_habits_tab(self):
        widget = self._build_habits_panel()
        self.tabs.addTab(widget, "⏰ Habits")

    def refresh_habit_list(self):
        """Refresh the habits table from memory."""
        try:
            rules = memory_system.get_habit_rules(enabled_only=False)
            self.habit_table.setRowCount(len(rules))
            for i, rule in enumerate(rules):
                # ID
                id_item = QTableWidgetItem(str(rule["id"]))
                self.habit_table.setItem(i, 0, id_item)
                # Name
                name_item = QTableWidgetItem(rule.get("name", ""))
                self.habit_table.setItem(i, 1, name_item)
                # Command
                cmd_item = QTableWidgetItem(rule.get("command", ""))
                self.habit_table.setItem(i, 2, cmd_item)
                # Time (HH:MM)
                time_str = f"{rule.get('hour', 0):02d}:{rule.get('minute', 0):02d}"
                time_item = QTableWidgetItem(time_str)
                self.habit_table.setItem(i, 3, time_item)
                # Days
                days = rule.get("days")
                if days is None:
                    days_str = "Every day"
                else:
                    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                    days_str = ", ".join(day_names[d] for d in days if 0 <= d < 7)
                days_item = QTableWidgetItem(days_str)
                self.habit_table.setItem(i, 4, days_item)
                # Enabled (checkbox)
                enabled = rule.get("enabled", False)
                chk = QCheckBox()
                chk.setChecked(enabled)
                chk.stateChanged.connect(lambda state, rid=rule["id"]: self.toggle_habit_rule(rid, state == Qt.Checked))
                self.habit_table.setCellWidget(i, 5, chk)
            self.habit_info.setText(f"Total habits: {len(rules)}")
        except Exception as e:
            self.habit_info.setText(f"Error loading habits: {e}")

    def add_habit_rule(self):
        """Open a dialog to add a new habit rule."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Habit Rule")
        layout = QFormLayout(dialog)

        name_edit = QLineEdit()
        layout.addRow("Name:", name_edit)

        command_edit = QLineEdit()
        layout.addRow("Command:", command_edit)

        hour_spin = QSpinBox()
        hour_spin.setRange(0, 23)
        layout.addRow("Hour (0-23):", hour_spin)

        minute_spin = QSpinBox()
        minute_spin.setRange(0, 59)
        layout.addRow("Minute (0-59):", minute_spin)

        # Days of week (multi-select)
        days_group = QGroupBox("Days (leave empty for every day)")
        days_layout = QHBoxLayout()
        day_checkboxes = []
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, name in enumerate(day_names):
            cb = QCheckBox(name)
            days_layout.addWidget(cb)
            day_checkboxes.append(cb)
        days_group.setLayout(days_layout)
        layout.addRow(days_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text().strip()
            command = command_edit.text().strip()
            hour = hour_spin.value()
            minute = minute_spin.value()
            days = [i for i, cb in enumerate(day_checkboxes) if cb.isChecked()] or None
            if name and command:
                try:
                    rule_id = memory_system.add_habit_rule(name, command, hour, minute, days)
                    if rule_id > 0:
                        self.refresh_habit_list()
                        self.status_signal.emit(f"Habit '{name}' added.")
                    else:
                        QMessageBox.warning(self, "Error", "Failed to add habit rule.")
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to add habit: {e}")

    def delete_habit_rule(self):
        """Delete the selected habit rule."""
        selected = self.habit_table.currentRow()
        if selected < 0:
            QMessageBox.information(self, "No Selection", "Please select a habit to delete.")
            return
        rule_id_item = self.habit_table.item(selected, 0)
        if not rule_id_item:
            return
        rule_id = int(rule_id_item.text())
        name_item = self.habit_table.item(selected, 1)
        name = name_item.text() if name_item else "Unknown"
        reply = QMessageBox.question(self, "Confirm Delete",
                                     f"Are you sure you want to delete habit '{name}'?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                memory_system.delete_habit_rule(rule_id)
                self.refresh_habit_list()
                self.status_signal.emit(f"Habit '{name}' deleted.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to delete habit: {e}")

    def toggle_habit_rule(self, rule_id: int, enabled: bool):
        """Toggle a habit rule's enabled state."""
        try:
            memory_system.toggle_habit_rule(rule_id, enabled)
            # Optionally refresh the whole table to reflect changes
            self.refresh_habit_list()
        except Exception as e:
            print(f"Failed to toggle habit {rule_id}: {e}")

    def create_image_tab(self):
        self.image_tab_widget = QWidget()
        root_layout = QVBoxLayout(self.image_tab_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        workspace = QWidget()
        workspace.setObjectName("imageStudioWorkspace")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header_row = QHBoxLayout()

        header = QLabel("🖼️ Image Studio")
        header.setStyleSheet("font-size:18px; font-weight:bold; padding:10px;")
        header_row.addWidget(header)
        header_row.addStretch()

        workspace_zoom_out = QPushButton("A-")
        workspace_zoom_out.setToolTip("Zoom out the full Images workspace (Ctrl+-)")
        workspace_zoom_out.clicked.connect(lambda: self._image_zoom_view.zoom_out())
        header_row.addWidget(workspace_zoom_out)

        workspace_zoom_reset = QPushButton("100%")
        workspace_zoom_reset.setToolTip("Reset Images workspace zoom (Ctrl+0)")
        workspace_zoom_reset.clicked.connect(lambda: self._image_zoom_view.zoom_reset())
        header_row.addWidget(workspace_zoom_reset)

        workspace_zoom_in = QPushButton("A+")
        workspace_zoom_in.setToolTip("Zoom in the full Images workspace (Ctrl+=)")
        workspace_zoom_in.clicked.connect(lambda: self._image_zoom_view.zoom_in())
        header_row.addWidget(workspace_zoom_in)
        layout.addLayout(header_row)

        sub = QLabel(
            "Generate local images with either the lightweight procedural engine or a real diffusion model. Photoreal and 3D-style results require a local diffusion checkpoint, ideally under models/image/. Use Ctrl+scroll or Ctrl+plus/minus to zoom this whole workspace."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#7d8ba2;padding:0 10px 10px 10px;")
        layout.addWidget(sub)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        prompt_group = QGroupBox("Prompt")
        prompt_layout = QVBoxLayout(prompt_group)
        self.image_prompt_input = QTextEdit()
        self.image_prompt_input.setPlaceholderText("Describe the image you want ELI to generate...")
        self.image_prompt_input.setMinimumHeight(120)
        prompt_layout.addWidget(self.image_prompt_input)

        prompt_btn_row = QHBoxLayout()
        recent_btn = QPushButton("Use Recent Context")
        recent_btn.clicked.connect(self.use_recent_context_for_image_prompt)
        prompt_btn_row.addWidget(recent_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.image_prompt_input.clear)
        prompt_btn_row.addWidget(clear_btn)
        prompt_btn_row.addStretch()
        prompt_layout.addLayout(prompt_btn_row)
        left_layout.addWidget(prompt_group)

        options_group = QGroupBox("Generation Options")
        options_layout = QFormLayout(options_group)
        self.image_preset_combo = QComboBox()
        options_layout.addRow("Preset", self.image_preset_combo)

        self.image_project_input = QLineEdit()
        self.image_project_input.setPlaceholderText("Optional folder with image/text references")
        project_row = QHBoxLayout()
        project_row.addWidget(self.image_project_input)
        project_btn = QPushButton("Browse…")
        project_btn.clicked.connect(self.browse_image_project_folder)
        project_row.addWidget(project_btn)
        options_layout.addRow("Project", project_row)

        self.image_scene_combo = QComboBox()
        self.image_scene_combo.addItems(["auto", "portrait", "landscape", "poster", "abstract", "emblem", "product", "cityscape", "space"])
        options_layout.addRow("Scene", self.image_scene_combo)

        self.image_style_combo = QComboBox()
        self.image_style_combo.addItems(["auto", "balanced", "cinematic", "minimal", "luxury", "neon", "fantasy"])
        options_layout.addRow("Style", self.image_style_combo)

        self.image_palette_combo = QComboBox()
        self.image_palette_combo.addItems(["auto", "blue_dawn", "crimson_sunset", "emerald_aurora", "golden_storm", "monochrome_luxury", "neon_noir", "rose_steel", "solar_glass", "violet_dusk"])
        options_layout.addRow("Palette", self.image_palette_combo)

        self.image_backend_combo = QComboBox()
        self.image_backend_combo.addItems(["auto", "diffusion", "procedural"])
        options_layout.addRow("Backend", self.image_backend_combo)

        model_row = QHBoxLayout()
        self.image_model_combo = QComboBox()
        self.image_model_combo.setEditable(True)
        self.image_model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.image_model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.image_model_combo.setMinimumContentsLength(28)
        model_row.addWidget(self.image_model_combo, stretch=1)
        refresh_models_btn = QPushButton("Refresh")
        refresh_models_btn.clicked.connect(self.refresh_image_model_sources)
        model_row.addWidget(refresh_models_btn)
        browse_model_btn = QPushButton("Path…")
        browse_model_btn.clicked.connect(self.browse_image_model_path)
        model_row.addWidget(browse_model_btn)
        options_layout.addRow("Model", model_row)

        self.image_device_combo = QComboBox()
        self.image_device_combo.addItems(["auto", "cuda", "cpu"])
        options_layout.addRow("Device", self.image_device_combo)

        self.image_quality_preset_combo = QComboBox()
        self.image_quality_preset_combo.addItems(["draft", "balanced", "ultra", "extreme"])
        self.image_quality_preset_combo.currentTextChanged.connect(self._apply_image_quality_preset)
        options_layout.addRow("Quality", self.image_quality_preset_combo)

        render_row = QHBoxLayout()
        self.image_steps_input = QSpinBox()
        self.image_steps_input.setRange(8, 120)
        self.image_steps_input.setValue(36)
        self.image_guidance_input = QDoubleSpinBox()
        self.image_guidance_input.setRange(1.0, 20.0)
        self.image_guidance_input.setSingleStep(0.1)
        self.image_guidance_input.setValue(7.2)
        render_row.addWidget(QLabel("Steps"))
        render_row.addWidget(self.image_steps_input)
        render_row.addSpacing(8)
        render_row.addWidget(QLabel("CFG"))
        render_row.addWidget(self.image_guidance_input)
        options_layout.addRow("Render", render_row)

        self.image_negative_input = QTextEdit()
        self.image_negative_input.setMaximumHeight(72)
        self.image_negative_input.setPlaceholderText("Optional negative prompt: cartoon, flat, blurry, low quality, malformed anatomy...")
        options_layout.addRow("Negative", self.image_negative_input)

        self.image_backend_note = QLabel("No local diffusion checkpoint detected yet. Drop one into models/image/ or paste a full local path to unlock photoreal rendering.")
        self.image_backend_note.setWordWrap(True)
        self.image_backend_note.setStyleSheet("color:#7d8ba2;font-size:11px;")
        options_layout.addRow("", self.image_backend_note)

        size_row = QHBoxLayout()
        self.image_width_input = QSpinBox()
        self.image_width_input.setRange(256, 4096)
        self.image_width_input.setSingleStep(64)
        self.image_width_input.setValue(1400)
        self.image_height_input = QSpinBox()
        self.image_height_input.setRange(256, 4096)
        self.image_height_input.setSingleStep(64)
        self.image_height_input.setValue(900)
        size_row.addWidget(self.image_width_input)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.image_height_input)
        options_layout.addRow("Size", size_row)

        batch_row = QHBoxLayout()
        self.image_count_input = QSpinBox()
        self.image_count_input.setRange(1, 24)
        self.image_count_input.setValue(1)
        self.image_seed_input = QSpinBox()
        self.image_seed_input.setRange(1, 999999)
        self.image_seed_input.setValue(77)
        batch_row.addWidget(self.image_count_input)
        batch_row.addWidget(QLabel("Seed"))
        batch_row.addWidget(self.image_seed_input)
        options_layout.addRow("Batch", batch_row)

        self.image_personalize_checkbox = QCheckBox("Personalise with saved user/image identity")
        self.image_personalize_checkbox.setChecked(True)
        options_layout.addRow("", self.image_personalize_checkbox)

        self.image_chat_context_checkbox = QCheckBox("Blend recent chat context into the prompt")
        self.image_chat_context_checkbox.setChecked(True)
        options_layout.addRow("", self.image_chat_context_checkbox)

        self.image_proactive_context_checkbox = QCheckBox("Blend proactive patterns/habits into the prompt")
        self.image_proactive_context_checkbox.setChecked(True)
        options_layout.addRow("", self.image_proactive_context_checkbox)

        self.image_prompt_context_display = QTextEdit()
        self.image_prompt_context_display.setReadOnly(True)
        self.image_prompt_context_display.setMaximumHeight(130)
        self.image_prompt_context_display.setPlaceholderText("Applied prompt context and personalisation notes will appear here.")
        options_layout.addRow("Context", self.image_prompt_context_display)

        left_layout.addWidget(options_group)

        generate_row = QHBoxLayout()
        self.image_generate_btn = QPushButton("Generate Images")
        self.image_generate_btn.setMinimumHeight(40)
        self.image_generate_btn.clicked.connect(self.generate_images_from_studio)
        generate_row.addWidget(self.image_generate_btn)
        self.image_open_output_btn = QPushButton("Open Output Folder")
        self.image_open_output_btn.clicked.connect(self.open_image_output_folder)
        generate_row.addWidget(self.image_open_output_btn)
        left_layout.addLayout(generate_row)
        left_layout.addStretch()

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.image_preview = _ZoomableImagePreview()

        preview_head = QHBoxLayout()
        preview_title = QLabel("Preview")
        preview_title.setStyleSheet("font-weight:bold; font-size:14px;")
        preview_head.addWidget(preview_title)
        preview_head.addStretch()
        zoom_out = QPushButton("−")
        zoom_out.clicked.connect(lambda: self.image_preview.zoom_out())
        preview_head.addWidget(zoom_out)
        zoom_reset = QPushButton("100%")
        zoom_reset.clicked.connect(self.image_preview.zoom_reset)
        preview_head.addWidget(zoom_reset)
        zoom_in = QPushButton("+")
        zoom_in.clicked.connect(lambda: self.image_preview.zoom_in())
        preview_head.addWidget(zoom_in)
        right_layout.addLayout(preview_head)

        right_layout.addWidget(self.image_preview, stretch=5)

        self.image_results_list = QListWidget()
        self.image_results_list.itemSelectionChanged.connect(self._show_selected_image_result)
        self.image_results_list.itemDoubleClicked.connect(lambda _item: self.open_selected_image_output())
        right_layout.addWidget(self.image_results_list, stretch=2)

        self.image_summary_display = QTextEdit()
        self.image_summary_display.setReadOnly(True)
        self.image_summary_display.setMaximumHeight(170)
        self.image_summary_display.setPlaceholderText("Generation summary, applied prompt, and output paths will appear here.")
        right_layout.addWidget(self.image_summary_display)

        # ── ELI Image Chat ──────────────────────────────────────────────────
        img_chat_group = QGroupBox("Ask ELI About This Image")
        img_chat_layout = QVBoxLayout(img_chat_group)
        img_chat_layout.setSpacing(4)

        # Label showing which image ELI will talk about
        self.image_eli_context_label = QLabel("No image selected — generate or click one in the list above.")
        self.image_eli_context_label.setStyleSheet(
            "color: #88aacc; font-size: 9px; font-style: italic; padding: 0 2px;"
        )
        self.image_eli_context_label.setWordWrap(True)
        img_chat_layout.addWidget(self.image_eli_context_label)

        self.image_eli_response = QTextEdit()
        self.image_eli_response.setReadOnly(True)
        self.image_eli_response.setMaximumHeight(100)
        self.image_eli_response.setPlaceholderText("ELI's answer will appear here…")
        img_chat_layout.addWidget(self.image_eli_response)

        img_chat_row = QHBoxLayout()
        self.image_eli_input = QLineEdit()
        self.image_eli_input.setPlaceholderText("Describe it, critique it, suggest edits…")
        self.image_eli_input.returnPressed.connect(self._ask_eli_about_image)
        img_chat_row.addWidget(self.image_eli_input, stretch=1)
        ask_img_btn = QPushButton("Ask ELI")
        ask_img_btn.setFixedWidth(90)
        ask_img_btn.clicked.connect(self._ask_eli_about_image)
        img_chat_row.addWidget(ask_img_btn)
        img_chat_layout.addLayout(img_chat_row)

        right_layout.addWidget(img_chat_group)
        self._current_image_path = None
        # ── end ELI Image Chat ──────────────────────────────────────────────

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([520, 760])
        layout.addWidget(splitter)

        self._image_zoom_view = _ZoomableSettingsView(workspace)
        root_layout.addWidget(self._image_zoom_view)
        self.tabs.addTab(self.image_tab_widget, "🖼️ Images")
        self.refresh_image_presets()
        self.refresh_image_model_sources()
        self.refresh_image_gallery()

    def browse_image_project_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Image Reference Folder",
            self.image_project_input.text().strip() if hasattr(self, "image_project_input") else str(PROJECT_ROOT),
        )
        if folder:
            if hasattr(self, "image_project_input"):
                self.image_project_input.setText(folder)
            if hasattr(self, "image_default_project_input"):
                self.image_default_project_input.setText(folder)

    def browse_image_model_path(self):
        start = ""
        if hasattr(self, "image_model_combo"):
            start = self.image_model_combo.currentText().strip()
        if not start and hasattr(self, "image_model_path_input"):
            start = self.image_model_path_input.text().strip()

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Diffusion Model File",
            start or str(PROJECT_ROOT / "models" / "image"),
            "Model Files (*.safetensors *.ckpt);;All Files (*)",
        )
        selected = file_path
        if not selected:
            selected = QFileDialog.getExistingDirectory(
                self,
                "Select Diffusion Model Folder",
                start or str(PROJECT_ROOT / "models" / "image"),
            )
        if not selected:
            return

        if hasattr(self, "image_model_combo"):
            self.image_model_combo.setEditText(selected)
        if hasattr(self, "image_model_path_input"):
            self.image_model_path_input.setText(selected)

    def refresh_image_model_sources(self):
        paths = []
        try:
            from eli.tools.image_engine import discover_local_image_models
            paths = [str(p) for p in discover_local_image_models()]
        except Exception as e:
            log.debug(f"[IMAGE] model scan failed: {e}")

        if hasattr(self, "image_model_combo"):
            current = self.image_model_combo.currentText().strip()
            self.image_model_combo.blockSignals(True)
            self.image_model_combo.clear()
            for path in paths:
                label = Path(path).name if Path(path).name else path
                self.image_model_combo.addItem(label, path)
            if current:
                idx = self.image_model_combo.findData(current)
                if idx >= 0:
                    self.image_model_combo.setCurrentIndex(idx)
                else:
                    self.image_model_combo.setEditText(current)
            self.image_model_combo.blockSignals(False)

        if hasattr(self, "image_backend_note"):
            if paths:
                self.image_backend_note.setText(
                    f"Detected {len(paths)} local diffusion model candidate(s). "
                    "Choose one to enable high-fidelity 3D-style rendering."
                )
            else:
                self.image_backend_note.setText(
                    "No local diffusion checkpoint detected yet. Drop one into models/image/ or paste a full local path to unlock photoreal rendering."
                )

    def _selected_image_model_path(self) -> str:
        if hasattr(self, "image_model_combo"):
            data = self.image_model_combo.currentData()
            if data:
                return str(data).strip()
            text = self.image_model_combo.currentText().strip()
            if text:
                return text
        if hasattr(self, "image_model_path_input"):
            return self.image_model_path_input.text().strip()
        return ""

    def _apply_image_quality_preset(self, preset: str):
        mapping = {
            "draft": (20, 5.5),
            "balanced": (32, 6.8),
            "ultra": (44, 7.8),
            "extreme": (60, 8.8),
        }
        steps, guidance = mapping.get(str(preset).strip().lower(), (36, 7.2))
        if hasattr(self, "image_steps_input"):
            self.image_steps_input.setValue(int(steps))
        if hasattr(self, "image_guidance_input"):
            self.image_guidance_input.setValue(float(guidance))

    def _apply_image_default_quality_preset(self, preset: str):
        mapping = {
            "draft": (20, 5.5),
            "balanced": (32, 6.8),
            "ultra": (44, 7.8),
            "extreme": (60, 8.8),
        }
        steps, guidance = mapping.get(str(preset).strip().lower(), (36, 7.2))
        if hasattr(self, "image_steps_default_input"):
            self.image_steps_default_input.setValue(int(steps))
        if hasattr(self, "image_guidance_default_input"):
            self.image_guidance_default_input.setValue(float(guidance))

    def refresh_image_presets(self):
        try:
            from eli.tools.image_engine import discover_presets
            presets = discover_presets()
        except Exception as e:
            presets = []
            log.debug(f"[IMAGE] preset scan failed: {e}")
        if hasattr(self, "image_preset_combo"):
            current = self.image_preset_combo.currentText()
            self.image_preset_combo.blockSignals(True)
            self.image_preset_combo.clear()
            self.image_preset_combo.addItem("")
            for preset in presets:
                self.image_preset_combo.addItem(preset)
            idx = self.image_preset_combo.findText(current)
            if idx >= 0:
                self.image_preset_combo.setCurrentIndex(idx)
            self.image_preset_combo.blockSignals(False)

    def refresh_image_gallery(self):
        try:
            from eli.tools.image_engine import list_recent_outputs
            outputs = list_recent_outputs(limit=30)
        except Exception as e:
            outputs = []
            log.debug(f"[IMAGE] output scan failed: {e}")
        if not hasattr(self, "image_results_list"):
            return
        self.image_results_list.clear()
        for path in outputs:
            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.image_results_list.addItem(item)
        if outputs:
            self.image_results_list.setCurrentRow(0)
            self._current_image_path = str(outputs[0])
            if hasattr(self, "image_eli_context_label"):
                self.image_eli_context_label.setText(f"ELI will discuss: {outputs[0].name}")
                self.image_eli_context_label.setStyleSheet(
                    "color: #66dd88; font-size: 9px; font-style: italic; padding: 0 2px;"
                )

    def _focus_generated_image_result(self, result) -> None:
        target = ""
        if getattr(result, "saved_paths", None):
            target = str(result.saved_paths[0])
        elif getattr(result, "contact_sheet", None):
            target = str(result.contact_sheet)
        if not target:
            return

        self.open_image_studio_tab()
        matched_row = -1
        for i in range(self.image_results_list.count()):
            item = self.image_results_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == target:
                matched_row = i
                break
        if matched_row < 0:
            item = QListWidgetItem(Path(target).name)
            item.setData(Qt.ItemDataRole.UserRole, target)
            self.image_results_list.insertItem(0, item)
            matched_row = 0
        if matched_row >= 0:
            self.image_results_list.setCurrentRow(matched_row)
            self.image_results_list.scrollToItem(self.image_results_list.item(matched_row))
        loaded = self.image_preview.set_image_path(target)
        self._current_image_path = target
        if hasattr(self, "image_eli_context_label"):
            from pathlib import Path as _P2
            self.image_eli_context_label.setText(f"ELI will discuss: {_P2(target).name}")
            self.image_eli_context_label.setStyleSheet(
                "color: #66dd88; font-size: 9px; font-style: italic; padding: 0 2px;"
            )
        if loaded:
            self.image_preview.update()
            QApplication.processEvents()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _show_selected_image_result(self):
        items = self.image_results_list.selectedItems()
        if not items:
            return
        path = items[0].data(Qt.ItemDataRole.UserRole)
        if path:
            self.image_preview.set_image_path(path)
            self._current_image_path = path
            if hasattr(self, "image_eli_context_label"):
                from pathlib import Path as _P
                self.image_eli_context_label.setText(f"ELI will discuss: {_P(path).name}")
                self.image_eli_context_label.setStyleSheet(
                    "color: #66dd88; font-size: 9px; font-style: italic; padding: 0 2px;"
                )

    def open_selected_image_output(self):
        items = self.image_results_list.selectedItems()
        if not items:
            return
        path = items[0].data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_image_output_folder(self):
        try:
            from eli.tools.image_engine import output_dir
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir())))
        except Exception as e:
            QMessageBox.warning(self, "Open Folder", f"Unable to open image output folder: {e}")

    def _on_image_chat_response(self, text: str):
        """Main-thread slot — updates the image chat response widget safely."""
        self.image_eli_response.setPlainText(text)
        if hasattr(self, "ask_img_btn_ref"):
            self.ask_img_btn_ref.setEnabled(True)

    def _ask_eli_about_image(self):
        """Ask ELI about the currently previewed image — thread-safe."""
        question = self.image_eli_input.text().strip()
        if not question:
            question = "Describe this image in detail."
        img_path = getattr(self, "_current_image_path", None)
        if not img_path:
            self.image_eli_response.setPlainText(
                "Select an image from the list above first."
            )
            return

        self.image_eli_input.clear()
        # Update via signal (already on main thread here, direct call is fine)
        self.image_eli_response.setPlainText("Asking ELI…")

        from pathlib import Path as _P
        img_name = _P(img_path).name
        # Give the user visible confirmation of which image is being discussed
        combined = (
            f"[Image: {img_path}]\n"
            f"The image is '{img_name}' (path: {img_path}).\n"
            f"{question}"
        )

        def _worker():
            try:
                backend = self._text_backend_ready(notify=False)
                if backend is None:
                    self._image_chat_sig.emit("Text backend not loaded.")
                    return
                context = self._resolve_dropped_attachments(combined, [])
                _ce = getattr(self, "_cognitive_engine", None)
                if _ce is not None:
                    try:
                        reply = _ce.process(
                            context,
                            conversation_history=list(self.conversation_history[-6:]),
                        )
                        reply = _eli_gui_visible_text(reply)
                    except Exception as _e:
                        reply = f"[CE error: {_e}]"
                else:
                    adapter = _GUIEngineAdapter(
                        backend=backend,
                        memory=self._central_memory,
                        max_tokens=-1,
                        temperature=self.temperature_input.value(),
                        n_ctx=getattr(backend, "n_ctx", 4096),
                        inference_lock=self.__class__._inference_lock,
                        cognitive_engine=None,
                    )
                    reply = adapter.generate(context)
                self._image_chat_sig.emit(reply.strip())
            except Exception as e:
                self._image_chat_sig.emit(f"Error: {e}")

        import threading as _thr
        _thr.Thread(target=_worker, daemon=True, name="eli-img-chat").start()

    def use_recent_context_for_image_prompt(self):
        recent = [
            str(m.get("content", "")).strip()
            for m in reversed(self.conversation_history)
            if m.get("role") == "user" and str(m.get("content", "")).strip()
        ][:2]
        if not recent:
            QMessageBox.information(self, "No Context", "No recent user messages are available yet.")
            return
        recent.reverse()
        self.image_prompt_input.setPlainText("\n".join(recent))

    def _image_settings_snapshot(self) -> Dict[str, Any]:
        data = {}
        try:
            from eli.core.runtime_settings import load_settings as _rs_load
            data = _rs_load() or {}
        except Exception:
            data = {}
        if hasattr(self, "user_name_input"):
            data["user_name"] = self.user_name_input.text().strip()
        if hasattr(self, "image_style_profile_combo"):
            data["image_style_profile"] = self.image_style_profile_combo.currentText().strip()
        if hasattr(self, "image_palette_profile_combo"):
            data["image_palette_profile"] = self.image_palette_profile_combo.currentText().strip()
        if hasattr(self, "image_backend_default_combo"):
            data["image_backend"] = self.image_backend_default_combo.currentText().strip()
        elif hasattr(self, "image_backend_combo"):
            data["image_backend"] = self.image_backend_combo.currentText().strip()
        if hasattr(self, "image_model_path_input"):
            data["image_model_path"] = self.image_model_path_input.text().strip() or self._selected_image_model_path()
        elif hasattr(self, "image_model_combo"):
            data["image_model_path"] = self._selected_image_model_path()
        if hasattr(self, "image_device_default_combo"):
            data["image_device"] = self.image_device_default_combo.currentText().strip()
        elif hasattr(self, "image_device_combo"):
            data["image_device"] = self.image_device_combo.currentText().strip()
        if hasattr(self, "image_quality_default_combo"):
            data["image_quality_preset"] = self.image_quality_default_combo.currentText().strip()
        elif hasattr(self, "image_quality_preset_combo"):
            data["image_quality_preset"] = self.image_quality_preset_combo.currentText().strip()
        if hasattr(self, "image_steps_default_input"):
            data["image_steps"] = int(self.image_steps_default_input.value())
        elif hasattr(self, "image_steps_input"):
            data["image_steps"] = int(self.image_steps_input.value())
        if hasattr(self, "image_guidance_default_input"):
            data["image_guidance"] = float(self.image_guidance_default_input.value())
        elif hasattr(self, "image_guidance_input"):
            data["image_guidance"] = float(self.image_guidance_input.value())
        if hasattr(self, "image_negative_default_input"):
            data["image_negative_prompt"] = self.image_negative_default_input.toPlainText().strip()
        elif hasattr(self, "image_negative_input"):
            data["image_negative_prompt"] = self.image_negative_input.toPlainText().strip()
        if hasattr(self, "image_profile_notes_input"):
            data["image_profile_notes"] = self.image_profile_notes_input.toPlainText().strip()
        if hasattr(self, "image_auto_personalize_checkbox"):
            data["image_auto_personalize"] = bool(self.image_auto_personalize_checkbox.isChecked())
        if hasattr(self, "image_auto_open_checkbox"):
            data["image_auto_open"] = bool(self.image_auto_open_checkbox.isChecked())
        if hasattr(self, "image_use_chat_context_checkbox"):
            data["image_use_chat_context"] = bool(self.image_use_chat_context_checkbox.isChecked())
        if hasattr(self, "image_use_proactive_context_checkbox"):
            data["image_use_proactive_context"] = bool(self.image_use_proactive_context_checkbox.isChecked())
        if hasattr(self, "image_default_project_input"):
            data["image_default_project_path"] = self.image_default_project_input.text().strip()
        return data

    def generate_images_from_studio(self):
        prompt = self.image_prompt_input.toPlainText().strip()
        if not prompt and not self.image_chat_context_checkbox.isChecked():
            QMessageBox.information(self, "Prompt Required", "Enter an image prompt or enable recent chat context.")
            return
        if self.image_backend_combo.currentText().strip() == "diffusion" and not self._selected_image_model_path():
            QMessageBox.warning(
                self,
                "Diffusion Model Required",
                "Diffusion backend is selected, but no local model path is configured. Paste or browse a local SDXL / Flux / diffusion checkpoint first.",
            )
            return

        self.image_generate_btn.setEnabled(False)
        self.image_generate_btn.setText("Generating...")
        self.image_summary_display.setPlainText("Generating images with the local image engine...")
        self.status_signal.emit("🖼️ Image generation started")

        def worker():
            try:
                from eli.tools.image_engine import ImageGenerationRequest, generate_images

                settings = self._image_settings_snapshot()
                proactive_ground = {}
                if self.image_proactive_context_checkbox.isChecked():
                    proactive_ground = self._build_proactive_ground_truth(query=prompt)

                req = ImageGenerationRequest(
                    prompt=prompt,
                    project=self.image_project_input.text().strip(),
                    preset=self.image_preset_combo.currentText().strip(),
                    scene_type=self.image_scene_combo.currentText().strip(),
                    style=self.image_style_combo.currentText().strip(),
                    palette=self.image_palette_combo.currentText().strip(),
                    backend=self.image_backend_combo.currentText().strip(),
                    model=self._selected_image_model_path(),
                    device=self.image_device_combo.currentText().strip(),
                    steps=int(self.image_steps_input.value()),
                    guidance=float(self.image_guidance_input.value()),
                    negative=self.image_negative_input.toPlainText().strip(),
                    count=int(self.image_count_input.value()),
                    width=int(self.image_width_input.value()),
                    height=int(self.image_height_input.value()),
                    seed=int(self.image_seed_input.value()),
                    sheet=int(self.image_count_input.value()) > 1,
                    use_chat_context=bool(self.image_chat_context_checkbox.isChecked()),
                    use_proactive_context=bool(self.image_proactive_context_checkbox.isChecked()),
                    auto_personalize=bool(self.image_personalize_checkbox.isChecked()),
                )
                result = generate_images(
                    req,
                    settings,
                    proactive_ground=proactive_ground,
                    conversation_history=self.conversation_history if req.use_chat_context else [],
                )
                self.image_generation_done_signal.emit(result, settings)
            except Exception as e:
                self.image_generation_failed_signal.emit(str(e))

        threading.Thread(target=worker, daemon=True, name="image-studio-generate").start()

    def _image_generation_done(self, result, settings: Dict[str, Any]):
        self.image_generate_btn.setEnabled(True)
        self.image_generate_btn.setText("Generate Images")
        self.status_signal.emit(f"🖼️ Generated {len(result.saved_paths)} image(s)")

        self.image_prompt_context_display.setPlainText(
            "\n".join(result.personalization_notes) if result.personalization_notes else "No extra personalization applied."
        )
        summary_lines = [
            f"Generated {len(result.saved_paths)} image(s)",
            f"Output folder: {result.out_dir}",
            "",
            "Applied prompt:",
            result.applied_prompt,
        ]
        if result.contact_sheet:
            summary_lines.extend(["", f"Contact sheet: {result.contact_sheet}"])
        self.image_summary_display.setPlainText("\n".join(summary_lines))

        self.refresh_image_gallery()
        self._focus_generated_image_result(result)

        try:
            if memory_system:
                memory_system.store(
                    f"Generated {len(result.saved_paths)} images from prompt: {result.applied_prompt[:240]}",
                    tags=["image_generation", self.image_style_combo.currentText().strip(), self.image_scene_combo.currentText().strip()],
                    kind="creative",
                    source="image_studio",
                )
        except Exception as e:
            log.debug(f"[IMAGE] memory log failed: {e}")

        try:
            if self._proactive_daemon:
                self._proactive_daemon.suggestion_queue.put((
                    "image_generation",
                    {
                        "suggestion": f"Generated {len(result.saved_paths)} personalised images",
                        "command": result.saved_paths[0] if result.saved_paths else "",
                    },
                ))
        except Exception as e:
            log.debug(f"[IMAGE] proactive queue update failed: {e}")

        try:
            note = (
                f"<b>🖼 Image Studio</b><br>"
                f"Generated {len(result.saved_paths)} image(s). "
                f"Style bias: {settings.get('image_style_profile', 'auto')} · "
                f"Palette bias: {settings.get('image_palette_profile', 'auto')}."
            )
            self.suggestions_display.append(note)
        except Exception:
            pass

    def _image_generation_failed(self, error_text: str):
        self.image_generate_btn.setEnabled(True)
        self.image_generate_btn.setText("Generate Images")
        self.image_summary_display.setPlainText(f"Image generation failed:\n{error_text}")
        self.status_signal.emit("❌ Image generation failed")

    # ---------- Self-Improvement tab (unchanged) ----------
    def _build_self_improve_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        header = QLabel('🔧 Self-Improvement Engine')
        header.setStyleSheet('font-size:18px; font-weight:bold; padding:10px;')
        layout.addWidget(header)
        fail_group = QGroupBox('Failure Analysis')
        fail_layout = QVBoxLayout(fail_group)
        self.failures_display = QTextEdit()
        self.failures_display.setReadOnly(True)
        self.failures_display.setMaximumHeight(200)
        fail_layout.addWidget(self.failures_display)
        analyze_btn = QPushButton('🔍 Analyze Failures')
        analyze_btn.clicked.connect(self._si_analyze_failures)
        fail_layout.addWidget(analyze_btn)
        layout.addWidget(fail_group)
        imp_group = QGroupBox('Improvement Log')
        imp_layout = QVBoxLayout(imp_group)
        self.improvements_display = QTextEdit()
        self.improvements_display.setReadOnly(True)
        imp_layout.addWidget(self.improvements_display)
        run_btn = QPushButton('⚡ Run Improvement Cycle')
        run_btn.clicked.connect(self._si_run_cycle)
        imp_layout.addWidget(run_btn)
        layout.addWidget(imp_group)
        return widget

    def create_self_improve_tab(self):
        widget = self._build_self_improve_panel()
        self.tabs.addTab(widget, '🔧 Self-Improve')

    def _update_failures_display(self, text: str):
        self.failures_display.setPlainText(text)
    def _update_improvements_display(self, text: str):
        self.improvements_display.append(text)
    def _si_analyze_failures(self):
        def worker():
            try:
                from eli.core.paths import memory_db_path
                import sqlite3
                db = str(memory_db_path())
                con = sqlite3.connect(db)
                try:
                    rows = con.execute(
                        "SELECT user_input, error, ts FROM failures ORDER BY ts DESC LIMIT 20"
                    ).fetchall()
                except Exception:
                    rows = []
                con.close()
                if not rows:
                    self.self_improve_failures_signal.emit("No failures recorded yet — keep chatting!")
                    return
                out = [f"[{(ts or '')[:16]}] {str(inp or '')[:70]} → {str(err or '')[:70]}"
                       for inp, err, ts in rows]
                self.self_improve_failures_signal.emit("\n".join(out))
            except Exception as e:
                self.self_improve_failures_signal.emit(f"Error: {e}")
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _si_run_cycle(self):
        def worker():
            try:
                lines = ["=== Self-Improvement Cycle ===\n"]

                # Run the actual improvement engine (analyze failures → store improvements)
                try:
                    from eli.runtime.self_improvement import SelfImprovementEngine
                    from eli.memory import get_agent_memory
                    engine = SelfImprovementEngine(memory=get_agent_memory())
                    result = engine.analyze_and_improve()
                    new_imps = result.get("improvements", [])
                    if new_imps:
                        lines.append(f"[Engine] Generated {len(new_imps)} new improvement records:")
                        for imp in new_imps[:6]:
                            lines.append(f"  • [{imp.get('category','?')}] {imp.get('description','')[:120]}")
                    else:
                        lines.append("[Engine] No new improvement records generated this cycle.")
                except Exception as _eng_err:
                    lines.append(f"[Engine] Could not run SelfImprovementEngine: {_eng_err}")

                # Also read stored improvements from agent DB
                import sqlite3
                from eli.core.paths import agent_db_path
                try:
                    con = sqlite3.connect(str(agent_db_path()))
                    imps = []
                    try:
                        imps = con.execute(
                            "SELECT category, description, status FROM improvements ORDER BY timestamp DESC LIMIT 20"
                        ).fetchall()
                    except Exception:
                        pass
                    fails = []
                    try:
                        fails = con.execute(
                            "SELECT user_input, error, occurrence_count FROM failures ORDER BY timestamp DESC LIMIT 6"
                        ).fetchall()
                    except Exception:
                        pass
                    con.close()
                except Exception as _db_err:
                    imps, fails = [], []
                    lines.append(f"[DB] Could not read agent DB: {_db_err}")

                if imps:
                    lines.append(f"\n=== Stored Improvements ({len(imps)}) ===")
                    for cat, desc, status in imps:
                        lines.append(f"  [{status or 'pending'}] {cat}: {(desc or '')[:120]}")

                if fails:
                    lines.append(f"\n=== Recent Failures ({len(fails)}) ===")
                    for ui, err, cnt in fails:
                        lines.append(f"  (×{cnt}) {(ui or '')[:60]} → {(err or '')[:80]}")

                # AI synthesis: generate concrete action suggestions for top failures
                backend = self._text_backend_ready(notify=False)
                if backend and fails:
                    fail_txt = "\n".join(
                        f"- (×{c}) {str(i or '')[:60]}: {str(e or '')[:60]}"
                        for i, e, c in fails[:4]
                    )
                    prompt = (
                        f"ELI self-improvement analysis. Recent recurring errors:\n{fail_txt}\n\n"
                        f"For each error, suggest ONE specific, actionable fix "
                        f"(file path + what to change or add). Be concrete."
                    )
                    try:
                        with self.__class__._inference_lock:
                            resp = backend.generate(prompt=prompt, max_tokens=400, temperature=0.4)
                        lines.append("\n=== AI Action Plan ===")
                        lines.append(resp.strip())
                    except Exception as _ai_err:
                        lines.append(f"\n[AI] Inference failed: {_ai_err}")

                if not imps and not fails:
                    lines.append("\nNo failures or improvements recorded yet.")
                    lines.append("Generate some interactions with ELI to build improvement data.")

                lines.append("\n--- Cycle complete ---")
                log.debug(f"[PROACTIVE] Self-improvement cycle done: {len(imps)} improvements, {len(fails)} failures")
                self.self_improve_improvements_signal.emit("\n".join(lines))
            except Exception as exc:
                self.self_improve_improvements_signal.emit(f"Error running cycle: {exc}")
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _build_memory_panel(self) -> QWidget:
        memory_widget = QWidget()
        layout = QVBoxLayout(memory_widget)
        stats_group = QGroupBox("Memory Statistics")
        stats_layout = QHBoxLayout(stats_group)
        self.memory_stats_label = QLabel("Loading...")
        stats_layout.addWidget(self.memory_stats_label)
        refresh_stats_btn = QPushButton("Refresh Stats")
        refresh_stats_btn.clicked.connect(self.refresh_memory_stats)
        stats_layout.addWidget(refresh_stats_btn)
        layout.addWidget(stats_group)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        search_group = QGroupBox("Search Memory")
        search_layout = QVBoxLayout(search_group)
        self.memory_search_input = QLineEdit()
        self.memory_search_input.setPlaceholderText("Enter search query...")
        self.memory_search_input.returnPressed.connect(self.search_memory)
        search_layout.addWidget(self.memory_search_input)
        search_btn = QPushButton("🔍 Search")
        search_btn.clicked.connect(self.search_memory)
        search_layout.addWidget(search_btn)
        left_layout.addWidget(search_group)
        store_group = QGroupBox("Store New Memory")
        store_layout = QVBoxLayout(store_group)
        self.memory_store_input = QTextEdit()
        self.memory_store_input.setPlaceholderText("Enter memory to store...")
        self.memory_store_input.setMaximumHeight(100)
        store_layout.addWidget(self.memory_store_input)
        self.memory_tags_input = QLineEdit()
        self.memory_tags_input.setPlaceholderText("Tags (comma-separated, optional)")
        store_layout.addWidget(self.memory_tags_input)
        store_btn = QPushButton("💾 Store Memory")
        store_btn.clicked.connect(self.store_memory)
        store_layout.addWidget(store_btn)
        left_layout.addWidget(store_group)
        left_layout.addStretch()
        splitter.addWidget(left_widget)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        results_label = QLabel("Memory Results")
        results_label.setStyleSheet("font-weight: bold;")
        right_layout.addWidget(results_label)
        self.memory_results_display = QTextEdit()
        self.memory_results_display.setReadOnly(True)
        self.memory_results_display.setPlaceholderText("Search results will appear here...")
        right_layout.addWidget(self.memory_results_display)
        recent_btn = QPushButton("📋 Show Recent Memories")
        recent_btn.clicked.connect(self.show_recent_memories)
        right_layout.addWidget(recent_btn)
        splitter.addWidget(right_widget)
        splitter.setSizes([400, 600])
        layout.addWidget(splitter)
        QTimer.singleShot(500, self.refresh_memory_stats)
        return memory_widget

    def _toggle_proactive_daemon(self):
        daemon = getattr(self, "_proactive_daemon", None)
        if daemon is None:
            return
        if daemon.paused:
            daemon.resume()
            self._proactive_toggle_btn.setText("⏸ Pause Proactive")
            self._proactive_toggle_btn.setStyleSheet(
                "background-color: #2a6030; color: #e8ffe8; border-radius: 4px; padding: 4px 12px;"
            )
            self._proactive_status_label.setText("Proactive: Active")
        else:
            daemon.pause()
            self._proactive_toggle_btn.setText("▶ Resume Proactive")
            self._proactive_toggle_btn.setStyleSheet(
                "background-color: #602020; color: #ffe8e8; border-radius: 4px; padding: 4px 12px;"
            )
            self._proactive_status_label.setText("Proactive: Paused")

    def create_proactive_tab(self):
        proactive_widget = QWidget()
        layout = QVBoxLayout(proactive_widget)

        # Header row with title and pause/resume button
        hdr_row = QHBoxLayout()
        header = QLabel("🎯 Proactive Insights")
        header.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px;")
        hdr_row.addWidget(header)
        hdr_row.addStretch()
        self._proactive_toggle_btn = QPushButton("⏸ Pause Proactive")
        self._proactive_toggle_btn.setStyleSheet(
            "background-color: #2a6030; color: #e8ffe8; border-radius: 4px; padding: 4px 12px;"
        )
        self._proactive_toggle_btn.setToolTip("Pause or resume the background proactive daemon")
        self._proactive_toggle_btn.clicked.connect(self._toggle_proactive_daemon)
        hdr_row.addWidget(self._proactive_toggle_btn)
        layout.addLayout(hdr_row)

        proactive_tabs = QTabWidget()
        suggestions_widget = QWidget()
        suggestions_layout = QVBoxLayout(suggestions_widget)
        self.suggestions_display = QTextEdit()
        self.suggestions_display.setReadOnly(True)
        self.suggestions_display.setPlaceholderText("AI-generated suggestions will appear here...")
        suggestions_layout.addWidget(self.suggestions_display)
        generate_suggestions_btn = QPushButton("🔮 Generate Suggestions")
        generate_suggestions_btn.clicked.connect(self.generate_suggestions)
        suggestions_layout.addWidget(generate_suggestions_btn)
        proactive_tabs.addTab(suggestions_widget, "💡 Suggestions")
        summaries_widget = QWidget()
        summaries_layout = QVBoxLayout(summaries_widget)
        self.summaries_display = QTextEdit()
        self.summaries_display.setReadOnly(True)
        self.summaries_display.setPlaceholderText("Conversation summaries will appear here...")
        summaries_layout.addWidget(self.summaries_display)
        generate_summary_btn = QPushButton("📝 Summarize Conversation")
        generate_summary_btn.clicked.connect(self.generate_summary)
        summaries_layout.addWidget(generate_summary_btn)
        proactive_tabs.addTab(summaries_widget, "📝 Summaries")
        insights_widget = QWidget()
        insights_layout = QVBoxLayout(insights_widget)
        self.insights_display = QTextEdit()
        self.insights_display.setReadOnly(True)
        self.insights_display.setPlaceholderText("Contextual insights will appear here...")
        insights_layout.addWidget(self.insights_display)
        analyze_btn = QPushButton("🔬 Analyze Context")
        analyze_btn.clicked.connect(self.analyze_context)
        insights_layout.addWidget(analyze_btn)
        proactive_tabs.addTab(insights_widget, "🔬 Insights")
        proactive_tabs.addTab(self._build_habits_panel(), "⏰ Habits")
        proactive_tabs.addTab(self._build_self_improve_panel(), "🔧 Self-Improve")
        proactive_tabs.addTab(self._build_memory_panel(), "🧠 Memory")
        layout.addWidget(proactive_tabs)
        self.tabs.addTab(proactive_widget, "🎯 Proactive")

    # ══════════════════════════════════════════════════════════════════════════
    # QUICK ACTIONS TAB
    # ══════════════════════════════════════════════════════════════════════════
    _QA_SAVE_FILE = APP_DIR / "quick_actions.json"

    def create_quick_actions_tab(self):
        widget = QWidget()
        root = QVBoxLayout(widget)
        root.setSpacing(6)
        root.setContentsMargins(8, 8, 8, 8)

        # Header
        hdr = QLabel("⚡ Quick Actions")
        hdr.setStyleSheet("font-size:15px;font-weight:bold;padding:2px 0 4px 0;")
        root.addWidget(hdr)

        sub = QLabel(
            "Drag any capability from the list on the left onto the board — "
            "or double-click to pin it instantly."
        )
        sub.setStyleSheet("font-size:10px;color:#8899aa;padding-bottom:6px;")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # Main splitter: list | board
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # ── LEFT: capability list ─────────────────────────────────────────
        left = QWidget()
        left.setMaximumWidth(240)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        ll.setSpacing(4)

        search_lbl = QLabel("Search capabilities")
        search_lbl.setStyleSheet("font-size:9px;color:#6677aa;")
        ll.addWidget(search_lbl)

        self._qa_search = QLineEdit()
        self._qa_search.setPlaceholderText("🔍 filter…")
        self._qa_search.setStyleSheet(
            "background:#1a1d23;border:1px solid #3b4060;"
            "border-radius:4px;padding:4px 8px;color:#c8d0e0;font-size:11px;"
        )
        self._qa_search.textChanged.connect(self._qa_filter)
        ll.addWidget(self._qa_search)

        # Category filter row — single-press to scope the list to a group.
        cat_row = QHBoxLayout()
        cat_row.setSpacing(2)
        cat_row.setContentsMargins(0, 2, 0, 2)
        self._qa_active_category = "All"
        self._qa_category_buttons: dict[str, QPushButton] = {}
        for label, emoji in (("All", "★"), ("Window", "🪟"), ("Media", "🎵"),
                             ("System", "⚙"), ("Stats", "📊"), ("Tools", "🛠")):
            b = QPushButton(f"{emoji} {label}")
            b.setCheckable(True)
            b.setChecked(label == "All")
            b.setStyleSheet(
                "QPushButton{background:#14171f;color:#8899aa;"
                "border:1px solid #2a2d3a;border-radius:4px;"
                "padding:3px 6px;font-size:9px;}"
                "QPushButton:checked{background:#2e3a5a;color:#88c0d0;"
                "border:1px solid #5a6c8e;}"
                "QPushButton:hover{background:#1e2230;}"
            )
            b.clicked.connect(lambda _checked, n=label: self._qa_set_category(n))
            self._qa_category_buttons[label] = b
            cat_row.addWidget(b)
        cat_row.addStretch(1)
        ll.addLayout(cat_row)

        self._qa_cap_list = _CapabilityList()
        self._qa_cap_list.setDragEnabled(True)
        self._qa_cap_list.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self._qa_cap_list.setStyleSheet(
            "QListWidget{background:#14171f;border:1px solid #2a2d3a;"
            "border-radius:4px;color:#c8d0e0;font-size:10px;}"
            "QListWidget::item{padding:4px 8px;border-bottom:1px solid #1e2230;}"
            "QListWidget::item:hover{background:#1e2230;}"
            "QListWidget::item:selected{background:#2e3a5a;color:#88c0d0;}"
        )
        self._qa_cap_list.itemDoubleClicked.connect(
            lambda it: self._qa_board.add_card(
                it.data(Qt.ItemDataRole.UserRole) or it.text().split()[0]
            ) and self._qa_save_buttons()
        )
        ll.addWidget(self._qa_cap_list, 1)

        # Refresh + count label
        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh List")
        refresh_btn.setStyleSheet(
            "QPushButton{background:#1e2230;color:#88c0d0;border:1px solid #3b4060;"
            "border-radius:4px;padding:4px 8px;font-size:10px;}"
            "QPushButton:hover{background:#2e3a5a;}"
        )
        refresh_btn.clicked.connect(self._qa_refresh_capabilities)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        self._qa_count_lbl = QLabel("")
        self._qa_count_lbl.setStyleSheet("font-size:9px;color:#6677aa;")
        btn_row.addWidget(self._qa_count_lbl)
        ll.addLayout(btn_row)

        splitter.addWidget(left)

        # ── RIGHT: button board ───────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(4, 0, 0, 0)
        rl.setSpacing(6)

        board_hdr = QHBoxLayout()
        board_lbl = QLabel("Button Board  —  drop here")
        board_lbl.setStyleSheet("font-size:10px;color:#8899aa;")
        board_hdr.addWidget(board_lbl)
        board_hdr.addStretch()

        add_all_btn = QPushButton("➕ Pin All Visible")
        add_all_btn.setToolTip("Pin every currently visible (filtered) capability")
        add_all_btn.setStyleSheet(
            "QPushButton{background:#1e2230;color:#a3be8c;border:1px solid #3d6b56;"
            "border-radius:4px;padding:3px 8px;font-size:10px;}"
            "QPushButton:hover{background:#2d4a3e;}"
        )
        add_all_btn.clicked.connect(self._qa_pin_visible)
        board_hdr.addWidget(add_all_btn)

        clear_btn = QPushButton("🗑️ Clear Board")
        clear_btn.setStyleSheet(
            "QPushButton{background:#1e2230;color:#bf616a;border:1px solid #5e3030;"
            "border-radius:4px;padding:3px 8px;font-size:10px;}"
            "QPushButton:hover{background:#3b1f1f;}"
        )
        clear_btn.clicked.connect(self._qa_clear_board)
        board_hdr.addWidget(clear_btn)
        rl.addLayout(board_hdr)

        # Drop-zone hint bar (shown when board is empty)
        self._qa_drop_hint = QLabel(
            "  ⬆  Drag a capability here  —  or double-click one in the list"
        )
        self._qa_drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qa_drop_hint.setStyleSheet(
            "color:#3b4060;font-size:13px;border:2px dashed #2a2d3a;"
            "border-radius:8px;padding:20px;background:#10121a;"
        )
        rl.addWidget(self._qa_drop_hint)

        # Scroll area wrapping the board
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea{background:#10121a;border:2px solid #2a2d3a;border-radius:6px;}"
        )
        self._qa_board = _QABoard(self._qa_run_action)
        self._qa_board.setStyleSheet("background:#10121a;")
        self._qa_board.changed.connect(self._qa_on_board_changed)
        self._qa_board.changed.connect(self._qa_save_buttons)
        scroll.setWidget(self._qa_board)
        rl.addWidget(scroll, 1)

        # Result display
        result_lbl = QLabel("Action Output:")
        result_lbl.setStyleSheet("font-size:9px;color:#6677aa;margin-top:4px;")
        rl.addWidget(result_lbl)

        self._qa_result = QTextEdit()
        self._qa_result.setReadOnly(True)
        self._qa_result.setMaximumHeight(100)
        self._qa_result.setStyleSheet(
            "background:#0d0f14;color:#a3be8c;font-size:10px;"
            "border:1px solid #2a2d3a;border-radius:4px;"
        )
        self._qa_result.setPlaceholderText("Action results appear here…")
        rl.addWidget(self._qa_result)

        splitter.addWidget(right)
        splitter.setSizes([210, 580])
        root.addWidget(splitter, 1)

        self.tabs.addTab(widget, "⚡ Quick Actions")

        # Wire the thread-safe result signal
        self._qa_result_sig.connect(
            self._qa_result.setPlainText, Qt.ConnectionType.QueuedConnection
        )

        # Load capabilities and saved buttons
        self._qa_refresh_capabilities()
        self._qa_load_buttons()

    # ── Quick Actions helpers ─────────────────────────────────────────────────

    # ── Action metadata: which actions need arg prompts and what category ──
    _QA_ACTION_ARGS = {
        "OPEN_APP":       ("App name (e.g. firefox)", "app"),
        "OPEN_URL":       ("URL to open", "url"),
        "OPEN_IN_IDE":    ("File/folder path", "path"),
        "OPEN_FILE_SYSTEM": ("Directory path (leave blank for home)", "path"),
        "SHELL_EXEC":     ("Shell command to run", "command"),
        "RUN_CMD":        ("Command to run", "command"),
        "SPEAK":          ("Text to speak", "text"),
        "VOLUME":         ("Volume level 0-100", "level"),
        "SET_TIMER":      ("Timer duration (e.g. 5 minutes)", "duration"),
        "SET_ALARM":      ("Alarm time (e.g. 08:30)", "time"),
        "PLAY_MEDIA":     ("Track/artist/playlist name", "query"),
        "GET_WEATHER":    ("City name (leave blank for local)", "city"),
        "MEMORY_RECALL":  ("Search query", "query"),
        "MEMORY_STORE":   ("Text to remember", "text"),
        "WEB_SEARCH":     ("Search query", "query"),
        "READ_FILE":      ("File path to read", "path"),
        "WRITE_NOTE":     ("Note content", "text"),
        "SEARCH_NOTES":   ("Search term", "query"),
        "SUMMARIZE_FILE": ("File path to summarize", "path"),
        "ANALYZE_PDF":    ("PDF file path", "path"),
        "ANALYZE_CSV":    ("CSV file path", "path"),
        "OCR_IMAGE":      ("Image file path", "path"),
        "EXECUTE_GOAL":       ("Goal description", "goal"),
        "SEQUENCE":           ("Commands separated by semicolons", "commands"),
        "SET_CLIPBOARD":      ("Text to copy to clipboard", "text"),
        "KEYBOARD":           ("Key sequence (e.g. ctrl+c)", "keys"),
        "MOUSE_CONTROL":      ("Action: click/move/scroll (e.g. 'click 100 200')", "action"),
        "ADD_EVENT":          ("Event (e.g. 'Meeting 2025-06-01 10:00')", "event"),
        "LIST_DIR":           ("Directory path (leave blank for current)", "path"),
        "CREATE_FOLDER":      ("Folder path to create", "path"),
        "GENERATE_DOCUMENT":  ("Document description or topic", "description"),
        "GENERATE_SCRIPT":    ("Script description", "description"),
        "GENERATE_PROJECT":   ("Project description", "description"),
        "NEW_NOTE":           ("Note title", "title"),
        "PLUGIN_INSTALL":     ("Plugin name or URL", "plugin"),
        "PLUGIN_SEARCH":      ("Search term", "query"),
        "PLUGIN_ENABLE":      ("Plugin name", "plugin"),
        "PLUGIN_DISABLE":     ("Plugin name", "plugin"),
        "PLUGIN_UNINSTALL":   ("Plugin name", "plugin"),
        "CONVERT_DOCUMENT":   ("File path to convert", "path"),
        "FIX_FILE":           ("File path to fix", "path"),
        "SCREEN_READ_ANALYZE": ("Area to capture (leave blank for full screen)", "area"),
        "CLOSE_APP":          ("App name to close", "app"),
        "SHOW_DIFF":          ("Two file paths separated by space", "paths"),
    }

    # User-facing 5-group structure for the Quick Actions tab category strip.
    # The category-filter buttons in the Quick Actions UI scope the
    # capability list to exactly these groups.
    _QA_CATEGORIES = {
        "Window":  {"OPEN_APP", "CLOSE_APP", "OPEN_URL", "OPEN_BROWSER",
                    "OPEN_IDE", "OPEN_IN_IDE", "OPEN_FILE_SYSTEM",
                    "OPEN_SYSTEM_SETTINGS", "OPEN_AUDIO_SETTINGS",
                    "OPEN_POWER_SETTINGS", "OPEN_COMMUNICATION_HUB",
                    "OPEN_MEDIA_HUB", "OPEN_NETWORK_BROWSER",
                    "TILE_WINDOWS", "MINIMISE_ALL", "RESTORE_WINDOWS",
                    "MAXIMISE_WINDOW", "NEXT_WINDOW", "PREVIOUS_WINDOW",
                    "SWITCH_WORKSPACE", "FOCUS_APP"},
        "Media":   {"PLAY_MEDIA", "PAUSE_MEDIA", "STOP_MEDIA", "NEXT_MEDIA",
                    "PREVIOUS_MEDIA", "SHUFFLE_MEDIA", "REPEAT_MEDIA",
                    "MEDIA_CONTROL", "VOLUME", "SPEAK", "DICTATE", "TRANSCRIBE"},
        "System":  {"TIME", "DATE", "GET_TIME", "GET_DATE", "GET_WEATHER",
                    "CPU_USAGE", "RAM_USAGE", "SYSTEM_STATS", "HARDWARE_PROFILE",
                    "KEYBOARD", "MOUSE_CONTROL", "SCREENSHOT",
                    "SET_CLIPBOARD", "GET_CLIPBOARD", "SHELL_EXEC", "RUN_CMD",
                    "LIST_DIR", "CREATE_FOLDER", "READ_FILE",
                    "SET_TIMER", "SET_ALARM",
                    "POMODORO_START", "POMODORO_STOP", "POMODORO_STATUS",
                    "ADD_EVENT", "LIST_EVENTS", "SMART_HOME",
                    "PROACTIVE_START", "PROACTIVE_STOP", "CHECK_CHRONAL_ALIGNMENT"},
        "Stats":   {"RUNTIME_STATUS", "REASONING_MODE_STATUS", "MEMORY_STATUS", "COGNITION_STATUS",
                    "AWARENESS_STATUS", "MEMORY_STATS", "MEMORY_RECALL",
                    "MEMORY_STORE", "CLEAR_CHAT_HISTORY",
                    "USER_IDENTITY_SUMMARY", "SELF_REPORT",
                    "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME",
                    "PERSONAL_MEMORY_SUMMARY", "PERSONAL_MEMORY_DEEP_EXPLAIN",
                    "ROUTING_FAULT_EXPLAIN", "NAME_SOURCE_AUDIT",
                    "EXPLAIN_LAST_RESPONSE", "RUNTIME_AUDIT", "IMPORT_AUDIT",
                    "RESOLVE_RUNTIME_PATHS", "GUI_RUNTIME_AUDIT",
                    "MORNING_REPORT", "PROACTIVE_STATUS", "HABIT_STATUS",
                    "PERSONA_LOCK_STATUS", "PERSONA_LOCK_SET",
                    "PERSONA_LOCK_CLEAR", "LIST_CAPABILITIES", "CODE_CHANGES"},
        "Tools":   {"SCREEN_READ_ANALYZE", "SCREEN_LOCATE", "OCR_IMAGE",
                    "WEB_SEARCH", "NEWS_FETCH",
                    "ANALYZE_PDF", "ANALYZE_CSV", "ANALYZE_PDF_FOLDER",
                    "SUMMARIZE_FILE", "WRITE_NOTE", "NEW_NOTE",
                    "LIST_NOTES", "SEARCH_NOTES", "CONVERT_DOCUMENT",
                    "EXECUTE_GOAL", "SEQUENCE",
                    "SELF_ANALYZE", "SELF_IMPROVE", "SELF_PATCH",
                    "SELF_TEST", "SELF_UPGRADE",
                    "GENERATE_DOCUMENT", "GENERATE_SCRIPT",
                    "GENERATE_PROJECT", "CREATE_DOCUMENT",
                    "FIX_FILE", "SHOW_DIFF", "DATA_FABRICATOR",
                    "PLUGIN_LIST", "PLUGIN_INSTALL", "PLUGIN_UNINSTALL",
                    "PLUGIN_ENABLE", "PLUGIN_DISABLE", "PLUGIN_SEARCH",
                    "REFRESH_USER_INFO", "HELP"},
    }

    def _qa_set_category(self, name: str):
        """User clicked a category button. Update active selection and
        re-filter the capability list."""
        self._qa_active_category = name
        for label, btn in getattr(self, "_qa_category_buttons", {}).items():
            try:
                btn.setChecked(label == name)
            except Exception:
                pass
        # Re-run the existing filter (which now considers the active category).
        try:
            self._qa_filter(self._qa_search.text())
        except Exception:
            pass

    def _qa_category_for(self, action: str) -> str:
        for cat, members in self._QA_CATEGORIES.items():
            if action in members:
                return cat
        return "Other"

    def _qa_refresh_capabilities(self):
        """
        Load all executor-backed actions.  Only include actions that have a real
        handler in executor_enhanced (SOURCE = 'executor' or 'executor+router').
        Router-only entries are excluded — they have no handler and will fail.
        """
        caps = set()

        # 1. Canonical SUPPORTED_ACTIONS list from executor (primary source of truth)
        try:
            from eli.execution.executor_enhanced import SUPPORTED_ACTIONS
            caps.update(a.upper() for a in SUPPORTED_ACTIONS)
        except Exception:
            pass

        # 2. CapabilitySync — only keep executor-backed entries
        try:
            from eli.runtime.capability_sync import CapabilitySync
            sync = CapabilitySync()
            discovered = sync.discover()
            for action, meta in discovered.items():
                if meta.get("source", "").startswith("executor"):
                    caps.add(action.upper())
        except Exception:
            pass

        if not caps:
            # Hard fallback — always-available no-arg actions
            caps = {"SCREENSHOT", "TIME", "DATE", "SYSTEM_STATS", "CPU_USAGE",
                    "RAM_USAGE", "MEMORY_STATS", "SELF_ANALYZE", "AWARENESS_STATUS",
                    "MORNING_REPORT", "NEWS_FETCH", "HABIT_STATUS", "PROACTIVE_STATUS"}

        self._qa_all_caps = sorted(caps)
        self._qa_render_list(self._qa_all_caps)
        self._qa_count_lbl.setText(f"{len(self._qa_all_caps)} capabilities")

    def _qa_render_list(self, caps: list):
        self._qa_cap_list.clear()
        for name in caps:
            cat = self._qa_category_for(name)
            arg_info = self._QA_ACTION_ARGS.get(name)
            display = f"[{cat}]  {name}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, name)
            tooltip = f"Category: {cat}\nAction: {name}"
            if arg_info:
                tooltip += f"\nRequires: {arg_info[0]}"
            else:
                tooltip += "\nNo arguments required"
            tooltip += "\n\nDrag or double-click to pin"
            item.setToolTip(tooltip)
            self._qa_cap_list.addItem(item)

    def _qa_filter(self, text: str):
        txt = text.strip().upper()
        cat = getattr(self, "_qa_active_category", "All")
        members = (
            None if cat == "All"
            else self._QA_CATEGORIES.get(cat, set())
        )
        caps = self._qa_all_caps
        if members is not None:
            caps = [c for c in caps if c in members]
        if txt:
            caps = [c for c in caps if txt in c]
        self._qa_render_list(caps)

    def _qa_pin_visible(self):
        for i in range(self._qa_cap_list.count()):
            it = self._qa_cap_list.item(i)
            # UserRole always holds the raw action name; text now has "[Cat]  NAME"
            name = it.data(Qt.ItemDataRole.UserRole)
            if not name:
                # fallback: strip "[Category]  " prefix if present
                raw = it.text()
                name = raw.split("]")[-1].strip() if "]" in raw else raw.split()[0]
            self._qa_board.add_card(name)
        self._qa_save_buttons()

    def _qa_clear_board(self):
        self._qa_board.clear_all()
        self._qa_save_buttons()

    def _qa_on_board_changed(self):
        has_cards = bool(self._qa_board.action_names())
        self._qa_drop_hint.setVisible(not has_cards)

    def _qa_run_action(self, action_name: str, args: dict):
        """Execute action in worker thread and show result via signal.

        If the action requires an argument and none were supplied (e.g. the
        card was clicked directly), prompt the user with an input dialog
        before dispatching.
        """
        # ── Arg prompting ────────────────────────────────────────────────────
        if not args and action_name in self._QA_ACTION_ARGS:
            prompt_text, arg_key = self._QA_ACTION_ARGS[action_name]
            value, ok = QInputDialog.getText(
                self, action_name.replace("_", " ").title(), prompt_text
            )
            if not ok or not value.strip():
                return
            args = {arg_key: value.strip()}

        self._qa_result.setPlainText(f"⏳ Running {action_name}…")

        def worker():
            try:
                import concurrent.futures
                from eli.execution.executor_enhanced import execute
                # Run with a 60-second timeout to prevent infinite hangs
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(execute, action_name, args)
                    try:
                        result = fut.result(timeout=60)
                    except concurrent.futures.TimeoutError:
                        self._qa_result_sig.emit(f"⏱ {action_name}: timed out after 60s")
                        return
                text = result.get("response") or result.get("content") or str(result)
                ok = result.get("ok", True)
                prefix = "✅" if ok else "❌"
                out = f"{prefix} {action_name}\n{str(text)[:1200]}"
            except Exception as exc:
                out = f"❌ {action_name}: {exc}"
            self._qa_result_sig.emit(out)

        threading.Thread(target=worker, daemon=True).start()

    def _qa_save_buttons(self):
        """Persist pinned actions to quick_actions.json."""
        try:
            import json as _j
            self.__class__._QA_SAVE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.__class__._QA_SAVE_FILE.write_text(
                _j.dumps(self._qa_board.action_names(), indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _qa_load_buttons(self):
        """Restore previously pinned actions."""
        try:
            import json as _j
            f = self.__class__._QA_SAVE_FILE
            if f.exists():
                for name in _j.loads(f.read_text(encoding="utf-8")):
                    self._qa_board.add_card(str(name))
        except Exception:
            pass
        self._qa_on_board_changed()

    # ══════════════════════════════════════════════════════════════════════════
    # SCREEN CONTROL / OCR TAB
    # ══════════════════════════════════════════════════════════════════════════
    def create_screen_control_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        header = QLabel("🖥️  Screen Control & OCR")
        header.setStyleSheet("font-size:16px; font-weight:bold; padding:8px 4px 4px 4px;")
        layout.addWidget(header)

        sub = QLabel("Capture the screen, run OCR to extract text, then ask ELI to analyse it.")
        sub.setStyleSheet("font-size:11px; color:#8899aa; padding-bottom:6px;")
        layout.addWidget(sub)

        # ── Screenshot + OCR row ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._sc_capture_btn = QPushButton("📸 Capture Full Screen")
        self._sc_capture_btn.clicked.connect(self._sc_capture)
        btn_row.addWidget(self._sc_capture_btn)

        self._sc_ocr_btn = QPushButton("🔍 Run OCR")
        self._sc_ocr_btn.setEnabled(False)
        self._sc_ocr_btn.clicked.connect(self._sc_run_ocr)
        btn_row.addWidget(self._sc_ocr_btn)

        self._sc_analyse_btn = QPushButton("🤖 Ask ELI")
        self._sc_analyse_btn.setEnabled(False)
        self._sc_analyse_btn.clicked.connect(self._sc_ask_eli)
        btn_row.addWidget(self._sc_analyse_btn)

        self._sc_clear_btn = QPushButton("🗑️ Clear")
        self._sc_clear_btn.clicked.connect(self._sc_clear)
        btn_row.addWidget(self._sc_clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Screenshot preview ────────────────────────────────────────────
        preview_label = QLabel("Screenshot Preview:")
        preview_label.setStyleSheet("font-size:10px; color:#8899aa; margin-top:4px;")
        layout.addWidget(preview_label)

        self._sc_preview = QLabel()
        self._sc_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sc_preview.setStyleSheet("background:#12141a; border:1px solid #2a2d3a; border-radius:4px;")
        self._sc_preview.setMinimumHeight(160)
        self._sc_preview.setText("(no screenshot yet)")
        layout.addWidget(self._sc_preview)

        # ── OCR output ────────────────────────────────────────────────────
        ocr_label = QLabel("Extracted Text (OCR):")
        ocr_label.setStyleSheet("font-size:10px; color:#8899aa; margin-top:6px;")
        layout.addWidget(ocr_label)

        self._sc_ocr_text = QTextEdit()
        self._sc_ocr_text.setReadOnly(False)
        self._sc_ocr_text.setPlaceholderText("OCR text will appear here — you can also type or paste text to analyse.")
        self._sc_ocr_text.setStyleSheet("background:#1a1d23; color:#c8d0e0; font-size:11px; border-radius:4px;")
        self._sc_ocr_text.setMaximumHeight(140)
        layout.addWidget(self._sc_ocr_text)

        # ── ELI response ──────────────────────────────────────────────────
        resp_label = QLabel("ELI Analysis:")
        resp_label.setStyleSheet("font-size:10px; color:#8899aa; margin-top:6px;")
        layout.addWidget(resp_label)

        self._sc_response = QTextEdit()
        self._sc_response.setReadOnly(True)
        self._sc_response.setPlaceholderText("ELI's analysis of the screen content will appear here.")
        self._sc_response.setStyleSheet("background:#1a1d23; color:#c8d0e0; font-size:11px; border-radius:4px;")
        layout.addWidget(self._sc_response)

        self._sc_screenshot_path: str = ""

        self.tabs.addTab(widget, "🖥️ Screen")

    # ── Screen control helpers ─────────────────────────────────────────────────
    def _sc_capture(self):
        """Take a screenshot in a worker thread, show preview on main thread."""
        self._sc_capture_btn.setEnabled(False)
        self._sc_capture_btn.setText("Capturing…")

        def worker():
            try:
                import tempfile, time as _t
                # Use NamedTemporaryFile to atomically claim the path (avoids mktemp TOCTOU race).
                with tempfile.NamedTemporaryFile(prefix="eli_sc_", suffix=".png", delete=False) as _tf:
                    out = _tf.name
                try:
                    from eli.perception.os_controller import take_screenshot

                    captured = take_screenshot("full")
                    cap_path = str(captured.get("path") or "")
                    if captured.get("ok") and cap_path:
                        self._sc_screenshot_path = cap_path
                        self._sc_capture_sig.emit(cap_path)
                        return
                except Exception:
                    pass
                # Try mss (fast), fall back to scrot/gnome-screenshot
                try:
                    import mss, mss.tools
                    with mss.mss() as sct:
                        mon = sct.monitors[0]
                        img = sct.grab(mon)
                        mss.tools.to_png(img.rgb, img.size, output=out)
                except Exception:
                    import subprocess
                    for cmd in [["scrot", out], ["gnome-screenshot", "-f", out],
                                ["import", "-window", "root", out]]:
                        try:
                            subprocess.run(cmd, timeout=10, check=True,
                                           capture_output=True)
                            break
                        except Exception:
                            continue
                import os
                if os.path.exists(out):
                    self._sc_screenshot_path = out
                    self._sc_capture_sig.emit(out)
                else:
                    self._sc_capture_sig.emit("")
            except Exception as exc:
                self._sc_capture_sig.emit(f"ERROR:{exc}")

        # Connect once
        try:
            self._sc_capture_sig.disconnect()
        except Exception:
            pass
        self._sc_capture_sig.connect(self._sc_on_capture, Qt.ConnectionType.QueuedConnection)
        threading.Thread(target=worker, daemon=True).start()

    def _sc_on_capture(self, path: str):
        self._sc_capture_btn.setEnabled(True)
        self._sc_capture_btn.setText("📸 Capture Full Screen")
        if not path or path.startswith("ERROR:"):
            self._sc_preview.setText(f"❌ Capture failed: {path}")
            return
        pix = QPixmap(path)
        if not pix.isNull():
            scaled = pix.scaled(self._sc_preview.width() or 640,
                                 160,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            self._sc_preview.setPixmap(scaled)
        else:
            self._sc_preview.setText(f"Screenshot saved: {path}")
        self._sc_ocr_btn.setEnabled(True)

    def _sc_run_ocr(self):
        if not self._sc_screenshot_path:
            self._sc_ocr_text.setPlainText("No screenshot captured yet.")
            return
        self._sc_ocr_btn.setEnabled(False)
        self._sc_ocr_btn.setText("Running OCR…")
        path = self._sc_screenshot_path

        def worker():
            import subprocess, shutil, tempfile, os
            text = ""

            # ── 1. tesseract CLI — fast, no Python binding needed ──────────
            tess = shutil.which("tesseract")
            if tess:
                try:
                    r = subprocess.run(
                        [tess, path, "stdout", "--psm", "11", "-l", "eng"],
                        capture_output=True, text=True, timeout=25,
                    )
                    text = r.stdout.strip()
                except subprocess.TimeoutExpired:
                    text = "(tesseract timed out)"
                except Exception:
                    pass

            # ── 2. pytesseract binding (also calls tesseract binary) ────────
            if not text:
                try:
                    import pytesseract
                    from PIL import Image
                    img = Image.open(path)
                    # Downscale for speed if > 2 MP
                    w, h = img.size
                    if w * h > 2_000_000:
                        scale = (2_000_000 / (w * h)) ** 0.5
                        img = img.resize((int(w * scale), int(h * scale)))
                    text = pytesseract.image_to_string(img, config="--psm 11").strip()
                except Exception:
                    pass

            # ── 3. Not installed ────────────────────────────────────────────
            if not text:
                text = (
                    "⚠️  No OCR engine found.\n\n"
                    "Install tesseract (fast, free, offline):\n"
                    "  Ubuntu/Debian:  sudo apt install tesseract-ocr\n"
                    "  macOS:          brew install tesseract\n"
                    "  Windows:        choco install tesseract\n\n"
                    "Then restart ELI and try again."
                )

            QTimer.singleShot(0, lambda: self._sc_ocr_done(text))

        threading.Thread(target=worker, daemon=True).start()

    def _sc_ocr_done(self, text: str):
        self._sc_ocr_btn.setEnabled(True)
        self._sc_ocr_btn.setText("🔍 Run OCR")
        self._sc_ocr_text.setPlainText(text.strip() or "(no text detected)")
        self._sc_analyse_btn.setEnabled(bool(text.strip()))

    def _sc_ask_eli(self):
        backend = self._text_backend_ready(notify=False)
        if backend is None:
            self._sc_response.setPlainText("⚠️ Load a model first.")
            return
        ocr_text = self._sc_ocr_text.toPlainText().strip()
        if not ocr_text:
            self._sc_response.setPlainText("⚠️ No OCR text to analyse. Run OCR first or paste text.")
            return
        self._sc_analyse_btn.setEnabled(False)
        self._sc_analyse_btn.setText("Analysing…")
        self._sc_response.setPlainText("🤖 ELI is analysing the screen content…")

        def worker():
            try:
                prompt = (
                    "You are ELI, a helpful AI assistant. The following text was extracted from "
                    "a screenshot of the user's screen via OCR. Analyse it and provide a helpful "
                    "summary, identify any important information, errors, or actions the user "
                    "might need to take.\n\n"
                    f"SCREEN TEXT:\n{ocr_text[:3000]}\n\n"
                    "Analysis:"
                )
                with self.__class__._inference_lock:
                    resp = backend.generate(prompt=prompt, max_tokens=512, temperature=0.6)
                QTimer.singleShot(0, lambda: self._sc_eli_done(resp))
            except Exception as exc:
                QTimer.singleShot(0, lambda: self._sc_eli_done(f"❌ Error: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _sc_eli_done(self, text: str):
        self._sc_analyse_btn.setEnabled(True)
        self._sc_analyse_btn.setText("🤖 Ask ELI")
        self._sc_response.setPlainText(text)

    def _sc_clear(self):
        self._sc_preview.setText("(no screenshot yet)")
        self._sc_ocr_text.clear()
        self._sc_response.clear()
        self._sc_screenshot_path = ""
        self._sc_ocr_btn.setEnabled(False)
        self._sc_analyse_btn.setEnabled(False)

    def create_ide_tab(self):
        ide_widget = QWidget()
        layout = QVBoxLayout(ide_widget)
        header = QLabel("⌨️  Integrated Development Environment")
        header.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px;")
        layout.addWidget(header)
        toolbar = QHBoxLayout()
        self.current_file_label = QLabel("No file open")
        toolbar.addWidget(self.current_file_label)
        toolbar.addStretch()
        new_file_btn = QPushButton("📄 New")
        new_file_btn.clicked.connect(self.ide_new_file)
        toolbar.addWidget(new_file_btn)
        open_file_btn = QPushButton("📂 Open")
        open_file_btn.clicked.connect(self.ide_open_file)
        toolbar.addWidget(open_file_btn)
        save_file_btn = QPushButton("💾 Save")
        save_file_btn.clicked.connect(self.ide_save_file)
        toolbar.addWidget(save_file_btn)
        save_as_btn = QPushButton("💾 Save As")
        save_as_btn.clicked.connect(self.ide_save_as)
        toolbar.addWidget(save_as_btn)
        run_btn = QPushButton("▶️ Run")
        run_btn.clicked.connect(self.ide_run_code)
        toolbar.addWidget(run_btn)
        layout.addLayout(toolbar)
        if QSCI_AVAILABLE:
            self.code_editor = QsciScintilla()
            self.code_editor.setLexer(QsciLexerPython(self.code_editor))
            self.code_editor.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
            self.code_editor.setMarginWidth(0, "00000")
            self.code_editor.setTabWidth(4)
            self.code_editor.setIndentationsUseTabs(False)
            self.code_editor.setAutoIndent(True)
        else:
            self.code_editor = QTextEdit()
            font = QFont("Courier New", 10)
            self.code_editor.setFont(font)
        layout.addWidget(self.code_editor, stretch=7)
        console_group = QGroupBox("Console Output")
        console_layout = QVBoxLayout(console_group)
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setMaximumHeight(200)
        console_layout.addWidget(self.console_output)
        clear_console_btn = QPushButton("Clear Console")
        clear_console_btn.clicked.connect(lambda: self.console_output.clear())
        console_layout.addWidget(clear_console_btn)
        layout.addWidget(console_group, stretch=3)
        self._ide_widget = ide_widget
        self.tabs.addTab(ide_widget, "⌨️  IDE")
        self.current_file_path = None

    def _engine_ask(self, prompt: str, max_tokens: int = 512) -> str:
        """Synchronous ELI inference adapter for Labs generation."""
        prompt = str(prompt or "").strip()
        if not prompt:
            return ""

        def _normalise_engine_text(result):
            if isinstance(result, dict):
                response = result.get("response")
                if response is not None and str(response).strip():
                    return str(response).strip()
                for key in ("content", "text", "answer", "message", "output"):
                    value = result.get(key)
                    if value is not None and str(value).strip():
                        return str(value).strip()
                return str(result).strip()
            if result is not None and str(result).strip():
                return str(result).strip()
            return ""

        try:
            from eli.kernel.engine import get_engine
            engine = get_engine()
            if engine is not None and hasattr(engine, "process"):
                result = engine.process(prompt, stream=False, reasoning_mode="quick")
                text = _normalise_engine_text(result)
                if text:
                    return text
        except Exception:
            pass

        backend = getattr(self, "active_backend", None)
        try:
            if backend is not None and hasattr(backend, "chat"):
                result = backend.chat(prompt, max_tokens=max_tokens)
                text = _normalise_engine_text(result)
                if text:
                    return text
        except Exception:
            pass

        try:
            from eli.cognition import gguf_inference
            result = gguf_inference.generate(prompt, max_tokens=max_tokens)
            text = _normalise_engine_text(result)
            if text:
                return text
        except Exception:
            pass

        return ""


    def create_eli_world_tab(self):
        """Create Eli's World tab: local embodied autonomy/world-state HMI."""
        try:
            from eli.gui.tabs.eli_world_tab import EliWorldTab
            self._eli_world_widget = EliWorldTab(parent=self)
            self.tabs.addTab(self._eli_world_widget, "🌍 Eli's World")
            log.debug("[EliWorld] tab loaded")
        except Exception as _eli_world_err:
            log.debug(f"[EliWorld] failed to load: {_eli_world_err}")
            try:
                fallback = QWidget()
                QVBoxLayout(fallback).addWidget(QLabel(f"Eli's World unavailable: {_eli_world_err}"))
                self.tabs.addTab(fallback, "🌍 Eli's World")
            except Exception as _fallback_err:
                log.debug(f"[EliWorld] fallback tab failed: {_fallback_err}")

    def create_labs_tab(self):
        try:
            from eli.gui.labs_tab import LabsTab
            self._labs_widget = LabsTab(parent_window=self)
            self.tabs.addTab(self._labs_widget, "⚗️  Labs")
        except Exception as _labs_err:
            log.debug(f"[Labs] failed to load: {_labs_err}")
            fallback = QWidget()
            QVBoxLayout(fallback).addWidget(QLabel(f"Labs tab unavailable: {_labs_err}"))
            self.tabs.addTab(fallback, "⚗️  Labs")

    def create_experimental_tab(self):
        """Create safe experimental prototype inventory tab."""
        try:
            from eli.gui.tabs.experimental_tab import ExperimentalTab
            self._experimental_widget = ExperimentalTab(parent=self)
            self.tabs.addTab(self._experimental_widget, "🧪 Experimental")
            log.debug("[Experimental] tab loaded")
        except Exception as _experimental_err:
            log.debug(f"[Experimental] failed to load: {_experimental_err}")
            try:
                fallback = QWidget()
                QVBoxLayout(fallback).addWidget(QLabel(f"Experimental tab unavailable: {_experimental_err}"))
                self.tabs.addTab(fallback, "🧪 Experimental")
            except Exception as _fallback_err:
                log.debug(f"[Experimental] fallback tab failed: {_fallback_err}")

    def create_files_tab(self):
        files_widget = QWidget()
        layout = QVBoxLayout(files_widget)
        header = QLabel("📁 File Browser")
        header.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px;")
        layout.addWidget(header)
        toolbar = QHBoxLayout()
        home_btn = QPushButton("🏠 Home")
        home_btn.clicked.connect(lambda: self.browse_directory(str(Path.home())))
        toolbar.addWidget(home_btn)
        project_btn = QPushButton("📦 Project Root")
        project_btn.clicked.connect(self.browse_project_root)
        toolbar.addWidget(project_btn)
        toolbar.addStretch()
        self.path_label = QLabel("Current: ~")
        toolbar.addWidget(self.path_label)
        layout.addLayout(toolbar)
        self.file_tree = QTreeView()
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath("")
        self.file_tree.setModel(self.file_model)
        self.file_tree.setRootIndex(self.file_model.index(str(Path.home())))
        self.file_tree.doubleClicked.connect(self.on_file_double_click)
        for i in range(1, 4):
            self.file_tree.hideColumn(i)
        layout.addWidget(self.file_tree)
        self.tabs.addTab(files_widget, "📁 Files")

    # ══════════════════════════════════════════════════════════════════════════
    # AGENT CREATOR WIZARD
    # ══════════════════════════════════════════════════════════════════════════

    _WIZARD_QUESTIONS = [
        (
            "**Question 1/3 — Name & Purpose**\n\n"
            "What should this agent be called, and what is its main job?\n"
            "*(e.g. WeatherAgent — checks current weather and clothing advice)*"
        ),
        (
            "**Question 2/3 — Trigger & Data**\n\n"
            "What keywords or user requests should activate this agent, "
            "and what data sources or APIs will it use?\n"
            "*(e.g. keywords: weather, rain, temperature; data: OpenWeatherMap or local sensor)*"
        ),
        (
            "**Question 3/3 — Persona & Output**\n\n"
            "How should this agent present its findings? "
            "Describe its tone, output format, and any special behaviour.\n"
            "*(e.g. brief bullet-point summary, friendly tone, always include emojis)*"
        ),
    ]

    def open_agent_wizard(self):
        """Switch to Chat tab and start the 3-question agent-creation wizard."""
        self.tabs.setCurrentIndex(0)  # Chat tab

        self._agent_wizard_state = {
            "step": 0,
            "answers": [],
        }

        intro = (
            "🤖 **Agent Creator Wizard**\n\n"
            "I'll ask you 3 quick questions, then generate a custom ELI agent "
            "from your answers and register it immediately.\n\n"
            "Type 'cancel' at any time to exit the wizard.\n\n"
            + self._WIZARD_QUESTIONS[0]
        )
        self._wizard_display_message(intro)

    def _wizard_display_message(self, text: str):
        """Append a wizard ELI message to the chat display (must run on main thread)."""
        ts = now_hms()
        # Convert markdown bold to HTML bold
        html = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
        html = html.replace("\n", "<br>")
        self.chat_display.append(
            f'<br><b><span style="color:#88c0d0;">🤖 ELI Wizard [{ts}]:</span></b>'
            f'<br><span style="color:#d8dee9;">{html}</span><br>'
        )
        self.chat_display.ensureCursorVisible()

    def _handle_wizard_input(self, user_text: str):
        """Process one wizard answer; advance to next question or generate the agent."""
        if user_text.strip().lower() in ("cancel", "exit", "stop", "quit"):
            self._agent_wizard_state = None
            self._wizard_display_message("Wizard cancelled. Back to normal chat mode.")
            return

        state = self._agent_wizard_state
        state["answers"].append(user_text)
        step = state["step"]
        state["step"] += 1

        if state["step"] < len(self._WIZARD_QUESTIONS):
            # Ask next question
            self.wizard_say_signal.emit(self._WIZARD_QUESTIONS[state["step"]])
        else:
            # All 3 answers collected — generate the agent
            self._agent_wizard_state = None
            self._wizard_display_message(
                "✅ Got all 3 answers! Generating your custom agent…"
            )
            answers = state["answers"]
            threading.Thread(
                target=self._generate_agent_from_answers,
                args=(answers,),
                daemon=True,
            ).start()

    def _agent_wizard_preview_signal_connect(self):
        """Lazy-create the wizard preview signal/slot (main-thread dialog)."""
        if getattr(self, "_wizard_preview_sig", None) is not None:
            return
        from eli.gui.qt_compat import pyqtSignal as _SigT  # type: ignore
        # Signal must be defined on the class, not the instance, but we
        # already create it via wizard_say_signal pattern. Use a Qt thread
        # marshalling pathway instead — schedule via QTimer on the main loop.

    def _show_agent_preview_dialog(self, class_base: str, agent_name: str,
                                    agent_code: str, agent_file: Path) -> bool:
        """Show the generated agent code in a confirm/cancel preview dialog.
        Must run on the GUI thread. Returns True if the user accepts."""
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Agent Preview — {class_base}")
        dlg.resize(900, 640)
        v = QVBoxLayout(dlg)

        info = QLabel(
            f"<b>Class:</b> {class_base} &nbsp;&nbsp; "
            f"<b>name:</b> {agent_name} &nbsp;&nbsp; "
            f"<b>file:</b> <code>{agent_file}</code><br>"
            "Review the generated agent below. Edit the body if you want to "
            "adjust behaviour before it is written and registered with the bus."
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding:6px; color:#c8d0e0;")
        v.addWidget(info)

        editor = QPlainTextEdit()
        editor.setFont(QFont("Courier New", 10))
        editor.setPlainText(agent_code)
        v.addWidget(editor, stretch=1)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel (don't write)")
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch(1)
        write_btn = QPushButton("✅ Write & Register")
        write_btn.setStyleSheet("background:#3d6b56;color:white;font-weight:bold;padding:6px 14px;")
        write_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(write_btn)
        v.addLayout(btn_row)

        accepted = (dlg.exec() == QDialog.DialogCode.Accepted)
        if accepted:
            # Use the (possibly edited) source from the dialog's editor.
            self._wizard_pending_code = editor.toPlainText()
        else:
            self._wizard_pending_code = None
        return accepted

    def _generate_agent_from_answers(self, answers: List[str]):
        """Parse wizard answers, generate code, show preview, then write."""
        try:
            name_purpose = answers[0]
            triggers_data = answers[1]
            persona_output = answers[2]

            # Derive a class name (PascalCase, preserve existing caps)
            raw_name = name_purpose.split("—")[0].split("-")[0].strip()
            words = [w for w in re.sub(r"[^a-zA-Z0-9 ]", "", raw_name).split() if w]
            if words:
                # If a word is already CamelCase keep it; otherwise title-case it
                def _pascal(w: str) -> str:
                    return w[0].upper() + w[1:] if w else ""
                class_base = "".join(_pascal(w) for w in words[:3])
                if not class_base.lower().endswith("agent"):
                    class_base += "Agent"
            else:
                class_base = "CustomAgent"

            # snake_case agent name: "WeatherAgent" → "weather_agent"
            agent_name = re.sub(r"(?<!^)(?=[A-Z])", "_", class_base).lower()
            agent_name = re.sub(r"_+", "_", agent_name).strip("_")

            # Build the agent file content
            agent_code = self._build_agent_code(
                class_name=class_base,
                agent_name=agent_name,
                name_purpose=name_purpose,
                triggers_data=triggers_data,
                persona_output=persona_output,
            )

            # Resolve target file path before showing preview.
            agents_custom_dir = Path(__file__).resolve().parents[1] / "brain" / "agents" / "custom"
            agents_custom_dir.mkdir(parents=True, exist_ok=True)
            (agents_custom_dir / "__init__.py").touch(exist_ok=True)
            agent_file = agents_custom_dir / f"{agent_name}.py"

            # Marshal the preview dialog onto the main thread; block until
            # the user decides. Use a one-shot QMetaObject invocation.
            self._wizard_pending_code = None
            self._wizard_preview_decided = threading.Event()

            def _show_on_main():
                try:
                    accepted = self._show_agent_preview_dialog(
                        class_base, agent_name, agent_code, agent_file
                    )
                    if not accepted:
                        self.wizard_say_signal.emit(
                            "🚫 Agent generation cancelled. Nothing was written."
                        )
                except Exception as _e:
                    self.wizard_say_signal.emit(f"❌ Preview dialog failed: {_e}")
                finally:
                    self._wizard_preview_decided.set()

            QTimer.singleShot(0, _show_on_main)
            # Wait up to 5 minutes for the user to confirm/cancel.
            self._wizard_preview_decided.wait(timeout=300)
            final_code = self._wizard_pending_code
            if not final_code:
                return  # user cancelled

            agent_file.write_text(final_code, encoding="utf-8")

            # Register in the live agent bus
            registered = self._register_agent_live(class_base, agent_file)

            # Save a record to memory
            try:
                if self._central_memory:
                    self._central_memory.store_memory(
                        text=(
                            f"Custom agent created: {class_base} ({agent_name})\n"
                            f"Purpose: {name_purpose}\n"
                            f"Triggers: {triggers_data}\n"
                            f"Persona: {persona_output}"
                        ),
                        tags=["agent", "custom", agent_name],
                        kind="agent_creation",
                        source="wizard",
                    )
            except Exception:
                pass

            msg = (
                f"🎉 **Agent `{class_base}` created!**\n\n"
                f"File: `{agent_file}`\n"
                f"{'✅ Registered live in agent bus.' if registered else '⚠️ File saved — restart ELI to activate.'}\n\n"
                f"To make it permanent, it will auto-load on next startup."
            )
            self.wizard_say_signal.emit(msg)

        except Exception as e:
            self.wizard_say_signal.emit(f"❌ Agent generation failed: {e}")

    def _build_agent_code(
        self,
        class_name: str,
        agent_name: str,
        name_purpose: str,
        triggers_data: str,
        persona_output: str,
    ) -> str:
        """Return the Python source for a new custom agent."""
        escaped_purpose = name_purpose.replace('"', '\\"')
        escaped_triggers = triggers_data.replace('"', '\\"')
        escaped_persona = persona_output.replace('"', '\\"')

        return f'''"""
Custom ELI Agent: {class_name}
Generated by Agent Creator Wizard.

Purpose  : {name_purpose}
Triggers : {triggers_data}
Persona  : {persona_output}
"""
from __future__ import annotations

from typing import Any, Dict
from eli.cognition.agent_bus import _BaseAgent, AgentResult
from eli.runtime.output_sanitizer import sanitize_visible_output



from eli.utils.log import get_logger
log = get_logger(__name__)

class {class_name}(_BaseAgent):
    name = "{agent_name}"
    timeout_s = 5.0

    # Configuration derived from wizard answers
    _purpose = "{escaped_purpose}"
    _triggers_info = "{escaped_triggers}"
    _persona = "{escaped_persona}"

    def run(
        self,
        user_input: str,
        intent: Dict[str, Any],
        session_id: str,
        user_id: str,
    ) -> AgentResult:
        """Run the custom agent logic."""
        try:
            # Keyword-based trigger check
            low = user_input.lower()
            trigger_words = [
                w.strip().lower()
                for w in self._triggers_info.replace(",", " ").split()
                if len(w.strip()) > 2
            ]
            if trigger_words and not any(tw in low for tw in trigger_words[:8]):
                return AgentResult(
                    agent=self.name,
                    ok=True,
                    confidence=0.0,
                    data={{"skipped": True, "reason": "no trigger match"}},
                )

            # Build a context block for the LLM
            context = (
                f"Agent: {{self.name}}\\n"
                f"Purpose: {{self._purpose}}\\n"
                f"Persona/output style: {{self._persona}}\\n"
                f"User query: {{user_input}}"
            )
            return AgentResult(
                agent=self.name,
                ok=True,
                confidence=0.65,
                data={{
                    "memory_context": context,
                    "agent_note": f"Custom agent {{self.name}} matched query.",
                }},
            )
        except Exception as exc:
            return AgentResult(
                agent=self.name, ok=False, confidence=0.0,
                data={{"error": str(exc)}},
            )


# Auto-register when imported
def _register():
    from eli.cognition.agent_bus import _ALL_AGENTS
    if not any(a.name == "{agent_name}" for a in _ALL_AGENTS):
        _ALL_AGENTS.append({class_name}())

_register()
'''

    def _register_agent_live(self, class_name: str, agent_file: Path) -> bool:
        """Dynamically import the generated agent file and append it to the bus."""
        try:
            import importlib.util as _ilu
            spec = _ilu.spec_from_file_location(class_name, str(agent_file))
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            # The module's _register() call already appended to _ALL_AGENTS
            # Expand the thread pool to accommodate
            from eli.cognition.agent_bus import get_bus
            bus = get_bus()
            if hasattr(bus, "_pool"):
                from concurrent.futures import ThreadPoolExecutor
                from eli.cognition.agent_bus import _ALL_AGENTS
                bus._pool._max_workers = len(_ALL_AGENTS)
            return True
        except Exception as e:
            log.debug(f"[WIZARD] Live registration failed: {e}")
            return False

    # ── Open advanced settings dialog ─────────────────────────────────────────
    def open_advanced_settings(self, tab: int = 0):
        dlg = AdvancedSettingsDialog(parent=self, start_tab=tab)
        dlg.exec()

    # ══════════════════════════════════════════════════════════════════════════
    # SETTINGS TAB
    # ══════════════════════════════════════════════════════════════════════════
    # ── Settings sidebar nav items ─────────────────────────────────────────────
    _SETTINGS_NAV = [
        ("Model",       "🧠"),
        ("Runtime",     "⚡"),
        ("Generation",  "✨"),
        ("Identity",    "🎨"),
        ("Audio",       "🎙"),
        ("Application", "🖥"),
        ("Agents",      "🤖"),
        ("Gaze",        "👁"),
        ("Advanced",    "⚙️"),
    ]

    def create_settings_tab(self):
        root = QWidget()
        self._settings_root = root
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── body: sidebar + content stack ─────────────────────────────────────
        body = QSplitter(Qt.Orientation.Horizontal)
        body.setHandleWidth(1)

        # ── LEFT sidebar ──────────────────────────────────────────────────────
        self._settings_nav = QListWidget()
        self._settings_nav.setFixedWidth(138)
        self._settings_nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._settings_nav.setFrameShape(QFrame.Shape.NoFrame)
        self._settings_nav.setSpacing(1)
        self._settings_nav.setStyleSheet("""
            QListWidget {
                background: #1e2027;
                border: none;
                padding: 8px 0;
            }
            QListWidget::item {
                color: #8b9ab0;
                font-size: 11px;
                font-weight: 500;
                padding: 7px 14px;
                border-radius: 0;
                border-left: 3px solid transparent;
            }
            QListWidget::item:hover {
                color: #cdd6e8;
                background: #262b35;
            }
            QListWidget::item:selected {
                color: #ffffff;
                background: #2a3040;
                border-left: 3px solid #5e81ac;
                font-weight: 700;
            }
        """)
        for label, icon in self._SETTINGS_NAV:
            item = QListWidgetItem(f"  {icon}  {label}")
            self._settings_nav.addItem(item)
        body.addWidget(self._settings_nav)

        # ── RIGHT content stack (wrapped in zoomable view) ────────────────────
        self._settings_stack = QStackedWidget()
        self._settings_stack.setStyleSheet(
            "QStackedWidget { background: #1a1d23; border: none; }"
        )
        self._settings_stack.addWidget(self._build_settings_model_page())
        self._settings_stack.addWidget(self._build_settings_runtime_page())
        self._settings_stack.addWidget(self._build_settings_generation_page())
        self._settings_stack.addWidget(self._build_settings_identity_page())
        self._settings_stack.addWidget(self._build_settings_audio_page())
        self._settings_stack.addWidget(self._build_settings_app_page())
        self._settings_stack.addWidget(self._build_settings_agents_page())
        self._settings_stack.addWidget(self._build_settings_gaze_page())
        self._settings_stack.addWidget(self._build_settings_advanced_page())

        self._settings_zoom_view = _ZoomableSettingsView(self._settings_stack)
        body.addWidget(self._settings_zoom_view)

        body.setSizes([138, 9999])
        body.setCollapsible(0, False)
        body.setCollapsible(1, False)
        root_layout.addWidget(body, stretch=1)

        # ── FOOTER: always-visible save bar ───────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(42)
        footer.setStyleSheet(
            "QWidget { background: #12141a; border-top: 1px solid #2a2d36; }"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 6, 14, 6)

        save_btn = QPushButton("💾  Save")
        save_btn.setFixedHeight(28)
        save_btn.setStyleSheet(
            "QPushButton{background:#5e81ac;color:#fff;font-weight:bold;"
            "border:none;border-radius:5px;padding:0 14px;font-size:11px;}"
            "QPushButton:hover{background:#81a1c1;}"
        )
        save_btn.clicked.connect(self.save_settings)
        footer_layout.addWidget(save_btn)

        detect_btn = QPushButton("🔍  Auto-Detect")
        detect_btn.setFixedHeight(28)
        detect_btn.setStyleSheet(
            "QPushButton{background:#3b4252;color:#d8dee9;font-weight:500;"
            "border:none;border-radius:5px;padding:0 14px;font-size:11px;}"
            "QPushButton:hover{background:#4c566a;}"
        )
        detect_btn.clicked.connect(self.detect_optimal_settings)
        footer_layout.addWidget(detect_btn)

        zoom_out_btn = QPushButton("A-")
        zoom_out_btn.setFixedHeight(28)
        zoom_out_btn.setToolTip("Zoom out settings (Ctrl+-)")
        zoom_out_btn.setStyleSheet(
            "QPushButton{background:#2e3440;color:#d8dee9;font-weight:600;"
            "border:none;border-radius:5px;padding:0 10px;font-size:10px;}"
            "QPushButton:hover{background:#3b4252;color:#ffffff;}"
        )
        zoom_out_btn.clicked.connect(self._settings_zoom_view.zoom_out)
        footer_layout.addWidget(zoom_out_btn)

        zoom_reset_btn = QPushButton("100%")
        zoom_reset_btn.setFixedHeight(28)
        zoom_reset_btn.setToolTip("Reset settings zoom (Ctrl+0)")
        zoom_reset_btn.setStyleSheet(
            "QPushButton{background:#2e3440;color:#d8dee9;font-weight:600;"
            "border:none;border-radius:5px;padding:0 10px;font-size:10px;}"
            "QPushButton:hover{background:#3b4252;color:#ffffff;}"
        )
        zoom_reset_btn.clicked.connect(
            lambda: self._settings_zoom_view.zoom_reset()
        )
        footer_layout.addWidget(zoom_reset_btn)

        zoom_in_btn = QPushButton("A+")
        zoom_in_btn.setFixedHeight(28)
        zoom_in_btn.setToolTip("Zoom in settings (Ctrl+=)")
        zoom_in_btn.setStyleSheet(
            "QPushButton{background:#2e3440;color:#d8dee9;font-weight:600;"
            "border:none;border-radius:5px;padding:0 10px;font-size:10px;}"
            "QPushButton:hover{background:#3b4252;color:#ffffff;}"
        )
        zoom_in_btn.clicked.connect(self._settings_zoom_view.zoom_in)
        footer_layout.addWidget(zoom_in_btn)

        footer_layout.addStretch()
        root_layout.addWidget(footer)

        # wire nav → stack
        self._settings_nav.currentRowChanged.connect(
            self._settings_stack.setCurrentIndex
        )
        self._settings_nav.setCurrentRow(0)

        self.tabs.addTab(root, "⚙️ Settings")

    # ── Per-page builders ──────────────────────────────────────────────────────

    def _settings_page(self, title: str, subtitle: str = "") -> tuple:
        """Return (page_widget, vbox) with a compact styled header."""
        page = QWidget()
        page.setStyleSheet("QWidget { background: transparent; }")
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(20, 14, 20, 12)
        vbox.setSpacing(10)

        h = QLabel(title)
        h.setStyleSheet("font-size:14px;font-weight:700;color:#e8eaf0;")
        vbox.addWidget(h)
        if subtitle:
            s = QLabel(subtitle)
            s.setStyleSheet("font-size:10px;color:#606880;margin-top:-4px;")
            s.setWordWrap(True)
            vbox.addWidget(s)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("QFrame{color:#282c38;max-height:1px;}")
        vbox.addWidget(sep)

        return page, vbox

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#8b9ab0;font-size:10px;font-weight:600;letter-spacing:0.3px;")
        return lbl

    def _section_card(self, parent_layout, section_title: str = "") -> QFormLayout:
        """Add a card section, return its QFormLayout."""
        card = QWidget()
        card.setStyleSheet(
            "QWidget{background:#1e2230;border-radius:6px;}"
            "QLabel{color:#c8d0e0;}"
        )
        card_vbox = QVBoxLayout(card)
        card_vbox.setContentsMargins(14, 10, 14, 10)
        card_vbox.setSpacing(7)
        if section_title:
            t = QLabel(section_title)
            t.setStyleSheet("color:#5e81ac;font-size:9px;font-weight:700;letter-spacing:0.8px;")
            card_vbox.addWidget(t)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        card_vbox.addLayout(form)
        parent_layout.addWidget(card)
        return form

    def _live_monitor_panel(self, title: str, accent: str) -> Dict[str, Any]:
        panel = QFrame()
        panel.setObjectName("runtimeMonitorCard")
        panel.setStyleSheet(
            "QFrame#runtimeMonitorCard{background:#151924;border:1px solid #2b3445;border-radius:10px;}"
            "QLabel{background:transparent;}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        top = QHBoxLayout()
        name = QLabel(title)
        name.setStyleSheet("color:#8eaac8;font-size:10px;font-weight:700;letter-spacing:0.7px;")
        value = QLabel("--%")
        value.setStyleSheet(f"color:{accent};font-size:20px;font-weight:800;")
        top.addWidget(name)
        top.addStretch()
        top.addWidget(value)
        layout.addLayout(top)

        detail = QLabel("Waiting for telemetry...")
        detail.setStyleSheet("color:#d6dce8;font-size:12px;font-weight:600;")
        layout.addWidget(detail)

        subtext = QLabel("No live sample yet.")
        subtext.setWordWrap(True)
        subtext.setStyleSheet("color:#6f8098;font-size:10px;")
        layout.addWidget(subtext)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(False)
        progress.setFixedHeight(8)
        progress.setStyleSheet(
            "QProgressBar{background:#0f131b;border:1px solid #202737;border-radius:4px;}"
            f"QProgressBar::chunk{{background:{accent};border-radius:4px;}}"
        )
        layout.addWidget(progress)

        graph = _MiniTelemetryGraph(accent)
        layout.addWidget(graph)

        return {
            "widget": panel,
            "value": value,
            "detail": detail,
            "subtext": subtext,
            "progress": progress,
            "graph": graph,
        }

    def _build_live_runtime_monitor_section(self, parent_layout):
        card = QFrame()
        card.setObjectName("liveRuntimeMonitor")
        card.setStyleSheet(
            "QFrame#liveRuntimeMonitor{background:#1e2230;border-radius:8px;}"
            "QLabel{background:transparent;}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        title = QLabel("LIVE SYSTEM MONITOR")
        title.setStyleSheet("color:#5e81ac;font-size:9px;font-weight:700;letter-spacing:0.8px;")
        layout.addWidget(title)

        self.runtime_monitor_summary_label = QLabel("Sampling live CPU, RAM, and VRAM telemetry...")
        self.runtime_monitor_summary_label.setWordWrap(True)
        self.runtime_monitor_summary_label.setStyleSheet("color:#c8d0e0;font-size:12px;font-weight:600;")
        layout.addWidget(self.runtime_monitor_summary_label)

        self.runtime_monitor_meta_label = QLabel("Refresh cadence: 2s")
        self.runtime_monitor_meta_label.setStyleSheet("color:#6f8098;font-size:10px;")
        layout.addWidget(self.runtime_monitor_meta_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self._cpu_monitor = self._live_monitor_panel("CPU LOAD", "#88c0d0")
        self._ram_monitor = self._live_monitor_panel("RAM USAGE", "#a3be8c")
        self._vram_monitor = self._live_monitor_panel("VRAM USAGE", "#ebcb8b")

        grid.addWidget(self._cpu_monitor["widget"], 0, 0)
        grid.addWidget(self._ram_monitor["widget"], 0, 1)
        grid.addWidget(self._vram_monitor["widget"], 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        parent_layout.addWidget(card)

    # ── Page 0 — Model ────────────────────────────────────────────────────────
    def _build_settings_model_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Model",
            "Choose and configure the AI backend ELI uses for inference."
        )

        # Provider card
        form = self._section_card(vbox, "PROVIDER")
        self.provider_combo = QComboBox()
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS['bundled_gguf'], 'bundled_gguf')
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS['custom_gguf'], 'custom_gguf')
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS['ollama'], 'ollama')
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
        form.addRow(self._field_label("Backend"), self.provider_combo)

        self.system_recommendation_label = QLabel("Recommendation pending.")
        self.system_recommendation_label.setWordWrap(True)
        self.system_recommendation_label.setStyleSheet("color:#606880;font-size:12px;")
        form.addRow(self._field_label("Hardware"), self.system_recommendation_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        refresh_btn = QPushButton("Refresh Sources")
        refresh_btn.clicked.connect(self.refresh_model_sources)
        recommend_btn = QPushButton("Detect & Recommend")
        recommend_btn.clicked.connect(self.apply_recommended_setup)
        btn_row.addWidget(refresh_btn)
        btn_row.addWidget(recommend_btn)
        btn_row.addStretch()
        form.addRow("", btn_row)

        # Bundled card
        form2 = self._section_card(vbox, "BUNDLED GGUF")
        self.bundled_model_combo = QComboBox()
        self.bundled_model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        form2.addRow(self._field_label("Model"), self.bundled_model_combo)

        # Custom card
        form3 = self._section_card(vbox, "CUSTOM GGUF")
        self.model_path_input = QLineEdit()
        self.model_path_input.setText(DEFAULT_MODEL_PATH)
        form3.addRow(self._field_label("File path"), self.model_path_input)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.browse_model_file)
        form3.addRow("", browse_btn)

        # Ollama card
        form4 = self._section_card(vbox, "OLLAMA")
        self.ollama_host_input = QLineEdit("http://localhost:11434")
        form4.addRow(self._field_label("Host"), self.ollama_host_input)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        form4.addRow(self._field_label("Model"), self.ollama_model_combo)
        refresh_ollama_btn = QPushButton("Refresh Ollama Models")
        refresh_ollama_btn.clicked.connect(self.refresh_ollama_models)
        form4.addRow("", refresh_ollama_btn)

        vbox.addStretch()
        return page

    # ── Page 1 — Runtime ──────────────────────────────────────────────────────
    def _build_settings_runtime_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Runtime",
            "Control how the model is loaded and how much hardware it uses."
        )
        form = self._section_card(vbox, "INFERENCE ENGINE")

        self.n_ctx_input = QSpinBox()
        self.n_ctx_input.setRange(512, 32768)
        self.n_ctx_input.setValue(16384)
        self.n_ctx_input.setSingleStep(512)
        self.n_ctx_input.setToolTip("Token context window — larger = more memory")
        form.addRow(self._field_label("Context size"), self.n_ctx_input)

        self.n_threads_input = QSpinBox()
        self.n_threads_input.setRange(1, 64)
        self.n_threads_input.setValue(8)
        form.addRow(self._field_label("CPU threads"), self.n_threads_input)

        self.n_gpu_layers_input = QSpinBox()
        self.n_gpu_layers_input.setRange(0, 9999)
        self.n_gpu_layers_input.setValue(99)
        self.n_gpu_layers_input.setToolTip("Loader parameter requested for GPU offload. Backend support is reported separately. (0 = CPU request, 99 = all-layer request)")
        form.addRow(self._field_label("GPU-layer parameter"), self.n_gpu_layers_input)

        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(1, 2048)
        self.batch_size_input.setValue(512)
        self.batch_size_input.setSingleStep(64)
        self.batch_size_input.setToolTip("Prompt processing batch size — larger is faster but uses more VRAM")
        form.addRow(self._field_label("Batch size"), self.batch_size_input)

        # KV-cache quantization. q4_0 cuts KV memory ~75% with negligible
        # quality loss for chat workloads — the unlock for ctx ≥ 16k on
        # small VRAM cards. Empty value = no quantization (fp16).
        self.cache_type_k_combo = QComboBox()
        self.cache_type_k_combo.addItems(["", "q4_0", "q8_0", "f16"])
        self.cache_type_k_combo.setToolTip(
            "KV cache quantization for keys. q4_0 = 4× more ctx for the same "
            "VRAM. Empty = fp16 (no quantization)."
        )
        form.addRow(self._field_label("KV cache K"), self.cache_type_k_combo)

        self.cache_type_v_combo = QComboBox()
        self.cache_type_v_combo.addItems(["", "q4_0", "q8_0", "f16"])
        self.cache_type_v_combo.setToolTip(
            "KV cache quantization for values. Match this to the K setting."
        )
        form.addRow(self._field_label("KV cache V"), self.cache_type_v_combo)

        self.auto_load_checkbox = QCheckBox("Auto-load backend on startup")
        self.auto_load_checkbox.setStyleSheet("color:#c8d0e0;")
        form.addRow("", self.auto_load_checkbox)

        self.startup_model_picker_checkbox = QCheckBox("Show startup model picker")
        self.startup_model_picker_checkbox.setStyleSheet("color:#c8d0e0;")
        self.startup_model_picker_checkbox.setChecked(True)
        form.addRow("", self.startup_model_picker_checkbox)

        self._build_live_runtime_monitor_section(vbox)

        # TTS backend status + voice selector
        tts_form = self._section_card(vbox, "VOICE / TTS")
        try:
            from eli.perception.tts_router import (
                available_backends as _tts_backends,
                list_voices as _list_voices,
                get_active_voice as _get_active_voice,
                set_active_voice as _set_active_voice,
            )
            _be = _tts_backends()
            _status_lines = [
                f"Piper (Python): ✅",
                f"Piper binary:   {'✅ found' if _be.get('piper_bin') else '⚠ not found'}",
                f"espeak-ng:      {'✅' if _be.get('espeak_ng') else '❌'}",
            ]
            _tts_lbl = QLabel("\n".join(_status_lines))
            _tts_lbl.setStyleSheet("color:#8eaac8; font-family:monospace; font-size:11px;")
            tts_form.addRow(_tts_lbl)

            # Voice selector — uses qt_compat-loaded QComboBox (PySide6 / PyQt6 / PyQt5)
            self._voice_selector = QComboBox()
            self._voice_selector.setStyleSheet(
                "QComboBox { background:#1e2535; color:#c8d0e0; border:1px solid #3a4560;"
                " border-radius:4px; padding:4px 8px; min-height:28px; }"
                "QComboBox::drop-down { border:none; }"
                "QComboBox QAbstractItemView { background:#1e2535; color:#c8d0e0; }"
            )
            _voices = _list_voices()
            _active = _get_active_voice()
            for _v in _voices:
                self._voice_selector.addItem(_v)
            if _active in _voices:
                self._voice_selector.setCurrentText(_active)

            def _on_voice_changed(_name: str):
                try:
                    _set_active_voice(_name)
                except Exception:
                    pass

            self._voice_selector.currentTextChanged.connect(_on_voice_changed)

            _voice_row_widget = QWidget()
            _voice_row_layout = QHBoxLayout(_voice_row_widget)
            _voice_row_layout.setContentsMargins(0, 0, 0, 0)
            _voice_row_layout.setSpacing(8)
            _voice_lbl = QLabel("Voice:")
            _voice_lbl.setStyleSheet("color:#8eaac8; min-width:50px;")
            _voice_row_layout.addWidget(_voice_lbl)
            _voice_row_layout.addWidget(self._voice_selector, 1)
            tts_form.addRow(_voice_row_widget)

            # Test voice button
            _test_btn = QPushButton("▶ Test Voice")
            _test_btn.setStyleSheet(
                "QPushButton { background:#1e3a2a; color:#5dbb7a; border:1px solid #2a5a3a;"
                " border-radius:4px; padding:4px 10px; }"
                "QPushButton:hover { background:#254a30; }"
            )
            def _test_voice():
                try:
                    from eli.perception.tts_router import speak
                    speak("ELI voice test. Systems operational.", voice_name=self._voice_selector.currentText())
                except Exception as e:
                    log.debug(f"[TTS] Test error: {e}")
            _test_btn.clicked.connect(_test_voice)
            tts_form.addRow(_test_btn)

        except Exception as _tts_err:
            tts_form.addRow(QLabel(f"TTS status unavailable: {_tts_err}"))

        vbox.addStretch()
        return page

    def _start_runtime_monitoring(self):
        if self._runtime_stats_timer is not None:
            return
        try:
            import psutil
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        self._runtime_stats_timer = QTimer(self)
        self._runtime_stats_timer.setInterval(2000)
        self._runtime_stats_timer.timeout.connect(self.refresh_runtime_telemetry)
        self.refresh_runtime_telemetry()
        self._runtime_stats_timer.start()

    def _start_live_data_monitoring(self):
        """Phase 7: keep memory / proactive panels live without the user
        clicking Refresh. Memory counts update every 30 s (cheap SQLite read);
        proactive daemon status updates every 5 s (in-process flag check).

        Each tick is wrapped in try/except so a transient read error never
        crashes the GUI loop. The same callbacks are still exposed for
        manual Refresh buttons."""
        # Memory stats — SQLite count read; safe to call on the main thread
        # because it's a single SELECT and finishes in < 5 ms.
        if self._memory_stats_timer is None:
            def _tick_memory():
                try:
                    self.refresh_memory_stats()
                except Exception as exc:
                    log.debug(f"[GUI] memory-stats tick failed (non-fatal): {exc}")
            self._memory_stats_timer = QTimer(self)
            self._memory_stats_timer.setInterval(30_000)
            self._memory_stats_timer.timeout.connect(_tick_memory)
            self._memory_stats_timer.start()

        # Proactive status label — pure in-memory flag check, very cheap.
        if self._proactive_status_timer is None:
            def _tick_proactive():
                try:
                    self._update_proactive_status_label()
                    self._check_proactive_daemon_crash()
                except Exception as exc:
                    log.debug(f"[GUI] proactive-status tick failed (non-fatal): {exc}")
            self._proactive_status_timer = QTimer(self)
            self._proactive_status_timer.setInterval(5_000)
            self._proactive_status_timer.timeout.connect(_tick_proactive)
            self._proactive_status_timer.start()

    def _read_live_runtime_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {
            "timestamp": now_hms(),
            "cpu_percent": 0.0,
            "cpu_threads": int(os.cpu_count() or 1),
            "ram_total_gb": 0.0,
            "ram_used_gb": 0.0,
            "ram_free_gb": 0.0,
            "ram_percent": 0.0,
            "gpu_present": False,
            "gpu_name": "No GPU telemetry",
            "gpu_util_percent": None,
            "vram_total_mb": 0,
            "vram_used_mb": 0,
            "vram_free_mb": 0,
            "vram_percent": 0.0,
        }
        try:
            import psutil
            vm = psutil.virtual_memory()
            stats["cpu_percent"] = float(psutil.cpu_percent(interval=None))
            stats["ram_total_gb"] = vm.total / (1024 ** 3)
            stats["ram_used_gb"] = vm.used / (1024 ** 3)
            stats["ram_free_gb"] = vm.available / (1024 ** 3)
            stats["ram_percent"] = float(vm.percent)
        except Exception:
            pass

        if shutil.which("nvidia-smi"):
            try:
                out = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=memory.used,memory.total,memory.free,utilization.gpu,name",
                        "--format=csv,noheader,nounits",
                    ],
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                ).decode().strip().splitlines()
                if out:
                    parts = [p.strip() for p in out[0].split(",")]
                    used_mb = int(float(parts[0]))
                    total_mb = int(float(parts[1]))
                    free_mb = int(float(parts[2]))
                    util = None
                    if len(parts) > 3 and parts[3] not in ("", "[N/A]", "N/A"):
                        util = float(parts[3])
                    name = parts[4] if len(parts) > 4 else "NVIDIA GPU"
                    stats.update({
                        "gpu_present": True,
                        "gpu_name": name,
                        "gpu_util_percent": util,
                        "vram_used_mb": used_mb,
                        "vram_total_mb": total_mb,
                        "vram_free_mb": free_mb,
                        "vram_percent": (used_mb / total_mb * 100.0) if total_mb > 0 else 0.0,
                    })
            except Exception:
                stats["gpu_name"] = "GPU detected, live VRAM probe failed"
        elif self.detected_system_info.get("has_gpu"):
            stats["gpu_name"] = "GPU detected, live VRAM telemetry unavailable"

        self.detected_system_info.update({
            "cpu_count": stats["cpu_threads"],
            "total_ram_gb": stats["ram_total_gb"] or self.detected_system_info.get("total_ram_gb", 0.0),
            "available_ram_gb": stats["ram_free_gb"] or self.detected_system_info.get("available_ram_gb", 0.0),
            "has_gpu": stats["gpu_present"] or self.detected_system_info.get("has_gpu", False),
            "vram_mb": stats["vram_free_mb"] or self.detected_system_info.get("vram_mb", 0),
        })
        return stats

    def _update_runtime_monitor_panel(
        self,
        panel: Dict[str, Any],
        percent: float,
        detail: str,
        subtext: str,
        history: deque,
        available: bool = True,
    ):
        pct = max(0.0, min(100.0, float(percent or 0.0)))
        panel["value"].setText(f"{pct:.0f}%" if available else "--")
        panel["detail"].setText(detail)
        panel["subtext"].setText(subtext)
        panel["progress"].setValue(int(round(pct)) if available else 0)
        panel["graph"].set_values(list(history) if available and history else [])

    def refresh_runtime_telemetry(self):
        stats = self._read_live_runtime_stats()

        self._runtime_stat_history["cpu"].append(stats["cpu_percent"])
        self._runtime_stat_history["ram"].append(stats["ram_percent"])
        if stats["gpu_present"]:
            self._runtime_stat_history["vram"].append(stats["vram_percent"])

        if not hasattr(self, "_cpu_monitor"):
            return

        self.runtime_monitor_summary_label.setText(
            f"CPU {stats['cpu_threads']} threads visible · "
            f"RAM {stats['ram_used_gb']:.1f}/{stats['ram_total_gb']:.1f} GB used · "
            f"{stats['gpu_name']}"
        )
        self.runtime_monitor_meta_label.setText(
            f"Live sample: {stats['timestamp']} · Refresh cadence: 2s"
        )

        self._update_runtime_monitor_panel(
            self._cpu_monitor,
            stats["cpu_percent"],
            f"{stats['cpu_percent']:.1f}% current CPU load",
            f"{stats['cpu_threads']} logical threads available to the runtime.",
            self._runtime_stat_history["cpu"],
            available=True,
        )
        self._update_runtime_monitor_panel(
            self._ram_monitor,
            stats["ram_percent"],
            f"{stats['ram_used_gb']:.1f} / {stats['ram_total_gb']:.1f} GB RAM used",
            f"{stats['ram_free_gb']:.1f} GB available right now.",
            self._runtime_stat_history["ram"],
            available=stats["ram_total_gb"] > 0,
        )

        if stats["gpu_present"] and stats["vram_total_mb"] > 0:
            util_txt = (
                f"GPU core util {stats['gpu_util_percent']:.0f}%"
                if stats["gpu_util_percent"] is not None else
                "GPU core utilization unavailable"
            )
            self._update_runtime_monitor_panel(
                self._vram_monitor,
                stats["vram_percent"],
                f"{stats['vram_used_mb'] / 1024.0:.1f} / {stats['vram_total_mb'] / 1024.0:.1f} GB VRAM used",
                f"{util_txt} · {stats['vram_free_mb'] / 1024.0:.1f} GB free on {stats['gpu_name']}.",
                self._runtime_stat_history["vram"],
                available=True,
            )
        else:
            self._update_runtime_monitor_panel(
                self._vram_monitor,
                0.0,
                "No compatible live VRAM telemetry detected.",
                stats["gpu_name"],
                self._runtime_stat_history["vram"],
                available=False,
            )

    # ── Page 2 — Generation ───────────────────────────────────────────────────
    def _build_settings_generation_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Generation",
            "Tune how ELI generates text — length, creativity, and sampling."
        )
        form = self._section_card(vbox, "SAMPLING")

        self.max_tokens_input = QSpinBox()
        self.max_tokens_input.setRange(128, 4096)
        self.max_tokens_input.setValue(4096)
        self.max_tokens_input.setSingleStep(128)
        form.addRow(self._field_label("Max tokens"), self.max_tokens_input)

        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setRange(0.0, 2.0)
        self.temperature_input.setValue(0.7)
        self.temperature_input.setSingleStep(0.05)
        self.temperature_input.setToolTip("0 = deterministic · 1 = creative · 2 = chaotic")
        form.addRow(self._field_label("Temperature"), self.temperature_input)

        # Visual temperature slider synced to spinbox
        self.temp_slider = QSlider(Qt.Orientation.Horizontal)
        self.temp_slider.setRange(0, 200)
        self.temp_slider.setValue(70)
        self.temp_slider.setToolTip("Drag to adjust temperature")
        self.temp_slider.valueChanged.connect(
            lambda v: self.temperature_input.setValue(v / 100)
        )
        self.temperature_input.valueChanged.connect(
            lambda v: self.temp_slider.setValue(int(v * 100))
        )
        form.addRow("", self.temp_slider)

        vbox.addStretch()
        return page

    def _build_settings_identity_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Identity",
            "Personalise how ELI presents visuals, remembers your preferences, and defaults the image studio."
        )

        form = self._section_card(vbox, "USER PROFILE")
        self.user_name_input = QLineEdit()
        self.user_name_input.setPlaceholderText("Your preferred name")
        form.addRow(self._field_label("Name"), self.user_name_input)

        self.image_profile_notes_input = QTextEdit()
        self.image_profile_notes_input.setPlaceholderText(
            "Visual identity cues, preferred subjects, moods, brand notes, favourite colours..."
        )
        self.image_profile_notes_input.setMinimumHeight(110)
        form.addRow(self._field_label("Visual notes"), self.image_profile_notes_input)

        form2 = self._section_card(vbox, "IMAGE PERSONALISATION")
        self.image_style_profile_combo = QComboBox()
        self.image_style_profile_combo.addItems(["auto", "balanced", "cinematic", "minimal", "luxury", "neon", "fantasy"])
        form2.addRow(self._field_label("Style bias"), self.image_style_profile_combo)

        self.image_palette_profile_combo = QComboBox()
        self.image_palette_profile_combo.addItems(["auto", "blue_dawn", "crimson_sunset", "emerald_aurora", "golden_storm", "monochrome_luxury", "neon_noir", "rose_steel", "solar_glass", "violet_dusk"])
        form2.addRow(self._field_label("Palette bias"), self.image_palette_profile_combo)

        self.image_auto_personalize_checkbox = QCheckBox("Blend image prompts with user/profile context")
        self.image_auto_personalize_checkbox.setStyleSheet("color:#c8d0e0;")
        form2.addRow("", self.image_auto_personalize_checkbox)

        self.image_use_chat_context_checkbox = QCheckBox("Use recent chat context in image prompting")
        self.image_use_chat_context_checkbox.setStyleSheet("color:#c8d0e0;")
        form2.addRow("", self.image_use_chat_context_checkbox)

        self.image_use_proactive_context_checkbox = QCheckBox("Use proactive patterns and habits in image prompting")
        self.image_use_proactive_context_checkbox.setStyleSheet("color:#c8d0e0;")
        form2.addRow("", self.image_use_proactive_context_checkbox)

        form3 = self._section_card(vbox, "IMAGE STUDIO DEFAULTS")
        self.image_default_project_input = QLineEdit()
        self.image_default_project_input.setPlaceholderText("Optional reference folder for project-aware image generation")
        form3.addRow(self._field_label("Reference folder"), self.image_default_project_input)

        browse_row = QHBoxLayout()
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self.browse_image_project_folder)
        browse_row.addWidget(browse_btn)
        browse_row.addStretch()
        form3.addRow("", browse_row)

        self.image_default_count_input = QSpinBox()
        self.image_default_count_input.setRange(1, 24)
        self.image_default_count_input.setValue(1)
        form3.addRow(self._field_label("Default batch"), self.image_default_count_input)

        size_row = QHBoxLayout()
        self.image_default_width_input = QSpinBox()
        self.image_default_width_input.setRange(256, 4096)
        self.image_default_width_input.setSingleStep(64)
        self.image_default_width_input.setValue(1400)
        self.image_default_height_input = QSpinBox()
        self.image_default_height_input.setRange(256, 4096)
        self.image_default_height_input.setSingleStep(64)
        self.image_default_height_input.setValue(900)
        size_row.addWidget(self.image_default_width_input)
        size_row.addWidget(QLabel("×"))
        size_row.addWidget(self.image_default_height_input)
        form3.addRow(self._field_label("Default size"), size_row)

        self.image_auto_open_checkbox = QCheckBox("Auto-preview the first generated image")
        self.image_auto_open_checkbox.setStyleSheet("color:#c8d0e0;")
        form3.addRow("", self.image_auto_open_checkbox)

        form4 = self._section_card(vbox, "IMAGE RENDER BACKEND")
        self.image_backend_default_combo = QComboBox()
        self.image_backend_default_combo.addItems(["auto", "diffusion", "procedural"])
        form4.addRow(self._field_label("Backend"), self.image_backend_default_combo)

        self.image_model_path_input = QLineEdit()
        self.image_model_path_input.setPlaceholderText("Path to a local SDXL / Flux / diffusion model directory or .safetensors checkpoint, ideally under models/image/")
        form4.addRow(self._field_label("Model path"), self.image_model_path_input)

        model_btn_row = QHBoxLayout()
        image_model_browse_btn = QPushButton("Browse…")
        image_model_browse_btn.clicked.connect(self.browse_image_model_path)
        model_btn_row.addWidget(image_model_browse_btn)
        model_refresh_btn = QPushButton("Detect Local Models")
        model_refresh_btn.clicked.connect(self.refresh_image_model_sources)
        model_btn_row.addWidget(model_refresh_btn)
        model_btn_row.addStretch()
        form4.addRow("", model_btn_row)

        self.image_device_default_combo = QComboBox()
        self.image_device_default_combo.addItems(["auto", "cuda", "cpu"])
        form4.addRow(self._field_label("Device"), self.image_device_default_combo)

        self.image_quality_default_combo = QComboBox()
        self.image_quality_default_combo.addItems(["draft", "balanced", "ultra", "extreme"])
        self.image_quality_default_combo.currentTextChanged.connect(self._apply_image_default_quality_preset)
        form4.addRow(self._field_label("Quality"), self.image_quality_default_combo)

        default_render_row = QHBoxLayout()
        self.image_steps_default_input = QSpinBox()
        self.image_steps_default_input.setRange(8, 120)
        self.image_steps_default_input.setValue(36)
        self.image_guidance_default_input = QDoubleSpinBox()
        self.image_guidance_default_input.setRange(1.0, 20.0)
        self.image_guidance_default_input.setSingleStep(0.1)
        self.image_guidance_default_input.setValue(7.2)
        default_render_row.addWidget(QLabel("Steps"))
        default_render_row.addWidget(self.image_steps_default_input)
        default_render_row.addSpacing(8)
        default_render_row.addWidget(QLabel("CFG"))
        default_render_row.addWidget(self.image_guidance_default_input)
        form4.addRow(self._field_label("Render"), default_render_row)

        self.image_negative_default_input = QTextEdit()
        self.image_negative_default_input.setPlaceholderText("Default negative prompt for diffusion renders")
        self.image_negative_default_input.setMaximumHeight(90)
        form4.addRow(self._field_label("Negative"), self.image_negative_default_input)

        vbox.addStretch()
        return page

    # ── Page — Audio (STT/TTS diagnostics) ────────────────────────────────────
    def _build_settings_audio_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Audio",
            "STT calibration, voice profile, and TTS diagnostics."
        )

        # ── Microphone selector ───────────────────────────────────────────
        mic_card = self._section_card(vbox, "STT — MICROPHONE DEVICE")

        self.mic_device_combo = QComboBox()
        self.mic_device_combo.setToolTip(
            "Select the microphone ELI listens on.\n"
            "Bluetooth headsets appear as PulseAudio sources.\n"
            "Changes take effect the next time the mic is toggled."
        )
        self._populate_mic_device_combo()
        self.mic_device_combo.currentIndexChanged.connect(lambda _: self._on_mic_device_changed(_save=True))
        mic_card.addRow(self._field_label("Device"), self.mic_device_combo)

        refresh_mic_btn = QPushButton("↻ Refresh")
        refresh_mic_btn.setToolTip("Re-scan for new microphones or Bluetooth devices.")
        refresh_mic_btn.clicked.connect(lambda: self._populate_mic_device_combo(restore=True))
        mic_card.addRow("", refresh_mic_btn)

        # Sensitivity
        self.dynamic_energy_checkbox = QCheckBox("Dynamic energy threshold (auto-adjusts to ambient noise)")
        self.dynamic_energy_checkbox.setToolTip(
            "Continuously adapts the voice detection threshold to ambient noise.\n"
            "Enable this if you have to shout or if ELI mishears background noise.\n"
            "Env: ELI_STT_DYNAMIC_ENERGY"
        )
        self.dynamic_energy_checkbox.stateChanged.connect(self._apply_stt_sensitivity)
        mic_card.addRow(self.dynamic_energy_checkbox)

        _thresh_row = QHBoxLayout()
        self.energy_threshold_input = QSpinBox()
        self.energy_threshold_input.setRange(50, 10000)
        self.energy_threshold_input.setValue(1200)
        self.energy_threshold_input.setSingleStep(50)
        self.energy_threshold_input.setToolTip(
            "Minimum audio energy to register as speech.\n"
            "Lower = more sensitive (picks up quiet speech).\n"
            "Higher = less sensitive (ignores background noise).\n"
            "Only used when dynamic threshold is OFF. Env: ELI_STT_ENERGY_THRESHOLD"
        )
        self.energy_threshold_input.valueChanged.connect(self._apply_stt_sensitivity)
        _thresh_row.addWidget(self.energy_threshold_input)
        _thresh_row.addStretch()
        mic_card.addRow(self._field_label("Energy threshold"), _thresh_row)

        # ── Wake word / listen mode ───────────────────────────────────────
        wake_card = self._section_card(vbox, "STT — WAKE WORD SETTINGS")

        self.allow_direct_chat_checkbox = QCheckBox(
            "Allow chat without wake word (direct listen mode)"
        )
        self.allow_direct_chat_checkbox.setToolTip(
            "When enabled, ELI transcribes every phrase as a chat message without\n"
            "requiring 'computer' first. Useful for hands-free or quiet environments.\n"
            "Env: ELI_STT_ALLOW_DIRECT_CHAT"
        )
        self.allow_direct_chat_checkbox.stateChanged.connect(
            lambda _: self._apply_direct_chat_env()
        )
        wake_card.addRow(self.allow_direct_chat_checkbox)

        # ── STT diagnostic panel ─────────────────────────────────────────
        stt_card = self._section_card(vbox, "STT — VOICE PROFILE & CALIBRATION")

        self._stt_diag_label = QLabel("Loading…")
        self._stt_diag_label.setStyleSheet(
            "color:#c8d0e0; padding:6px 10px; "
            "background:#14171f; border:1px solid #2a2d3a; border-radius:4px; "
            "font-family:'Courier New',monospace; font-size:10px;"
        )
        self._stt_diag_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._stt_diag_label.setWordWrap(True)
        stt_card.addRow(self._stt_diag_label)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("↻ Refresh Diagnostics")
        refresh_btn.clicked.connect(self._refresh_stt_diagnostics)
        btn_row.addWidget(refresh_btn)
        reset_btn = QPushButton("🗑 Reset Voice Profile")
        reset_btn.setToolTip("Clear voice_profile.json so STT recalibrates from scratch.")
        reset_btn.clicked.connect(self._reset_voice_profile)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        stt_card.addRow(btn_row)

        # ── TTS diagnostic panel ─────────────────────────────────────────
        tts_card = self._section_card(vbox, "TTS — BACKENDS & VOICE")

        self._tts_diag_label = QLabel("Loading…")
        self._tts_diag_label.setStyleSheet(
            "color:#c8d0e0; padding:6px 10px; "
            "background:#14171f; border:1px solid #2a2d3a; border-radius:4px; "
            "font-family:'Courier New',monospace; font-size:10px;"
        )
        self._tts_diag_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._tts_diag_label.setWordWrap(True)
        tts_card.addRow(self._tts_diag_label)

        tts_btn_row = QHBoxLayout()
        tts_refresh = QPushButton("↻ Refresh TTS Status")
        tts_refresh.clicked.connect(self._refresh_tts_diagnostics)
        tts_btn_row.addWidget(tts_refresh)
        tts_test = QPushButton("🔊 Test Voice")
        tts_test.clicked.connect(self._test_tts_voice)
        tts_btn_row.addWidget(tts_test)
        tts_btn_row.addStretch(1)
        tts_card.addRow(tts_btn_row)

        vbox.addStretch(1)

        # Initial paint, then auto-refresh every 5 seconds while visible.
        self._refresh_stt_diagnostics()
        self._refresh_tts_diagnostics()
        try:
            self._stt_diag_timer = QTimer(self)
            self._stt_diag_timer.setInterval(5000)
            self._stt_diag_timer.timeout.connect(self._refresh_stt_diagnostics)
            self._stt_diag_timer.start()
        except Exception:
            pass
        return page

    def _refresh_stt_diagnostics(self):
        """Read voice_profile.json + current recognizer state and render."""
        try:
            from pathlib import Path as _P
            import json as _json
            try:
                from eli.core.paths import get_paths
                vp_path = _P(get_paths().artifacts_dir) / "runtime" / "voice_profile.json"
            except Exception:
                vp_path = _P.home() / ".eli_voice_profile.json"

            profile = {}
            if vp_path.exists():
                try:
                    profile = _json.loads(vp_path.read_text(encoding="utf-8"))
                except Exception:
                    profile = {}

            count = int(profile.get("count", 0) or 0)
            mean = float(profile.get("energy_mean", 0.0) or 0.0)
            mn = float(profile.get("energy_min", 0.0) or 0.0)
            mx = float(profile.get("energy_max", 0.0) or 0.0)
            dmean = float(profile.get("duration_mean_s", 0.0) or 0.0)
            last_e = profile.get("last_energy", "?")
            last_d = profile.get("last_duration_s", "?")

            # Live recognizer state if present.
            live_threshold = "?"
            live_pause = "?"
            live_dynamic = "?"
            try:
                from eli.perception.audio_stt import get_audio_stt as _g
                stt_obj = _g()
                if stt_obj is not None:
                    rec = getattr(stt_obj, "recognizer", None)
                    if rec is not None:
                        live_threshold = f"{getattr(rec, 'energy_threshold', '?'):.0f}"
                        live_pause = f"{getattr(rec, 'pause_threshold', '?')}"
                        live_dynamic = str(getattr(rec, 'dynamic_energy_threshold', '?'))
            except Exception:
                pass

            text = (
                f"Voice profile file: {vp_path}\n"
                f"Samples recorded:   {count}\n"
                f"Mean speech energy: {mean:.1f}    "
                f"min={mn:.1f}    max={mx:.1f}\n"
                f"Last sample:        energy={last_e}    duration={last_d}\n"
                f"Mean utterance dur: {dmean:.2f} s\n\n"
                f"--- Live recognizer ---\n"
                f"energy_threshold:   {live_threshold}\n"
                f"pause_threshold:    {live_pause}\n"
                f"dynamic_energy:     {live_dynamic}\n\n"
                f"After ~5 confirmed utterances, the threshold biases\n"
                f"toward your range (50%–90% of mean speech energy)."
            )
            self._stt_diag_label.setText(text)
        except Exception as e:
            self._stt_diag_label.setText(f"Failed to read STT diagnostics: {e}")

    def _reset_voice_profile(self):
        try:
            from pathlib import Path as _P
            from eli.core.paths import get_paths
            vp_path = _P(get_paths().artifacts_dir) / "runtime" / "voice_profile.json"
            if vp_path.exists():
                vp_path.unlink()
            QMessageBox.information(
                self, "Voice Profile Reset",
                f"Removed {vp_path}. STT will recalibrate from ambient on next utterance."
            )
            self._refresh_stt_diagnostics()
        except Exception as ex:
            QMessageBox.warning(self, "Reset failed", str(ex))

    def _refresh_tts_diagnostics(self):
        try:
            from eli.perception.tts_router import available_backends, get_active_voice
            backends = available_backends()
            active = get_active_voice()
            voices = backends.get("piper_voices", [])
            txt_lines = [
                f"Active voice:       {active}",
                f"Active model file:  {backends.get('active_model') or '(missing)'}",
                f"Piper binary:       {backends.get('piper_bin') or '(not found)'}",
                f"Installed voices:   {len(voices)} ({', '.join(voices[:6])}{'…' if len(voices) > 6 else ''})",
                f"pyttsx3 fallback:   {backends.get('pyttsx3')}",
                f"espeak-ng fallback: {backends.get('espeak_ng')}",
                f"espeak fallback:    {backends.get('espeak')}",
            ]
            self._tts_diag_label.setText("\n".join(txt_lines))
        except Exception as e:
            self._tts_diag_label.setText(f"Failed to read TTS diagnostics: {e}")

    def _test_tts_voice(self):
        try:
            from eli.perception.tts_router import speak_text
            speak_text("Voice test complete. STT and TTS are wired.")
            self._tts_diag_label.setText(
                self._tts_diag_label.text() + "\n\n[Test] sent 'Voice test complete' to TTS."
            )
        except Exception as ex:
            QMessageBox.warning(self, "TTS test failed", str(ex))

    # ── Page 3 — Application ──────────────────────────────────────────────────
    def _build_settings_app_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Application",
            "General application behaviour — persistence, logging, and theme."
        )
        form = self._section_card(vbox, "BEHAVIOUR")

        self.auto_save_checkbox = QCheckBox("Auto-save conversations")
        self.auto_save_checkbox.setChecked(True)
        self.auto_save_checkbox.setStyleSheet("color:#c8d0e0;")
        form.addRow("", self.auto_save_checkbox)

        self.log_to_file_checkbox = QCheckBox("Write session log to file")
        self.log_to_file_checkbox.setChecked(False)
        self.log_to_file_checkbox.setStyleSheet("color:#c8d0e0;")
        form.addRow("", self.log_to_file_checkbox)

        form2 = self._section_card(vbox, "APPEARANCE")
        theme_btn = QPushButton("🌗  Toggle Dark / Light Theme")
        theme_btn.clicked.connect(self.toggle_theme)
        form2.addRow("", theme_btn)

        vbox.addStretch()
        return page

    # ── Page 4 — Agents ───────────────────────────────────────────────────────
    def _build_settings_agents_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Agents",
            "Create a new custom ELI agent through a guided 3-question chat wizard."
        )

        card = QWidget()
        card.setStyleSheet(
            "QWidget{background:#1e2230;border-radius:8px;}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(10)

        wizard_label = QLabel(
            "The <b>Agent Wizard</b> switches to your Chat tab and asks three questions:\n"
            "  1. Name &amp; purpose of the new agent\n"
            "  2. Trigger keywords and data sources\n"
            "  3. Persona and output style\n\n"
            "ELI then generates a Python agent file, registers it live in the agent bus, "
            "and auto-loads it on every future startup."
        )
        wizard_label.setWordWrap(True)
        wizard_label.setStyleSheet(
            "color:#8b9ab0;font-size:11px;background:transparent;"
        )
        card_layout.addWidget(wizard_label)

        launch_btn = QPushButton("🤖  Launch Agent Creator Wizard")
        launch_btn.setFixedHeight(34)
        launch_btn.setStyleSheet(
            "QPushButton{background:#5e81ac;color:#fff;font-weight:700;"
            "border:none;border-radius:6px;font-size:11px;}"
            "QPushButton:hover{background:#81a1c1;}"
        )
        launch_btn.clicked.connect(self.open_agent_wizard)
        card_layout.addWidget(launch_btn)

        vbox.addWidget(card)
        vbox.addStretch()
        return page

    # ── Page 5 — Gaze ─────────────────────────────────────────────────────────
    def _build_settings_gaze_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Gaze Engine",
            "Webcam-based gaze tracking — iris position → screen coordinates via ridge regression.",
        )

        # ── Enable toggle ─────────────────────────────────────────────────────
        form = self._section_card(vbox, "ENGINE")

        self.gaze_enabled_checkbox = QCheckBox("Enable gaze engine on startup")
        self.gaze_enabled_checkbox.setChecked(False)
        self.gaze_enabled_checkbox.setStyleSheet("color:#c8d0e0;")
        self.gaze_enabled_checkbox.toggled.connect(self._on_gaze_toggle)
        form.addRow("", self.gaze_enabled_checkbox)

        # Camera index
        gaze_cam_row = QWidget()
        gaze_cam_lay = QHBoxLayout(gaze_cam_row)
        gaze_cam_lay.setContentsMargins(0, 0, 0, 0)
        gaze_cam_lay.setSpacing(6)
        self.gaze_camera_input = QLineEdit("auto")
        self.gaze_camera_input.setFixedWidth(60)
        self.gaze_camera_input.setStyleSheet(
            "QLineEdit{background:#252930;color:#c8d0e0;border:1px solid #3a3f4b;"
            "border-radius:4px;padding:2px 6px;font-size:11px;}"
        )
        self.gaze_camera_input.setToolTip(
            "Camera index (0, 1, 2 …) or 'auto' to scan all V4L2 devices"
        )
        gaze_cam_lay.addWidget(self.gaze_camera_input)
        gaze_cam_lay.addStretch()
        form.addRow(self._field_label("Camera"), gaze_cam_row)

        # ── Status row ───────────────────────────────────────────────────────
        form2 = self._section_card(vbox, "STATUS")

        self._gaze_status_label = QLabel("● stopped")
        self._gaze_status_label.setStyleSheet("color:#6b7a90;font-size:11px;")
        form2.addRow("", self._gaze_status_label)

        self._gaze_cal_label = QLabel("Calibration: unknown")
        self._gaze_cal_label.setStyleSheet("color:#6b7a90;font-size:10px;")
        form2.addRow("", self._gaze_cal_label)

        refresh_btn = QPushButton("↻  Refresh status")
        refresh_btn.setFixedHeight(26)
        refresh_btn.setStyleSheet(
            "QPushButton{background:#2e3440;color:#8b9ab0;font-size:10px;"
            "border:1px solid #3a3f4b;border-radius:4px;}"
            "QPushButton:hover{background:#3b4252;color:#d8dee9;}"
        )
        refresh_btn.clicked.connect(self._refresh_gaze_status)
        form2.addRow("", refresh_btn)

        # ── Control buttons ───────────────────────────────────────────────────
        form3 = self._section_card(vbox, "CONTROLS")

        btn_row = QWidget()
        btn_lay = QHBoxLayout(btn_row)
        btn_lay.setContentsMargins(0, 0, 0, 0)
        btn_lay.setSpacing(8)

        start_btn = QPushButton("▶  Start")
        start_btn.setFixedHeight(30)
        start_btn.setStyleSheet(
            "QPushButton{background:#4c7a4c;color:#fff;font-weight:600;"
            "border:none;border-radius:5px;padding:0 14px;font-size:11px;}"
            "QPushButton:hover{background:#5a9a5a;}"
        )
        start_btn.clicked.connect(self._gaze_start_clicked)
        btn_lay.addWidget(start_btn)

        stop_btn = QPushButton("⏹  Stop")
        stop_btn.setFixedHeight(30)
        stop_btn.setStyleSheet(
            "QPushButton{background:#7a3c3c;color:#fff;font-weight:600;"
            "border:none;border-radius:5px;padding:0 14px;font-size:11px;}"
            "QPushButton:hover{background:#9a4c4c;}"
        )
        stop_btn.clicked.connect(self._gaze_stop_clicked)
        btn_lay.addWidget(stop_btn)

        btn_lay.addStretch()
        form3.addRow("", btn_row)

        # ── Calibration ───────────────────────────────────────────────────────
        form4 = self._section_card(vbox, "CALIBRATION")

        cal_info = QLabel(
            "Calibration maps your iris position to screen coordinates via ridge\n"
            "regression on MediaPipe landmarks.  Run the script below with your\n"
            "webcam active and follow the on-screen dot targets (~2 min)."
        )
        cal_info.setWordWrap(True)
        cal_info.setStyleSheet("color:#6b7a90;font-size:10px;background:transparent;")
        form4.addRow("", cal_info)

        cal_btn = QPushButton("📋  Show calibration instructions")
        cal_btn.setFixedHeight(28)
        cal_btn.setStyleSheet(
            "QPushButton{background:#3b4252;color:#d8dee9;font-weight:500;"
            "border:none;border-radius:5px;padding:0 14px;font-size:11px;}"
            "QPushButton:hover{background:#4c566a;}"
        )
        cal_btn.clicked.connect(self._gaze_calibrate_info)
        form4.addRow("", cal_btn)

        vbox.addStretch()

        # Populate status on page build
        QTimer.singleShot(200, self._refresh_gaze_status)
        return page

    def _on_gaze_toggle(self, checked: bool):
        self.save_settings(silent=True)
        if checked:
            self._gaze_start_clicked()
        else:
            self._gaze_stop_clicked()

    def _gaze_start_clicked(self):
        try:
            from eli.perception.gaze_engine import start_gaze_engine
            cam = getattr(self, "gaze_camera_input", None)
            camera = cam.text().strip() if cam else "auto"
            if camera not in ("auto",) and not camera.isdigit():
                camera = "auto"
            result = start_gaze_engine(camera=camera if camera == "auto" else int(camera))
            msg = result.get("message", "")
            if not result.get("ok") and not result.get("already_running"):
                QMessageBox.warning(self, "Gaze Engine", msg)
        except Exception as e:
            QMessageBox.warning(self, "Gaze Engine", str(e))
        self._refresh_gaze_status()

    def _gaze_stop_clicked(self):
        try:
            from eli.perception.gaze_engine import stop_gaze_engine
            stop_gaze_engine()
        except Exception as e:
            QMessageBox.warning(self, "Gaze Engine", str(e))
        self._refresh_gaze_status()

    def _gaze_calibrate_info(self):
        try:
            import subprocess, sys as _sys
            from eli.perception.gaze_engine import get_calibration_path, needs_calibration
            cal_path = get_calibration_path()
            script = str(
                __import__("pathlib").Path(__file__).resolve().parents[2]
                / "experimental" / "eli_ar_avatar_kit" / "scripts"
                / "eli_gaze_calibrate_plus.py"
            )
            exists_note = "✅ Calibration file exists." if not needs_calibration() else "⚠ No calibration file yet."
            QMessageBox.information(
                self,
                "Gaze Calibration",
                f"{exists_note}\n\n"
                f"To calibrate, run in a terminal:\n\n"
                f"  python {script} --points 25\n\n"
                f"Saved to:\n  {cal_path}",
            )
        except Exception as e:
            QMessageBox.information(self, "Gaze Calibration", str(e))

    def _refresh_gaze_status(self):
        try:
            from eli.perception.gaze_engine import get_gaze_status
            st = get_gaze_status()
            running = st.get("running", False)
            calibrated = st.get("calibrated", False)
            if hasattr(self, "_gaze_status_label"):
                if running:
                    self._gaze_status_label.setText("● running")
                    self._gaze_status_label.setStyleSheet("color:#88c0d0;font-size:11px;font-weight:600;")
                else:
                    self._gaze_status_label.setText("● stopped")
                    self._gaze_status_label.setStyleSheet("color:#6b7a90;font-size:11px;")
            if hasattr(self, "_gaze_cal_label"):
                if calibrated:
                    self._gaze_cal_label.setText(f"Calibration: ✅  {st.get('calibration_path','')}")
                    self._gaze_cal_label.setStyleSheet("color:#a3be8c;font-size:10px;")
                else:
                    self._gaze_cal_label.setText("Calibration: ⚠  not found — run: gaze calibrate")
                    self._gaze_cal_label.setStyleSheet("color:#bf616a;font-size:10px;")
        except Exception:
            if hasattr(self, "_gaze_status_label"):
                self._gaze_status_label.setText("● unavailable")

    # ── Page 6 — Advanced ─────────────────────────────────────────────────────
    def _build_settings_advanced_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Advanced",
            "Deep control over agents, installed models, plugins, and self-upgrade tools."
        )

        _ADVANCED_CARDS = [
            (
                "🤖  Agents",
                "View, edit, enable or disable every agent in the bus.\nAdjust timeout, persona, and description per agent.",
                lambda: self.open_advanced_settings(0),
                "Manage Agents",
                "#5e81ac",
            ),
            (
                "🔌  Plugins",
                "Install plugins from the registry, enable, disable, or uninstall them.",
                lambda: self.open_advanced_settings(2),
                "Manage Plugins",
                "#88c0d0",
            ),
            (
                "🔄  Self-Upgrade",
                "Run improvement cycles, rebuild the FAISS index, update the capability manifest, and refresh ELI's persona.",
                lambda: self.open_advanced_settings(3),
                "Open Upgrade Tools",
                "#a3be8c",
            ),
        ]

        for icon_title, desc, callback, btn_label, color in _ADVANCED_CARDS:
            card = QWidget()
            card.setStyleSheet(
                f"QWidget{{background:#1e2230;border-radius:8px;border-left:3px solid {color};}}"
                "QLabel{background:transparent;}"
            )
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(12)

            text_col = QVBoxLayout()
            title_lbl = QLabel(f"<b>{icon_title}</b>")
            title_lbl.setStyleSheet("color:#e8eaf0;font-size:11px;")
            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet("color:#6b7a90;font-size:10px;")
            text_col.addWidget(title_lbl)
            text_col.addWidget(desc_lbl)
            cl.addLayout(text_col, stretch=1)

            action_btn = QPushButton(btn_label)
            action_btn.setFixedHeight(28)
            action_btn.setFixedWidth(130)
            action_btn.setStyleSheet(
                f"QPushButton{{background:{color};color:#1a1d23;font-weight:700;"
                f"border:none;border-radius:5px;font-size:10px;}}"
                f"QPushButton:hover{{background:#fff;color:#1a1d23;}}"
            )
            action_btn.clicked.connect(callback)
            cl.addWidget(action_btn)

            vbox.addWidget(card)

        vbox.addStretch()
        return page

    # ---------- Settings helpers ----------
    def current_provider(self) -> str:
        if not hasattr(self, 'provider_combo'):
            return 'bundled_gguf'
        return str(self.provider_combo.currentData() or 'bundled_gguf')

    def refresh_model_sources(self):
        self.detected_system_info = detect_system_capabilities()
        models = discover_gguf_models()
        if hasattr(self, 'bundled_model_combo'):
            self.bundled_model_combo.blockSignals(True)
            self.bundled_model_combo.clear()
            for m in models:
                if m.get('source') == 'bundled':
                    label = f"{m['name']}  ({m['size_gb']:.2f} GB)"
                    self.bundled_model_combo.addItem(label, m['path'])
            self.bundled_model_combo.blockSignals(False)
        self.refresh_ollama_models(quiet=True)
        if hasattr(self, 'bundled_model_combo') and self.bundled_model_combo.count() == 0:
            print("⚠️ No bundled GGUF models found – adding default path.")
            default_path = DEFAULT_MODEL_PATH
            label = f"{Path(default_path).name} (default)"
            self.bundled_model_combo.addItem(label, default_path)
        ram = self.detected_system_info.get('total_ram_gb') or 0.0
        cpu = self.detected_system_info.get('cpu_count') or 1
        self.system_recommendation_label.setText(f"Detected: {format_gb(float(ram))} RAM, {cpu} CPU threads visible.")
        pending = getattr(self, '_pending_bundled_model_path', '')
        if pending:
            idx = self.bundled_model_combo.findData(pending)
            if idx >= 0:
                self.bundled_model_combo.setCurrentIndex(idx)
        self.on_provider_changed()

    def refresh_ollama_models(self, quiet: bool = False):
        if not hasattr(self, 'ollama_model_combo'):
            return
        host = self.ollama_host_input.text().strip() if hasattr(self, 'ollama_host_input') else 'http://localhost:11434'
        current = self.ollama_model_combo.currentText().strip()
        self.ollama_model_combo.clear()
        try:
            names = self.ollama_manager.list_models(host)
            self.ollama_model_combo.addItems(names)
            if current:
                self.ollama_model_combo.setEditText(current)
            if not quiet:
                self.status_signal.emit(f"Found {len(names)} Ollama models")
        except Exception as e:
            if current:
                self.ollama_model_combo.setEditText(current)
            if not quiet:
                self.status_signal.emit(f"Ollama scan failed: {e}")

    def on_provider_changed(self):
        provider = self.current_provider()
        bundled_enabled = provider == 'bundled_gguf'
        custom_enabled = provider == 'custom_gguf'
        ollama_enabled = provider == 'ollama'
        self.bundled_model_combo.setEnabled(bundled_enabled)
        self.model_path_input.setEnabled(custom_enabled)
        self.ollama_host_input.setEnabled(ollama_enabled)
        self.ollama_model_combo.setEnabled(ollama_enabled)

    def resolve_selected_model_path(self) -> str:
        provider = self.current_provider()
        if provider == 'bundled_gguf':
            path = self.bundled_model_combo.currentData()
            if path:
                return str(path)
            else:
                print("⚠️ Bundled combo empty – using default model path.")
                return DEFAULT_MODEL_PATH
        return self.model_path_input.text().strip()

    def apply_recommended_setup(self):
        models = discover_gguf_models()
        try:
            ollama_models = self.ollama_manager.list_models(self.ollama_host_input.text().strip())
        except Exception:
            ollama_models = []
        rec = recommend_model_setup(models, detect_system_capabilities(), ollama_models)
        provider = rec.get('provider', 'bundled_gguf')
        idx = self.provider_combo.findData(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)
        if provider == 'bundled_gguf' and rec.get('path'):
            j = self.bundled_model_combo.findData(rec['path'])
            if j >= 0:
                self.bundled_model_combo.setCurrentIndex(j)
        elif provider == 'ollama' and rec.get('ollama_model'):
            self.ollama_model_combo.setEditText(rec['ollama_model'])
        self.system_recommendation_label.setText(rec.get('reason', 'Recommendation applied.'))
        self.status_signal.emit('Recommendation applied')

    def detect_optimal_settings(self):
        selected_path = self.resolve_selected_model_path()
        if selected_path:
            tuned = self._apply_hardware_recommendation_for_model(selected_path)
            if tuned.get("ok"):
                return
        sysinfo = detect_system_capabilities()
        optimal = recommend_optimal_settings(sysinfo)
        self.n_ctx_input.setValue(optimal['n_ctx'])
        self.n_gpu_layers_input.setValue(optimal['n_gpu_layers'])
        self.n_threads_input.setValue(optimal['n_threads'])
        self.batch_size_input.setValue(optimal.get('batch_size', 128))
        self.temperature_input.setValue(optimal['temperature'])
        self.max_tokens_input.setValue(optimal['max_tokens'])
        self.status_signal.emit(
            f"Auto-detected: ctx={optimal['n_ctx']}  gpu={optimal['n_gpu_layers']}  "
            f"threads={optimal['n_threads']}  batch={optimal.get('batch_size', 128)}"
        )
        try:
            self.save_settings(silent=True)
        except Exception as _se:
            log.debug(f"[SETTINGS] Auto-save after detect_optimal failed: {_se}")

    def _apply_hardware_recommendation_for_model(self, model_path: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "model_path": model_path}
        dock = self._ensure_hardware_tuning_dock()
        if dock is not None:
            dock.show()
            dock.raise_()
            dock.set_status("Running hardware tuning…")
            dock.set_summary(f"Model: {Path(model_path).name}")
            dock.log_view.clear()
            self._toggle_hardware_tuning_dock(True)
        self._hardware_tuning_log(f"Starting tuning for {model_path}")
        try:
            from eli.core.hardware_profile import detect_hardware as _hp_detect
            from eli.core.hardware_profile import recommend as _hp_recommend
            _gpu_support = None
            try:
                from llama_cpp import llama_cpp as _llama_native
                _supports_fn = getattr(_llama_native, "llama_supports_gpu_offload", None)
                _gpu_support = bool(_supports_fn()) if callable(_supports_fn) else None
                self._hardware_tuning_log(f"llama.cpp GPU offload support: {_gpu_support}")
            except Exception as _gpu_probe_err:
                self._hardware_tuning_log(f"llama.cpp GPU offload probe failed: {_gpu_probe_err}")

            model_file = resolve_model_path(model_path)
            if not model_file.exists():
                raise FileNotFoundError(f"Model not found: {model_file}")
            size_bytes = int(model_file.stat().st_size)
            hw = _hp_detect()
            rec = _hp_recommend(hw, [{
                "name": model_file.name,
                "path": str(model_file),
                "size_bytes": size_bytes,
                "size_gb": size_bytes / 1e9,
            }])

            # Runtime CUDA/backend may be unavailable even if VRAM probe reports
            # a GPU. In that case force CPU-safe values so the GUI does not keep
            # applying aggressive GPU-centric params.
            if _gpu_support is False:
                rec.n_gpu_layers = 0
                rec.batch_size = min(int(getattr(rec, "batch_size", 128) or 128), 128)
                self._hardware_tuning_log(
                    "GPU offload unavailable at runtime -> forcing CPU-safe tuning "
                    "(gpu_layers=0, batch<=128)."
                )

            self.n_ctx_input.setValue(int(rec.n_ctx))
            self.n_threads_input.setValue(int(rec.n_threads))
            self.n_gpu_layers_input.setValue(int(rec.n_gpu_layers))
            self.batch_size_input.setValue(int(rec.batch_size))
            # UI spinbox does not allow -1 sentinel, so use a context-scaled cap.
            _max_tok = int(rec.max_tokens)
            if _max_tok <= 0:
                _max_tok = max(1024, min(int(rec.n_ctx // 4), int(self.max_tokens_input.maximum())))
            self.max_tokens_input.setValue(max(int(self.max_tokens_input.minimum()), min(int(self.max_tokens_input.maximum()), _max_tok)))
            self.temperature_input.setValue(float(rec.temperature))

            _ck = str(getattr(rec, "cache_type_k", "") or "")
            _cv = str(getattr(rec, "cache_type_v", "") or "")
            _ki = self.cache_type_k_combo.findText(_ck)
            if _ki < 0 and _ck:
                self.cache_type_k_combo.addItem(_ck)
                _ki = self.cache_type_k_combo.findText(_ck)
            if _ki >= 0:
                self.cache_type_k_combo.setCurrentIndex(_ki)
            _vi = self.cache_type_v_combo.findText(_cv)
            if _vi < 0 and _cv:
                self.cache_type_v_combo.addItem(_cv)
                _vi = self.cache_type_v_combo.findText(_cv)
            if _vi >= 0:
                self.cache_type_v_combo.setCurrentIndex(_vi)

            for line in list(getattr(rec, "reasoning", []) or []):
                self._hardware_tuning_log(str(line))

            summary = (
                f"Applied: ctx={int(rec.n_ctx)} gpu_layers={int(rec.n_gpu_layers)} "
                f"threads={int(rec.n_threads)} batch={int(rec.batch_size)} "
                f"kv={_ck or 'fp16'}"
            )
            self.system_recommendation_label.setText(summary)
            if dock is not None:
                dock.set_status("Tuning complete")
                dock.set_summary(summary)
            self.status_signal.emit(summary)

            # Persist tuned values so CLI startup and next session see the same
            # parameters that the dock is reporting. Without this save, the disk
            # file keeps stale defaults and conflicts with what the dock shows.
            try:
                self.save_settings(silent=True)
                self._hardware_tuning_log("Settings saved — CLI and next session will use these values.")
            except Exception as _save_err:
                self._hardware_tuning_log(f"Warning: auto-save after tuning failed: {_save_err}")

            result.update({"ok": True, "recommendation": rec.to_dict() if hasattr(rec, "to_dict") else {}})
            return result
        except Exception as e:
            msg = f"Hardware tuning failed: {e}"
            self._hardware_tuning_log(msg)
            if dock is not None:
                dock.set_status("Tuning failed")
                dock.set_summary(msg)
            log.debug(f"[SETTINGS] {msg}")
            result["error"] = str(e)
            return result

    def _run_startup_model_picker(self) -> bool:
        models = discover_gguf_models()
        ollama_names: List[str] = []
        try:
            ollama_names = self.ollama_manager.list_models(
                self.ollama_host_input.text().strip() if hasattr(self, "ollama_host_input") else "http://localhost:11434"
            )
        except Exception:
            ollama_names = []

        dlg = StartupModelSelectionDialog(
            parent=self,
            models=models,
            current_provider=self.current_provider(),
            current_model_path=self.resolve_selected_model_path(),
            ollama_host=self.ollama_host_input.text().strip() if hasattr(self, "ollama_host_input") else "http://localhost:11434",
            ollama_model=self.ollama_model_combo.currentText().strip() if hasattr(self, "ollama_model_combo") else "",
            ollama_models=ollama_names,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False

        provider = dlg.selected_provider()
        idx = self.provider_combo.findData(provider)
        if idx >= 0:
            self.provider_combo.setCurrentIndex(idx)

        if provider == "ollama":
            self.ollama_host_input.setText(dlg.selected_ollama_host())
            self.ollama_model_combo.setEditText(dlg.selected_ollama_model())
        else:
            selected_path = dlg.selected_model_path()
            if provider == "bundled_gguf":
                j = self.bundled_model_combo.findData(selected_path)
                if j >= 0:
                    self.bundled_model_combo.setCurrentIndex(j)
                else:
                    _custom_idx = self.provider_combo.findData("custom_gguf")
                    if _custom_idx >= 0:
                        self.provider_combo.setCurrentIndex(_custom_idx)
                    self.model_path_input.setText(selected_path)
            else:
                self.model_path_input.setText(selected_path)

            if selected_path:
                tune_result = self._apply_hardware_recommendation_for_model(selected_path)
                if not bool(tune_result.get("ok")):
                    try:
                        QMessageBox.warning(
                            self,
                            "Hardware tuning failed",
                            "Could not derive/apply hardware-optimal settings for the selected model. "
                            "Model load was cancelled.",
                        )
                    except Exception:
                        pass
                    return False

        self._first_run_complete = True
        self.save_settings(silent=True)
        if dlg.should_load_now():
            self.load_model()
        return True

    def maybe_run_first_time_setup(self):
        try:
            # Skip auto-load if the launcher already wired a model
            if getattr(self, 'active_backend', None) and getattr(self.active_backend, 'is_loaded', False):
                return
            if getattr(self, "_startup_model_prompt_done", False):
                return
            self._startup_model_prompt_done = True

            if hasattr(self, "startup_model_picker_checkbox"):
                self._show_startup_model_picker = bool(self.startup_model_picker_checkbox.isChecked())

            if self._show_startup_model_picker:
                self._run_startup_model_picker()
                # Model loading is selection-driven from the picker itself.
                # Never fall through to auto-load when picker is enabled.
                return

            if self.auto_load_checkbox.isChecked():
                self.load_model()
        except Exception as e:
            log.debug(f'[FIRST RUN] setup warning: {e}')

    def _text_backend_ready(self, notify: bool = True):
        backend = self.get_active_backend()
        if backend and getattr(backend, 'is_loaded', False):
            return backend
        if notify:
            try:
                _eli_color = getattr(self, '_eli_text_color', '#88c0d0')
                if getattr(self, '_model_loading', False):
                    self.chat_display.append(
                        f'\n<b><span style="color:{_eli_color};">ELI:</span></b>'
                        f'<br>Still loading the model — give me just a moment. '
                        f'Once the status bar turns green I\'ll be ready to go.<br>'
                    )
                else:
                    self.chat_display.append(
                        f'\n<b><span style="color:{_eli_color};">ELI:</span></b>'
                        f'<br>No model is loaded yet. Open the <b>Settings</b> tab '
                        f'or use the <b>Model</b> menu to load one.<br>'
                    )
            except Exception:
                log.debug('[WARN] Model not loaded')
        return None

    def get_active_backend(self):
        return self.ollama_manager if self.current_provider() == 'ollama' else model_manager

    # ---------- Event Handlers ----------
    def eventFilter(self, obj, event):
        if obj == self.chat_input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                mods = event.modifiers()
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    return False  # Shift+Enter — let Qt insert a newline
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    def prompt_load_model(self):
        self._run_startup_model_picker()

    def load_model(self):
        provider = self.current_provider()
        if provider != "ollama":
            selected_path = self.resolve_selected_model_path()
            if selected_path:
                tune_result = self._apply_hardware_recommendation_for_model(selected_path)
                if not bool(tune_result.get("ok")):
                    self.status_signal.emit("🔴 Hardware tuning failed; model load cancelled")
                    return

        n_ctx = self.n_ctx_input.value()
        n_threads = self.n_threads_input.value()
        n_gpu_layers = self.n_gpu_layers_input.value()
        batch_size = self.batch_size_input.value()
        cache_type_k = self.cache_type_k_combo.currentText().strip()
        cache_type_v = self.cache_type_v_combo.currentText().strip()
        use_mmap = True
        use_mlock = False
        try:
            from eli.core.runtime_settings import load_settings as _rs_load
            _s = _rs_load() or {}
            use_mmap = bool(_s.get("use_mmap", True))
            use_mlock = bool(_s.get("use_mlock", False))
        except Exception:
            pass
        self.status_signal.emit("🔄 Loading model...")
        self.status_signal.emit("Send disabled")
        try:
            self.send_btn.setText("Loading...")
        except Exception:
            pass

        def load_worker():
            self._model_loading = True
            try:
                if provider == 'ollama':
                    host = self.ollama_host_input.text().strip()
                    model_name = self.ollama_model_combo.currentText().strip()
                    success = self.ollama_manager.load_model(host, model_name)
                    backend = self.ollama_manager
                    model_name_display = model_name
                else:
                    model_path = self.resolve_selected_model_path()
                    success = model_manager.load_model(
                        model_path=model_path,
                        n_ctx=n_ctx,
                        n_threads=n_threads,
                        n_gpu_layers=n_gpu_layers,
                        n_batch=batch_size,
                        cache_type_k=cache_type_k,
                        cache_type_v=cache_type_v,
                        use_mmap=use_mmap,
                        use_mlock=use_mlock,
                    )
                    backend = model_manager
                    model_name_display = Path(getattr(model_manager, 'model_path', model_path or 'model')).name

                if success:
                    self.active_backend = backend
                    memory_system.log_event('model_load', f"Loaded {model_name_display} via {provider}")
                    if provider != "ollama":
                        self.status_signal.emit(
                            f"🟢 Model ready: {model_name_display} "
                            f"(ctx={int(getattr(model_manager, 'n_ctx', 0) or 0)} "
                            f"gpu={int(getattr(model_manager, 'n_gpu_layers', 0) or 0)} "
                            f"batch={int(getattr(model_manager, 'n_batch', 0) or 0)})"
                        )
                    else:
                        self.status_signal.emit(f"🟢 Model ready: {model_name_display}")
                    try:
                        if provider != "ollama":
                            _requested_gpu = int(getattr(model_manager, "requested_n_gpu_layers", 0) or 0)
                            _effective_gpu = int(getattr(model_manager, "n_gpu_layers", 0) or 0)
                            _gpu_supported = getattr(model_manager, "gpu_offload_supported", None)
                            if _requested_gpu > 0 and (_gpu_supported is False or _effective_gpu <= 0):
                                self.status_signal.emit(
                                    "⚠️ GPU offload unavailable; running CPU-only. "
                                    "Check NVIDIA driver/CUDA runtime."
                                )
                    except Exception:
                        pass
                    self.status_signal.emit("Send enabled")
                else:
                    err = getattr(backend, 'load_error', None) or 'Unknown error'
                    self.status_signal.emit(f"🔴 Model load failed: {err}")
                    self.status_signal.emit("🔴 Model: Not loaded")
                    self.status_signal.emit("Send enabled")
                    print(f"Model Load Error: {err}")
            finally:
                self._model_loading = False
                self.status_signal.emit("Ready")

        threading.Thread(target=load_worker, daemon=True).start()

    def load_model_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GGUF Model",
            str(Path.home()),
            "GGUF Files (*.gguf);;All Files (*)"
        )
        if file_path:
            idx = self.provider_combo.findData('custom_gguf')
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self.model_path_input.setText(file_path)

    def unload_model(self):
        self.get_active_backend().unload()
        self.status_signal.emit("🔴 Model: Not loaded")
        self.status_signal.emit("Send enabled")

    def _resolve_dropped_attachments(self, raw_text: str, dropped_paths: list) -> str:
        """Expand [Image:], [File:], [PDF:] tags into inline content for LLM context."""
        import re as _re
        from pathlib import Path as _P

        # Extract tags from the raw text
        tag_pattern = _re.compile(r'\[(Image|File|PDF):\s*(.+?)\]')
        extras = []
        for m in tag_pattern.finditer(raw_text):
            kind, path = m.group(1), m.group(2).strip()
            p = _P(path)
            if not p.exists():
                continue
            if kind == "Image":
                extras.append(f"[Attached image: {p.name} — path: {path}]")
            elif kind == "PDF":
                try:
                    import pdfplumber
                    with pdfplumber.open(str(p)) as _pdf:
                        text = "\n".join(pg.extract_text() or "" for pg in _pdf.pages[:6])
                except Exception:
                    try:
                        from pypdf import PdfReader
                        r = PdfReader(str(p))
                        text = "\n".join(pg.extract_text() or "" for pg in r.pages[:6])
                    except Exception:
                        text = "[Could not extract PDF text]"
                extras.append(f"[PDF content — {p.name}]:\n{text[:4000]}")
            else:
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")[:4000]
                    extras.append(f"[File content — {p.name}]:\n{text}")
                except Exception as e:
                    extras.append(f"[File: {p.name} — could not read: {e}]")

        # Strip the tags from the visible message, append content
        clean = tag_pattern.sub("", raw_text).strip()
        if extras:
            clean = clean + "\n\n" + "\n\n".join(extras)
        return clean

    def send_message(self):
        if self.is_generating:
            return
        user_message = self.chat_input.toPlainText().strip()
        if not user_message:
            return

        # Auto reasoning-mode selection (toggle on the bottom row controls it)
        try:
            self._maybe_auto_select_reasoning_mode(user_message)
        except Exception as _amx:
            log.debug(f"[GUI] auto reasoning-mode selection failed: {_amx}")

        # Resolve any drag-and-drop attachments into inline context
        dropped_paths = list(getattr(self.chat_input, "_dropped_paths", []))
        if dropped_paths or any(t in user_message for t in ("[Image:", "[File:", "[PDF:")):
            user_message = self._resolve_dropped_attachments(user_message, dropped_paths)
            if hasattr(self.chat_input, "_dropped_paths"):
                self.chat_input._dropped_paths.clear()

        _uc = getattr(self, '_user_text_color', '#a3be8c')
        self.chat_display.append(
            f'\n<b><span style="color:{_uc};">🧑 You [{now_hms()}]:</span></b>'
            f'<br>{user_message}<br>'
        )
        self.chat_input.clear()
        self.conversation_history.append({'role': 'user', 'content': user_message})

        # ── Agent wizard intercept ──────────────────────────────────────────
        if self._agent_wizard_state is not None:
            self._handle_wizard_input(user_message)
            return
        # ───────────────────────────────────────────────────────────────────

        image_prompt = self._extract_image_prompt_from_chat(user_message)
        if image_prompt:
            self._start_chat_image_request(image_prompt, source_text=user_message)
            return

        # Normal chat input always goes through CognitiveEngine.process().
        # Direct executor dispatch is reserved for explicit Quick Action buttons,
        # otherwise routed commands can bypass agent evidence and final synthesis.

        backend = self._text_backend_ready(notify=True)
        if backend is None:
            return

        self.is_generating = True
        self.status_signal.emit('Send disabled')
        self.send_btn.setText('Generating...')
        self.status_signal.emit('🔄 Generating response...')

        def generate_worker():
            try:
                max_tokens  = self.max_tokens_input.value()
                temperature = self.temperature_input.value()
                reasoning_mode = getattr(self, '_reasoning_mode', 'quick')
                n_ctx = getattr(backend, 'n_ctx', 4096)

                # ── CognitiveEngine-first runtime path ──
                adapter = _GUIEngineAdapter(
                    backend          = backend,
                    memory           = self._central_memory,
                    max_tokens       = max_tokens,
                    temperature      = temperature,
                    n_ctx            = n_ctx,
                    inference_lock   = self.__class__._inference_lock,
                    cognitive_engine = getattr(self, '_cognitive_engine', None),
                )

                _ce = getattr(self, '_cognitive_engine', None)
                _ce_ok = False
                _orchestrator_ok = False

                if _ce is not None:
                    log.debug("[GUI] PATH1 -> CognitiveEngine.process (orchestrator owned inside CE)")
                    try:
                        result = _ce.process(
                            user_message,
                            stream=True,
                            reasoning_mode=reasoning_mode,
                        )
                        _ce_ok = True
                    except Exception as _ce_err:
                        log.debug(f"[GUI] CognitiveEngine.process failed: {_ce_err}")
                        result = None

                if not _ce_ok:
                    log.debug("[GUI] PATH2 removed -> falling back to direct backend only if CognitiveEngine fails")
                    result = None

                full_tokens = []
                _response_streamed = False
                _storage_handled = False  # CognitiveEngine stores turns internally

                import types as _types

                if (_ce_ok or _orchestrator_ok) and result is not None:
                    if isinstance(result, (_types.GeneratorType,)) or hasattr(result, '__next__'):
                        # ── Streaming CHAT response ──
                        first_token = True
                        for token in result:
                            token = str(token or "")
                            if not token:
                                continue
                            full_tokens.append(token)
                            if first_token:
                                self.chat_response_signal.emit('__STREAM_START__')
                                first_token = False
                            self.chat_response_signal.emit(token)
                        if first_token:
                            # The engine's _stream_chat() handles all internal
                            # recovery (Stage 11 → direct GGUF fallback → fault message).
                            # A zero-token generator here means a truly silent action
                            # (e.g. VOLUME) that intentionally produces no visible output.
                            # Do NOT re-call process() — that would execute the action twice.
                            log.debug("[GUI] Stream generator produced zero tokens (silent action or suppressed output).")
                            response = ""
                            _response_streamed = True
                            _storage_handled = True
                        else:
                            self.chat_response_signal.emit('__STREAM_END__')
                            _response_streamed = True
                            response = ''.join(full_tokens)
                        if _ce_ok:
                            # CognitiveEngine stores turns in its finalization paths.
                            _storage_handled = True
                    elif isinstance(result, dict):
                        # ── Action result or non-streaming CHAT ──
                        try:
                            self._generated_artifact_open_sig.emit(dict(result))
                        except Exception as _artifact_emit_err:
                            log.debug(f"[GUI] generated artifact open signal failed: {_artifact_emit_err}")
                        response = _eli_gui_visible_text(result)
                        if _ce_ok:
                            _storage_handled = True
                    else:
                        response = _eli_gui_visible_text(result)
                else:
                    # ── PATH 3: Direct backend fallback (all pipelines failed) ──
                    memory_context = self._retrieve_relevant_memories(user_message, limit=10)
                    system_prompt  = ELI_SYSTEM_PROMPT + self._get_mode_prefix()
                    if memory_context:
                        system_prompt += "\n\n" + memory_context
                    messages = [{'role': 'system', 'content': system_prompt}]
                    messages.extend(self.conversation_history[-10:])
                    with self.__class__._inference_lock:
                        if hasattr(backend, 'chat_stream'):
                            first_token = True
                            for token in backend.chat_stream(
                                    messages, max_tokens=max_tokens, temperature=temperature):
                                full_tokens.append(token)
                                if first_token:
                                    self.chat_response_signal.emit('__STREAM_START__')
                                    first_token = False
                                self.chat_response_signal.emit(token)
                            self.chat_response_signal.emit('__STREAM_END__')
                            _response_streamed = True
                            response = ''.join(full_tokens)
                        else:
                            response = backend.chat(
                                messages=messages,
                                max_tokens=max_tokens,
                                temperature=temperature,
                            )

                # ── Identity / persona guardrails ──
                low = response.lower()
                banned = [
                    'i am an ai model', 'as an ai assistant', 'trained on',
                    "memory is part of my training data",
                    "i don't retain new information",
                    'each interaction is independent',
                    'i am a large language model',
                    'i do not retain personal data',
                    "i don't have memory of past conversations",
                    'i cannot remember previous interactions',
                ]
                if any(b in low for b in banned):
                    response = "⚠️ Empty response from backend."

                try:
                    from eli.cognition.reasoning_modes import apply_final_reasoning_contract as _rm_final
                    response = _rm_final(response)
                except Exception:
                    pass

                self.conversation_history.append({'role': 'assistant', 'content': response})
                self._last_eli_response = response

                # ── Persist to conversation_turns table (skip if CognitiveEngine stored) ──
                if not _storage_handled:
                    try:
                        # Canonical persistence lives in CognitiveEngine.
                        # GUI direct SQLite fallback disabled to prevent duplicate rows.
                        pass
                    except Exception:
                        pass

                if not _response_streamed:
                    self.chat_response_signal.emit(response)

                if getattr(self, '_tts_auto', False):
                    self._speak_response(response)
                self._mem_refresh_sig.emit()
                # Refresh confidence/grounding badge in status bar (via queued signal — worker thread safe)
                try:
                    self._conf_meta_update_sig.emit()
                except Exception:
                    pass

            except Exception as e:
                self.chat_response_signal.emit(f"❌ Error: {str(e)}")
                try:
                    import sqlite3 as _sq2, time as _t2, traceback as _tb2
                    from eli.core.paths import memory_db_path as _mdp
                    _c2 = _sq2.connect(str(_mdp()))
                    _c2.execute(
                        "CREATE TABLE IF NOT EXISTS failures "
                        "(id INTEGER PRIMARY KEY, ts REAL, user_input TEXT, error TEXT, traceback TEXT)")
                    _c2.execute(
                        "INSERT INTO failures (ts, user_input, error, traceback) VALUES (?,?,?,?)",
                        (_t2.time(), str(locals().get('user_message', ''))[:500],
                         str(e)[:500], _tb2.format_exc()[:1000]))
                    _c2.commit(); _c2.close()
                except Exception:
                    pass
            finally:
                self.is_generating = False
                self.status_signal.emit('Send enabled')
                self.status_signal.emit('🟢 Ready')

        threading.Thread(target=generate_worker, daemon=True).start()

    # ---------- Chat management methods ----------
    def clear_chat(self):
        reply = QMessageBox.question(
            self,
            "Clear Chat",
            "Are you sure you want to clear the conversation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.chat_display.clear()
            self.conversation_history = []
            self.status_signal.emit("Chat cleared")

    def new_conversation(self):
        if self.conversation_history:
            self.save_conversation()
        self.clear_chat()

    def save_conversation(self):
        if not self.conversation_history:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = CONVERSATIONS_DIR / f"conversation_{timestamp}.json"
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    "timestamp": now_timestamp(),
                    "messages": self.conversation_history
                }, f, indent=2, ensure_ascii=False)
            self.status_signal.emit(f"Conversation saved: {filename.name}")
        except Exception as e:
            QMessageBox.warning(self, "Save Error", f"Failed to save: {str(e)}")

    # ---------- Memory tab methods ----------
    def refresh_memory_stats(self):
        stats = memory_system.get_stats()
        total = stats.get("total", 0)
        by_kind = stats.get("by_kind", {})
        stats_text = f"Total Memories: {total}\n\n"
        stats_text += "By Type:\n"
        for kind, count in by_kind.items():
            stats_text += f"  • {kind}: {count}\n"
        self.memory_stats_label.setText(stats_text)

    def search_memory(self):
        query = self.memory_search_input.text().strip()
        if not query:
            return
        self.memory_results_display.clear()
        self.memory_results_display.append(f"<b>Searching for:</b> {query}<br><br>")
        results = memory_system.search(query, limit=20)
        if results:
            self.memory_results_display.append(f"<b>Found {len(results)} results:</b><br><br>")
            for i, mem in enumerate(results, 1):
                ts = mem.get('timestamp') or mem.get('ts','')
                if isinstance(ts, float):
                    import datetime
                    ts = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                self.memory_results_display.append(
                    f"<b>{i}. [{ts}] ({mem.get('kind','?')})</b><br>"
                    f"{mem.get('text','')}<br>"
                    f"<i>Tags: {mem.get('tags','')}</i><br><br>"
                )
        else:
            self.memory_results_display.append("<i>No memories found.</i>")

    def store_memory(self):
        text = self.memory_store_input.toPlainText().strip()
        if not text:
            return
        tags_text = self.memory_tags_input.text().strip()
        tags = [t.strip() for t in tags_text.split(",")] if tags_text else []
        if memory_system.store(text, tags=tags):
            QMessageBox.information(self, "Success", "Memory stored successfully!")
            self.memory_store_input.clear()
            self.memory_tags_input.clear()
            self.refresh_memory_stats()
        else:
            QMessageBox.warning(self, "Error", "Failed to store memory.")

    def show_recent_memories(self):
        self.memory_results_display.clear()
        self.memory_results_display.append("<b>Recent Memories:</b><br><br>")
        results = memory_system.get_recent(limit=20)
        if results:
            for i, mem in enumerate(results, 1):
                ts = mem.get('timestamp') or mem.get('ts','')
                if isinstance(ts, float):
                    import datetime
                    ts = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
                self.memory_results_display.append(
                    f"<b>{i}. [{ts}] ({mem.get('kind','?')})</b><br>"
                    f"{mem.get('text','')}<br>"
                    f"<i>Tags: {mem.get('tags','')}</i><br><br>"
                )
        else:
            self.memory_results_display.append("<i>No memories found.</i>")

    # ---------- Proactive tab methods (thread‑safe) ----------
    def _update_suggestions_display(self, html: str):
        from datetime import datetime as _dt
        import re as _re

        event_no = int(getattr(self, "_proactive_event_count", 0) or 0) + 1
        self._proactive_event_count = event_no
        stamp = _dt.now().strftime("%H:%M:%S")
        plain = _re.sub(r'<[^>]+>', '', html)[:300]

        entry = (
            f"<div style='margin:6px 0;padding:8px;border-left:3px solid #88c0d0;'>"
            f"<b>Proactive #{event_no} · {stamp}</b><br>{html}</div>"
        )
        self.suggestions_display.append(entry)

        # Update tab label and status bar
        try:
            for _i in range(self.tabs.count()):
                if "Proactive" in self.tabs.tabText(_i):
                    self.tabs.setTabText(_i, f"🎯 Proactive ({event_no})")
                    break
        except Exception:
            pass
        self._update_proactive_status_label()

        # Forward to ProactiveDock (hidden by default — don't auto-show or auto-speak)
        if self._proactive_dock is not None:
            self._proactive_dock.post_message(f"[{stamp}] #{event_no}: {plain}")
            # TTS only if user explicitly opened dock AND toggled TTS on
            if self._proactive_dock.isVisible() and self._proactive_dock.tts_toggle.isChecked():
                try:
                    from eli.perception.tts_router import maybe_speak
                    maybe_speak(plain, enabled=True)
                except Exception:
                    pass

    def _update_confidence_meta_label(self):
        """Refresh the status-bar confidence/grounding badge from engine._last_request_meta."""
        label = getattr(self, "_confidence_meta_label", None)
        if label is None:
            return
        try:
            ce = getattr(self, "_cognitive_engine", None)
            meta = dict(getattr(ce, "_last_request_meta", {}) or {}) if ce is not None else {}
            if not meta:
                label.setText("")
                return
            agg = meta.get("aggregated_confidence") or meta.get("confidence")
            grnd = meta.get("grounding_confidence")
            lbl = meta.get("confidence_label", "")
            action = meta.get("result_action") or meta.get("action") or ""
            parts = []
            if agg is not None:
                try:
                    _a = float(agg)
                    parts.append(f"conf {_a:.2f}" + (f" ({lbl})" if lbl else ""))
                except Exception:
                    pass
            if grnd is not None:
                try:
                    _g = float(grnd)
                    grnd_tag = "✓" if _g >= 0.40 else ("~" if _g >= 0.10 else "⚠")
                    parts.append(f"grounding {grnd_tag}{_g:.2f}")
                except Exception:
                    pass
            if action:
                parts.append(action)
            label.setText("  " + "  |  ".join(parts) + "  " if parts else "")
            label.setToolTip(
                f"Last response metadata:\n"
                + "\n".join(f"  {k}: {v}" for k, v in sorted(meta.items()))
            )
        except Exception:
            pass

    def _update_proactive_status_label(self):
        """Refresh the status-bar proactive indicator."""
        label = getattr(self, "_proactive_status_label", None)
        if label is None:
            return
        daemon = getattr(self, "_proactive_daemon", None)
        # daemon being set means it was started; running flag lags by one thread tick
        if daemon is not None:
            count = getattr(self, "_proactive_event_count", 0)
            label.setText(f"  🟢 Proactive: active  |  events: {count}  ")
            label.setToolTip("ELI proactive daemon is running. See 🎯 Proactive tab.")
        else:
            label.setText("  🔴 Proactive: off  ")
            label.setToolTip("Proactive daemon is not running.")

    def _check_proactive_daemon_crash(self):
        """Check for a proactive daemon crash flag and surface it to the user.

        The proactive daemon writes artifacts/proactive_daemon_down.flag when it
        crashes.  This method reads that flag, shows a status-bar warning with a
        restart button, and clears the flag once acknowledged.
        """
        try:
            from eli.core.paths import get_paths as _gp
            flag_path = _gp().artifacts_dir / "proactive_daemon_down.flag"
            if not flag_path.exists():
                return
            crash_msg = flag_path.read_text(encoding="utf-8", errors="replace").strip()
            flag_path.unlink(missing_ok=True)

            label = getattr(self, "_proactive_status_label", None)
            if label is not None:
                label.setText("  ⚠️ Proactive: crashed  ")
                label.setToolTip(
                    f"Proactive daemon crashed: {crash_msg[:120]}\n"
                    "Click to restart."
                )
                # One-shot: clicking the label attempts to restart the daemon
                try:
                    label.mousePressEvent = lambda _e: self._restart_proactive_daemon()
                except Exception:
                    pass

            log.debug(f"[GUI] Proactive daemon crash detected: {crash_msg[:200]}")
        except Exception:
            pass

    def _restart_proactive_daemon(self):
        """Attempt to restart the proactive daemon after a crash."""
        try:
            from eli.planning.proactive_daemon import start_daemon as _start_pd
            self._proactive_daemon = _start_pd()
            log.debug("[GUI] Proactive daemon restarted.")
            self._update_proactive_status_label()
        except Exception as exc:
            log.debug(f"[GUI] Failed to restart proactive daemon: {exc}")

    def _update_summary_display(self, html: str):
        self.summaries_display.clear()
        self.summaries_display.append(html)

    def _update_insights_display(self, html: str):
        self.insights_display.clear()
        self.insights_display.append(html)

    def _build_proactive_ground_truth(self, query: str = "") -> dict:
        """
        Gather live grounded data from every available ELI subsystem.
        Returns a dict with all evidence for use in proactive methods.
        """
        import sqlite3 as _sq, json as _json
        ground = {
            "memories": [],
            "recent_conv": [],
            "daemon_patterns": [],
            "agent_obs": [],
            "agent_errors": [],
            "agent_improvements": [],
            "bus_context": "",
            "memory_stats": {},
            "faiss_count": 0,
            "habit_rules": [],
        }

        # 1. FTS5 + FAISS memory recall on query / recent topic
        if self._central_memory:
            _q = query or " ".join(
                m.get("content", "")[:100] for m in self.conversation_history[-3:]
                if m.get("role") == "user"
            )
            try:
                ground["memories"] = self._central_memory.recall_memory(_q[:300], limit=10) or []
            except Exception: pass
            try:
                ground["recent_conv"] = self._central_memory.get_recent_conversation(limit=20) or []
            except Exception: pass
            try:
                ground["memory_stats"] = memory_system.get_stats() if memory_system else {}
            except Exception: pass
            try:
                vs = getattr(self._central_memory, "vector_store", None)
                if vs:
                    ground["faiss_count"] = vs.ntotal
            except Exception: pass

        # 2. Proactive daemon patterns (live analysis)
        if self._proactive_daemon:
            try:
                ground["daemon_patterns"] = self._proactive_daemon.analyze_user_patterns() or []
            except Exception: pass
            try:
                mem_h = self._proactive_daemon.user_mem
                if mem_h and hasattr(mem_h, "get_habit_rules"):
                    ground["habit_rules"] = mem_h.get_habit_rules(enabled_only=True) or []
            except Exception: pass

        # 3. Agent DB: errors, improvements, observations
        try:
            from eli.core.paths import agent_db_path as _adp
            _acon = _sq.connect(str(_adp()))
            _acon.row_factory = _sq.Row
            try:
                ground["agent_errors"] = [dict(r) for r in _acon.execute(
                    "SELECT user_input, error, occurrence_count FROM failures "
                    "ORDER BY timestamp DESC LIMIT 8").fetchall()]
            except Exception: pass
            try:
                ground["agent_improvements"] = [dict(r) for r in _acon.execute(
                    "SELECT category, detail FROM improvements "
                    "ORDER BY timestamp DESC LIMIT 8").fetchall()]
            except Exception: pass
            try:
                for (content,) in _acon.execute(
                        "SELECT content FROM observations ORDER BY ts DESC LIMIT 5").fetchall():
                    try:
                        items = _json.loads(content or "[]")
                        ground["agent_obs"].extend(
                            items if isinstance(items, list) else [items])
                    except Exception:
                        ground["agent_obs"].append({"raw": str(content)[:150]})
            except Exception: pass
            _acon.close()
        except Exception: pass

        # 4. AgentBus dispatch (13 specialist agents — SQLite-only, fast)
        try:
            from eli.cognition.agent_bus import get_bus as _gb
            _last_user = next(
                (m["content"] for m in reversed(self.conversation_history)
                 if m.get("role") == "user"), query or "proactive analysis")
            _dr = _gb().dispatch(_last_user, {"action": "CHAT"},
                                 session_id="proactive-gui", user_id="local-user")
            ground["bus_context"] = (_dr.memory_context or "")[:1200]
        except Exception: pass

        return ground

    def generate_suggestions(self):
        backend = self._text_backend_ready(notify=False)
        if backend is None:
            self.status_signal.emit('⚠️ Load a model first to generate suggestions.')
            return

        self.suggestions_display.clear()
        self.suggestions_display.append('<i>🔮 Generating grounded suggestions — please wait...</i>')

        def worker():
            try:
                g = self._build_proactive_ground_truth()

                # Build rich context from actual data
                parts = []

                conv_lines = [
                    f"{'User' if m['role']=='user' else 'ELI'}: {m['content'][:200]}"
                    for m in self.conversation_history[-8:]
                ]
                if conv_lines:
                    parts.append("RECENT CONVERSATION:\n" + "\n".join(conv_lines))

                if g["memories"]:
                    mem_lines = [f"• {m.get('text','')[:160]}" for m in g["memories"][:6]]
                    parts.append(f"RETRIEVED MEMORIES (FTS5+FAISS, {g['faiss_count']} vectors indexed):\n"
                                 + "\n".join(mem_lines))

                if g["daemon_patterns"]:
                    pat_lines = [f"• [{p.get('type','')}] {p.get('suggestion','')} "
                                 f"{'(×'+str(p['count'])+')' if p.get('count') else ''}"
                                 for p in g["daemon_patterns"][:5]]
                    parts.append("DETECTED USAGE PATTERNS:\n" + "\n".join(pat_lines))

                if g["habit_rules"]:
                    rule_lines = [f"• {r.get('name','?')} @ "
                                  f"{r.get('hour',0):02d}:{r.get('minute',0):02d}"
                                  for r in g["habit_rules"][:4]]
                    parts.append("ACTIVE HABIT RULES:\n" + "\n".join(rule_lines))

                if g["agent_errors"]:
                    err_lines = [f"• {e.get('error','')[:100]} (×{e.get('occurrence_count',1)})"
                                 for e in g["agent_errors"][:4]]
                    parts.append("RECENT ERRORS (self-improvement backlog):\n" + "\n".join(err_lines))

                if g["bus_context"]:
                    parts.append(f"AGENT INTELLIGENCE:\n{g['bus_context'][:800]}")

                if g["agent_obs"]:
                    obs_lines = [f"• {str(o.get('suggestion') or o.get('phrase') or o)[:120]}"
                                 for o in g["agent_obs"][:4]]
                    parts.append("PROACTIVE OBSERVATIONS:\n" + "\n".join(obs_lines))

                grounded = "\n\n".join(parts) if parts else "No runtime data available yet."
                stats = g["memory_stats"]

                system = (
                    "You are ELI — a fully local AI assistant with persistent memory and self-awareness. "
                    "Generate 3-5 SPECIFIC, ACTIONABLE suggestions grounded ONLY in the data below. "
                    "Reference actual topics, memory items, patterns, errors, and habits by name. "
                    "NO generic advice. Every suggestion must cite its source data. "
                    "Format: numbered list. Each item: one clear action + why (from the data)."
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content":
                     f"Runtime context:\n{grounded}\n\n"
                     f"Memory: {stats.get('total',0)} entries, {g['faiss_count']} vectors. "
                     f"Session: {len(self.conversation_history)} turns.\n\n"
                     "What should I focus on next?"},
                ]
                temp = self.temperature_input.value() if hasattr(self, "temperature_input") else 0.5
                with self.__class__._inference_lock:
                    response = backend.chat(messages=messages, max_tokens=640, temperature=temp)

                src_note = (f"<small>Sources: {len(g['memories'])} memory hits · "
                            f"{len(g['daemon_patterns'])} patterns · "
                            f"{len(g['agent_errors'])} errors · "
                            f"{g['faiss_count']} FAISS vectors · AgentBus active</small>")
                self.proactive_suggestions_signal.emit(
                    f"<b>💡 ELI Proactive Suggestions</b><br>{src_note}<hr><br>{response}")
            except Exception as e:
                self.proactive_suggestions_signal.emit(f"❌ Error: {str(e)}")

        threading.Thread(target=worker, daemon=True).start()

    def generate_summary(self):
        backend = self._text_backend_ready(notify=False)
        if backend is None:
            self.status_signal.emit('⚠️ Load a model first to summarize.')
            return
        if not self.conversation_history:
            QMessageBox.information(self, 'No Conversation', 'No conversation to summarize.')
            return

        self.summaries_display.clear()
        self.summaries_display.append('📝 Generating grounded summary...')

        def worker():
            try:
                g = self._build_proactive_ground_truth()

                # Full conversation transcript
                conv_text = "\n".join(
                    f"{'User' if m['role']=='user' else 'ELI'}: {m['content'][:300]}"
                    for m in self.conversation_history
                )

                # Semantic memories triggered by this session
                mem_block = ""
                if g["memories"]:
                    mem_block = "\n\nRelated stored memories:\n" + "\n".join(
                        f"• {m.get('text','')[:180]}" for m in g["memories"][:5])

                # Agent insights
                bus_block = f"\n\nAgent context:\n{g['bus_context'][:600]}" if g["bus_context"] else ""

                system = (
                    "You are ELI. Produce a precise, factual summary of this conversation. "
                    "Extract: main topics, decisions made, open questions, action items. "
                    "Reference specific things said. No filler. No generic openers."
                )
                user_content = (
                    f"CONVERSATION TRANSCRIPT:\n{conv_text}"
                    f"{mem_block}{bus_block}\n\n"
                    f"Session: {len(self.conversation_history)} turns. "
                    f"Memory: {g['memory_stats'].get('total',0)} stored entries."
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_content},
                ]
                temp = self.temperature_input.value() if hasattr(self, "temperature_input") else 0.4
                with self.__class__._inference_lock:
                    response = backend.chat(messages=messages, max_tokens=700, temperature=temp)

                self.proactive_summary_signal.emit(
                    f"<b>📝 Conversation Summary</b> "
                    f"<small>({len(self.conversation_history)} turns · "
                    f"{g['memory_stats'].get('total',0)} memories · "
                    f"{g['faiss_count']} FAISS vectors)</small><hr><br>{response}")
            except Exception as e:
                self.proactive_summary_signal.emit(f"❌ Error: {str(e)}")

        threading.Thread(target=worker, daemon=True).start()

    def analyze_context(self):
        backend = self._text_backend_ready(notify=False)
        if backend is None:
            self.status_signal.emit('⚠️ Load a model first to analyze context.')
            return

        self.insights_display.clear()
        self.insights_display.append('🔬 Analyzing full ELI runtime context...')

        def worker():
            try:
                g = self._build_proactive_ground_truth()
                stats = g["memory_stats"]

                parts = []

                # Memory system state
                mem_block = (
                    f"MEMORY SYSTEM STATE:\n"
                    f"• Total memories: {stats.get('total',0)}\n"
                    f"• FAISS vectors indexed: {g['faiss_count']}\n"
                    f"• Memory by kind: {stats.get('by_kind',{})}\n"
                    f"• Conversation turns: {len(self.conversation_history)} (session)"
                )
                parts.append(mem_block)

                if g["memories"]:
                    parts.append("TOP RECALLED MEMORIES (FTS5+FAISS):\n" + "\n".join(
                        f"• [{m.get('_source','?')}] {m.get('text','')[:160]}"
                        for m in g["memories"][:6]))

                if g["daemon_patterns"]:
                    parts.append("DETECTED BEHAVIOURAL PATTERNS:\n" + "\n".join(
                        f"• [{p.get('type','')}] {p.get('suggestion','')} "
                        f"{'(×'+str(p['count'])+')' if p.get('count') else ''}"
                        for p in g["daemon_patterns"][:6]))

                if g["habit_rules"]:
                    parts.append("ACTIVE HABITS:\n" + "\n".join(
                        f"• {r.get('name','?')} at {r.get('hour',0):02d}:{r.get('minute',0):02d}"
                        for r in g["habit_rules"][:4]))

                if g["agent_errors"]:
                    parts.append("SELF-IMPROVEMENT BACKLOG (failures):\n" + "\n".join(
                        f"• {e.get('error','')[:100]} (×{e.get('occurrence_count',1)})"
                        for e in g["agent_errors"][:5]))

                if g["agent_improvements"]:
                    parts.append("RECENT IMPROVEMENTS LOGGED:\n" + "\n".join(
                        f"• [{i.get('category','')}] {i.get('detail','')[:120]}"
                        for i in g["agent_improvements"][:4]))

                if g["bus_context"]:
                    parts.append(f"AGENT BUS INTELLIGENCE:\n{g['bus_context'][:900]}")

                grounded = "\n\n".join(parts)

                system = (
                    "You are ELI — a self-aware local AI. Analyse the runtime state below. "
                    "Identify: cognitive strengths, memory gaps, failure patterns, "
                    "habit opportunities, and areas for self-improvement. "
                    "Be analytical and specific. Reference actual data. No generic observations."
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": f"RUNTIME STATE:\n{grounded}"},
                ]
                temp = self.temperature_input.value() if hasattr(self, "temperature_input") else 0.6
                with self.__class__._inference_lock:
                    response = backend.chat(messages=messages, max_tokens=700, temperature=temp)

                self.proactive_insights_signal.emit(
                    f"<b>🔬 ELI Runtime Analysis</b> "
                    f"<small>({stats.get('total',0)} memories · {g['faiss_count']} vectors · "
                    f"{len(g['daemon_patterns'])} patterns · {len(g['agent_errors'])} errors)</small>"
                    f"<hr><br>{response}")
            except Exception as e:
                self.proactive_insights_signal.emit(f"❌ Error: {str(e)}")

        threading.Thread(target=worker, daemon=True).start()

    # ---------- IDE, Documents, Files methods ----------
    def _focus_tab_widget(self, widget) -> None:
        try:
            idx = self.tabs.indexOf(widget)
            if idx >= 0:
                self.tabs.setCurrentIndex(idx)
        except Exception:
            pass

    def _load_path_into_main_ide(self, path: Path) -> bool:
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
            if QSCI_AVAILABLE:
                self.code_editor.setText(content)
            else:
                self.code_editor.setPlainText(content)
            self.current_file_path = str(path)
            self.current_file_label.setText(f"File: {path.name}")
            self._focus_tab_widget(getattr(self, "_ide_widget", None))
            self.status_signal.emit(f"Opened in IDE: {path.name}")
            return True
        except Exception as e:
            self.status_signal.emit(f"Failed to open generated script in IDE: {e}")
            return False

    def _load_path_into_labs_sim_ide(self, path: Path) -> bool:
        try:
            labs = getattr(self, "_labs_widget", None)
            sim = getattr(labs, "_sim_ide_tab", None)
            if labs is None or sim is None:
                return False
            content = path.read_text(encoding='utf-8', errors='replace')
            if hasattr(sim, "_set_code"):
                sim._set_code(content)
            elif hasattr(sim, "_editor"):
                editor = sim._editor
                if hasattr(editor, "setText"):
                    editor.setText(content)
                else:
                    editor.setPlainText(content)
            else:
                return False
            try:
                sim._current_file = path
                sim._file_label.setText(str(path))
            except Exception:
                pass
            try:
                inner = getattr(labs, "_inner_tabs", None)
                if inner is not None:
                    idx = inner.indexOf(sim)
                    if idx >= 0:
                        inner.setCurrentIndex(idx)
            except Exception:
                pass
            self._focus_tab_widget(labs)
            self.status_signal.emit(f"Opened in Labs Sim/IDE: {path.name}")
            return True
        except Exception as e:
            log.debug(f"[GUI] Labs Sim/IDE open failed: {e}")
            return False

    def _open_generated_artifact_from_result(self, result) -> None:
        if not isinstance(result, dict):
            return

        action = str(result.get("action") or "").upper()
        if action not in {
            "GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT",
            "FIX_FILE", "GENERATE_DOCUMENT", "CREATE_DOCUMENT",
            "CREATE_DOC", "WRITE_DOCUMENT",
        }:
            return

        raw_path = (
            result.get("script_path")
            or result.get("doc_path")
            or result.get("path")
            or result.get("file")
        )
        if not raw_path:
            return

        path = Path(str(raw_path)).expanduser()
        if not path.exists() or not path.is_file():
            self.status_signal.emit(f"Generated artifact path not found: {path}")
            return

        suffix = path.suffix.lower()
        wants_labs = bool(result.get("open_in_labs"))
        wants_ide = bool(result.get("open_in_ide"))
        is_script_action = action in {
            "GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT",
            "GENERATE_CODE", "WRITE_CODE", "FIX_FILE",
        }

        # Every generated script goes to the IDE tab — no extension whitelist.
        if is_script_action:
            if wants_labs and suffix == ".py" and self._load_path_into_labs_sim_ide(path):
                return
            self._load_path_into_main_ide(path)
            return

        if suffix in {".md", ".txt", ".log"}:
            try:
                self.open_text_file(path)
                self.status_signal.emit(f"Opened document: {path.name}")
            except Exception as e:
                self.status_signal.emit(f"Failed to open generated document: {e}")
            return

        if suffix == ".pdf":
            try:
                self.open_pdf(path)
                self.status_signal.emit(f"Opened PDF: {path.name}")
            except Exception as e:
                self.status_signal.emit(f"Failed to open generated PDF: {e}")
            return

    def ide_new_file(self):
        if QSCI_AVAILABLE:
            self.code_editor.clear()
        else:
            self.code_editor.clear()
        self.current_file_path = None
        self.current_file_label.setText("New file (unsaved)")

    def ide_open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open File",
            str(Path.home()),
            "Python Files (*.py);;All Files (*)"
        )
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                if QSCI_AVAILABLE:
                    self.code_editor.setText(content)
                else:
                    self.code_editor.setPlainText(content)
                self.current_file_path = file_path
                self.current_file_label.setText(f"File: {Path(file_path).name}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open file: {str(e)}")

    def ide_save_file(self):
        if not self.current_file_path:
            self.ide_save_as()
            return
        try:
            if QSCI_AVAILABLE:
                content = self.code_editor.text()
            else:
                content = self.code_editor.toPlainText()
            with open(self.current_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.status_signal.emit(f"Saved: {Path(self.current_file_path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file: {str(e)}")

    def ide_save_as(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save As",
            str(Path.home()),
            "Python Files (*.py);;All Files (*)"
        )
        if file_path:
            self.current_file_path = file_path
            self.ide_save_file()
            self.current_file_label.setText(f"File: {Path(file_path).name}")

    def ide_run_code(self):
        if not self.current_file_path:
            QMessageBox.warning(self, "No File", "Please save the file first.")
            return
        self.console_output.clear()
        self.console_output.append(f"Running: {Path(self.current_file_path).name}\n")
        def run_worker():
            try:
                result = subprocess.run(
                    [sys.executable, self.current_file_path],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                output = result.stdout + result.stderr
                self.console_output.append(output)
                if result.returncode == 0:
                    self.console_output.append("\n✅ Execution completed successfully")
                else:
                    self.console_output.append(f"\n❌ Execution failed with code {result.returncode}")
            except subprocess.TimeoutExpired:
                self.console_output.append("\n⏱️  Execution timeout (30s)")
            except Exception as e:
                self.console_output.append(f"\n❌ Error: {str(e)}")
        thread = threading.Thread(target=run_worker, daemon=True)
        thread.start()

    def open_document(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Document",
            str(Path.home()),
            "Documents (*.txt *.md *.pdf *.log);;All Files (*)"
        )
        if file_path:
            path_obj = Path(file_path)
            if path_obj.suffix.lower() == '.pdf':
                self.open_pdf(path_obj)
            else:
                self.open_text_file(path_obj)

    def _load_into_labs_file_chat(self, path: Path) -> bool:
        """Load a file into Labs > File Chat and switch to that tab. Returns True on success."""
        try:
            labs = getattr(self, "_labs_widget", None)
            if labs is None:
                return False
            fc = getattr(labs, "_file_chat_tab", None)
            if fc is None:
                return False
            fc._load_path(str(path))
            # Switch to Labs tab, then to File Chat sub-tab
            self._focus_tab_widget(labs)
            inner = getattr(labs, "_inner_tabs", None)
            if inner is not None:
                idx = inner.indexOf(fc)
                if idx >= 0:
                    inner.setCurrentIndex(idx)
            return True
        except Exception:
            return False

    def open_text_file(self, path: Path):
        if self._load_into_labs_file_chat(path):
            return
        # Fallback: floating read-only viewer
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
            dlg = QDialog(self)
            dlg.setWindowTitle(str(path.name))
            dlg.resize(800, 600)
            v = QVBoxLayout(dlg)
            t = QTextEdit()
            t.setReadOnly(True)
            t.setPlainText(content)
            v.addWidget(t)
            btn = QPushButton("Close")
            btn.clicked.connect(dlg.accept)
            v.addWidget(btn)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file: {str(e)}")

    def open_pdf(self, path: Path):
        text = ""
        try:
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                for page in reader.pages[:10]:
                    text += page.extract_text() + "\n\n"
            except ImportError:
                try:
                    import PyPDF2
                    with open(path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages[:10]:
                            text += page.extract_text() + "\n\n"
                except ImportError:
                    text = (
                        f"PDF viewing requires pypdf or PyPDF2.\n\n"
                        f"Install with: pip install pypdf\n\nFile: {path}"
                    )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open PDF: {str(e)}")
            return
        # Write extracted text to a temp .txt and load into Labs File Chat
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', prefix=path.stem + '_',
                delete=False, encoding='utf-8'
            ) as tmp:
                tmp.write(text)
                tmp_path = Path(tmp.name)
            if self._load_into_labs_file_chat(tmp_path):
                return
        except Exception:
            pass
        # Fallback: floating viewer
        dlg = QDialog(self)
        dlg.setWindowTitle(str(path.name))
        dlg.resize(800, 600)
        v = QVBoxLayout(dlg)
        t = QTextEdit()
        t.setReadOnly(True)
        t.setPlainText(text)
        v.addWidget(t)
        btn = QPushButton("Close")
        btn.clicked.connect(dlg.accept)
        v.addWidget(btn)
        dlg.exec()

    def browse_directory(self, path: str):
        self.file_tree.setRootIndex(self.file_model.index(path))
        self.path_label.setText(f"Current: {path}")

    def browse_project_root(self):
        project_root = Path(__file__).parent.parent.parent.parent
        self.browse_directory(str(project_root))

    def on_file_double_click(self, index):
        path = self.file_model.filePath(index)
        path_obj = Path(path)
        if path_obj.is_file():
            if path_obj.suffix == '.py':
                self.tabs.setCurrentIndex(3)
                try:
                    content = path_obj.read_text(encoding='utf-8')
                    if QSCI_AVAILABLE:
                        self.code_editor.setText(content)
                    else:
                        self.code_editor.setPlainText(content)
                    self.current_file_path = str(path_obj)
                    self.current_file_label.setText(f"File: {path_obj.name}")
                except Exception as e:
                    QMessageBox.critical(self, "Error", f"Failed to open: {str(e)}")
            elif path_obj.suffix in ['.txt', '.md', '.pdf', '.log']:
                self.tabs.setCurrentIndex(4)
                if path_obj.suffix == '.pdf':
                    self.open_pdf(path_obj)
                else:
                    self.open_text_file(path_obj)

    def browse_model_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select GGUF Model",
            "local_models",
            "GGUF Files (*.gguf);;All Files (*)"
        )
        if file_path:
            idx = self.provider_combo.findData('custom_gguf') if hasattr(self, 'provider_combo') else -1
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self.model_path_input.setText(file_path)

    def load_settings(self):
        """Load settings via runtime_settings (single canonical source)."""
        self._first_run_complete = False
        try:
            from eli.core.runtime_settings import load_settings as _rs_load
            s = _rs_load() or {}
        except Exception as e:
            print(f"⚠️ Failed to load runtime settings: {e}")
            s = {}

        # Numeric / generation params
        try:
            self.n_ctx_input.setValue(int(s.get("n_ctx", 16384)))
            self.n_threads_input.setValue(int(s.get("n_threads", 8)))
            self.n_gpu_layers_input.setValue(int(s.get("n_gpu_layers", 99)))
            self.max_tokens_input.setValue(int(s.get("max_tokens", 4096)))
            self.temperature_input.setValue(float(s.get("temperature", 0.7)))
            _batch = s.get("batch_size") or s.get("n_batch")
            if _batch:
                self.batch_size_input.setValue(int(_batch))
            # KV cache quantization combos
            try:
                _k = str(s.get("cache_type_k", "") or "")
                _v = str(s.get("cache_type_v", "") or "")
                _kidx = self.cache_type_k_combo.findText(_k)
                if _kidx >= 0:
                    self.cache_type_k_combo.setCurrentIndex(_kidx)
                _vidx = self.cache_type_v_combo.findText(_v)
                if _vidx >= 0:
                    self.cache_type_v_combo.setCurrentIndex(_vidx)
            except Exception:
                pass
        except Exception as e:
            print(f"⚠️ Failed to apply numeric settings to widgets: {e}")

        # Provider + paths
        try:
            provider = s.get("provider", "bundled_gguf")
            idx = self.provider_combo.findData(provider)
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            model_path = s.get("model_path") or DEFAULT_MODEL_PATH
            self.model_path_input.setText(model_path or "")
            bundled_path = s.get("bundled_model_path", "")
            if bundled_path:
                self._pending_bundled_model_path = bundled_path
            self.ollama_host_input.setText(s.get("ollama_host", "http://localhost:11434"))
            self.ollama_model_combo.setEditText(s.get("ollama_model", ""))
        except Exception as e:
            print(f"⚠️ Failed to apply provider/path settings to widgets: {e}")

        # Mic device selection
        try:
            _mic = s.get("mic_device")
            if _mic:
                self._saved_mic_device = tuple(_mic) if isinstance(_mic, list) else _mic
                self._on_mic_device_changed(_save=False)
        except Exception:
            pass

        # STT sensitivity (energy threshold)
        try:
            _dynamic = bool(s.get("stt_dynamic_energy", False))
            _threshold = int(s.get("stt_energy_threshold", 1200))
            self.dynamic_energy_checkbox.blockSignals(True)
            self.dynamic_energy_checkbox.setChecked(_dynamic)
            self.dynamic_energy_checkbox.blockSignals(False)
            self.energy_threshold_input.blockSignals(True)
            self.energy_threshold_input.setValue(_threshold)
            self.energy_threshold_input.blockSignals(False)
            import os as _os_e
            _os_e.environ["ELI_STT_DYNAMIC_ENERGY"] = "1" if _dynamic else "0"
            _os_e.environ["ELI_STT_ENERGY_THRESHOLD"] = str(_threshold)
        except Exception:
            pass

        # STT behaviour flags
        try:
            _direct = bool(s.get("allow_direct_chat_without_wake", False))
            self.allow_direct_chat_checkbox.blockSignals(True)
            self.allow_direct_chat_checkbox.setChecked(_direct)
            self.allow_direct_chat_checkbox.blockSignals(False)
            import os as _os_s
            _os_s.environ["ELI_STT_ALLOW_DIRECT_CHAT"] = "1" if _direct else "0"
            if hasattr(self, "wake_word_btn"):
                self.wake_word_btn.blockSignals(True)
                self.wake_word_btn.setChecked(not _direct)
                self.wake_word_btn.setText("Wake: ON" if not _direct else "Wake: OFF")
                self.wake_word_btn.blockSignals(False)
        except Exception:
            pass

        # Gaze engine
        try:
            _gaze_on = bool(s.get("gaze_engine_enabled", False))
            _gaze_cam = str(s.get("gaze_camera", "auto") or "auto")
            if hasattr(self, "gaze_enabled_checkbox"):
                self.gaze_enabled_checkbox.blockSignals(True)
                self.gaze_enabled_checkbox.setChecked(_gaze_on)
                self.gaze_enabled_checkbox.blockSignals(False)
            if hasattr(self, "gaze_camera_input"):
                self.gaze_camera_input.blockSignals(True)
                self.gaze_camera_input.setText(_gaze_cam)
                self.gaze_camera_input.blockSignals(False)
            if _gaze_on:
                try:
                    from eli.perception.gaze_engine import start_gaze_engine
                    start_gaze_engine(camera=_gaze_cam if _gaze_cam == "auto" else int(_gaze_cam) if _gaze_cam.isdigit() else "auto")
                except Exception as _ge:
                    log.debug(f"[GUI] Gaze engine auto-start failed: {_ge}")
        except Exception:
            pass

        # GUI-local flags + theme
        try:
            self.auto_save_checkbox.setChecked(bool(s.get("auto_save", True)))
            self.log_to_file_checkbox.setChecked(bool(s.get("log_to_file", False)))
            self.auto_load_checkbox.setChecked(bool(s.get("auto_load", True)))
            self._show_startup_model_picker = bool(s.get("show_startup_model_picker", True))
            if hasattr(self, "startup_model_picker_checkbox"):
                self.startup_model_picker_checkbox.setChecked(self._show_startup_model_picker)
            self._first_run_complete = bool(s.get("first_run_complete", False))
            self.current_theme = s.get("theme", self.current_theme)
            self._user_text_color = s.get(
                "user_text_color", getattr(self, "_user_text_color", "#a3be8c"))
        except Exception as e:
            print(f"⚠️ Failed to apply GUI flags: {e}")

        # Identity + image studio defaults
        try:
            _gui_user_name = str(s.get("user_name", "") or "").strip()
            if not _gui_user_name:
                try:
                    from eli.kernel.state import get_user_name as _gun
                    _gui_user_name = _gun() or ""
                except Exception:
                    pass
            self.user_name_input.setText(_gui_user_name)
            self.image_profile_notes_input.setPlainText(str(s.get("image_profile_notes", "") or ""))
            self.image_style_profile_combo.setCurrentText(str(s.get("image_style_profile", "auto") or "auto"))
            self.image_palette_profile_combo.setCurrentText(str(s.get("image_palette_profile", "auto") or "auto"))
            self.image_backend_default_combo.setCurrentText(str(s.get("image_backend", "auto") or "auto"))
            self.image_model_path_input.setText(str(s.get("image_model_path", "") or ""))
            self.image_device_default_combo.setCurrentText(str(s.get("image_device", "auto") or "auto"))
            self.image_quality_default_combo.setCurrentText(str(s.get("image_quality_preset", "ultra") or "ultra"))
            self.image_steps_default_input.setValue(int(s.get("image_steps", 36) or 36))
            self.image_guidance_default_input.setValue(float(s.get("image_guidance", 7.2) or 7.2))
            self.image_negative_default_input.setPlainText(str(s.get("image_negative_prompt", "") or ""))
            self.image_auto_personalize_checkbox.setChecked(bool(s.get("image_auto_personalize", True)))
            self.image_auto_open_checkbox.setChecked(bool(s.get("image_auto_open", True)))
            self.image_use_chat_context_checkbox.setChecked(bool(s.get("image_use_chat_context", True)))
            self.image_use_proactive_context_checkbox.setChecked(bool(s.get("image_use_proactive_context", True)))
            self.image_default_project_input.setText(str(s.get("image_default_project_path", "") or ""))
            self.image_default_count_input.setValue(int(s.get("image_default_count", 1) or 1))
            self.image_default_width_input.setValue(int(s.get("image_default_width", 1400) or 1400))
            self.image_default_height_input.setValue(int(s.get("image_default_height", 900) or 900))

            self.image_project_input.setText(str(s.get("image_default_project_path", "") or ""))
            self.image_count_input.setValue(int(s.get("image_default_count", 1) or 1))
            self.image_width_input.setValue(int(s.get("image_default_width", 1400) or 1400))
            self.image_height_input.setValue(int(s.get("image_default_height", 900) or 900))
            self.image_backend_combo.setCurrentText(str(s.get("image_backend", "auto") or "auto"))
            self.image_model_combo.setEditText(str(s.get("image_model_path", "") or ""))
            self.image_device_combo.setCurrentText(str(s.get("image_device", "auto") or "auto"))
            self.image_quality_preset_combo.setCurrentText(str(s.get("image_quality_preset", "ultra") or "ultra"))
            self.image_steps_input.setValue(int(s.get("image_steps", 36) or 36))
            self.image_guidance_input.setValue(float(s.get("image_guidance", 7.2) or 7.2))
            self.image_negative_input.setPlainText(str(s.get("image_negative_prompt", "") or ""))
            self.image_personalize_checkbox.setChecked(bool(s.get("image_auto_personalize", True)))
            self.image_chat_context_checkbox.setChecked(bool(s.get("image_use_chat_context", True)))
            self.image_proactive_context_checkbox.setChecked(bool(s.get("image_use_proactive_context", True)))
        except Exception as e:
            print(f"⚠️ Failed to apply identity/image settings: {e}")

        self.apply_theme()

    def save_settings(self, silent: bool = False):
        """Save settings via runtime_settings — single canonical merge-write."""
        provider = self.current_provider()
        model_path = self.resolve_selected_model_path() if provider != "ollama" else self.model_path_input.text()
        bundled_path = str(self.bundled_model_combo.currentData() or "")
        existing = {}
        try:
            from eli.core.runtime_settings import load_settings as _rs_load
            existing = _rs_load() or {}
        except Exception:
            existing = {}

        updates = {
            "provider": provider,
            "model_path": model_path,
            "custom_model_path": self.model_path_input.text(),
            "bundled_model_path": bundled_path,
            "ollama_host": self.ollama_host_input.text().strip(),
            "ollama_model": self.ollama_model_combo.currentText().strip(),
            "n_ctx": int(self.n_ctx_input.value()),
            "n_threads": int(self.n_threads_input.value()),
            "n_gpu_layers": int(self.n_gpu_layers_input.value()),
            "batch_size": int(self.batch_size_input.value()),
            "max_tokens": int(self.max_tokens_input.value()),
            "temperature": float(self.temperature_input.value()),
            "cache_type_k": self.cache_type_k_combo.currentText().strip(),
            "cache_type_v": self.cache_type_v_combo.currentText().strip(),
            "auto_save": bool(self.auto_save_checkbox.isChecked()),
            "log_to_file": bool(self.log_to_file_checkbox.isChecked()),
            "auto_load": bool(self.auto_load_checkbox.isChecked()),
            "show_startup_model_picker": bool(getattr(self, "startup_model_picker_checkbox", None).isChecked()) if hasattr(self, "startup_model_picker_checkbox") else bool(getattr(self, "_show_startup_model_picker", True)),
            "first_run_complete": bool(getattr(self, "_first_run_complete", False)),
            "theme": self.current_theme,
            "user_text_color": getattr(self, "_user_text_color", "#a3be8c"),
            "user_name": self.user_name_input.text().strip(),
            "image_style_profile": self.image_style_profile_combo.currentText().strip(),
            "image_palette_profile": self.image_palette_profile_combo.currentText().strip(),
            "image_profile_notes": self.image_profile_notes_input.toPlainText().strip(),
            "image_backend": self.image_backend_default_combo.currentText().strip(),
            "image_model_path": self.image_model_path_input.text().strip() or self._selected_image_model_path(),
            "image_device": self.image_device_default_combo.currentText().strip(),
            "image_quality_preset": self.image_quality_default_combo.currentText().strip(),
            "image_steps": int(self.image_steps_default_input.value()),
            "image_guidance": float(self.image_guidance_default_input.value()),
            "image_negative_prompt": self.image_negative_default_input.toPlainText().strip(),
            "image_default_project_path": self.image_default_project_input.text().strip(),
            "image_default_count": int(self.image_default_count_input.value()),
            "image_default_width": int(self.image_default_width_input.value()),
            "image_default_height": int(self.image_default_height_input.value()),
            "image_auto_personalize": bool(self.image_auto_personalize_checkbox.isChecked()),
            "image_auto_open": bool(self.image_auto_open_checkbox.isChecked()),
            "image_use_chat_context": bool(self.image_use_chat_context_checkbox.isChecked()),
            "image_use_proactive_context": bool(self.image_use_proactive_context_checkbox.isChecked()),
            "allow_direct_chat_without_wake": bool(self.allow_direct_chat_checkbox.isChecked()),
            "mic_device": list(self.mic_device_combo.currentData()) if self.mic_device_combo.currentData() else None,
            "stt_dynamic_energy": bool(self.dynamic_energy_checkbox.isChecked()),
            "stt_energy_threshold": int(self.energy_threshold_input.value()),
            "gaze_engine_enabled": bool(getattr(self, "gaze_enabled_checkbox", None) and self.gaze_enabled_checkbox.isChecked()),
            "gaze_camera": str(self.gaze_camera_input.text().strip() if hasattr(self, "gaze_camera_input") else "auto"),
        }

        try:
            from eli.core.runtime_settings import save_settings as _rs_save
            _rs_save(updates)
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
            else:
                log.debug(f"[SETTINGS] Save failed: {e}")
            return

        try:
            from eli.kernel.state import set_user_name as _set_user_name, update_user_profile as _update_profile
            _set_user_name(updates.get("user_name", ""))
            _update_profile(
                image_style=updates.get("image_style_profile", "auto"),
                image_palette=updates.get("image_palette_profile", "auto"),
                image_visual_notes=updates.get("image_profile_notes", ""),
            )
        except Exception as e:
            log.debug(f"[SETTINGS] User profile sync skipped: {e}")

        # max_tokens, temperature, top_p, top_k, repeat_penalty are
        # per-inference params — handled at call time, no reload needed.
        # The keys below force a Llama instance rebuild because they
        # change how the model is constructed.
        reload_keys = {
            "provider", "model_path", "custom_model_path", "bundled_model_path",
            "ollama_host", "ollama_model", "n_ctx", "n_threads",
            "n_gpu_layers", "batch_size",
            "cache_type_k", "cache_type_v",
            "use_mmap", "use_mlock",
        }
        requires_reload = any(existing.get(k) != updates.get(k) for k in reload_keys)

        # On explicit user save with reload-required keys changed, kick
        # off a proactive reload in a background thread so the new
        # config is live before the user sends the next message — and
        # so the chat/generate pipeline is never blocked on the lock
        # at first-message time. silent saves (color picker, first-run
        # wiring) skip this — they shouldn't disturb the loaded model.
        try:
            if requires_reload and not silent and gguf_inference:
                changed_keys = sorted(
                    k for k in reload_keys
                    if existing.get(k) != updates.get(k)
                )
                log.debug(f"[SETTINGS] Reload-required keys changed: {changed_keys}")
                import threading as _settings_reload_thr

                def _do_reload():
                    try:
                        result = gguf_inference.reload_model(await_completion=True)
                        if result.get("ok"):
                            params = result.get("params") or {}
                            log.debug(
                                "[SETTINGS] Model reloaded — "
                                f"ctx={params.get('n_ctx')} "
                                f"gpu_layers={params.get('n_gpu_layers')} "
                                f"threads={params.get('n_threads')} "
                                f"batch={params.get('n_batch')}"
                            )
                        else:
                            log.debug(f"[SETTINGS] Reload failed: {result.get('error')}")
                    except Exception as exc:
                        log.debug(f"[SETTINGS] Reload thread error: {exc}")

                _settings_reload_thr.Thread(
                    target=_do_reload, name="settings-reload", daemon=True,
                ).start()
        except Exception as e:
            log.debug(f"[SETTINGS] Active reload skipped: {e}")

        if not silent:
            if requires_reload:
                msg = (
                    "Settings saved.\n\n"
                    "Runtime/model changes take effect on the next message\n"
                    "(the model reloads automatically with the new parameters)."
                )
            else:
                msg = "Settings saved.\n\nVisual, identity, and image-studio preferences updated."
            QMessageBox.information(
                self, "Settings Saved",
                msg
            )
            self.status_signal.emit("Settings saved")

    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme()

    def apply_theme(self):
        if self.current_theme == "dark":
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background: #141821;
                    color: #e6ecf5;
                }
                QMenuBar {
                    background: #10141c;
                    color: #dce4f2;
                    border-bottom: 1px solid #232b38;
                }
                QMenuBar::item {
                    background: transparent;
                    padding: 6px 10px;
                }
                QMenuBar::item:selected {
                    background: #243043;
                    border-radius: 4px;
                }
                QMenu {
                    background: #18202c;
                    color: #e6ecf5;
                    border: 1px solid #2b3647;
                }
                QMenu::item:selected {
                    background: #273449;
                }
                QToolBar {
                    background: #0f131a;
                    border-bottom: 1px solid #232b38;
                    spacing: 6px;
                    padding: 6px 8px;
                }
                QToolButton, QPushButton {
                    background: #232b38;
                    color: #edf3fb;
                    border: 1px solid #334055;
                    padding: 8px 10px;
                    border-radius: 8px;
                }
                QToolButton:hover, QPushButton:hover {
                    background: #2c384d;
                    border-color: #4e6a91;
                }
                QToolButton:pressed, QPushButton:pressed {
                    background: #1c2431;
                }
                QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {
                    background: #10151e;
                    color: #edf3fb;
                    border: 1px solid #2c384c;
                    border-radius: 8px;
                    padding: 6px;
                    selection-background-color: #35507a;
                }
                QComboBox QAbstractItemView, QListWidget {
                    background: #121925;
                }
                QGroupBox {
                    border: 1px solid #2b3647;
                    border-radius: 10px;
                    margin-top: 12px;
                    padding-top: 12px;
                    background: #181e29;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 6px;
                    color: #94a8c6;
                }
                QWidget {
                    font-size: 11px;
                }
                QLabel {
                    font-size: 11px;
                }
                QPushButton {
                    font-size: 11px;
                    padding: 3px 8px;
                }
                QGroupBox {
                    font-size: 11px;
                }
                QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                    font-size: 11px;
                }
                QMenuBar {
                    font-size: 11px;
                }
                QMenu {
                    font-size: 11px;
                }
                QToolBar QToolButton {
                    font-size: 11px;
                }
                QTabWidget::pane {
                    border: 1px solid #243043;
                    background: #141821;
                }
                QTabBar::tab {
                    background: #111723;
                    color: #9fb0c9;
                    padding: 3px 8px;
                    border: 1px solid #243043;
                    border-bottom: none;
                    border-top-left-radius: 5px;
                    border-top-right-radius: 5px;
                    margin-right: 1px;
                    font-size: 11px;
                    min-width: 0px;
                }
                QTabBar::tab:selected {
                    background: #1f2a3a;
                    color: #ffffff;
                }
                QSplitter::handle {
                    background: #202938;
                }
                QScrollBar:vertical {
                    background: #10151d;
                    width: 12px;
                    margin: 2px;
                }
                QScrollBar::handle:vertical {
                    background: #334055;
                    border-radius: 6px;
                    min-height: 26px;
                }
                QStatusBar {
                    background: #10141c;
                    color: #dce4f2;
                    border-top: 1px solid #232b38;
                }
            """)
        else:
            self.setStyleSheet("")

    def show_about(self):
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h2>{APP_NAME}</h2>"
            f"<p>Version {APP_VERSION}</p>"
            f"<p><b>100% Local AI Assistant</b></p>"
            f"<p>Supports bundled GGUF, custom GGUF, and Ollama backends</p>"
            f"<p>Primarily local-first; Ollama can be used when selected</p>"
            f"<hr>"
            f"<p>Features:</p>"
            f"<ul>"
            f"<li>Local GGUF model inference</li>"
            f"<li>SQLite memory system</li>"
            f"<li>Integrated code editor</li>"
            f"<li>Proactive suggestions</li>"
            f"<li>Document viewer</li>"
            f"<li>File browser</li>"
            f"<li>Habits scheduler</li>"
            f"</ul>"
        )

    def _append_log(self, message: str):
        log.debug(f"[LOG] {message}")

    def _update_status(self, message: str):
        if message == 'Send enabled':
            self.send_btn.setEnabled(True)
            self.send_btn.setText('Send')
            return
        if message == 'Send disabled':
            self.send_btn.setEnabled(False)
            return
        if message.startswith('🟢 Model ready:'):
            model_name = message.split(':', 1)[1].strip()
            self.model_info_label.setText(f"🟢 {model_name}")
            self.send_btn.setEnabled(True)
            self.status_label.setText("🟢 Ready")
            return
        elif message.startswith('🔴 Model:'):
            self.model_info_label.setText(message)
            self.send_btn.setEnabled(True)
            self.send_btn.setText('Send')
            self.status_label.setText("🔴 No model")
            return
        self.status_label.setText(message)

    def _append_chat_response(self, text: str):
        """Handle streamed tokens and complete responses (always on GUI thread)."""
        _ELI_HEADER_COLOR = "#88c0d0"   # nordic blue for ELI's name
        _ELI_BODY_COLOR   = "#d8dee9"   # light grey for ELI's response text

        if text == "__STREAM_START__":
            self._stream_buffer = []
            self._streaming = True
            ts = datetime.now().strftime("%H:%M:%S")
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertBlock()
            header_fmt = QTextCharFormat()
            header_fmt.setFontWeight(QFont.Weight.Bold)
            header_fmt.setForeground(QColor(_ELI_HEADER_COLOR))
            cursor.setCharFormat(header_fmt)
            cursor.insertText(f"🤖 ELI [{ts}]:")
            cursor.insertBlock()
            body_fmt = QTextCharFormat()
            body_fmt.setFontWeight(QFont.Weight.Normal)
            body_fmt.setForeground(QColor(_ELI_BODY_COLOR))
            cursor.setCharFormat(body_fmt)
            self.chat_display.setTextCursor(cursor)
            return

        if text == "__STREAM_END__":
            self._streaming = False
            self._stream_buffer = []
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertBlock()
            self.chat_display.setTextCursor(cursor)
            self.chat_display.ensureCursorVisible()
            self.send_btn.setText("Send")
            self.send_btn.setEnabled(True)
            self.is_generating = False
            return

        if getattr(self, "_streaming", False):
            # Append token using the body colour format
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            body_fmt = QTextCharFormat()
            body_fmt.setFontWeight(QFont.Weight.Normal)
            body_fmt.setForeground(QColor(_ELI_BODY_COLOR))
            cursor.setCharFormat(body_fmt)
            self.chat_display.setTextCursor(cursor)
            self.chat_display.insertPlainText(text)
            self.chat_display.ensureCursorVisible()
            return

        # ── Non-streamed complete response ───────────────────────────────────
        # Pre-process: extract user-visible text from any stray dict blobs
        # before display so raw Python repr never reaches the chat widget.
        _r = text
        _r_stripped = _r.strip()
        if _r_stripped.startswith("\u26a1 {") or _r_stripped.startswith("{'") or _r_stripped.startswith("{\""):
            try:
                import ast as _ast, re as _re2
                _blob = _re2.sub(r"^\u26a1\s*", "", _r_stripped)
                _data = _ast.literal_eval(_blob)
                if isinstance(_data, dict):
                    if _data.get("ok") and "results" in _data:
                        _rs = _data["results"]
                        _r = "\U0001f4cb " + " | ".join(r["text"] for r in _rs[:3]) if _rs else "\U0001f4cb No memories found."
                    else:
                        # Any other result dict \u2014 extract the user-visible field
                        _r = (
                            _data.get("response") or _data.get("content")
                            or _data.get("text") or _data.get("message")
                            or _data.get("result") or _data.get("answer")
                            or _data.get("output") or _r
                        )
                        if not isinstance(_r, str):
                            _r = str(_r)
            except Exception:
                pass

        ts = datetime.now().strftime("%H:%M:%S")
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertBlock()
        header_fmt = QTextCharFormat()
        header_fmt.setFontWeight(QFont.Weight.Bold)
        header_fmt.setForeground(QColor(_ELI_HEADER_COLOR))
        cursor.setCharFormat(header_fmt)
        cursor.insertText(f"🤖 ELI [{ts}]:")
        cursor.insertBlock()
        body_fmt = QTextCharFormat()
        body_fmt.setFontWeight(QFont.Weight.Normal)
        body_fmt.setForeground(QColor(_ELI_BODY_COLOR))
        cursor.setCharFormat(body_fmt)
        cursor.insertText(_r)
        cursor.insertBlock()
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()

    def _update_proactive(self, data: dict):
        pass

    def closeEvent(self, event):
        if getattr(self, "_eli_shutdown_started", False):
            try:
                event.accept()
            except Exception:
                pass
            return

        self._eli_shutdown_started = True

        try:
            self._cancel_stream_requested = True
        except Exception:
            pass

        try:
            if self._runtime_stats_timer is not None:
                self._runtime_stats_timer.stop()
        except Exception:
            pass

        # Phase 7: stop the live-data timers too so they don't fire
        # mid-shutdown and try to read a closed memory/database handle.
        for _attr in ("_memory_stats_timer", "_proactive_status_timer"):
            try:
                _t = getattr(self, _attr, None)
                if _t is not None:
                    _t.stop()
            except Exception:
                pass

        try:
            _ce = getattr(self, '_cognitive_engine', None)
            if _ce is not None and hasattr(_ce, 'shutdown'):
                _ce.shutdown()
        except Exception as _sd_err:
            log.debug(f"[GUI] CognitiveEngine shutdown failed (non-fatal): {_sd_err}")

        try:
            if self.auto_save_checkbox.isChecked() and self.conversation_history:
                self.save_conversation()
        except Exception as _save_err:
            log.debug(f"[GUI] Conversation autosave failed during close: {_save_err}")

        try:
            event.accept()
        except Exception:
            pass

# ============================================================
# MAIN ENTRY POINT
# ============================================================
def main():
    print(f"""
╔══════════════════════════════════════════════════════════════════════╗
║  {APP_NAME} v{APP_VERSION}                                           ║
║  100% Local AI Assistant                                             ║
╚══════════════════════════════════════════════════════════════════════╝
    """)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName(APP_NAME)

    # ── First-boot check: show wizard if no models are installed ─────────────
    try:
        _existing_models = discover_gguf_models()
    except Exception:
        _existing_models = []
    if not _existing_models:
        _wizard = FirstBootWizard()
        _wizard.exec()
        # Re-check after wizard — user may have placed a model
        try:
            _existing_models = discover_gguf_models()
        except Exception:
            _existing_models = []
        if not _existing_models:
            # Wizard dismissed without a model — still launch but warn
            log.debug("[ELI] No models installed. GUI will launch without a model loaded.")

    window = EliMainWindow()
    window._debug_boot_ts = time.time()
    window.show()

    window.status_label.setText('🔴 Model not loaded')
    window.model_info_label.setText('🔴 Model: Not loaded')
    window.send_btn.setEnabled(False)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
