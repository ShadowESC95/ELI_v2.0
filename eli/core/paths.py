"""
ELI Path Resolution — Single Source of Truth
==============================================
All modules MUST use this module for path resolution.
Never construct data/config/cache paths elsewhere.

Supports three modes:
  1. Development: ELI_DATA_DIR env var or running from source tree
  2. Installed package: platformdirs for platform-standard directories  
  3. Frozen app: sys._MEIPASS for PyInstaller bundles

Usage:
    from eli.core.paths import (
        data_dir, config_dir, cache_dir, logs_dir,
        models_dir, plugins_dir, voices_dir, db_dir,
        user_db_path, agent_db_path, memory_db_path,
        artifacts_dir, project_root,
    )
"""

import os
import sys
import logging
from pathlib import Path
from functools import lru_cache

log = logging.getLogger(__name__)

_APP_NAME = "eli"
_APP_AUTHOR = "eli"


def _env_truthy(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.strip().lower() in {"1", "true", "yes", "on"}

# ── Frozen app detection (PyInstaller / cx_Freeze) ──

def is_frozen() -> bool:
    """True if running as a frozen (PyInstaller/cx_Freeze) bundle."""
    return getattr(sys, 'frozen', False)

def _frozen_base() -> Path:
    """Base directory for frozen app resources."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(sys.executable).parent


# ── Source tree detection ──

def _find_project_root() -> Path | None:
    """Walk up from this file to find the project root (contains pyproject.toml)."""
    p = Path(__file__).resolve().parent
    for _ in range(5):
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return None



# ── Dev-mode detection ──

def _is_dev_mode() -> bool:
    """True if running from a source tree (not installed or frozen).

    Source checkouts resolve to project-local artifacts. Packaged installs use
    platform-standard directories unless the launcher provides ELI_PROJECT_ROOT.
    """
    if is_frozen():
        return False
    forced = _env_truthy("ELI_DEV_MODE")
    if forced is None:
        forced = _env_truthy("ELI_FORCE_DEV_MODE")
    if forced is not None:
        return forced
    # Explicit ELI_PROJECT_ROOT override (set by bin/elix) is the strongest
    # signal a user can give. Honor it first.
    explicit_root = os.environ.get("ELI_PROJECT_ROOT")
    if explicit_root:
        p = Path(explicit_root).expanduser().resolve()
        eli_pkg = p / "eli"
        if eli_pkg.is_dir() and (eli_pkg / "cognition").is_dir() and (eli_pkg / "gui").is_dir():
            return True
    root = _find_project_root()
    if root is None:
        return False
    # Release installers also ship pyproject.toml and the eli package. Treat
    # auto-detected source layout as dev mode only for real checkouts; packaged
    # installs should use platformdirs unless a launcher set ELI_PROJECT_ROOT.
    if not (root / ".git").exists():
        return False
    # Modern source layout: project_root/eli/cognition and project_root/eli/gui
    eli_pkg = root / "eli"
    if eli_pkg.is_dir() and (eli_pkg / "cognition").is_dir() and (eli_pkg / "gui").is_dir():
        return True
    # Legacy flat layout: project_root/brain and project_root/gui
    if (root / "brain").is_dir() and (root / "gui").is_dir():
        return True
    return False


# ── Platform-aware directories ──

def _get_platformdirs():
    """Import platformdirs when available."""
    try:
        import platformdirs
        return platformdirs
    except ImportError:
        return None

@lru_cache(maxsize=1)
def data_dir() -> Path:
    """
    Persistent user data: databases, conversations, persona, notes.
    Override: ELI_DATA_DIR env var.
    Dev mode: <project_root>/artifacts
    Installed: ~/.local/share/eli (Linux), %LOCALAPPDATA%/eli (Win), ~/Library/Application Support/eli (Mac)
    """
    override = os.environ.get("ELI_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    
    if _is_dev_mode():
        return project_root() / "artifacts"
    
    pd = _get_platformdirs()
    if pd:
        return Path(pd.user_data_dir(_APP_NAME, _APP_AUTHOR))
    
    # Manual fallback
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / _APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME
    else:
        return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / _APP_NAME

@lru_cache(maxsize=1)
def config_dir() -> Path:
    """
    Configuration files: config.yaml, user_id, settings.json.
    Override: ELI_CONFIG_DIR env var.
    Dev mode: <project_root>/config
    Installed: ~/.config/eli (Linux), %APPDATA%/eli (Win), ~/Library/Preferences/eli (Mac)
    """
    override = os.environ.get("ELI_CONFIG_DIR")
    if override:
        return Path(override).expanduser().resolve()
    
    if _is_dev_mode():
        return project_root() / "config"
    
    pd = _get_platformdirs()
    if pd:
        return Path(pd.user_config_dir(_APP_NAME, _APP_AUTHOR))
    
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / _APP_NAME
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / _APP_NAME
    else:
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / _APP_NAME

@lru_cache(maxsize=1)
def cache_dir() -> Path:
    """
    Temporary/cache data: model caches, compiled assets.
    Override: ELI_CACHE_DIR env var.
    Dev mode: <project_root>/cache
    Installed: ~/.cache/eli (Linux), %LOCALAPPDATA%/eli/cache (Win), ~/Library/Caches/eli (Mac)
    """
    override = os.environ.get("ELI_CACHE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    
    if _is_dev_mode():
        return project_root() / "cache"
    
    pd = _get_platformdirs()
    if pd:
        return Path(pd.user_cache_dir(_APP_NAME, _APP_AUTHOR))
    
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / _APP_NAME / "cache"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / _APP_NAME
    else:
        return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / _APP_NAME


# ── Derived directories ──

def db_dir() -> Path:
    """SQLite database directory.

    Always nested under data_dir() / 'db' regardless of dev/install mode so
    function and property resolvers agree (previously dev mode returned
    data_dir() directly, splitting writes between artifacts/ and artifacts/db/).
    """
    return data_dir() / "db"

def logs_dir() -> Path:
    """Log files directory."""
    return data_dir() / "logs"

def models_dir() -> Path:
    """GGUF model files directory."""
    override = os.environ.get("ELI_MODELS_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if _is_dev_mode():
        return project_root() / "models"
    return data_dir() / "models"

def voices_dir() -> Path:
    """Voice model files (Piper ONNX)."""
    if _is_dev_mode():
        return project_root() / "voices"
    return data_dir() / "voices"

def plugins_dir() -> Path:
    """User-installed plugins."""
    if _is_dev_mode():
        return project_root() / "plugins"
    return data_dir() / "plugins"

def artifacts_dir() -> Path:
    """Alias for data_dir() — backward compat with existing code."""
    return data_dir()

def conversations_dir() -> Path:
    """Conversation log directory."""
    return data_dir() / "conversations"

def proactive_dir() -> Path:
    """Proactive daemon state directory."""
    return data_dir() / "proactive"

def documents_dir() -> Path:
    """Generated documents directory."""
    return data_dir() / "documents"

def scripts_dir() -> Path:
    """User-generated scripts directory."""
    return data_dir() / "scripts"

def notes_dir() -> Path:
    """User notes directory."""
    return data_dir() / "notes"


# ── Database paths ──

def user_db_path() -> Path:
    """Primary user database (conversations, memories).

    Honor both ELI_USER_DB (documented form) and ELI_MEMORY_DB (legacy launcher
    form). Either takes precedence over the platformdirs/dev-mode fallback.
    """
    override = os.environ.get("ELI_USER_DB") or os.environ.get("ELI_MEMORY_DB")
    if override:
        return Path(override).expanduser().resolve()
    return db_dir() / "user.sqlite3"

def agent_db_path() -> Path:
    """Agent bus state database."""
    override = os.environ.get("ELI_AGENT_DB")
    if override:
        return Path(override).expanduser().resolve()
    return db_dir() / "agent.sqlite3"

def memory_db_path() -> Path:
    """Dedicated semantic memory + knowledge store.

    Currently consolidated into user.sqlite3 (single canonical DB).

    Honors ELI_MEMORY_DB then ELI_USER_DB then dev-mode/platformdirs fallback.
    """
    override = os.environ.get("ELI_MEMORY_DB") or os.environ.get("ELI_USER_DB")
    if override:
        return Path(override).expanduser().resolve()
    return db_dir() / "user.sqlite3"


def knowledge_graph_db_path() -> Path:
    """Knowledge graph lives inside user.sqlite3 as extra tables."""
    return memory_db_path()


# ── Persona paths ──

def persona_base_path() -> Path:
    """Base persona text file."""
    if _is_dev_mode():
        return project_root() / "eli" / "brain" / "persona" / "persona.txt"
    return config_dir() / "persona.txt"

def persona_path() -> Path:
    """Canonical base persona file."""
    return project_root() / "eli" / "cognition" / "persona.txt"


def persona_auto_path() -> Path:
    """Canonical auto-updating persona overlay."""
    return project_root() / "eli" / "cognition" / "persona.auto.txt"


def notebook_dir() -> Path:
    """ELI notebook / journal directory."""
    if _is_dev_mode():
        return project_root() / "eli_notebook"
    return data_dir() / "notebook"


# ── Ensure directories exist ──

def ensure_dirs():
    """Create all required directories if they don't exist. Returns PATHS."""
    dirs = [
        data_dir(), config_dir(), cache_dir(), logs_dir(),
        models_dir(), plugins_dir(), voices_dir(),
        conversations_dir(), proactive_dir(), documents_dir(),
        scripts_dir(), notes_dir(), notebook_dir(),
        db_dir(),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    return PATHS


# ── Backward compatibility aliases ──
# These preserve the API that existing modules expect from the old paths.py

def get_artifacts_dir() -> Path:
    """Backward compat alias."""
    return data_dir()

def get_project_root() -> Path:
    """Backward compat alias."""
    return project_root()

def get_user_db_path() -> Path:
    """Backward compat alias."""
    return user_db_path()

def get_agent_db_path() -> Path:
    """Backward compat alias."""
    return agent_db_path()

def get_models_dir() -> Path:
    """Backward compat alias."""
    return models_dir()

# ── GGUF model path (runtime setting, not a fixed path) ──

_gguf_model_path: str | None = None

def project_root() -> Path:
    return Path(__file__).resolve().parents[2]

def models_root() -> Path:
    return models_dir()

def gguf_models_dir() -> Path:
    return models_root() / "gguf" / "base"

def embedding_models_dir() -> Path:
    return models_root() / "embeddings"

def lora_adapters_dir() -> Path:
    return models_root() / "lora" / "adapters"

def lora_merged_dir() -> Path:
    return models_root() / "lora" / "merged"

def training_root() -> Path:
    return project_root() / "training"

def get_gguf_model_path() -> str | None:
    env = os.environ.get("ELI_GGUF_MODEL_PATH") or os.environ.get("ELI_MODEL")
    if env:
        return env
    if _gguf_model_path:
        return _gguf_model_path
    d = gguf_models_dir()
    if d.exists():
        hits = sorted(d.glob("*.gguf"))
        if hits:
            return str(hits[0])
    return None

def set_gguf_model_path(path: str):
    """Set the GGUF model path at runtime."""
    global _gguf_model_path
    _gguf_model_path = path
    os.environ["ELI_MODEL"] = path


# ── Startup info ──

def path_info() -> dict:
    """Return a dict of all resolved paths for diagnostics."""
    return {
        "project_root": str(project_root()),
        "data_dir": str(data_dir()),
        "config_dir": str(config_dir()),
        "cache_dir": str(cache_dir()),
        "db_dir": str(db_dir()),
        "logs_dir": str(logs_dir()),
        "models_dir": str(models_dir()),
        "voices_dir": str(voices_dir()),
        "plugins_dir": str(plugins_dir()),
        "user_db": str(user_db_path()),
        "agent_db": str(agent_db_path()),
        "is_dev_mode": _is_dev_mode(),
        "is_frozen": is_frozen(),
    }




# ══════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY — DO NOT REMOVE
# These exports are used by 30+ modules across the codebase.
# Migrate callers to the new functions above over time.
# ══════════════════════════════════════════════════════════════

class EliPaths:
    """Legacy path object — provides attribute access to all paths."""

    @property
    def project_root(self): return project_root()
    @property
    def root(self): return project_root()
    @property
    def artifacts_dir(self): return data_dir()
    @property
    def data_dir(self): return data_dir()
    @property
    def config_dir(self): return config_dir()
    @property
    def cache_dir(self): return cache_dir()
    @property
    def db_dir(self): return db_dir()
    @property
    def logs_dir(self): return logs_dir()
    @property
    def log_dir(self): return logs_dir()
    @property
    def models_dir(self): return models_dir()
    @property
    def voices_dir(self): return voices_dir()
    @property
    def plugins_dir(self): return plugins_dir()
    @property
    def user_db(self): return user_db_path()
    @property
    def agent_db(self): return agent_db_path()
    @property
    def memory_db(self): return memory_db_path()
    @property
    def knowledge_graph_db(self): return knowledge_graph_db_path()
    @property
    def db(self): return memory_db_path()
    @property
    def conversations_dir(self): return conversations_dir()
    @property
    def proactive_dir(self): return proactive_dir()
    @property
    def documents_dir(self): return documents_dir()
    @property
    def scripts_dir(self): return scripts_dir()
    @property
    def notes_dir(self): return notes_dir()
    @property
    def notebook_dir(self): return notebook_dir()
    @property
    def persona_base(self): return persona_base_path()
    @property
    def persona_auto(self): return persona_auto_path()
    @property
    def model(self): return Path(get_gguf_model_path()).resolve() if get_gguf_model_path() else None

    def __repr__(self):
        return f"EliPaths(root={project_root()}, data={data_dir()}, dev={_is_dev_mode()})"

# Singleton instances used by 30+ modules
PATHS = EliPaths()

def get_paths() -> EliPaths:
    """Return the global PATHS singleton."""
    return PATHS

# Module-level constants for direct import
PROJECT_ROOT = project_root()
ARTIFACTS_DIR = data_dir()
DB_PATH = user_db_path()

def resolve_db_paths():
    """Backward compat — returns object with .user_db, .agent_db, .memory_db as Paths."""
    return PATHS


@lru_cache(maxsize=1)
def canonical_project_root() -> Path:
    return Path(__file__).resolve().parents[2].resolve()

def legacy_repo_alias_root() -> Path:
    return (Path.home() / "eli").resolve(strict=False)

def resolve_user_repo_path(raw_path: str | os.PathLike | None) -> Path:
    """
    Resolve user-facing paths.

    Rules:
    - '~/eli' and '~/eli/...' are treated as a legacy alias for the current repo root.
    - all other paths are expanded normally and resolved non-strictly.
    """
    if raw_path is None:
        return canonical_project_root()

    text = str(raw_path).strip()
    if not text:
        return canonical_project_root()

    expanded = Path(os.path.expanduser(text))
    legacy_root = legacy_repo_alias_root()
    project_root = canonical_project_root()

    try:
        rel = expanded.relative_to(legacy_root)
        return (project_root / rel).resolve(strict=False)
    except ValueError:
        return expanded.resolve(strict=False)

if __name__ == "__main__":
    ensure_dirs()
    info = path_info()
    for k, v in info.items():
        print(f"  {k:20s} = {v}")
