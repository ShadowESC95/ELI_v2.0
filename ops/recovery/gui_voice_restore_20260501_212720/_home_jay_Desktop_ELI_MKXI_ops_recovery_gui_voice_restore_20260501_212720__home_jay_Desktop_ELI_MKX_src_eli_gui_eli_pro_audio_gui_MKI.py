#!/usr/bin/env python3
"""
ELI MKIX - Modern Comprehensive GUI
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

# Qt imports with PyQt6-first policy for MKI/QScintilla
try:
    from PyQt6.QtWidgets import *
    from PyQt6.QtCore import *
    from PyQt6.QtGui import *
    QT_VERSION = 6
    QT_API = "PyQt6"
except ImportError:
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
            from PyQt5.QtWidgets import *
            from PyQt5.QtCore import *
            from PyQt5.QtGui import *
            QT_VERSION = 5
            QT_API = "PyQt5"
        except ImportError:
            print("❌ Please install PyQt6, PySide6, or PyQt5")
            sys.exit(1)

# Try to import syntax highlighter
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
    from eli.brain.memory import get_memory, Memory
    from eli.brain.cognition import gguf_inference
    from eli.brain.proactive.proactive_daemon import start_daemon   # <-- ADDED
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
    start_daemon = None   # <-- ADDED

# ============================================================
# Adapter for central Memory to match GUI's expected interface
# ============================================================
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

APP_NAME = "ELI MKIX"
APP_VERSION = "7.0.7"

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Settings file: prefer eli.core.paths config_dir, fall back to PROJECT_ROOT/config
try:
    from eli.core.paths import config_dir as _config_dir
    APP_DIR = Path(_config_dir())
except Exception:
    APP_DIR = PROJECT_ROOT / "config"
SETTINGS_FILE = APP_DIR / "settings.json"

if CENTRAL_IMPORTS_AVAILABLE and get_paths:
    _paths = get_paths()
    MEMORY_DB = _paths.memory_db
    CONVERSATIONS_DIR = _paths.conversations_dir
    ARTIFACTS_DIR = _paths.artifacts_dir
    DEFAULT_MODEL_PATH = str(_paths.model) if _paths.model and _paths.model.exists() else str(PROJECT_ROOT / "models" / "mistral-7b-instruct-v0.2.Q3_K_M.gguf")
    BUNDLED_MODEL_DIR = PROJECT_ROOT / "models"
    CUSTOM_MODELS_DIR = APP_DIR / "models"
else:
    MEMORY_DB = PROJECT_ROOT / "artifacts" / "eli_memory.sqlite3"
    CONVERSATIONS_DIR = PROJECT_ROOT / "artifacts" / "conversations"
    ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
    DEFAULT_MODEL_PATH = str(PROJECT_ROOT / "models" / "mistral-7b-instruct-v0.2.Q3_K_M.gguf")
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

def recommend_model_setup(models, sysinfo, ollama_models=None):
    return {}


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
                    'source': 'bundled' if BUNDLED_MODEL_DIR in path.parents else 'custom',
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
            info['has_gpu'] = True
        elif shutil.which('rocm-smi'):
            info['has_gpu'] = True
    except Exception:
        pass
    return info

def recommend_optimal_settings(sysinfo: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-detect sensible defaults from the current machine's hardware."""
    ram_gb    = sysinfo.get('total_ram_gb', 8)
    vram_mb   = sysinfo.get('vram_mb', 0)
    cpu_count = sysinfo.get('cpu_count', 4)
    has_gpu   = sysinfo.get('has_gpu', False)

    # Context window: scale with RAM
    if ram_gb >= 32:   n_ctx = 8192
    elif ram_gb >= 16: n_ctx = 4096
    else:              n_ctx = 2048

    # GPU layers: fit as much as VRAM allows
    if not has_gpu or vram_mb == 0:
        n_gpu_layers = 0
    elif vram_mb >= 8000:
        n_gpu_layers = 99   # offload everything
    elif vram_mb >= 6000:
        n_gpu_layers = 35
    elif vram_mb >= 4000:
        n_gpu_layers = 20
    elif vram_mb >= 2000:
        n_gpu_layers = 10
    else:
        n_gpu_layers = 4

    n_threads  = max(1, cpu_count - 2)
    batch_size = 512 if vram_mb >= 6000 else (256 if vram_mb >= 4000 else 128)

    return {
        'n_ctx':        n_ctx,
        'n_gpu_layers': n_gpu_layers,
        'n_threads':    n_threads,
        'batch_size':   batch_size,
        'temperature':  0.7,
        'max_tokens':   512,
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
    def _write_shared_runtime_snapshot(self, model_path: str, n_ctx: int, n_threads: int, n_gpu_layers: int):
        try:
            from eli.core.paths import get_paths
            snap_path = Path(get_paths().artifacts_dir) / 'runtime_snapshot.json'
            payload = {
                'provider': 'gguf',
                'model_path': str(model_path),
                'model_name': Path(model_path).name if model_path else '',
                'n_ctx': int(n_ctx or 0),
                'n_gpu_layers': int(n_gpu_layers or 0),
                'n_threads': int(n_threads or 0),
                'n_batch': int(getattr(self, 'n_batch', 0) or 0),
                'loaded': bool(getattr(self, 'is_loaded', False)),
                'pid': __import__('os').getpid(),
                'ts': time.time(),
            }
            snap_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
            print(f'✅ shared runtime snapshot written: {snap_path}')
        except Exception as e:
            print(f'[GUI] shared runtime snapshot write failed: {e}')

    def load_model(self, model_path: str, n_ctx: int = 4096,
                   n_threads: int = 8, n_gpu_layers: int = 0, n_batch: int = 512) -> bool:
        try:
            from llama_cpp import Llama
            path_obj = resolve_model_path(model_path)
            self.model_path = str(path_obj)
            if not path_obj.exists():
                self.load_error = f"Model not found: {path_obj}"
                return False
            print(f"🔄 Loading model: {path_obj.name}")
            print(f"   Size: {path_obj.stat().st_size / (1024**3):.2f} GB")
            print(f"   GPU layers: {n_gpu_layers}")
            print(f"   Batch size: {n_batch}")
            self.n_ctx = int(n_ctx)
            self.n_threads = int(n_threads)
            self.n_gpu_layers = int(n_gpu_layers)
            self.n_batch = int(n_batch)
            self.model = Llama(
                model_path=str(path_obj),
                n_ctx=n_ctx,
                n_threads=n_threads,
                n_gpu_layers=n_gpu_layers,
                n_batch=n_batch,
                verbose=False,
                chat_format="chatml",
            )
            setattr(self.model, "n_ctx", int(n_ctx))
            setattr(self.model, "n_threads", int(n_threads))
            setattr(self.model, "n_gpu_layers", int(n_gpu_layers))
            try:
                from eli.core import runtime_settings as _rs
                _st = _rs.load_settings() or {}
                _nb = int(_st.get("n_batch", _st.get("batch_size", 0)) or 0)
                if _nb > 0:
                    setattr(self.model, "n_batch", _nb)
            except Exception:
                pass
            self.n_ctx = int(n_ctx)
            self.n_threads = int(n_threads)
            self.n_gpu_layers = int(n_gpu_layers)
            try:
                from eli.brain.cognition import gguf_inference as _gg
                _gg._llm = self.model
            except Exception as _wire_err:
                print(f"[GUI] gguf runtime handoff failed: {_wire_err}")
            self.is_loaded = True
            self.n_ctx = int(n_ctx or 0)
            self.n_threads = int(n_threads or 0)
            self.n_gpu_layers = int(n_gpu_layers or 0)
            self.n_batch = int(getattr(self.model, 'n_batch', 0) or 0)
            try:
                from eli.brain.cognition import gguf_inference as _ggi
                _ggi._llm = self.model
                _ggi._live_runtime_override = {
                    "provider": "gguf",
                    "loaded": True,
                    "model_path": str(path_obj),
                    "model_name": path_obj.name,
                    "n_ctx": int(n_ctx),
                    "n_gpu_layers": int(n_gpu_layers),
                    "n_threads": int(n_threads),
                    "n_batch": int(n_batch),
                }
                print("✅ gguf_inference live runtime override published")
            except Exception as e:
                print(f"[GUI] live runtime override publish failed: {e}")
            self.load_error = None
            print(f"✅ Model loaded successfully")
            self._write_shared_runtime_snapshot(str(path_obj), n_ctx, n_threads, n_gpu_layers)
            return True
        except Exception as e:
            self.load_error = f"Failed to load model: {str(e)}"
            print(f"❌ {self.load_error}")
            self.model = None
            self.is_loaded = False
            gc.collect()
            return False
    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 512,
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
    def generate(self, prompt: str, max_tokens: int = 512,
                temperature: float = 0.7) -> str:
        messages = [
            {'role': 'system', 'content': ELI_SYSTEM_PROMPT},
            {'role': 'user',   'content': prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature)
    def chat_stream(self, messages, max_tokens=1024, temperature=0.7):
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
                print(f"[OLLAMA] model not in /api/tags yet, continuing anyway: {self.model_name}")
            self.load_error = None
            self.is_loaded = True
            return True
        except Exception as e:
            self.load_error = f"Failed to connect to Ollama: {e}"
            self.is_loaded = False
            return False
    def chat(self, messages: List[Dict[str, str]], max_tokens: int = 512,
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
    def generate(self, prompt: str, max_tokens: int = 512,
                temperature: float = 0.7) -> str:
        messages = [
            {'role': 'system', 'content': ELI_SYSTEM_PROMPT},
            {'role': 'user',   'content': prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, temperature=temperature)
    def chat_stream(self, messages, max_tokens=1024, temperature=0.7):
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
            'eli.tools.automation.executor_enhanced',
            'eli.tools.executor_enhanced',
            'eli.tools.automation.executor_enhanced',
        ]
        router_candidates = [
            'eli.tools.automation.router_enhanced',
            'eli.tools.router_enhanced',
            'eli.tools.automation.router_enhanced',
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
            from eli.tools.automation.executor_enhanced import execute as execute_enhanced
            result = execute_enhanced(action, args or {})
            if isinstance(result, dict):
                return result.get("response") or result.get("content") or str(result)
            return str(result)
        except Exception:
            return f"Action {action} not implemented in fallback mode"

executor_bridge = ExecutorBridge()

# ============================================================
# AGENT EDIT DIALOG
# ============================================================
class AgentEditDialog(QDialog):
    """Edit an individual agent's metadata and persona."""

    def __init__(self, agent_info: dict, parent=None):
        super().__init__(parent)
        self.agent_info = dict(agent_info)
        self.setWindowTitle(f"Edit Agent: {agent_info.get('name', 'Unknown')}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(self.agent_info.get("name", ""))
        self.name_edit.setReadOnly(True)  # class name is fixed
        form.addRow("Name:", self.name_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlainText(self.agent_info.get("description", ""))
        self.desc_edit.setFixedHeight(80)
        form.addRow("Description:", self.desc_edit)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.5, 60.0)
        self.timeout_spin.setSingleStep(0.5)
        self.timeout_spin.setValue(float(self.agent_info.get("timeout_s", 5.0)))
        form.addRow("Timeout (s):", self.timeout_spin)

        self.persona_edit = QTextEdit()
        self.persona_edit.setPlainText(self.agent_info.get("persona", ""))
        self.persona_edit.setPlaceholderText(
            "Optional persona / system-prompt injection for this agent…"
        )
        self.persona_edit.setFixedHeight(120)
        form.addRow("Persona / Notes:", self.persona_edit)

        self.enabled_chk = QCheckBox("Enabled")
        self.enabled_chk.setChecked(self.agent_info.get("enabled", True))
        form.addRow(self.enabled_chk)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def get_result(self) -> dict:
        return {
            **self.agent_info,
            "description": self.desc_edit.toPlainText().strip(),
            "timeout_s": self.timeout_spin.value(),
            "persona": self.persona_edit.toPlainText().strip(),
            "enabled": self.enabled_chk.isChecked(),
        }


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
        "RUNTIME_STATUS", "MEMORY_STATUS", "COGNITION_STATUS",
        # Memory
        "MEMORY_STATS", "AWARENESS_STATUS",
        # Help & capabilities
        "HELP", "LIST_CAPABILITIES",
        # Self-awareness / improvement
        "SELF_TEST", "SELF_ANALYZE", "SELF_IMPROVE", "SELF_UPGRADE",
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


# ============================================================
# ADVANCED SETTINGS DIALOG
# ============================================================
class AdvancedSettingsDialog(QDialog):
    """
    Comprehensive settings dialog with four tabs:
      1. Agents   — list, edit, enable/disable all bus agents
      2. Models   — list installed GGUF + Ollama models
      3. Plugins  — install, enable/disable, uninstall
      4. Upgrade  — self-improvement cycle + capability manifest
    """
    # Thread-safe signals — worker threads emit these; Qt delivers them on the main thread
    _plugin_log_sig  = pyqtSignal(str)
    _plugin_refresh_sig = pyqtSignal()
    _upgrade_log_sig = pyqtSignal(str)

    def __init__(self, parent=None, start_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Advanced Settings")
        self.setMinimumSize(780, 560)
        self._agent_overrides: dict = {}
        self._build_ui()
        # Connect thread-safe signals to actual GUI slots
        self._plugin_log_sig.connect(self._do_log_plugin,  Qt.ConnectionType.QueuedConnection)
        self._plugin_refresh_sig.connect(self._populate_plugins_table, Qt.ConnectionType.QueuedConnection)
        self._upgrade_log_sig.connect(self._do_log_upgrade, Qt.ConnectionType.QueuedConnection)
        # Jump to the requested tab
        if 0 <= start_tab < self.inner_tabs.count():
            self.inner_tabs.setCurrentIndex(start_tab)

    # ── UI skeleton ────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        self.inner_tabs = QTabWidget()
        root.addWidget(self.inner_tabs)

        self.inner_tabs.addTab(self._build_agents_tab(), "🤖 Agents")
        self.inner_tabs.addTab(self._build_models_tab(), "🧠 Models")
        self.inner_tabs.addTab(self._build_plugins_tab(), "🔌 Plugins")
        self.inner_tabs.addTab(self._build_upgrade_tab(), "🔄 Self-Upgrade")

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)

    # ── Agents tab ─────────────────────────────────────────────────────────────
    def _build_agents_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel("All registered ELI agents. Edit timeout, description, persona, or disable individual agents.")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.agents_table = QTableWidget()
        self.agents_table.setColumnCount(5)
        self.agents_table.setHorizontalHeaderLabels(
            ["Name", "Description", "Timeout (s)", "Enabled", "Actions"]
        )
        self.agents_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.agents_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.agents_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.agents_table)

        self._populate_agents_table()

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._populate_agents_table)
        btn_row.addWidget(refresh_btn)
        save_btn = QPushButton("💾 Apply Changes")
        save_btn.clicked.connect(self._apply_agent_changes)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    def _get_agent_list(self) -> list:
        """Return list of agent info dicts from the live agent bus."""
        agents = []
        try:
            from eli.brain.agents.agent_bus import _ALL_AGENTS
            for ag in _ALL_AGENTS:
                overrides = self._agent_overrides.get(ag.name, {})
                agents.append({
                    "name": ag.name,
                    "class": type(ag).__name__,
                    "description": overrides.get("description", getattr(ag, "__doc__", "") or ""),
                    "timeout_s": overrides.get("timeout_s", getattr(ag, "timeout_s", 5.0)),
                    "enabled": overrides.get("enabled", getattr(ag, "_enabled", True)),
                    "persona": overrides.get("persona", ""),
                })
        except Exception as e:
            agents.append({
                "name": f"(unavailable: {e})", "class": "", "description": "",
                "timeout_s": 5.0, "enabled": True, "persona": "",
            })
        return agents

    def _populate_agents_table(self):
        agents = self._get_agent_list()
        self.agents_table.setRowCount(len(agents))
        self._agent_rows = agents  # store for apply

        for row, ag in enumerate(agents):
            self.agents_table.setItem(row, 0, QTableWidgetItem(ag["name"]))
            desc = (ag["description"] or "").strip().replace("\n", " ")[:80]
            self.agents_table.setItem(row, 1, QTableWidgetItem(desc))
            self.agents_table.setItem(row, 2, QTableWidgetItem(str(ag["timeout_s"])))

            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(8, 0, 8, 0)
            chk = QCheckBox()
            chk.setChecked(ag.get("enabled", True))
            chk.setProperty("agent_name", ag["name"])
            chk_layout.addWidget(chk)
            self.agents_table.setCellWidget(row, 3, chk_widget)

            edit_btn = QPushButton("✏️ Edit")
            edit_btn.setProperty("agent_name", ag["name"])
            edit_btn.clicked.connect(lambda _, r=row, a=ag: self._edit_agent(r, a))
            self.agents_table.setCellWidget(row, 4, edit_btn)

        self.agents_table.resizeRowsToContents()

    def _edit_agent(self, row: int, agent_info: dict):
        dlg = AgentEditDialog(agent_info, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            self._agent_overrides[agent_info["name"]] = result
            # Update table display
            self.agents_table.item(row, 2).setText(str(result["timeout_s"]))
            desc = (result["description"] or "").replace("\n", " ")[:80]
            self.agents_table.item(row, 1).setText(desc)
            # Update the checkbox in col 3
            chk_w = self.agents_table.cellWidget(row, 3)
            if chk_w:
                chk = chk_w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(result["enabled"])

    def _apply_agent_changes(self):
        """Write timeout/enabled overrides back to live agent instances."""
        try:
            from eli.brain.agents.agent_bus import _ALL_AGENTS
            applied = []
            for ag in _ALL_AGENTS:
                overrides = self._agent_overrides.get(ag.name, {})
                if overrides:
                    if "timeout_s" in overrides:
                        ag.timeout_s = overrides["timeout_s"]
                    if "enabled" in overrides:
                        ag._enabled = overrides["enabled"]
                    applied.append(ag.name)
            # Also read checkbox states from table
            for row in range(self.agents_table.rowCount()):
                chk_w = self.agents_table.cellWidget(row, 3)
                if chk_w:
                    chk = chk_w.findChild(QCheckBox)
                    if chk:
                        name = chk.property("agent_name")
                        for ag in _ALL_AGENTS:
                            if ag.name == name:
                                ag._enabled = chk.isChecked()
            QMessageBox.information(self, "Agents", f"Applied overrides to: {', '.join(applied) or 'none'}.\nChanges are live until restart.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not apply changes: {e}")

    # ── Models tab ─────────────────────────────────────────────────────────────
    def _build_models_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel("Installed GGUF models and available Ollama models.")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.models_table = QTableWidget()
        self.models_table.setColumnCount(4)
        self.models_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Path / Tag"])
        self.models_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.models_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.models_table)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh Models")
        refresh_btn.clicked.connect(self._populate_models_table)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._populate_models_table()
        return w

    def _populate_models_table(self):
        rows = []
        # GGUF models
        try:
            models = discover_gguf_models()
            for m in models:
                size_str = f"{m.get('size_gb', 0.0):.2f} GB"
                rows.append((m.get("name", "?"), "GGUF", size_str, m.get("path", "")))
        except Exception:
            pass
        # Ollama models
        try:
            host = "http://localhost:11434"
            om = OllamaModelManager()
            ollama_names = om.list_models(host)
            for name in ollama_names:
                rows.append((name, "Ollama", "—", host))
        except Exception:
            pass

        self.models_table.setRowCount(len(rows))
        for i, (name, mtype, size, path) in enumerate(rows):
            self.models_table.setItem(i, 0, QTableWidgetItem(name))
            self.models_table.setItem(i, 1, QTableWidgetItem(mtype))
            self.models_table.setItem(i, 2, QTableWidgetItem(size))
            self.models_table.setItem(i, 3, QTableWidgetItem(str(path)))
        self.models_table.resizeRowsToContents()

    # ── Plugins tab ────────────────────────────────────────────────────────────
    def _build_plugins_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel("Manage ELI plugins. Install from registry, enable, disable, or uninstall.")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.plugins_table = QTableWidget()
        self.plugins_table.setColumnCount(5)
        self.plugins_table.setHorizontalHeaderLabels(
            ["ID", "Version", "Status", "Description", "Actions"]
        )
        self.plugins_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.plugins_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.plugins_table)

        self.plugin_log = QTextEdit()
        self.plugin_log.setReadOnly(True)
        self.plugin_log.setFixedHeight(90)
        self.plugin_log.setPlaceholderText("Plugin operations log…")
        layout.addWidget(self.plugin_log)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._populate_plugins_table)
        btn_row.addWidget(refresh_btn)
        registry_btn = QPushButton("🌐 Fetch Registry")
        registry_btn.clicked.connect(self._fetch_registry)
        btn_row.addWidget(registry_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._populate_plugins_table()
        return w

    def _get_plugin_manager(self):
        try:
            from eli.plugins.manager import get_manager
            return get_manager()
        except Exception as e:
            self._log_plugin(f"Plugin manager unavailable: {e}")
            return None

    def _log_plugin(self, msg: str):
        """Thread-safe: callable from any thread."""
        self._plugin_log_sig.emit(str(msg))

    def _do_log_plugin(self, msg: str):
        """Runs on main thread via signal."""
        if hasattr(self, "plugin_log"):
            self.plugin_log.append(msg)

    def _populate_plugins_table(self):
        mgr = self._get_plugin_manager()
        if mgr is None:
            self.plugins_table.setRowCount(0)
            return

        installed = {p["id"]: p for p in mgr.list_installed()}
        available = mgr.list_available()

        # Merge: show all available, mark which are installed
        all_ids = {e["id"] for e in available}
        # Also add installed ones not in registry
        for pid in installed:
            all_ids.add(pid)

        rows = []
        for entry in available:
            pid = entry["id"]
            inst = installed.get(pid)
            status = "installed+enabled" if (inst and inst.get("enabled")) else \
                     "installed" if inst else "available"
            rows.append({
                "id": pid,
                "version": entry.get("version", "?"),
                "status": status,
                "description": entry.get("description", ""),
                "installed": inst is not None,
                "enabled": inst.get("enabled", False) if inst else False,
            })

        self.plugins_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.plugins_table.setItem(i, 0, QTableWidgetItem(row["id"]))
            self.plugins_table.setItem(i, 1, QTableWidgetItem(row["version"]))
            self.plugins_table.setItem(i, 2, QTableWidgetItem(row["status"]))
            self.plugins_table.setItem(i, 3, QTableWidgetItem(row["description"][:60]))

            btn_w = QWidget()
            btn_l = QHBoxLayout(btn_w)
            btn_l.setContentsMargins(4, 2, 4, 2)
            btn_l.setSpacing(4)

            if not row["installed"]:
                inst_btn = QPushButton("⬇ Install")
                inst_btn.clicked.connect(lambda _, pid=row["id"]: self._install_plugin(pid))
                btn_l.addWidget(inst_btn)
            else:
                if row["enabled"]:
                    dis_btn = QPushButton("⏸ Disable")
                    dis_btn.clicked.connect(lambda _, pid=row["id"]: self._disable_plugin(pid))
                    btn_l.addWidget(dis_btn)
                else:
                    en_btn = QPushButton("▶ Enable")
                    en_btn.clicked.connect(lambda _, pid=row["id"]: self._enable_plugin(pid))
                    btn_l.addWidget(en_btn)
                rm_btn = QPushButton("🗑 Remove")
                rm_btn.clicked.connect(lambda _, pid=row["id"]: self._uninstall_plugin(pid))
                btn_l.addWidget(rm_btn)

            self.plugins_table.setCellWidget(i, 4, btn_w)

        self.plugins_table.resizeRowsToContents()

    def _install_plugin(self, plugin_id: str):
        self._log_plugin(f"Installing {plugin_id}…")
        def worker():
            mgr = self._get_plugin_manager()
            if mgr:
                result = mgr.install(plugin_id, progress_cb=self._log_plugin)
                if result.get("ok", True):
                    self._log_plugin(f"✅ {plugin_id} installed.")
                else:
                    self._log_plugin(f"❌ {plugin_id}: {result.get('error','unknown error')}")
            # signal-safe table refresh from worker thread
            self._plugin_refresh_sig.emit()
        threading.Thread(target=worker, daemon=True).start()

    def _enable_plugin(self, plugin_id: str):
        mgr = self._get_plugin_manager()
        if mgr:
            mgr.enable(plugin_id)
            self._log_plugin(f"✅ {plugin_id} enabled.")
            self._populate_plugins_table()

    def _disable_plugin(self, plugin_id: str):
        mgr = self._get_plugin_manager()
        if mgr:
            mgr.disable(plugin_id)
            self._log_plugin(f"⏸ {plugin_id} disabled.")
            self._populate_plugins_table()

    def _uninstall_plugin(self, plugin_id: str):
        reply = QMessageBox.question(
            self, "Uninstall Plugin",
            f"Remove plugin '{plugin_id}'? This will delete its files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            mgr = self._get_plugin_manager()
            if mgr:
                mgr.uninstall(plugin_id)
                self._log_plugin(f"🗑 {plugin_id} uninstalled.")
                self._populate_plugins_table()

    def _fetch_registry(self):
        self._log_plugin("Fetching plugin registry…")
        def worker():
            mgr = self._get_plugin_manager()
            if mgr:
                try:
                    mgr.refresh_registry()
                    self._log_plugin("✅ Registry refreshed.")
                except Exception as e:
                    self._log_plugin(f"❌ Registry fetch error: {e}")
            self._plugin_refresh_sig.emit()
        threading.Thread(target=worker, daemon=True).start()

    # ── Self-Upgrade tab ───────────────────────────────────────────────────────
    def _build_upgrade_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel(
            "Self-upgrade tools: run improvement cycle, update capability manifest, "
            "view improvement proposals, and apply system updates."
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        # Status panel
        status_group = QGroupBox("System Status")
        status_layout = QFormLayout(status_group)
        self.upgrade_agent_status = QLabel("Loading…")
        status_layout.addRow("Agent Bus:", self.upgrade_agent_status)
        self.upgrade_plugin_status = QLabel("Loading…")
        status_layout.addRow("Plugins:", self.upgrade_plugin_status)
        self.upgrade_memory_status = QLabel("Loading…")
        status_layout.addRow("Memory:", self.upgrade_memory_status)
        layout.addWidget(status_group)

        # Action buttons
        actions_group = QGroupBox("Actions")
        actions_layout = QGridLayout(actions_group)

        cycle_btn = QPushButton("🔄 Run Self-Improvement Cycle")
        cycle_btn.setToolTip("Analyze recent failures and generate improvement proposals")
        cycle_btn.clicked.connect(self._run_improvement_cycle)
        actions_layout.addWidget(cycle_btn, 0, 0)

        manifest_btn = QPushButton("📋 Update Capability Manifest")
        manifest_btn.setToolTip("Scan executor and plugins and regenerate capability_manifest.json")
        manifest_btn.clicked.connect(self._update_capability_manifest)
        actions_layout.addWidget(manifest_btn, 0, 1)

        persona_btn = QPushButton("🧬 Refresh Persona")
        persona_btn.setToolTip("Re-derive ELI's persona from memory and self-model")
        persona_btn.clicked.connect(self._refresh_persona)
        actions_layout.addWidget(persona_btn, 1, 0)

        kg_btn = QPushButton("🗺 Rebuild Knowledge Graph")
        kg_btn.setToolTip("Re-extract entity triples from all stored memories")
        kg_btn.clicked.connect(self._rebuild_kg)
        actions_layout.addWidget(kg_btn, 1, 1)

        faiss_btn = QPushButton("🔢 Rebuild FAISS Index")
        faiss_btn.setToolTip("Re-vectorize all memories in the FAISS index")
        faiss_btn.clicked.connect(self._rebuild_faiss)
        actions_layout.addWidget(faiss_btn, 2, 0)

        layout.addWidget(actions_group)

        # Output log
        self.upgrade_log = QTextEdit()
        self.upgrade_log.setReadOnly(True)
        self.upgrade_log.setPlaceholderText("Upgrade output will appear here…")
        layout.addWidget(self.upgrade_log)

        # Load initial status
        QTimer.singleShot(200, self._refresh_upgrade_status)
        return w

    def _log_upgrade(self, msg: str):
        """Thread-safe: callable from any thread."""
        self._upgrade_log_sig.emit(str(msg))

    def _do_log_upgrade(self, msg: str):
        """Runs on main thread via signal."""
        if hasattr(self, "upgrade_log"):
            self.upgrade_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _refresh_upgrade_status(self):
        try:
            from eli.brain.agents.agent_bus import _ALL_AGENTS
            enabled = sum(1 for a in _ALL_AGENTS if getattr(a, "_enabled", True))
            self.upgrade_agent_status.setText(f"{enabled}/{len(_ALL_AGENTS)} agents active")
        except Exception as e:
            self.upgrade_agent_status.setText(f"unavailable ({e})")

        try:
            from eli.plugins.manager import get_manager
            mgr = get_manager()
            inst = mgr.list_installed()
            enabled_plugins = [p for p in inst if p.get("enabled")]
            self.upgrade_plugin_status.setText(f"{len(enabled_plugins)}/{len(inst)} enabled")
        except Exception as e:
            self.upgrade_plugin_status.setText(f"unavailable ({e})")

        try:
            from eli.brain.memory.memory import get_memory
            mem = get_memory()
            import sqlite3
            from eli.core.paths import user_db_path
            conn = sqlite3.connect(str(user_db_path()))
            mc = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            conn.close()
            self.upgrade_memory_status.setText(f"{mc} memories stored")
        except Exception as e:
            self.upgrade_memory_status.setText(f"unavailable ({e})")

    def _run_improvement_cycle(self):
        self._log_upgrade("Starting self-improvement cycle…")
        def worker():
            try:
                from eli.brain.reflection.self_improvement import SelfImprovementEngine
                eng = SelfImprovementEngine()
                result = eng.analyze_and_improve()
                proposals = result.get("improvements", []) if isinstance(result, dict) else list(result or [])
                if proposals:
                    for p in proposals[:5]:
                        desc = p.get("description", str(p))[:120] if isinstance(p, dict) else str(p)[:120]
                        self._log_upgrade(f"  💡 {desc}")
                    self._log_upgrade(f"✅ Cycle complete. {len(proposals)} proposal(s) generated.")
                else:
                    self._log_upgrade("✅ Cycle complete. No new proposals.")
            except Exception as e:
                self._log_upgrade(f"❌ Cycle error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _update_capability_manifest(self):
        self._log_upgrade("Updating capability manifest…")
        def worker():
            try:
                from eli.tools.registry.capability_updater import update_capability_manifest
                update_capability_manifest()
                self._log_upgrade("✅ Capability manifest updated.")
            except Exception as e:
                # fallback: run auto_update.py script
                try:
                    import subprocess, sys
                    root = Path(__file__).resolve().parents[2]
                    result = subprocess.run(
                        [sys.executable, str(root / "auto_update.py"), "--dry-run"],
                        capture_output=True, text=True, timeout=30
                    )
                    self._log_upgrade(result.stdout[-500:] if result.stdout else f"❌ {e}")
                except Exception as e2:
                    self._log_upgrade(f"❌ {e} / {e2}")
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_persona(self):
        self._log_upgrade("Refreshing persona overlay…")
        def worker():
            try:
                from eli.brain.awareness.persona_updater import update_persona_overlay
                update_persona_overlay()
                self._log_upgrade("✅ Persona refreshed.")
            except Exception as e:
                self._log_upgrade(f"❌ Persona refresh error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_kg(self):
        self._log_upgrade("Rebuilding knowledge graph from memories…")
        def worker():
            try:
                from eli.brain.memory.knowledge_graph import get_knowledge_graph, reset_knowledge_graph
                import sqlite3
                from eli.core.paths import user_db_path
                reset_knowledge_graph()
                kg = get_knowledge_graph()
                conn = sqlite3.connect(str(user_db_path()))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT COALESCE(text, content, '') AS text, COALESCE(source,'user') AS source "
                    "FROM memories WHERE COALESCE(text,content,'') != ''"
                ).fetchall()
                conn.close()
                ok = 0
                for row in rows:
                    kg.extract_from_memory(row["text"], source=row["source"])
                    ok += 1
                stats = kg.stats()
                self._log_upgrade(
                    f"✅ KG rebuilt from {ok} memories → {stats['entities']} entities, {stats['relations']} relations."
                )
            except Exception as e:
                self._log_upgrade(f"❌ KG rebuild error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_faiss(self):
        self._log_upgrade("Rebuilding FAISS vector index (full) — this may take a minute…")
        def worker():
            try:
                import subprocess, sys
                root = Path(__file__).resolve().parents[2]
                script = root / "scripts" / "rebuild_vector_index.py"
                if not script.exists():
                    self._log_upgrade(f"❌ Script not found: {script}")
                    return
                result = subprocess.run(
                    [sys.executable, str(script), "--full"],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(root)
                )
                out = (result.stdout + result.stderr)[-800:]
                self._log_upgrade(out)
                self._log_upgrade("✅ FAISS rebuild complete." if result.returncode == 0 else "❌ FAISS rebuild failed.")
            except Exception as e:
                self._log_upgrade(f"❌ FAISS rebuild error: {e}")
        threading.Thread(target=worker, daemon=True).start()


# ============================================================
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
            print(f"[GUI] parse_intent CE delegation failed: {_ce_delegate_err}")

        try:
            from eli.tools.automation.router_enhanced import route
            return route(user_input)
        except Exception as e:
            print(f"[ENGINE-ADAPTER] parse_intent fallback: {e}")
            return {"action": "CHAT", "args": {"message": user_input},
                    "confidence": 0.7, "meta": {}}

    def verify_persona_lock(self) -> bool:
        return True

    def repair_persona_lock(self):
        pass

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
            from eli.brain.agents.agent_bus import get_bus
            dr = get_bus().dispatch(
                user_input, intent,
                session_id=self.session_id,
                user_id=self.user_id,
            )
            ctx = (dr.memory_context or "").strip()
            print(f"[ENGINE-ADAPTER] AgentBus: agents_used={dr.agents_used} "
                  f"conf={dr.aggregated_confidence:.2f} ctx_chars={len(ctx)}")
            return ctx
        except Exception as e:
            print(f"[ENGINE-ADAPTER] AgentBus dispatch failed: {e}")
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
            print(f"[GUI] assemble_precise_context CE delegation failed: {_ce_delegate_err}")

        import time as _t

        # Token budget: leave enough room for response + safety margin
        _char_budget = max(3000, self._n_ctx * 3 - self._max_tokens * 5)

        # 1. Persona — compact for small models, full for 7B+
        _use_compact = self._n_ctx <= 8192
        persona = self._compact_persona() if _use_compact else (ELI_SYSTEM_PROMPT or "")

        # 2. User profile
        _user_block = ""
        try:
            from eli.brain.state import get_user_profile_text as _gup
            _user_block = _gup().strip()
        except Exception:
            pass
        if not _user_block:
            try:
                from eli.brain.state import get_user_name as _gun
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

        # 5. Reasoning-mode instruction
        _mode_instr = {
            "chain_of_thought": "\nThink step-by-step. Show your reasoning chain, then give the final answer.",
            "self_consistency": "\nGenerate 3 independent reasoning paths, then synthesise the most consistent answer.",
            "tree_of_thoughts": "\nExplore multiple solution branches. Prune weak paths, commit to the strongest.",
            "constitutional_ai": "\nDraft a response, critique it for accuracy and ethics, then output the revised version.",
        }.get(str(reasoning_mode or "quick").lower(), "")

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
            print(f"[GUI] generate_from_assembled_prompt CE delegation failed: {_ce_delegate_err}")

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
            print(f"[ENGINE-ADAPTER] generate_from_assembled_prompt: {e}")
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
            print(f"[GUI] generate_stream_from_assembled_prompt CE delegation failed: {_ce_delegate_err}")

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
            print(f"[ENGINE-ADAPTER] generate_stream_from_assembled_prompt: {e}")
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
            self.memory.add_conversation_turn(
                "user", user_input, self.session_id, self.user_id)
            self.memory.add_conversation_turn(
                "assistant", response, self.session_id, self.user_id)
            # Disabled: automatic assistant-response semantic storage was poisoning retrieval.
            pass
        except Exception as e:
            print(f"[ENGINE-ADAPTER] post_storage failed: {e}")
        # Weight decay — 1 % of responses (amortised cost)
        try:
            import random as _rnd
            if _rnd.random() < 0.01 and hasattr(self.memory, "apply_weight_decay"):
                decayed = self.memory.apply_weight_decay()
                if decayed:
                    print(f"[MEMORY] Weight decay: {decayed} entries aged")
        except Exception:
            pass


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
    # Wizard signal — emits wizard question text to main thread
    wizard_say_signal = pyqtSignal(str)
    # Thread-safe memory stats refresh
    _mem_refresh_sig = pyqtSignal()
    # Screen control: capture result (path or "ERROR:...")
    _sc_capture_sig  = pyqtSignal(str)
    # Quick Actions: result from worker thread → main thread
    _qa_result_sig   = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        try:
            QTimer.singleShot(0, self._ensure_operator_console_dock)
        except Exception:
            pass

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - 100% Local")
        screen = QApplication.primaryScreen().availableGeometry()
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(400, 300)
        self.setGeometry(screen.x() + 20, screen.y() + 20, screen.width() - 40, screen.height() - 40)
        self.is_generating = False
        self.conversation_history = []
        self.current_theme = "dark"
        self._user_text_color = "#a3be8c"  # user message colour (changeable via picker)
        # Agent wizard state
        self._agent_wizard_state: Optional[dict] = None
        self.ollama_manager = OllamaModelManager()
        self.active_backend = model_manager
        self.detected_system_info: Dict[str, Any] = {}
        self._central_memory = None
        if CENTRAL_IMPORTS_AVAILABLE and get_memory:
            self._central_memory = get_memory()

        # Streaming VoiceWorker — interruptible TTS with thread-safe interrupt()
        try:
            from eli.tools.io.voice_worker_streaming import VoiceWorker as _StreamingVW
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
        self.wizard_say_signal.connect(self._wizard_display_message, Qt.ConnectionType.QueuedConnection)
        self._mem_refresh_sig.connect(self.refresh_memory_stats, Qt.ConnectionType.QueuedConnection)

        ensure_dirs()
        self.init_ui()
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
                from eli.brain.cognition import gguf_inference as _ggi
                try:
                    _pre_snap = _ggi.get_runtime_snapshot() or {}
                except Exception:
                    _pre_snap = {}

                model_manager.n_ctx = _pre_int('n_ctx', _pre_snap.get('n_ctx', 0))
                model_manager.n_threads = _pre_int('n_threads', _pre_snap.get('n_threads', 0))
                model_manager.n_gpu_layers = _pre_int('n_gpu_layers', _pre_snap.get('n_gpu_layers', 0))
                model_manager.n_batch = _pre_int('n_batch', _pre_snap.get('n_batch', 0))

                _ggi._llm = _pre
                _ggi._live_runtime_override = {
                    "provider": "gguf",
                    "loaded": True,
                    "model_path": str(model_manager.model_path or ""),
                    "model_name": Path(model_manager.model_path).name if model_manager.model_path else "",
                    "n_ctx": int(model_manager.n_ctx or 0),
                    "n_gpu_layers": int(model_manager.n_gpu_layers or 0),
                    "n_threads": int(model_manager.n_threads or 0),
                    "n_batch": int(model_manager.n_batch or 0),
                }
                _ggi._live_runtime_params = dict(_ggi._live_runtime_override)
                try:
                    _ggi._write_shared_runtime_snapshot(dict(_ggi._live_runtime_override))
                except Exception as _gg_snap_err:
                    print(f"[GUI] gguf preloaded snapshot write failed: {_gg_snap_err}")
                print("✅ gguf_inference preloaded runtime override published")
            except Exception as _pre_wire_err:
                model_manager.n_ctx = _pre_int('n_ctx', 0)
                model_manager.n_threads = _pre_int('n_threads', 0)
                model_manager.n_gpu_layers = _pre_int('n_gpu_layers', 0)
                model_manager.n_batch = _pre_int('n_batch', 0)
                print(f"[GUI] preloaded runtime handoff failed: {_pre_wire_err}")

            try:
                model_manager._write_shared_runtime_snapshot(
                    model_manager.model_path,
                    model_manager.n_ctx,
                    model_manager.n_threads,
                    model_manager.n_gpu_layers,
                )
            except Exception as _pre_snap_err:
                print(f"[GUI] preloaded runtime snapshot write failed: {_pre_snap_err}")

            self.active_backend = model_manager
            self.status_signal.emit(
                f"🟢 Model ready: {Path(model_manager.model_path).name}"
            )
        QTimer.singleShot(600, self.maybe_run_first_time_setup)

        # ---------- START PROACTIVE DAEMON ----------
        self._proactive_daemon = None
        self._proactive_dock = None
        if start_daemon:
            try:
                from eli.brain.proactive.proactive_daemon import start_daemon as _start_pd
                self._proactive_daemon = _start_pd()
                print("[GUI] Proactive daemon started")
                # Attach ProactiveDock so proactive output has a dedicated panel
                try:
                    from eli.gui.docks.proactive_dock import ProactiveDock
                    self._proactive_dock = ProactiveDock(self)
                    self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._proactive_dock)
                    self._proactive_dock.hide()  # hidden by default; shown when daemon posts
                    print("[GUI] ProactiveDock attached")
                except Exception as _dock_err:
                    print(f"[GUI] ProactiveDock unavailable (non-fatal): {_dock_err}")
                # Consume daemon suggestion_queue → proactive tab (thread-safe)
                threading.Thread(
                    target=self._daemon_queue_consumer, daemon=True,
                    name="eli-daemon-queue").start()
            except Exception as e:
                print(f"[GUI] Failed to start proactive daemon: {e}")
        else:
            print("[GUI] Proactive daemon not available (import failed)")

        # ---------- COGNITIVE ENGINE SINGLETON ----------
        self._cognitive_engine = None
        try:
            from eli.brain.cognition.cognitive_engine import CognitiveEngine
            self._cognitive_engine = CognitiveEngine()
            print("[GUI] CognitiveEngine singleton ready (reflection/habit/awareness active)")
        except Exception as _ce_init_err:
            print(f"[GUI] CognitiveEngine init skipped (non-fatal): {_ce_init_err}")

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
                    phrase = data.get("phrase") or data.get("name", "")
                    cnt   = data.get("count", "")
                    line  = f"<b>[{stype}]</b> {phrase}{f' (×{cnt})' if cnt else ''}: {sugg}"
                    self.proactive_suggestions_signal.emit(line)
                elif kind == "improvement":
                    cat  = data.get("category", "code")
                    det  = data.get("detail", "") or data.get("description", "")
                    self.proactive_insights_signal.emit(
                        f"<b>[{cat}]</b> {det[:200]}")
                elif kind == "habit":
                    name = data.get("name", "")
                    sugg = data.get("suggestion", "")
                    self.proactive_suggestions_signal.emit(
                        f"<b>[habit]</b> {name}: {sugg}")
                else:
                    self.proactive_suggestions_signal.emit(
                        f"<b>[{kind}]</b> {str(data)[:200]}")
                # NOTE: do NOT touch _proactive_dock widgets from this thread —
                # dock forwarding is handled by _update_suggestions_display on the GUI thread.
            except Exception as _sig_err:
                print(f"[GUI] daemon queue signal failed: {_sig_err}")

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

    # ---------- TTS / STT (unchanged) ----------
    def _speak_response(self, text: str):
        import re as _re, threading, subprocess, unicodedata
        if not text or not isinstance(text, str): return
        printable = sum(1 for c in text if unicodedata.category(c)[0] != 'C')
        if printable / max(len(text), 1) < 0.8: return
        clean = _re.sub(r'[*_`#>|\[\]~]', '', text)
        clean = _re.sub(r'\s+', ' ', clean).strip()[:600]
        if not clean: return
        # Use streaming VoiceWorker if available (supports interrupt())
        if self._voice_worker is not None:
            self._voice_worker.speak(clean)
            return
        PIPER = os.environ.get("ELI_PIPER_BIN",
                    str(Path.home() / ".local" / "bin" / "piper"))
        MODEL = os.environ.get("ELI_PIPER_MODEL",
                    str(PROJECT_ROOT / "voices" / "en_US-amy-medium.onnx"))
        def _run():
            try:
                p = subprocess.run([PIPER,'--model',MODEL,'--output-raw'],
                    input=clean.encode(), capture_output=True, timeout=30)
                if p.returncode == 0 and p.stdout:
                    subprocess.run(['aplay','-r','22050','-f','S16_LE','-t','raw','-'],
                        input=p.stdout, capture_output=True, timeout=60)
                else:
                    subprocess.run(['espeak-ng','-s','165',clean], capture_output=True)
            except Exception as e: print(f'[TTS] {e}')
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

    def _on_stt_transcript(self, text: str):
        text = text.strip()
        if not text:
            return
        print(f"[STT→GUI] {text}")
        self.chat_input.setPlainText(text)
        self.send_message()

    def _stt_toggle(self, checked: bool):
        if checked:
            self.stt_btn.setText("🔴 Mic: ON")
            def _cb(text):
                text = (text or "").strip()
                if text:
                    print(f"[STT] emitting: {text}")
                    self.stt_transcript.emit(text)
            try:
                from eli.tools.io.audio_stt import start_audio_listening, stop_audio_listening
                start_audio_listening(callback=_cb)
                self._stt_stop_ref = stop_audio_listening
                print("[STT] listening started — say: computer, <command>")
            except Exception as e:
                print(f"[STT] start failed: {e}")
                self.stt_btn.setChecked(False)
                self.stt_btn.setText("🎤 Mic: OFF")
        else:
            self.stt_btn.setText("🎤 Mic: OFF")
            try:
                fn = getattr(self, "_stt_stop_ref", None)
                if fn:
                    fn()
                print("[STT] listening stopped")
            except Exception as e:
                print(f"[STT] stop failed: {e}")

    def change_reasoning_mode(self, label: str = 'quick'):
        mapping = {
            "⚡ Quick": "quick",
            "🔗 Chain of Thought": "chain_of_thought",
            "🔄 Self-Consistency": "self_consistency",
            "🌳 Tree of Thoughts": "tree_of_thoughts",
            "⚖️ Constitutional AI": "constitutional_ai",
        }
        self._reasoning_mode = mapping.get(label, "quick")
        try:
            self.chat_display.append(f'<span style="color:#88c0d0;font-size:11px;">⚙️ Mode: {label}</span><br>')
        except Exception:
            pass

    def _get_mode_prefix(self) -> str:
        mode = getattr(self, '_reasoning_mode', 'quick')
        prefixes = {
            'quick': '',
            'chain_of_thought': '\n\n[REASONING MODE: Chain of Thought]\nThink step-by-step. Show your reasoning chain explicitly before giving the final answer.',
            'self_consistency': '\n\n[REASONING MODE: Self-Consistency]\nGenerate 3 independent reasoning paths, then synthesize the most consistent answer.',
            'tree_of_thoughts': '\n\n[REASONING MODE: Tree of Thoughts]\nExplore multiple solution branches. Evaluate each branch, prune weak paths, and commit to the strongest.',
            'constitutional_ai': '\n\n[REASONING MODE: Constitutional AI]\nFirst draft your response, then critique it against accuracy/ethics/rigor, then revise and output the improved version.',
        }
        return prefixes.get(mode, '')

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
        main_layout.addWidget(self.tabs)
        self.create_chat_tab()
        self.create_memory_tab()
        self.create_habits_tab()          # <-- NEW HABITS TAB (FIXED)
        self.create_proactive_tab()
        self.create_self_improve_tab()
        self.create_quick_actions_tab()
        self.create_screen_control_tab()
        self.create_ide_tab()
        self.create_documents_tab()
        self.create_files_tab()
        self.create_settings_tab()
        self.status_bar = self.statusBar()
        self.status_label = QLabel("🔴 Model not loaded")
        self.status_bar.addWidget(self.status_label)
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
        unload_model = QAction("Unload Model", self)
        unload_model.triggered.connect(self.unload_model)
        model_menu.addAction(unload_model)
        view_menu = menubar.addMenu("&View")
        toggle_theme = QAction("Toggle Theme", self)
        toggle_theme.setShortcut("Ctrl+T")
        toggle_theme.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme)
        help_menu = menubar.addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def create_chat_tab(self):
        chat_widget = QWidget()
        layout = QVBoxLayout(chat_widget)
        header = QLabel(f"💬 {APP_NAME} - Local AI Assistant")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
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
        self.chat_display = ZoomableTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlaceholderText("Conversation will appear here...")
        layout.addWidget(self.chat_display, stretch=7)
        input_group = QGroupBox("Your Message")
        input_layout = QVBoxLayout(input_group)
        self.chat_input = QTextEdit()
        self.chat_input.setPlaceholderText("Type your message here... (Ctrl+Return to send)")
        self.chat_input.setMaximumHeight(100)
        self.chat_input.installEventFilter(self)
        input_layout.addWidget(self.chat_input)
        btn_layout = QHBoxLayout()
        self.send_btn = QPushButton("Send")
        self.send_btn.setMinimumHeight(40)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                border-radius: 5px;
                padding: 10px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #cccccc; }
        """)
        self.send_btn.clicked.connect(self.send_message)
        btn_layout.addWidget(self.send_btn)
        clear_btn = QPushButton("Clear Chat")
        clear_btn.setMinimumHeight(40)
        clear_btn.clicked.connect(self.clear_chat)
        btn_layout.addWidget(clear_btn)
        self.tts_btn = QPushButton("🔊 Speak Last")
        self.tts_btn.setMinimumHeight(40)
        self.tts_btn.setToolTip("Speak last ELI response via Piper TTS")
        self.tts_btn.setStyleSheet("""
            QPushButton { background-color: #2196F3; color: white;
                          font-weight: bold; border-radius: 5px; padding: 8px; }
            QPushButton:hover { background-color: #1976D2; }
        """)
        self.tts_btn.clicked.connect(self._speak_last_response)
        btn_layout.addWidget(self.tts_btn)
        self.auto_speak_btn = QPushButton("🔇 Auto-Speak: OFF")
        self.auto_speak_btn.setMinimumHeight(40)
        self.auto_speak_btn.setCheckable(True)
        self.auto_speak_btn.setToolTip("Auto-speak every ELI response")
        self.auto_speak_btn.setStyleSheet("""
            QPushButton { background-color: #607D8B; color: white;
                          font-weight: bold; border-radius: 5px; padding: 8px; }
            QPushButton:checked { background-color: #2196F3; }
            QPushButton:hover { background-color: #455A64; }
        """)
        self.auto_speak_btn.toggled.connect(self._on_auto_speak_toggled)
        btn_layout.addWidget(self.auto_speak_btn)
        self.stt_btn = QPushButton("🎤 Mic: OFF")
        self.stt_btn.setMinimumHeight(40)
        self.stt_btn.setCheckable(True)
        self.stt_btn.setToolTip("Toggle voice input on/off")
        self.stt_btn.setStyleSheet("""
            QPushButton { background-color: #607D8B; color: white;
                          font-weight: bold; border-radius: 5px; padding: 8px; }
            QPushButton:checked { background-color: #FF5722; }
            QPushButton:hover { background-color: #455A64; }
        """)
        self.stt_btn.toggled.connect(self._stt_toggle)
        btn_layout.addWidget(self.stt_btn)
        self.reasoning_mode_combo = QComboBox()
        self.reasoning_mode_combo.addItems(['⚡ Quick','🔗 Chain of Thought','🔄 Self-Consistency','🌳 Tree of Thoughts','⚖️ Constitutional AI'])
        self.reasoning_mode_combo.setMinimumHeight(40)
        self.reasoning_mode_combo.setMinimumWidth(190)
        self.reasoning_mode_combo.setToolTip('Reasoning mode')
        self.reasoning_mode_combo.setStyleSheet('QComboBox{background:#2d2d2d;color:#88c0d0;border:1px solid #88c0d0;border-radius:6px;padding:4px 8px;font-size:12px;}QComboBox QAbstractItemView{background:#2d2d2d;color:#ccc;selection-background-color:#3e3e3e;}')
        btn_layout.addWidget(self.reasoning_mode_combo)
        self.reasoning_mode_combo.currentTextChanged.connect(self.change_reasoning_mode)
        user_color_btn = QPushButton("🎨")
        user_color_btn.setMinimumHeight(40)
        user_color_btn.setMaximumWidth(44)
        user_color_btn.setToolTip("Pick colour for your messages")
        user_color_btn.clicked.connect(self._pick_user_color)
        btn_layout.addWidget(user_color_btn)
        btn_layout.addStretch()
        input_layout.addLayout(btn_layout)
        layout.addWidget(input_group, stretch=2)
        self.tabs.addTab(chat_widget, "💬 Chat")

    # ========== HABITS TAB (FIXED) ==========
    def create_habits_tab(self):
        """Habits management tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        header = QLabel("⏰ Habits Scheduler")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
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

        self.tabs.addTab(widget, "⏰ Habits")
        self.refresh_habit_list()

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

    # ---------- Self-Improvement tab (unchanged) ----------
    def create_self_improve_tab(self):
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
                from eli.core.paths import memory_db_path
                import sqlite3
                db = str(memory_db_path())
                con = sqlite3.connect(db)
                try:
                    imps = con.execute(
                        "SELECT area, suggestion, status FROM improvements ORDER BY ts DESC LIMIT 20"
                    ).fetchall()
                except Exception:
                    imps = []
                try:
                    fails = con.execute(
                        "SELECT user_input, error FROM failures ORDER BY ts DESC LIMIT 5"
                    ).fetchall()
                except Exception:
                    fails = []
                try:
                    _row = con.execute("SELECT COUNT(*) FROM memories").fetchone()
                    mem_count = _row[0] if _row else 0
                    _row2 = con.execute("SELECT COUNT(*) FROM conversation_turns").fetchone()
                    turn_count = _row2[0] if _row2 else 0
                except Exception:
                    mem_count = turn_count = 0
                con.close()

                lines = []
                if imps:
                    lines.append("=== Stored Improvements ===")
                    for area, sug, status in imps:
                        lines.append(f"[{status or 'pending'}] {area}: {sug}")
                backend = self._text_backend_ready(notify=False)
                if backend and fails:
                    fail_txt = "\n".join(
                        f"- {str(i or '')[:60]}: {str(e or '')[:60]}" for i, e in fails
                    )
                    prompt = f"Recent ELI errors:\n{fail_txt}\n\nSuggest 3 specific improvements:"
                    with self.__class__._inference_lock:
                        resp = backend.generate(prompt=prompt, max_tokens=300, temperature=0.6)
                    lines.append("\n=== AI Suggestions ===")
                    lines.append(resp)
                elif not imps and not fails:
                    lines.append("No failures or improvements recorded yet.")
                    lines.append("Chat with ELI, trigger errors, or use the app to generate data.")
                    lines.append(f"Memory DB: {mem_count} memories, {turn_count} conversation turns stored.")
                lines.append("--- Cycle complete ---")
                self.self_improve_improvements_signal.emit("\n".join(lines))
            except Exception as e:
                self.self_improve_improvements_signal.emit(f"Error: {e}")
        import threading
        threading.Thread(target=worker, daemon=True).start()

    def create_memory_tab(self):
        memory_widget = QWidget()
        layout = QVBoxLayout(memory_widget)
        header = QLabel("🧠 Memory System")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)
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
        self.tabs.addTab(memory_widget, "🧠 Memory")
        self.tabs.currentChanged.connect(lambda idx: self.refresh_memory_stats() if self.tabs.tabText(idx) == "🧠 Memory" else None)
        QTimer.singleShot(500, self.refresh_memory_stats)

    def create_proactive_tab(self):
        proactive_widget = QWidget()
        layout = QVBoxLayout(proactive_widget)
        header = QLabel("🎯 Proactive Insights")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)
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

    _QA_CATEGORIES = {
        "System":  {"SCREENSHOT", "HARDWARE_PROFILE", "SYSTEM_STATS", "CPU_USAGE",
                    "RAM_USAGE", "SHELL_EXEC", "RUN_CMD", "OPEN_FILE_SYSTEM",
                    "CREATE_FOLDER", "LIST_DIR", "READ_FILE", "TIME", "DATE",
                    "GET_TIME", "GET_DATE", "CLOSE_APP", "SET_CLIPBOARD",
                    "GET_CLIPBOARD", "KEYBOARD", "MOUSE_CONTROL",
                    "SCREEN_READ_ANALYZE"},
        "Apps":    {"OPEN_APP", "OPEN_URL", "OPEN_BROWSER", "OPEN_IDE",
                    "OPEN_IN_IDE", "OPEN_SYSTEM_SETTINGS", "OPEN_AUDIO_SETTINGS",
                    "OPEN_POWER_SETTINGS", "OPEN_COMMUNICATION_HUB",
                    "OPEN_MEDIA_HUB", "OPEN_NETWORK_BROWSER"},
        "Media":   {"PLAY_MEDIA", "PAUSE_MEDIA", "STOP_MEDIA", "NEXT_MEDIA",
                    "PREVIOUS_MEDIA", "SHUFFLE_MEDIA", "REPEAT_MEDIA",
                    "MEDIA_CONTROL", "VOLUME", "SPEAK", "DICTATE", "TRANSCRIBE"},
        "Memory":  {"MEMORY_RECALL", "MEMORY_STORE", "MEMORY_STATS",
                    "CLEAR_CHAT_HISTORY"},
        "AI":      {"SELF_ANALYZE", "SELF_IMPROVE", "SELF_TEST", "SELF_UPGRADE",
                    "AWARENESS_STATUS", "CODE_CHANGES", "COGNITION_STATUS",
                    "MEMORY_STATUS", "RUNTIME_STATUS", "MORNING_REPORT",
                    "EXPLAIN_MEMORY_RUNTIME", "EXPLAIN_COGNITION_RUNTIME",
                    "RUNTIME_AUDIT", "IMPORT_AUDIT", "RESOLVE_RUNTIME_PATHS",
                    "GUI_RUNTIME_AUDIT", "GENERATE_DOCUMENT", "GENERATE_SCRIPT",
                    "GENERATE_PROJECT", "FIX_FILE", "SHOW_DIFF",
                    "DATA_FABRICATOR", "CREATE_DOCUMENT"},
        "Tools":   {"WEB_SEARCH", "NEWS_FETCH", "GET_WEATHER", "SET_TIMER",
                    "SET_ALARM", "ANALYZE_PDF", "ANALYZE_CSV", "OCR_IMAGE",
                    "SUMMARIZE_FILE", "WRITE_NOTE", "LIST_NOTES", "SEARCH_NOTES",
                    "NEW_NOTE", "CONVERT_DOCUMENT", "EXECUTE_GOAL", "SEQUENCE"},
        "Plugins": {"LIST_EVENTS", "ADD_EVENT", "SMART_HOME",
                    "PLUGIN_LIST", "PLUGIN_INSTALL", "PLUGIN_UNINSTALL",
                    "PLUGIN_ENABLE", "PLUGIN_DISABLE", "PLUGIN_SEARCH",
                    "POMODORO_START", "POMODORO_STOP", "POMODORO_STATUS"},
        "Persona": {"PERSONA_LOCK_STATUS", "PERSONA_LOCK_SET", "PERSONA_LOCK_CLEAR",
                    "HABIT_STATUS", "PROACTIVE_START", "PROACTIVE_STOP",
                    "PROACTIVE_STATUS", "CHECK_CHRONAL_ALIGNMENT"},
    }

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
            from eli.tools.automation.executor_enhanced import SUPPORTED_ACTIONS
            caps.update(a.upper() for a in SUPPORTED_ACTIONS)
        except Exception:
            pass

        # 2. CapabilitySync — only keep executor-backed entries
        try:
            from eli.brain.awareness.capability_sync import CapabilitySync
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
        if not txt:
            self._qa_render_list(self._qa_all_caps)
        else:
            self._qa_render_list([c for c in self._qa_all_caps if txt in c])

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
                from eli.tools.automation.executor_enhanced import execute
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
                out = tempfile.mktemp(prefix="eli_sc_", suffix=".png")
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
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
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
        self.tabs.addTab(ide_widget, "⌨️  IDE")
        self.current_file_path = None

    def create_documents_tab(self):
        docs_widget = QWidget()
        layout = QVBoxLayout(docs_widget)
        header = QLabel("📄 Document Viewer")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)
        toolbar = QHBoxLayout()
        open_doc_btn = QPushButton("📂 Open Document")
        open_doc_btn.clicked.connect(self.open_document)
        toolbar.addWidget(open_doc_btn)
        toolbar.addStretch()
        self.doc_info_label = QLabel("No document loaded")
        toolbar.addWidget(self.doc_info_label)
        layout.addLayout(toolbar)
        self.doc_display = QTextEdit()
        self.doc_display.setReadOnly(True)
        self.doc_display.setPlaceholderText("Open a document to view its contents...")
        layout.addWidget(self.doc_display)
        self.tabs.addTab(docs_widget, "📄 Documents")

    def create_files_tab(self):
        files_widget = QWidget()
        layout = QVBoxLayout(files_widget)
        header = QLabel("📁 File Browser")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
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

    def _generate_agent_from_answers(self, answers: List[str]):
        """Parse wizard answers and write a new agent Python file + register it."""
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

            # Write to eli/brain/agents/custom/
            agents_custom_dir = Path(__file__).resolve().parents[1] / "brain" / "agents" / "custom"
            agents_custom_dir.mkdir(parents=True, exist_ok=True)
            (agents_custom_dir / "__init__.py").touch(exist_ok=True)

            agent_file = agents_custom_dir / f"{agent_name}.py"
            agent_file.write_text(agent_code, encoding="utf-8")

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
from eli.brain.agents.agent_bus import _BaseAgent, AgentResult


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
    from eli.brain.agents.agent_bus import _ALL_AGENTS
    if not any(a.name == "{agent_name}" for a in _ALL_AGENTS):
        _ALL_AGENTS.append({class_name}())


    def _ensure_operator_console_dock(self):
        try:
            dock = getattr(self, "_operator_console_dock", None)
            if dock is None:
                from eli.gui.docks.operator_console_dock import OperatorConsoleDock
                dock = OperatorConsoleDock(self)
                self._operator_console_dock = dock
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            return dock
        except Exception as exc:
            print(f"[WARN] operator console dock init failed: {exc}")
            return None

    def show_operator_console(self):
        dock = self._ensure_operator_console_dock()
        if dock is not None:
            dock.show()
            try:
                dock.raise_()
            except Exception:
                pass
            try:
                dock.refresh_all()
            except Exception:
                pass
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
            from eli.brain.agents.agent_bus import get_bus
            bus = get_bus()
            if hasattr(bus, "_pool"):
                from concurrent.futures import ThreadPoolExecutor
                from eli.brain.agents.agent_bus import _ALL_AGENTS
                bus._pool._max_workers = len(_ALL_AGENTS)
            return True
        except Exception as e:
            print(f"[WIZARD] Live registration failed: {e}")
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
        ("Application", "🖥"),
        ("Agents",      "🤖"),
        ("Advanced",    "⚙️"),
    ]

    def create_settings_tab(self):
        root = QWidget()
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
        self._settings_stack.addWidget(self._build_settings_app_page())
        self._settings_stack.addWidget(self._build_settings_agents_page())
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

        zoom_reset_btn = QPushButton("⊙  100%")
        zoom_reset_btn.setFixedHeight(28)
        zoom_reset_btn.setToolTip("Reset zoom (Ctrl+Scroll to zoom)")
        zoom_reset_btn.setStyleSheet(
            "QPushButton{background:#2e3440;color:#6b7a90;font-weight:500;"
            "border:none;border-radius:5px;padding:0 10px;font-size:10px;}"
            "QPushButton:hover{background:#3b4252;color:#d8dee9;}"
        )
        zoom_reset_btn.clicked.connect(
            lambda: self._settings_zoom_view.zoom_reset()
        )
        footer_layout.addWidget(zoom_reset_btn)

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
        self.n_ctx_input.setValue(4096)
        self.n_ctx_input.setSingleStep(512)
        self.n_ctx_input.setToolTip("Token context window — larger = more memory")
        form.addRow(self._field_label("Context size"), self.n_ctx_input)

        self.n_threads_input = QSpinBox()
        self.n_threads_input.setRange(1, 64)
        self.n_threads_input.setValue(8)
        form.addRow(self._field_label("CPU threads"), self.n_threads_input)

        self.n_gpu_layers_input = QSpinBox()
        self.n_gpu_layers_input.setRange(0, 200)
        self.n_gpu_layers_input.setValue(10)
        self.n_gpu_layers_input.setToolTip("Layers offloaded to GPU (0 = CPU only, 99 = all layers)")
        form.addRow(self._field_label("GPU layers"), self.n_gpu_layers_input)

        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(1, 2048)
        self.batch_size_input.setValue(128)
        self.batch_size_input.setSingleStep(64)
        self.batch_size_input.setToolTip("Prompt processing batch size — larger is faster but uses more VRAM")
        form.addRow(self._field_label("Batch size"), self.batch_size_input)

        self.auto_load_checkbox = QCheckBox("Auto-load backend on startup")
        self.auto_load_checkbox.setStyleSheet("color:#c8d0e0;")
        form.addRow("", self.auto_load_checkbox)

        # TTS backend status (live probe via tts_router.available_backends)
        tts_form = self._section_card(vbox, "VOICE / TTS BACKENDS")
        try:
            from eli.tools.io.tts_router import available_backends as _tts_backends
            _be = _tts_backends()
            _status_lines = [
                f"Piper binary: {'✅ found' if _be.get('piper_bin') else '❌ not found'}",
                f"Piper model:  {'✅ found' if _be.get('piper_model') else '❌ not found'}",
                f"espeak-ng:    {'✅' if _be.get('espeak_ng') else '❌'}",
                f"espeak:       {'✅' if _be.get('espeak') else '❌'}",
            ]
            _tts_lbl = QLabel("\n".join(_status_lines))
            _tts_lbl.setStyleSheet("color:#8eaac8; font-family:monospace; font-size:11px;")
            tts_form.addRow(_tts_lbl)
        except Exception:
            tts_form.addRow(QLabel("TTS status unavailable"))

        vbox.addStretch()
        return page

    # ── Page 2 — Generation ───────────────────────────────────────────────────
    def _build_settings_generation_page(self) -> QWidget:
        page, vbox = self._settings_page(
            "Generation",
            "Tune how ELI generates text — length, creativity, and sampling."
        )
        form = self._section_card(vbox, "SAMPLING")

        self.max_tokens_input = QSpinBox()
        self.max_tokens_input.setRange(128, 4096)
        self.max_tokens_input.setValue(2048)
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

    # ── Page 5 — Advanced ─────────────────────────────────────────────────────
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

    def maybe_run_first_time_setup(self):
        try:
            # Skip auto-load if the launcher already wired a model
            if getattr(self, 'active_backend', None) and getattr(self.active_backend, 'is_loaded', False):
                return
            if getattr(self, '_first_run_complete', False):
                if self.auto_load_checkbox.isChecked():
                    self.load_model()
                return
            self.apply_recommended_setup()
            provider = MODEL_PROVIDER_LABELS.get(self.current_provider(), self.current_provider())
            target = self.resolve_selected_model_path() or self.ollama_model_combo.currentText().strip()
            msg = (
                'First-run setup detected.\n\n'
                f'Recommended provider: {provider}\n'
                f'Recommended model: {Path(target).name if target else target}\n\n'
                f'{self.system_recommendation_label.text()}\n\n'
                'Apply this recommendation and mark first run complete?'
            )
            reply = QMessageBox.question(self, 'First-run setup', msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes)
            if reply == QMessageBox.StandardButton.Yes:
                self._first_run_complete = True
                self.save_settings(silent=True)
                if self.auto_load_checkbox.isChecked():
                    self.load_model()
        except Exception as e:
            print(f'[FIRST RUN] setup warning: {e}')

    def _text_backend_ready(self, notify: bool = True):
        backend = self.get_active_backend()
        if backend and getattr(backend, 'is_loaded', False):
            return backend
        if notify:
            try:
                QMessageBox.warning(self, 'Model Not Loaded',
                    'Please load a model first via Model menu or Settings tab.')
            except Exception:
                print('[WARN] Model not loaded')
        return None

    def get_active_backend(self):
        return self.ollama_manager if self.current_provider() == 'ollama' else model_manager

    # ---------- Event Handlers ----------
    def eventFilter(self, obj, event):
        if obj == self.chat_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    def prompt_load_model(self):
        self.maybe_run_first_time_setup()

    def load_model(self):
        provider = self.current_provider()
        n_ctx = self.n_ctx_input.value()
        n_threads = self.n_threads_input.value()
        n_gpu_layers = self.n_gpu_layers_input.value()
        self.status_signal.emit("🔄 Loading model...")
        self.status_signal.emit("Send disabled")
        try:
            self.send_btn.setText("Loading...")
        except Exception:
            pass

        def load_worker():
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
                        n_gpu_layers=n_gpu_layers
                    )
                    backend = model_manager
                    model_name_display = Path(getattr(model_manager, 'model_path', model_path or 'model')).name

                if success:
                    self.active_backend = backend
                    memory_system.log_event('model_load', f"Loaded {model_name_display} via {provider}")
                    self.status_signal.emit("🟢 Model loaded - Ready")
                    self.status_signal.emit(f"🟢 Model ready: {model_name_display}")
                    self.status_signal.emit("Send enabled")
                else:
                    err = getattr(backend, 'load_error', None) or 'Unknown error'
                    self.status_signal.emit(f"🔴 Model load failed: {err}")
                    self.status_signal.emit("🔴 Model: Not loaded")
                    self.status_signal.emit("Send enabled")
                    print(f"Model Load Error: {err}")
            finally:
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
        self.status_signal.emit("🔴 Model not loaded")
        self.status_signal.emit("🔴 Model: Not loaded")
        self.status_signal.emit("Send enabled")

    def send_message(self):
        if self.is_generating:
            return
        user_message = self.chat_input.toPlainText().strip()
        if not user_message:
            return
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

        intent = executor_bridge.route_command(user_message)
        action = intent.get('action')
        args = intent.get('args', {})

        engine_owned_actions = {
            "RUNTIME_STATUS",
            "MEMORY_STATUS",
            "COGNITION_STATUS",
            "MEMORY_RECALL",
            "RESOLVE_RUNTIME_PATHS",
            "GUI_RUNTIME_AUDIT",
            "RUNTIME_AUDIT",
            "EXPLAIN_MEMORY_RUNTIME",
            "EXPLAIN_COGNITION_RUNTIME",
        }

        if action != 'CHAT' and action not in engine_owned_actions:
            self.is_generating = True
            self.status_signal.emit('Send disabled')
            self.send_btn.setText('Running...')
            self.status_signal.emit(f'⚡ Executing {action}...')

            def execute_worker():
                try:
                    result = executor_bridge.execute_action(action, args)
                    self.chat_response_signal.emit(f"⚡ {result}")
                except Exception as e:
                    self.chat_response_signal.emit(f"❌ Command error: {str(e)}")
                finally:
                    self.is_generating = False
                    self.status_signal.emit('Send enabled')
                    self.status_signal.emit('🟢 Ready')

            threading.Thread(target=execute_worker, daemon=True).start()
            return

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

                # ── PATH 1: AgentOrchestrator via _GUIEngineAdapter (11-stage pipeline) ──
                adapter = _GUIEngineAdapter(
                    backend          = backend,
                    memory           = self._central_memory,
                    max_tokens       = max_tokens,
                    temperature      = temperature,
                    n_ctx            = n_ctx,
                    inference_lock   = self.__class__._inference_lock,
                    cognitive_engine = getattr(self, '_cognitive_engine', None),
                )
                _orchestrator_ok = False
                try:
                    from eli.brain.cognition.orchestrator import AgentOrchestrator
                    result = AgentOrchestrator(adapter).run(
                        user_message,
                        stream=True,
                        reasoning_mode=reasoning_mode,
                    )
                    _orchestrator_ok = True
                except Exception as _orch_err:
                    print(f"[GUI] Orchestrator failed, falling back to CognitiveEngine: {_orch_err}")
                    result = None

                # ── PATH 2: CognitiveEngine fallback (reflection/habits/bus/governance) ──
                _ce_ok = False
                if not _orchestrator_ok:
                    print("[GUI] PATH2 FALLBACK -> CognitiveEngine")
                    _ce = getattr(self, '_cognitive_engine', None)
                    if _ce is not None:
                        try:
                            result = _ce.process(
                                user_message,
                                stream=True,
                                reasoning_mode=reasoning_mode,
                            )
                            _ce_ok = True
                        except Exception as _ce_err:
                            print(f"[GUI] CognitiveEngine.process failed: {_ce_err}")
                            result = None

                full_tokens = []
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
                            response = ""
                            try:
                                if _orchestrator_ok:
                                    from eli.brain.cognition.orchestrator import AgentOrchestrator
                                    fallback_result = AgentOrchestrator(adapter).run(
                                        user_message,
                                        stream=False,
                                        reasoning_mode=reasoning_mode,
                                    )
                                elif _ce_ok:
                                    fallback_result = _ce.process(
                                        user_message,
                                        stream=False,
                                        reasoning_mode=reasoning_mode,
                                    )
                                else:
                                    fallback_result = None

                                if isinstance(fallback_result, dict):
                                    response = str(
                                        fallback_result.get("content")
                                        or fallback_result.get("response")
                                        or fallback_result.get("result")
                                        or ""
                                    )
                                elif fallback_result is not None:
                                    response = str(fallback_result or "")
                            except Exception as _empty_stream_fallback_err:
                                print(f"[GUI] Empty-stream fallback failed: {_empty_stream_fallback_err}")
                                response = ""

                            if response:
                                self.chat_response_signal.emit(response)
                                _response_streamed = True
                                _storage_handled = True
                            else:
                                response = (
                                    "❌ Stage 11 produced an empty stream, and the non-streaming "
                                    "fallback also returned no visible output."
                                )
                                self.chat_response_signal.emit(response)
                                _response_streamed = True
                        else:
                            self.chat_response_signal.emit('__STREAM_END__')
                            _response_streamed = True
                            response = ''.join(full_tokens)
                        if _ce_ok:
                            # CognitiveEngine stores turns in its finally block — skip GUI double-store
                            _storage_handled = True
                        else:
                            # AgentOrchestrator skips post-storage on streaming; do it here
                            try:
                                adapter.enqueue_post_response_storage(
                                    user_message, response, {}, command=False)
                            except Exception:
                                pass
                    elif isinstance(result, dict):
                        # ── Action result or non-streaming CHAT ──
                        response = str(
                            result.get("content")
                            or result.get("response")
                            or result.get("result")
                            or ""
                        )
                        if _ce_ok:
                            _storage_handled = True
                    else:
                        response = str(result or "")
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

                self.conversation_history.append({'role': 'assistant', 'content': response})
                self._last_eli_response = response

                # ── Persist to conversation_turns table (skip if CognitiveEngine stored) ──
                if not _storage_handled:
                    try:
                        import sqlite3 as _sq, time as _t
                        from eli.core.paths import user_db_path as _udp
                        _udb = str(_udp())
                        _con = _sq.connect(_udb)
                        _ts  = _t.strftime('%Y-%m-%d %H:%M:%S')
                        _con.execute(
                            "INSERT OR IGNORE INTO conversation_turns "
                            "(timestamp,role,content,ts) VALUES (?,?,?,?)",
                            (_ts, 'user', user_message, _ts))
                        _con.execute(
                            "INSERT OR IGNORE INTO conversation_turns "
                            "(timestamp,role,content,ts) VALUES (?,?,?,?)",
                            (_ts, 'assistant', response, _ts))
                        _con.commit(); _con.close()
                    except Exception:
                        pass

                if not _response_streamed:
                    self.chat_response_signal.emit(response)

                if getattr(self, '_tts_auto', False):
                    self._speak_response(response)
                self._mem_refresh_sig.emit()

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
        self.suggestions_display.clear()
        self.suggestions_display.append(html)
        # Forward to ProactiveDock — safe here because this slot runs on the GUI thread
        if self._proactive_dock is not None:
            import re as _re
            plain = _re.sub(r'<[^>]+>', '', html)[:300]
            self._proactive_dock.post_message(plain)
            if self._proactive_dock.tts_toggle.isChecked():
                try:
                    from eli.tools.io.tts_router import maybe_speak
                    maybe_speak(plain, enabled=True)
                except Exception:
                    pass

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
            from eli.brain.agents.agent_bus import get_bus as _gb
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
            QMessageBox.warning(self, 'Model Not Loaded', 'Please load a chat model first.')
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
            QMessageBox.warning(self, 'Model Not Loaded', 'Please load a chat model first.')
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
            QMessageBox.warning(self, 'Model Not Loaded', 'Please load a chat model first.')
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

    def open_text_file(self, path: Path):
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
            self.doc_display.setPlainText(content)
            self.doc_info_label.setText(f"File: {path.name} ({len(content)} chars)")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open file: {str(e)}")

    def open_pdf(self, path: Path):
        try:
            try:
                import pypdf
                reader = pypdf.PdfReader(str(path))
                text = ""
                for page in reader.pages[:10]:
                    text += page.extract_text() + "\n\n"
                self.doc_display.setPlainText(text)
                self.doc_info_label.setText(f"PDF: {path.name} ({len(reader.pages)} pages)")
                return
            except ImportError:
                pass
            try:
                import PyPDF2
                with open(path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages[:10]:
                        text += page.extract_text() + "\n\n"
                self.doc_display.setPlainText(text)
                self.doc_info_label.setText(f"PDF: {path.name} ({len(reader.pages)} pages)")
                return
            except ImportError:
                pass
            self.doc_display.setPlainText(
                f"PDF viewing requires pypdf or PyPDF2.\n\n"
                f"Install with: pip install pypdf\n\n"
                f"File: {path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open PDF: {str(e)}")

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
            self.n_ctx_input.setValue(int(s.get("n_ctx", 8192)))
            self.n_threads_input.setValue(int(s.get("n_threads", 8)))
            self.n_gpu_layers_input.setValue(int(s.get("n_gpu_layers", 0)))
            self.max_tokens_input.setValue(int(s.get("max_tokens", 512)))
            self.temperature_input.setValue(float(s.get("temperature", 0.7)))
            _batch = s.get("batch_size") or s.get("n_batch")
            if _batch:
                self.batch_size_input.setValue(int(_batch))
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

        # GUI-local flags + theme
        try:
            self.auto_save_checkbox.setChecked(bool(s.get("auto_save", True)))
            self.log_to_file_checkbox.setChecked(bool(s.get("log_to_file", False)))
            self.auto_load_checkbox.setChecked(bool(s.get("auto_load", True)))
            self._first_run_complete = bool(s.get("first_run_complete", False))
            self.current_theme = s.get("theme", self.current_theme)
            self._user_text_color = s.get(
                "user_text_color", getattr(self, "_user_text_color", "#a3be8c"))
        except Exception as e:
            print(f"⚠️ Failed to apply GUI flags: {e}")

        self.apply_theme()

    def save_settings(self, silent: bool = False):
        """Save settings via runtime_settings — single canonical merge-write."""
        provider = self.current_provider()
        model_path = self.resolve_selected_model_path() if provider != "ollama" else self.model_path_input.text()
        bundled_path = str(self.bundled_model_combo.currentData() or "")

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
            "auto_save": bool(self.auto_save_checkbox.isChecked()),
            "log_to_file": bool(self.log_to_file_checkbox.isChecked()),
            "auto_load": bool(self.auto_load_checkbox.isChecked()),
            "first_run_complete": bool(getattr(self, "_first_run_complete", False)),
            "theme": self.current_theme,
            "user_text_color": getattr(self, "_user_text_color", "#a3be8c"),
        }

        try:
            from eli.core.runtime_settings import save_settings as _rs_save
            _rs_save(updates)
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")
            else:
                print(f"[SETTINGS] Save failed: {e}")
            return

        # Unload GGUF so next message picks up new params
        try:
            if gguf_inference:
                gguf_inference.unload_model()
                print("[SETTINGS] Model unloaded — will reload with new params on next message")
        except Exception as e:
            print(f"[SETTINGS] Model unload skipped: {e}")

        if not silent:
            QMessageBox.information(
                self, "Settings Saved",
                "Settings saved.\n\n"
                "ctx / GPU / batch changes take effect on the next message\n"
                "(model reloads automatically with new parameters)."
            )
            self.status_signal.emit("Settings saved")

    def toggle_theme(self):
        self.current_theme = "light" if self.current_theme == "dark" else "dark"
        self.apply_theme()

    def apply_theme(self):
        if self.current_theme == "dark":
            self.setStyleSheet("""
                QMainWindow, QWidget {
                    background-color: #2b2b2b;
                    color: #e0e0e0;
                }
                QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox {
                    background-color: #3c3f41;
                    color: #e0e0e0;
                    border: 1px solid #555555;
                    padding: 5px;
                }
                QPushButton {
                    background-color: #4a4a4a;
                    color: #e0e0e0;
                    border: 1px solid #555555;
                    padding: 8px;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background-color: #5a5a5a;
                }
                QGroupBox {
                    border: 1px solid #555555;
                    border-radius: 5px;
                    margin-top: 10px;
                    padding-top: 10px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px;
                }
                QTabWidget::pane {
                    border: 1px solid #555555;
                }
                QTabBar::tab {
                    background-color: #3c3f41;
                    color: #e0e0e0;
                    padding: 8px 16px;
                    border: 1px solid #555555;
                }
                QTabBar::tab:selected {
                    background-color: #4a4a4a;
                }
                QStatusBar {
                    background-color: #3c3f41;
                    color: #e0e0e0;
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
        print(f"[LOG] {message}")

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
            self.model_info_label.setText(f"🟢 Model: {model_name}")
            self.send_btn.setEnabled(True)
        elif message.startswith('🔴 Model:'):
            self.model_info_label.setText(message)
            self.send_btn.setEnabled(True)
            self.send_btn.setText('Send')
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
        # Pre-process: pretty-format command result blobs before display
        _r = text
        if _r.strip().startswith("\u26a1 {") or (_r.strip().startswith("{'ok':") and "results" in _r):
            try:
                import ast as _ast, re as _re2
                _blob = _re2.sub(r"^\u26a1\s*", "", _r.strip())
                _data = _ast.literal_eval(_blob)
                if isinstance(_data, dict) and _data.get("ok") and "results" in _data:
                    _rs = _data["results"]
                    _r = "\U0001f4cb " + " | ".join(r["text"] for r in _rs[:3]) if _rs else "\U0001f4cb No memories found."
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
        # Flush WorkingMemory, session narrative, and self-improvement log
        try:
            _ce = getattr(self, '_cognitive_engine', None)
            if _ce is not None and hasattr(_ce, 'shutdown'):
                _ce.shutdown()
        except Exception as _sd_err:
            print(f"[GUI] CognitiveEngine shutdown failed (non-fatal): {_sd_err}")
        if self.auto_save_checkbox.isChecked() and self.conversation_history:
            self.save_conversation()
        event.accept()

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

    window = EliMainWindow()
    window.show()

    window.status_label.setText('🔴 Model not loaded')
    window.model_info_label.setText('🔴 Model: Not loaded')
    window.send_btn.setEnabled(False)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
