#!/usr/bin/env python3
"""
ELI MKVII - Modern Comprehensive GUI
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


def _eli_gui_longform_guard(message: str, intent: dict) -> dict:
    raw = " ".join((message or "").split())
    low = raw.lower()

    strong_prefixes = (
        "open ", "launch ", "run ", "execute ", "delete ",
        "create file ", "make file ", "store memory ", "save memory ",
        "search memory ", "show recent memories", "analyze failures",
        "run improvement cycle", "summarize conversation",
    )

    if low.startswith(strong_prefixes):
        return intent

    word_count = len(raw.split())
    is_question = "?" in raw or low.startswith((
        "what ", "why ", "how ", "who ", "where ", "when ",
        "can you ", "could you ", "would you ", "do you ",
        "just wondering", "i'm asking", "i am asking", "explain",
    ))
    has_clauses = (", " in raw) or (" because " in low) or (" if " in low) or raw.count(".") >= 1

    if intent and intent.get("action") != "CHAT":
        if len(raw) >= 180 or (word_count >= 24 and (is_question or has_clauses)):
            return {
                "action": "CHAT",
                "args": {"message": message},
                "confidence": 0.99,
                "meta": {"matched_by": "gui.longform_guard"},
            }

    return intent


import os
import sys
SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

import json
import time
import threading
import traceback
import gc
import subprocess
import webbrowser
import urllib.request
import urllib.error
from pathlib import Path
from eli.core.paths import PATHS
from eli.brain.memory.memory import Memory as CentralMemory
SRC_ROOT = str(Path(__file__).resolve().parents[2])
from typing import Dict, Any, List, Optional, Tuple
from queue import Queue, Empty
from datetime import datetime
import re
import shutil
from eli.core import runtime_settings as runtime_settings

# PyQt imports with fallback
try:
    from PyQt6.QtWidgets import *
    from PyQt6.QtCore import *
    from PyQt6.QtGui import *
    QT_VERSION = 6
except ImportError:
    try:
        from PyQt5.QtWidgets import *
        from PyQt5.QtCore import *
        from PyQt5.QtGui import *
        QT_VERSION = 5
    except ImportError:
        print("❌ Please install PyQt5 or PyQt6: pip install PyQt6")
        sys.exit(1)

# Try to import syntax highlighter
try:
    if QT_VERSION == 6:
        from PyQt6.Qsci import QsciScintilla, QsciLexerPython
    else:
        from PyQt5.Qsci import QsciScintilla, QsciLexerPython
    QSCI_AVAILABLE = True
except ImportError:
    QSCI_AVAILABLE = False
    print("⚠️  QScintilla not available. IDE will use basic editor.")
    print("   Install with: pip install PyQt6-QScintilla")

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

    def get_recent(self, limit: int = 10) -> list:
        return self.get_recent_memories(limit=limit)

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

APP_NAME = "ELI MKVII"
APP_VERSION = "7.0.7"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_DIR = Path.home() / ".eli_mkvii"
SETTINGS_FILE = APP_DIR / "settings.json"

if CENTRAL_IMPORTS_AVAILABLE and get_paths:
    _paths = get_paths()
    MEMORY_DB = _paths.memory_db
    USER_DB = _paths.user_db
    AGENT_DB = _paths.agent_db
    CONVERSATIONS_DIR = getattr(_paths, "conversations_dir", APP_DIR / "conversations")
    ARTIFACTS_DIR = getattr(_paths, "artifacts_dir", APP_DIR / "artifacts")
    DEFAULT_MODEL_PATH = str(_paths.model) if _paths.model.exists() else str(PROJECT_ROOT / "local_models" / "Qwen2.5-32B-Instruct-Q4_K_M.gguf")
    BUNDLED_MODEL_DIR = PROJECT_ROOT / "local_models"
    CUSTOM_MODELS_DIR = APP_DIR / "models"
else:
    MEMORY_DB = PATHS.memory_db
    USER_DB = PATHS.user_db
    AGENT_DB = PATHS.agent_db
    CONVERSATIONS_DIR = APP_DIR / "conversations"
    ARTIFACTS_DIR = APP_DIR / "artifacts"
    DEFAULT_MODEL_PATH = str(PROJECT_ROOT / "local_models" / "Qwen2.5-32B-Instruct-Q4_K_M.gguf")
    BUNDLED_MODEL_DIR = PROJECT_ROOT / "local_models"
    CUSTOM_MODELS_DIR = APP_DIR / "models"

if CENTRAL_IMPORTS_AVAILABLE and config:
    ELI_SYSTEM_PROMPT = config.get_eli_persona()
else:
    def _load_eli_persona() -> str:
        import pathlib
        for p in [
            pathlib.Path("/home/jay/Eli_OS_AGI/src/eli/brain/persona/persona.txt"),
            pathlib.Path("/home/jay/Eli_OS_AGI/src/eli/brain/cognition/persona.txt"),
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
                total = cursor.fetchone()[0]
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
    ram_gb = sysinfo.get('total_ram_gb', 8)
    cpu_count = sysinfo.get('cpu_count', 4)
    has_gpu = sysinfo.get('has_gpu', False)

    n_ctx = 8192  # Safe default for RTX 2060 SUPER with 8GB VRAM
    n_gpu_layers = 10 if has_gpu else 0  # RTX 2060 SUPER: 10 layers fit in 8GB
    n_threads = cpu_count
    temperature = 0.7
    max_tokens = 2048

    return {
        'n_ctx': n_ctx,
        'n_gpu_layers': n_gpu_layers,
        'n_threads': n_threads,
        'temperature': temperature,
        'max_tokens': max_tokens,
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
    t = (text or "").strip()
    low = t.lower()
    bad = [
        "i am an ai model", "as an ai assistant", "trained on",
        "i don't retain new information", "each interaction is independent",
        "i am a large language model", "i do not retain personal data",
        "i don't have memory of past conversations", "i cannot remember previous interactions",
        "my memory is part of my training data",
        "volatile and non-volatile", "ram", "ssd", "solid-state drives",
        "memory architecture is based on", "segmented into modules", "training data",
    ]
    if any(b in low for b in bad):
        return ("I'm ELI MKVII running locally. Memory is handled by the app's SQLite layer "
                "plus session history configured in this app.")
    return text

def _policy_identity_memory_response(user_text: str, model_text: str) -> str:
    u = (user_text or "").lower()
    t = (model_text or "")
    triggers = [
        "who are you", "what are you", "memory wired", "retain information",
        "between conversations", "do you remember", "general ai assistant", "are you an ai",
    ]
    if any(k in u for k in triggers):
        return (
            "I’m ELI MKVII running locally for Jason’s research/engineering workflow. "
            "State is handled by this app’s session history plus local SQLite memory "
            "(~/.eli_mkvii/memory.db, table: memories). "
            "I don’t use cloud persistence in this flow."
        )
    return t

class LocalModelManager:
    provider_name = "gguf"
    def __init__(self):
        self.model = None
        self.model_path = None
        self.is_loaded = False
        self.load_error = None
    def load_model(self, model_path: str, n_ctx: int = 4096,
                   n_threads: int = 8, n_gpu_layers: int = 0) -> bool:
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
            self.model = Llama(
                model_path=str(path_obj),
                n_ctx=n_ctx,
                n_threads=n_threads,
                n_gpu_layers=n_gpu_layers,
                verbose=False,
                chat_format="chatml",
            )
            self.is_loaded = True
            self.load_error = None
            print(f"✅ Model loaded successfully")
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
            Path(SRC_ROOT),
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
        import sys as _sys2; _s = SRC_ROOT
        if _s not in _sys2.path: _sys2.path.insert(0, _s)
        import sys as _sys
        _src = SRC_ROOT
        if _src not in _sys.path:
            _sys.path.insert(0, _src)
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
        return f"Unhandled GUI fallback action: {action}"

executor_bridge = ExecutorBridge()

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

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - 100% Local")
        self.setGeometry(100, 100, 1400, 900)
        self.is_generating = False
        self.conversation_history = []
        self.current_theme = "dark"
        self.ollama_manager = OllamaModelManager()
        self.active_backend = model_manager
        self.detected_system_info: Dict[str, Any] = {}
        self._central_memory = None
        if CENTRAL_IMPORTS_AVAILABLE and get_memory:
            self._central_memory = get_memory()
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

        ensure_dirs()
        self.init_ui()
        self.load_settings()
        self.refresh_model_sources()
        self.apply_theme()
        QTimer.singleShot(600, self.maybe_run_first_time_setup)

        # ---------- START PROACTIVE DAEMON ----------
        if start_daemon:
            try:
                self.proactive_thread = threading.Thread(target=start_daemon, daemon=True)
                self.proactive_thread.start()
                print("[GUI] Proactive daemon started")
            except Exception as e:
                print(f"[GUI] Failed to start proactive daemon: {e}")
        else:
            print("[GUI] Proactive daemon not available (import failed)")

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

        # 3. Pull recent conversation turns from central memory
        try:
            recent_rows = []
            if getattr(self, "_central_memory", None):
                recent_rows = self._central_memory.get_recent_conversation(limit=20)
            if recent_rows:
                lines = []
                for row in recent_rows:
                    role = str(row.get("role", ""))
                    content = str(row.get("content", ""))
                    snippet = content[:120].replace('\n', ' ')
                    lines.append(f"  [{role}]: {snippet}")
                context_parts.append("Recent conversation history:\n" + "\n".join(lines))
        except Exception as e:
            print(f"[MEMORY] recent conversation fetch failed: {e}")

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
        PIPER = '/home/jay/.local/bin/piper'
        MODEL = '/home/jay/Eli_OS_AGI/src/eli/voices/en_US-amy-medium.onnx'
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
        import sys
        sys.path.insert(0, SRC_ROOT)
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
        self.chat_display = QTextEdit()
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
        if QT_VERSION == 6:
            from PyQt6.QtWidgets import QAbstractItemView
            self.habit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        else:
            from PyQt5.QtWidgets import QAbstractItemView
            self.habit_table.setSelectionBehavior(QAbstractItemView.SelectRows)
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
            mem = getattr(self, "_central_memory", None)
            if mem is None:
                self.self_improve_failures_signal.emit("Central memory unavailable.")
                return

            try:
                rows = mem.get_recent_failures(limit=20)
                if not rows:
                    self.self_improve_failures_signal.emit("Failures: 0")
                    return

                lines = [f"Failures: {len(rows)}", ""]
                for row in rows:
                    ts = row.get("timestamp", "")
                    user_input = str(row.get("user_input", "") or "")[:120]
                    err = str(row.get("error", "") or "")[:160]
                    cmd = str(row.get("command", "") or "")
                    occ = row.get("occurrence_count", 1)
                    line = f"- [{ts}] {user_input} -> {err}"
                    if cmd:
                        line += f" | cmd={cmd}"
                    if occ:
                        line += f" | x{occ}"
                    lines.append(line)

                self.self_improve_failures_signal.emit("\n".join(lines))
            except Exception as e:
                self.self_improve_failures_signal.emit(f"Failure analysis error: {e}")

        import threading
        threading.Thread(target=worker, daemon=True).start()


    def _si_run_cycle(self):
        def worker():
            mem = getattr(self, "_central_memory", None)
            if mem is None:
                self.self_improve_improvements_signal.emit("Central memory unavailable.")
                return

            try:
                fails = mem.get_recent_failures(limit=10)
                imps = mem.get_recent_improvements(limit=20)
                obs = mem.get_recent_observations(limit=10)

                lines = [
                    f"Failures: {len(fails)} | Improvements: {len(imps)} | Observations: {len(obs)}",
                    "",
                ]

                if imps:
                    lines.append("=== Recent Improvements ===")
                    for row in imps[:10]:
                        lines.append(
                            f"- [{row.get('timestamp','')}] "
                            f"[{row.get('category','runtime')}] "
                            f"{row.get('description','')} | status={row.get('status','pending')}"
                        )
                    lines.append("")

                if fails:
                    lines.append("=== Recent Failures ===")
                    for row in fails[:5]:
                        lines.append(
                            f"- [{row.get('timestamp','')}] "
                            f"{str(row.get('user_input',''))[:80]} -> {str(row.get('error',''))[:120]}"
                        )
                    lines.append("")

                if obs:
                    lines.append("=== Recent Observations ===")
                    for row in obs[:5]:
                        lines.append(f"- [{row.get('category','system')}] {str(row.get('observation',''))[:120]}")

                lines.append("")
                lines.append("--- Cycle complete ---")
                self.self_improve_improvements_signal.emit("\n".join(lines))
            except Exception as e:
                self.self_improve_improvements_signal.emit(f"Improvement cycle error: {e}")

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

    def create_settings_tab(self):
        settings_widget = QWidget()
        layout = QVBoxLayout(settings_widget)
        header = QLabel("⚙️ Settings")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        provider_group = QGroupBox("Model Provider")
        provider_layout = QFormLayout(provider_group)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS['bundled_gguf'], 'bundled_gguf')
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS['custom_gguf'], 'custom_gguf')
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS['ollama'], 'ollama')
        self.provider_combo.currentIndexChanged.connect(self.on_provider_changed)
        provider_layout.addRow("Provider:", self.provider_combo)
        self.system_recommendation_label = QLabel("Recommendation pending.")
        self.system_recommendation_label.setWordWrap(True)
        provider_layout.addRow("Hardware:", self.system_recommendation_label)
        action_row_widget = QWidget()
        action_row = QHBoxLayout(action_row_widget)
        action_row.setContentsMargins(0, 0, 0, 0)
        refresh_models_btn = QPushButton("Refresh Sources")
        refresh_models_btn.clicked.connect(self.refresh_model_sources)
        recommend_btn = QPushButton("Detect & Recommend")
        recommend_btn.clicked.connect(self.apply_recommended_setup)
        action_row.addWidget(refresh_models_btn)
        action_row.addWidget(recommend_btn)
        provider_layout.addRow("", action_row_widget)
        layout.addWidget(provider_group)

        bundled_group = QGroupBox("Bundled GGUF Models")
        bundled_layout = QFormLayout(bundled_group)
        self.bundled_model_combo = QComboBox()
        self.bundled_model_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        bundled_layout.addRow("Bundled model:", self.bundled_model_combo)
        layout.addWidget(bundled_group)

        custom_group = QGroupBox("Custom GGUF")
        custom_layout = QFormLayout(custom_group)
        self.model_path_input = QLineEdit()
        self.model_path_input.setText(DEFAULT_MODEL_PATH)
        custom_layout.addRow("Custom path:", self.model_path_input)
        browse_model_btn = QPushButton("Browse...")
        browse_model_btn.clicked.connect(self.browse_model_file)
        custom_layout.addRow("", browse_model_btn)
        layout.addWidget(custom_group)

        ollama_group = QGroupBox("Ollama")
        ollama_layout = QFormLayout(ollama_group)
        self.ollama_host_input = QLineEdit("http://localhost:11434")
        ollama_layout.addRow("Ollama host:", self.ollama_host_input)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        ollama_layout.addRow("Ollama model:", self.ollama_model_combo)
        refresh_ollama_btn = QPushButton("Refresh Ollama Models")
        refresh_ollama_btn.clicked.connect(self.refresh_ollama_models)
        ollama_layout.addRow("", refresh_ollama_btn)
        layout.addWidget(ollama_group)

        runtime_group = QGroupBox("Runtime")
        runtime_layout = QFormLayout(runtime_group)
        self.n_ctx_input = QSpinBox()
        self.n_ctx_input.setRange(512, 32768)
        self.n_ctx_input.setValue(4096)
        self.n_ctx_input.setSingleStep(512)
        runtime_layout.addRow("Context Size:", self.n_ctx_input)

        self.n_threads_input = QSpinBox()
        self.n_threads_input.setRange(1, 64)
        self.n_threads_input.setValue(8)
        runtime_layout.addRow("CPU Threads:", self.n_threads_input)

        self.n_gpu_layers_input = QSpinBox()
        self.n_gpu_layers_input.setRange(0, 200)
        self.n_gpu_layers_input.setValue(10)
        runtime_layout.addRow("GPU Layers:", self.n_gpu_layers_input)

        self.auto_load_checkbox = QCheckBox("Auto-load selected backend on startup")
        runtime_layout.addRow(self.auto_load_checkbox)
        layout.addWidget(runtime_group)

        gen_group = QGroupBox("Generation Settings")
        gen_layout = QFormLayout(gen_group)
        self.max_tokens_input = QSpinBox()
        self.max_tokens_input.setRange(128, 4096)
        self.max_tokens_input.setValue(2048)
        self.max_tokens_input.setSingleStep(128)
        gen_layout.addRow("Max Tokens:", self.max_tokens_input)

        self.temperature_input = QDoubleSpinBox()
        self.temperature_input.setRange(0.0, 2.0)
        self.temperature_input.setValue(0.7)
        self.temperature_input.setSingleStep(0.1)
        gen_layout.addRow("Temperature:", self.temperature_input)
        layout.addWidget(gen_group)

        app_group = QGroupBox("Application Settings")
        app_layout = QFormLayout(app_group)
        self.auto_save_checkbox = QCheckBox("Auto-save conversations")
        self.auto_save_checkbox.setChecked(True)
        app_layout.addRow(self.auto_save_checkbox)
        self.log_to_file_checkbox = QCheckBox("Log to file")
        self.log_to_file_checkbox.setChecked(False)
        app_layout.addRow(self.log_to_file_checkbox)
        layout.addWidget(app_group)

        btn_layout = QHBoxLayout()
        save_settings_btn = QPushButton("💾 Save Settings")
        save_settings_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(save_settings_btn)

        detect_optimal_btn = QPushButton("🔍 Detect Optimal Settings")
        detect_optimal_btn.clicked.connect(self.detect_optimal_settings)
        btn_layout.addWidget(detect_optimal_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        layout.addStretch()
        self.tabs.addTab(settings_widget, "⚙️ Settings")

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
        self.temperature_input.setValue(optimal['temperature'])
        self.max_tokens_input.setValue(optimal['max_tokens'])
        self.status_signal.emit(f"Optimal settings applied: ctx={optimal['n_ctx']}, GPU layers={optimal['n_gpu_layers']}, threads={optimal['n_threads']}")

    def maybe_run_first_time_setup(self):
        try:
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
                from PySide6.QtWidgets import QMessageBox
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

        user_label = "USER*"
        try:
            from eli.core import runtime_settings as _rt
            settings = _rt.load_settings()
            saved_name = str(settings.get("user_name", "") or "").strip()
            if saved_name:
                user_label = saved_name
            else:
                mem = getattr(self, "_central_memory", None)
                if mem is not None:
                    for row in mem.get_recent_processed_memories(limit=25):
                        txt = str(row.get("text", "") or "")
                        m = re.search(r"\b(?:user'?s name is|my name is|name is|called)\s+([A-Z][A-Za-z'_-]{1,31})\b", txt)
                        if m:
                            user_label = m.group(1).strip()
                            settings["user_name"] = user_label
                            _rt.save_settings(settings)
                            try:
                                _rt.apply_env(settings)
                            except Exception:
                                pass
                            break
        except Exception:
            pass

        self.chat_display.append(f"\n<b>🧑 {user_label} [{now_hms()}]:</b><br>{user_message}<br>")
        self.chat_input.clear()
        self.conversation_history.append({"role": "user", "content": user_message})

        self.is_generating = True
        self.status_signal.emit("Send disabled")
        self.send_btn.setText("Generating...")
        self.status_signal.emit("🔄 Generating response...")

        def generate_worker():
            try:
                from eli.brain.cognition.cognitive_engine import get_engine
                engine = get_engine()

                full_tokens = []
                first_token = True
                response = ""

                with self.__class__._inference_lock:
                    result = engine.process(user_message, source="gui", stream=True)

                    if hasattr(result, "__iter__") and not isinstance(result, dict):
                        for token in result:
                            token = str(token or "")
                            if not token:
                                continue
                            full_tokens.append(token)
                            if first_token:
                                self.chat_response_signal.emit("__STREAM_START__")
                                first_token = False
                            self.chat_response_signal.emit(token)

                        if not first_token:
                            self.chat_response_signal.emit("__STREAM_END__")
                        response = "".join(full_tokens).strip()
                    else:
                        payload = result if isinstance(result, dict) else {"content": str(result)}
                        response = str(payload.get("content") or payload.get("response") or "").strip()

                if not response:
                    response = "No response generated."

                if "_sanitize_identity_drift" in globals():
                    response = _sanitize_identity_drift(response)
                if "_policy_identity_memory_response" in globals():
                    response = _policy_identity_memory_response(user_message, response)

                self.conversation_history.append({"role": "assistant", "content": response})
                self._last_eli_response = response

                if not full_tokens:
                    self.chat_response_signal.emit(response)

                if getattr(self, "_tts_auto", False):
                    self._speak_response(response)

                try:
                    from PyQt6.QtCore import QTimer
                except Exception:
                    try:
                        from PyQt5.QtCore import QTimer
                    except Exception:
                        QTimer = None

                if QTimer is not None:
                    QTimer.singleShot(200, self.refresh_memory_stats)

            except Exception as e:
                self.chat_response_signal.emit(f"❌ Error: {str(e)}")
            finally:
                self.is_generating = False
                self.status_signal.emit("Send enabled")
                self.status_signal.emit("🟢 Ready")

        threading.Thread(target=generate_worker, daemon=True).start()

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
        mem = getattr(self, "_central_memory", None)
        if mem is None:
            try:
                from eli.brain.memory.memory import Memory
                mem = CentralMemory(PATHS.memory_db)
            except Exception as e:
                self.memory_stats_label.setText(f"Memory stats unavailable: {e}")
                return

        try:
            if hasattr(mem, "get_dashboard_counts"):
                counts = mem.get_dashboard_counts() if hasattr(mem, "get_dashboard_counts") else {}
                by_kind = counts.get("by_kind", {}) or {}
                lines = [
                    f"Processed Memories: {counts.get('processed_memories', 0)}",
                    f"Raw Memories: {counts.get('raw_memories', 0)}",
                    f"Conversation Turns: {counts.get('conversation_turns', 0)}",
                    f"Conversations: {counts.get('conversations', 0)}",
                    f"Habit Rules: {counts.get('habit_rules', 0)}",
                    f"Habit Events: {counts.get('habit_events', 0)}",
                    f"Observations: {counts.get('observations', 0)}",
                    f"Failures: {counts.get('failures', 0)}",
                    f"Improvements: {counts.get('improvements', 0)}",
                    "",
                    "By Type:",
                ]
                for kind, value in sorted(by_kind.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
                    lines.append(f"• {kind}: {value}")
                self.memory_stats_label.setText("\n".join(lines))
                return

            processed = mem.get_recent_processed_memories(limit=500) if hasattr(mem, "get_recent_processed_memories") else []
            failures = mem.get_recent_failures(limit=200) if hasattr(mem, "get_recent_failures") else []
            improvements = mem.get_recent_improvements(limit=200) if hasattr(mem, "get_recent_improvements") else []
            observations = mem.get_recent_observations(limit=200) if hasattr(mem, "get_recent_observations") else []

            lines = [
                f"Processed Memories: {len(processed)}",
                f"Failures: {len(failures)}",
                f"Improvements: {len(improvements)}",
                f"Observations: {len(observations)}",
            ]
            self.memory_stats_label.setText("\n".join(lines))
        except Exception as e:
            self.memory_stats_label.setText(f"Failed to refresh memory stats: {e}")

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
        mem = getattr(self, "_central_memory", None)
        if not mem:
            self.memory_results_display.append("<i>Central memory unavailable.</i>")
            return

        try:
            results = mem.get_recent_processed_memories(limit=20)
        except Exception as e:
            self.memory_results_display.append(f"<i>Error loading processed memories: {e}</i>")
            return

        self.memory_results_display.append("<b>Recent Processed Memories:</b><br><br>")
        if not results:
            self.memory_results_display.append("<i>No processed memories found.</i>")
            return

        for i, row in enumerate(results, 1):
            ts = row.get("timestamp", "")
            kind = row.get("kind", "note")
            text = row.get("text", "")
            tags = row.get("tags", "")
            self.memory_results_display.append(
                f"<b>{i}. [{ts}] ({kind})</b><br>{text}<br><i>Tags: {tags}</i><br><br>"
            )

    def _update_suggestions_display(self, html: str):
        self.suggestions_display.clear()
        self.suggestions_display.append(html)

    def _update_summary_display(self, html: str):
        self.summaries_display.clear()
        self.summaries_display.append(html)

    def _update_insights_display(self, html: str):
        self.insights_display.clear()
        self.insights_display.append(html)


    def generate_suggestions(self):
        backend = self._text_backend_ready(notify=False)
        if backend is None:
            QMessageBox.warning(self, 'Model Not Loaded', 'Please load a chat model first.')
            return

        self.suggestions_display.clear()
        self.suggestions_display.append('<i>🔮 Generating suggestions — please wait...</i>')

        def worker():
            try:
                mem = getattr(self, "_central_memory", None)
                obs = mem.get_recent_observations(limit=8) if mem else []
                recent = mem.get_recent_processed_memories(limit=8) if mem else []

                habit_events = []
                if mem and hasattr(mem, "get_habit_events"):
                    try:
                        habit_events = mem.get_habit_events(days=7)
                    except Exception:
                        habit_events = []

                context = []
                if obs:
                    context.append("Recent observations:")
                    for row in obs[:5]:
                        context.append(f"- [{row.get('category','system')}] {row.get('observation', row.get('content',''))}")

                if habit_events:
                    context.append("\nRecent habit events:")
                    for row in habit_events[:5]:
                        context.append(f"- {row.get('event_type','event')}: {row.get('details','')}")

                if recent:
                    context.append("\nRecent processed memories:")
                    for row in recent[:5]:
                        context.append(f"- {row.get('text','')[:120]}")

                if not context:
                    context.append("No stored proactive context yet.")

                prompt = (
                    "\n".join(context)
                    + "\n\nGive 3 concrete proactive suggestions grounded only in the stored context. "
                    + "Do not dump raw JSON or raw dicts."
                )

                with self.__class__._inference_lock:
                    temp = self.temperature_input.value() if hasattr(self, 'temperature_input') else 0.7
                    response = backend.generate(prompt=prompt, max_tokens=384, temperature=temp)

                self.proactive_suggestions_signal.emit(f"<b>💡 Proactive Suggestions</b><br><br>{response}")
            except Exception as e:
                self.proactive_suggestions_signal.emit(f"❌ Error: {str(e)}")

        import threading
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
        self.summaries_display.append('📝 Generating summary...\n\n')

        def worker():
            try:
                conversation = ''
                for msg in self.conversation_history:
                    role = 'User' if msg['role'] == 'user' else 'Assistant'
                    conversation += f"{role}: {msg['content']}\n\n"
                prompt = f"Please provide a concise summary of this conversation:\n\n{conversation}\n\nSummary:"
                with self.__class__._inference_lock:
                    temp = self.temperature_input.value() if hasattr(self, 'temperature_input') else 0.5
                    response = backend.generate(prompt=prompt, max_tokens=512, temperature=temp)
                self.proactive_summary_signal.emit(f"<b>📝 Conversation Summary:</b><br><br>{response}")
            except Exception as e:
                self.proactive_summary_signal.emit(f"❌ Error: {str(e)}")

        threading.Thread(target=worker, daemon=True).start()


    def analyze_context(self):
        backend = self._text_backend_ready(notify=False)
        if backend is None:
            QMessageBox.warning(self, 'Model Not Loaded', 'Please load a chat model first.')
            return

        self.insights_display.clear()
        self.insights_display.append('🔬 Analyzing context...\n\n')

        def worker():
            try:
                mem = getattr(self, "_central_memory", None)
                recent = mem.get_recent_processed_memories(limit=10) if mem else []
                obs = mem.get_recent_observations(limit=10) if mem else []

                context = []
                context.append(f"Processed memories: {len(recent)}")
                context.append(f"Observations: {len(obs)}")
                context.append("")

                if recent:
                    context.append("Recent processed memories:")
                    for row in recent[:5]:
                        context.append(f"- {row.get('text','')[:100]}")

                if obs:
                    context.append("\nRecent observations:")
                    for row in obs[:5]:
                        context.append(f"- [{row.get('category','system')}] {row.get('observation', row.get('content',''))[:100]}")

                prompt = (
                    "\n".join(context)
                    + "\n\nAnalyse the actual stored context only. "
                    + "Do not invent directories, modules, or systems that are not present."
                )

                with self.__class__._inference_lock:
                    temp = self.temperature_input.value() if hasattr(self, 'temperature_input') else 0.7
                    response = backend.generate(prompt=prompt, max_tokens=384, temperature=temp)

                self.proactive_insights_signal.emit(f"<b>🔬 Context Insights:</b><br><br>{response}")
            except Exception as e:
                self.proactive_insights_signal.emit(f"❌ Error: {str(e)}")

        import threading
        threading.Thread(target=worker, daemon=True).start()

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
        self._first_run_complete = False
        try:
            settings = runtime_settings.load_settings()
            self.auto_save_checkbox.setChecked(bool(settings.get('auto_save', True)))
            self.log_to_file_checkbox.setChecked(bool(settings.get('log_to_file', False)))
            self.auto_load_checkbox.setChecked(bool(settings.get('auto_load', True)))
            self._first_run_complete = bool(settings.get('first_run_complete', False))
            self.current_theme = settings.get('theme', self.current_theme)

            if hasattr(self, 'n_ctx_input'):
                self.n_ctx_input.setValue(int(settings.get('n_ctx', 8192)))
            if hasattr(self, 'n_threads_input'):
                self.n_threads_input.setValue(int(settings.get('n_threads', 8)))
            if hasattr(self, 'n_gpu_layers_input'):
                self.n_gpu_layers_input.setValue(int(settings.get('n_gpu_layers', 10)))
            if hasattr(self, 'max_tokens_input'):
                self.max_tokens_input.setValue(int(settings.get('max_tokens', 2048)))
            if hasattr(self, 'temperature_input'):
                self.temperature_input.setValue(float(settings.get('temperature', 0.7)))

            provider = settings.get('provider', 'bundled_gguf')
            if hasattr(self, 'provider_combo'):
                idx = self.provider_combo.findData(provider)
                if idx >= 0:
                    self.provider_combo.setCurrentIndex(idx)

            if hasattr(self, 'model_path_input'):
                self.model_path_input.setText(settings.get('custom_model_path') or settings.get('model_path') or DEFAULT_MODEL_PATH)
            self._pending_bundled_model_path = settings.get('bundled_model_path', '')

            if hasattr(self, 'ollama_host_input'):
                self.ollama_host_input.setText(settings.get('ollama_host', 'http://localhost:11434'))
            if hasattr(self, 'ollama_model_combo'):
                self.ollama_model_combo.setEditText(settings.get('ollama_model', ''))
        except Exception as e:
            print(f"⚠️ Failed to load runtime settings: {e}")

        self.apply_theme()

    def save_settings(self, silent: bool = False):
        provider = self.current_provider()
        model_path = self.resolve_selected_model_path() if provider != 'ollama' else self.model_path_input.text()
        bundled_path = str(self.bundled_model_combo.currentData() or '')
        ollama_host = self.ollama_host_input.text().strip()
        ollama_model = self.ollama_model_combo.currentText().strip()
        n_ctx = self.n_ctx_input.value()
        n_threads = self.n_threads_input.value()
        n_gpu_layers = self.n_gpu_layers_input.value()
        max_tokens = self.max_tokens_input.value()
        temperature = self.temperature_input.value()
        auto_save = self.auto_save_checkbox.isChecked()
        log_to_file = self.log_to_file_checkbox.isChecked()
        auto_load = self.auto_load_checkbox.isChecked()
        first_run = bool(getattr(self, '_first_run_complete', False))
        theme = self.current_theme

        if CENTRAL_IMPORTS_AVAILABLE and config:
            try:
                config.set('provider', provider)
                if provider != 'ollama':
                    config.set_gguf_model_path(model_path)
                config.set('bundled_model_path', bundled_path)
                config.set('ollama_host', ollama_host)
                config.set('ollama_model', ollama_model)
                config.set_gguf_n_ctx(n_ctx)
                config.set_n_threads(n_threads)
                config.set_gguf_n_gpu_layers(n_gpu_layers)
                config.set_num_predict(max_tokens)
                config.set_temperature(temperature)
                config.set('auto_save', auto_save)
                config.set('log_to_file', log_to_file)
                config.set('auto_load', auto_load)
                config.set('first_run_complete', first_run)
                config.set('theme', theme)
                if gguf_inference:
                    gguf_inference.unload_model()
            except Exception as e:
                print(f"⚠️ Failed to save central config: {e}")

        settings = {
            'provider': provider,
            'model_path': model_path,
            'custom_model_path': self.model_path_input.text(),
            'bundled_model_path': bundled_path,
            'ollama_host': ollama_host,
            'ollama_model': ollama_model,
            'n_ctx': n_ctx,
            'n_threads': n_threads,
            'n_gpu_layers': n_gpu_layers,
            'max_tokens': max_tokens,
            'temperature': temperature,
            'auto_save': auto_save,
            'log_to_file': log_to_file,
            'auto_load': auto_load,
            'first_run_complete': first_run,
            'theme': theme,
        }

        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding='utf-8')
            if not silent:
                QMessageBox.information(self, 'Success', 'Settings saved to both central config and local file!')
                self.status_signal.emit('Settings saved')
        except Exception as e:
            QMessageBox.critical(self, 'Error', f'Failed to save local settings: {str(e)}')

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
        if text == "__STREAM_START__":
            self._stream_buffer = []
            self._streaming = True
            # Insert bold name/timestamp as a separate block
            ts = datetime.now().strftime("%H:%M:%S")
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertBlock()                     # blank line before
            bold_fmt = QTextCharFormat()
            bold_fmt.setFontWeight(QFont.Weight.Bold)
            cursor.setCharFormat(bold_fmt)
            cursor.insertText(f"🤖 ELI [{ts}]:")
            cursor.insertBlock()                     # new block for response
            normal_fmt = QTextCharFormat()
            normal_fmt.setFontWeight(QFont.Weight.Normal)
            cursor.setCharFormat(normal_fmt)
            self.chat_display.setTextCursor(cursor)
            return

        if text == "__STREAM_END__":
            self._streaming = False
            self._stream_buffer = []
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertBlock()                     # blank line after
            self.chat_display.setTextCursor(cursor)
            self.chat_display.ensureCursorVisible()
            self.send_btn.setText("Send")
            self.send_btn.setEnabled(True)
            self.is_generating = False
            return

        if getattr(self, "_streaming", False):
            # Append token as plain text in the current block (already normal format)
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.chat_display.setTextCursor(cursor)
            self.chat_display.insertPlainText(text)
            self.chat_display.ensureCursorVisible()
            return

        # Non‑streamed complete response
        ts = datetime.now().strftime("%H:%M:%S")
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertBlock()                         # blank line before
        bold_fmt = QTextCharFormat()
        bold_fmt.setFontWeight(QFont.Weight.Bold)
        cursor.setCharFormat(bold_fmt)
        cursor.insertText(f"🤖 ELI [{ts}]:")
        cursor.insertBlock()                         # new block for response
        normal_fmt = QTextCharFormat()
        normal_fmt.setFontWeight(QFont.Weight.Normal)
        cursor.setCharFormat(normal_fmt)
        cursor.insertText(text)
        cursor.insertBlock()                         # blank line after
        self.chat_display.setTextCursor(cursor)
        self.chat_display.ensureCursorVisible()
        
        # Non-streamed complete response
        _r = text
        # Handle command result blobs
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
        self.chat_display.append(f"<b>\U0001f916 ELI [{now_hms()}]:</b><br>{_r}<br>")
        self.chat_display.ensureCursorVisible()


    def _update_proactive(self, data: dict):
        if not isinstance(data, dict):
            return

        def _pick(*names):
            for name in names:
                w = getattr(self, name, None)
                if w is not None:
                    return w
            return None

        def _set(widget, text):
            if widget is None:
                return
            try:
                if hasattr(widget, "setPlainText"):
                    widget.setPlainText(text)
                elif hasattr(widget, "setText"):
                    widget.setText(text)
                elif hasattr(widget, "clear") and hasattr(widget, "append"):
                    widget.clear()
                    widget.append(text)
            except Exception:
                pass

        def _fmt(value):
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            try:
                return json.dumps(value, indent=2, ensure_ascii=False)
            except Exception:
                return str(value)

        suggestions_widget = _pick("suggestions_display", "proactive_suggestions_display", "suggestions_text")
        summary_widget = _pick("summary_display", "summaries_display", "proactive_summary_display", "summary_text")
        insights_widget = _pick("insights_display", "proactive_insights_display", "insights_text")

        if "suggestions" in data:
            _set(suggestions_widget, _fmt(data.get("suggestions")))
        if "summary" in data or "summaries" in data:
            _set(summary_widget, _fmt(data.get("summary", data.get("summaries"))))
        if "insights" in data or "observations" in data:
            _set(insights_widget, _fmt(data.get("insights", data.get("observations"))))


    def closeEvent(self, event):
        saved = False
        try:
            if self.auto_save_checkbox.isChecked() and self.conversation_history:
                self.save_conversation()
                saved = True
        except Exception as e:
            print(f"[GUI] close-save failed: {e}")

        if saved:
            print("[GUI] Conversation auto-saved on close.")
            try:
                self.statusBar().showMessage("Conversation auto-saved on close.", 3000)
            except Exception:
                pass

        event.accept()

# ============================================================
# MAIN ENTRY POINT
# ============================================================
def _read_boot_settings():
    cfg = Path.home() / '.eli_mkvii' / 'settings.json'
    defaults = {
        'provider': 'bundled_gguf',
        'model_path': DEFAULT_MODEL_PATH,
        'ollama_host': 'http://localhost:11434',
        'ollama_model': '',
        'n_ctx': 4096,
        'n_threads': 8,
        'n_gpu_layers': 0,
        'auto_load': True,
    }
    try:
        if cfg.exists():
            d = json.loads(cfg.read_text(encoding='utf-8'))
            for key in list(defaults):
                if key in d:
                    defaults[key] = d[key]
    except Exception as e:
        print(f'[BOOT] settings read fallback: {e}')
    return defaults

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
