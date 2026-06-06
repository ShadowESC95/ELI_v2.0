# eli/plugins/manager.py
"""
ELI Plugin Manager
==================
Handles discovery, loading, downloading, installing, enabling and disabling plugins.

Usage (from executor or GUI):
    from eli.plugins.manager import get_manager
    mgr = get_manager()
    mgr.list_available()        # all plugins in registry
    mgr.list_installed()        # locally installed plugins
    mgr.install("weather")      # download + enable
    mgr.uninstall("weather")    # disable + remove files
    mgr.enable("weather")       # re-enable disabled plugin
    mgr.disable("weather")      # disable without removing
    mgr.execute("weather", "GET_WEATHER", {"city": "Dublin"})
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from eli.core.legacy_paths import legacy_named_paths, migrate_text_file
from eli.core.paths import get_paths
from eli.utils.log import get_logger

# Module logger. The manager's methods (auto-load, install, …) reference `log`;
# the only other `log = get_logger(...)` in this file lives INSIDE the
# generated-stub f-string template, so without this real definition any method
# that logged raised "name 'log' is not defined" — surfacing in the GUI as
# "Plugin manager unavailable: name 'log' is not defined".
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _eli_src() -> Path:
    return Path(__file__).resolve().parent.parent


def _plugins_dir() -> Path:
    d = _eli_src() / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_file() -> Path:
    """JSON file tracking enabled/disabled state and metadata per plugin."""
    state_dir = Path(os.environ.get("ELI_ARTIFACTS_DIR", "")).expanduser()
    if not state_dir or not state_dir.is_absolute():
        state_dir = Path(get_paths().config_dir)
    state_file = state_dir / "plugins_state.json"
    migrate_text_file(
        state_file,
        legacy_named_paths("plugins_state.json"),
        default_text=json.dumps({"enabled": [], "disabled": [], "installed": {}}, indent=2),
    )
    return state_file


def _registry_url() -> str:
    return os.environ.get(
        "ELI_PLUGIN_REGISTRY_URL",
        "https://raw.githubusercontent.com/eli-plugins/registry/main/index.json",
    )


def _local_registry() -> Path:
    """Bundled fallback registry shipped with ELI."""
    return _eli_src() / "plugins" / "registry" / "index.json"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    p = _state_file()
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"enabled": [], "disabled": [], "installed": {}}


def _save_state(state: Dict[str, Any]) -> None:
    _state_file().write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _fetch_registry(timeout: int = 8) -> List[Dict[str, Any]]:
    """Fetch registry from network, falling back to bundled index.json."""
    try:
        req = urllib.request.Request(
            _registry_url(),
            headers={"User-Agent": "ELI-plugin-manager/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            return data.get("plugins", [])
    except Exception:
        pass

    # Fallback: bundled registry
    p = _local_registry()
    if p.exists():
        try:
            return json.loads(p.read_text()).get("plugins", [])
        except Exception:
            pass
    return []


# ---------------------------------------------------------------------------
# Plugin base (re-exported for convenience)
# ---------------------------------------------------------------------------

from eli.plugins.base.base import Plugin  # noqa: E402


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class PluginManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded: Dict[str, Plugin] = {}
        self._registry_cache: Optional[List[Dict]] = None
        self._state: Dict[str, Any] = _load_state()
        self._auto_load()

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def refresh_registry(self) -> List[Dict]:
        """Re-fetch the online registry."""
        self._registry_cache = _fetch_registry()
        return self._registry_cache

    def list_available(self) -> List[Dict]:
        """Return all plugins from registry (cached)."""
        if self._registry_cache is None:
            self._registry_cache = _fetch_registry()
        return self._registry_cache

    def get_registry_entry(self, plugin_id: str) -> Optional[Dict]:
        for p in self.list_available():
            if p["id"] == plugin_id:
                return p
        return None

    # ------------------------------------------------------------------
    # Discovery & loading
    # ------------------------------------------------------------------

    def _auto_load(self) -> None:
        """Load all enabled plugins from disk at startup."""
        enabled = set(self._state.get("enabled", []))
        for pkg_dir in _plugins_dir().iterdir():
            if not pkg_dir.is_dir():
                continue
            plugin_py = pkg_dir / "plugin.py"
            if not plugin_py.exists():
                continue
            pid = pkg_dir.name
            if pid in ("base", "registry", "__pycache__"):
                continue
            if self._state.get("disabled") and pid in self._state["disabled"]:
                continue
            try:
                self._load_plugin_from_file(pid, plugin_py)
            except Exception as exc:
                log.debug(f"[PLUGIN] Failed to auto-load {pid}: {exc}")

    def _load_plugin_from_file(self, plugin_id: str, path: Path) -> Optional[Plugin]:
        spec = importlib.util.spec_from_file_location(
            f"plugins.{plugin_id}.plugin", path
        )
        if spec is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"plugins.{plugin_id}.plugin"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]

        # Find Plugin subclass
        import inspect
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if inspect.isclass(attr) and issubclass(attr, Plugin) and attr is not Plugin:
                instance = attr()
                with self._lock:
                    self._loaded[plugin_id] = instance
                log.debug(f"[PLUGIN] Loaded: {plugin_id} — {instance.description}")
                return instance
        return None

    def list_installed(self) -> List[Dict]:
        """Plugins with a local plugin.py file."""
        result = []
        for pkg_dir in _plugins_dir().iterdir():
            if not pkg_dir.is_dir():
                continue
            plugin_py = pkg_dir / "plugin.py"
            if not plugin_py.exists():
                continue
            pid = pkg_dir.name
            if pid in ("base", "registry", "__pycache__"):
                continue
            disabled = pid in self._state.get("disabled", [])
            meta = self._state.get("installed", {}).get(pid, {})
            result.append({
                "id": pid,
                "enabled": not disabled,
                "loaded": pid in self._loaded,
                "version": meta.get("version", "?"),
                "description": meta.get("description", ""),
            })
        return result

    # ------------------------------------------------------------------
    # Install / uninstall
    # ------------------------------------------------------------------

    def install(
        self,
        plugin_id: str,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        """
        Install a plugin by id.
        1. Looks up registry entry
        2. pip-installs any required packages
        3. Downloads plugin.py (or copies builtin stub)
        4. Enables it
        """
        entry = self.get_registry_entry(plugin_id)
        if entry is None:
            return {"ok": False, "error": f"Plugin '{plugin_id}' not found in registry"}

        def _log(msg: str) -> None:
            log.debug(f"[PLUGIN:install:{plugin_id}] {msg}")
            if progress_cb:
                progress_cb(msg)

        _log(f"Installing {entry['name']} v{entry['version']}…")

        # 1. pip deps
        for pkg in entry.get("pip", []):
            _log(f"  pip install {pkg}")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "--quiet", pkg],
                    timeout=120,
                )
            except Exception as exc:
                return {"ok": False, "error": f"pip install {pkg} failed: {exc}"}

        # 2. Create plugin dir
        plugin_dir = _plugins_dir() / plugin_id
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "__init__.py").touch()

        # 3. Download or generate plugin.py
        source_url = entry.get("source")
        plugin_py = plugin_dir / "plugin.py"

        if source_url:
            _log(f"  Downloading from {source_url}")
            try:
                req = urllib.request.Request(
                    source_url,
                    headers={"User-Agent": "ELI-plugin-manager/1.0"},
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    plugin_py.write_bytes(r.read())
            except Exception as exc:
                return {"ok": False, "error": f"Download failed: {exc}"}
        else:
            # builtin — generate a stub if plugin.py doesn't already exist
            if not plugin_py.exists():
                _log("  Generating builtin stub")
                plugin_py.write_text(_make_builtin_stub(entry))

        # 4. Save state
        state = _load_state()
        enabled = set(state.get("enabled", []))
        disabled = set(state.get("disabled", []))
        enabled.add(plugin_id)
        disabled.discard(plugin_id)
        state["enabled"] = sorted(enabled)
        state["disabled"] = sorted(disabled)
        state.setdefault("installed", {})[plugin_id] = {
            "version": entry["version"],
            "description": entry.get("description", ""),
            "source": source_url or "builtin",
        }
        _save_state(state)
        self._state = state

        # 5. Load into memory
        loaded = self._load_plugin_from_file(plugin_id, plugin_py)
        if loaded is None:
            return {"ok": False, "error": "Plugin installed but could not be loaded"}

        _log(f"  ✅ {entry['name']} installed and loaded")
        return {
            "ok": True,
            "plugin_id": plugin_id,
            "name": entry["name"],
            "actions": entry.get("actions", []),
            "content": f"✅ Plugin '{entry['name']}' installed successfully.",
            "response": f"✅ Plugin '{entry['name']}' installed successfully.",
        }

    def uninstall(self, plugin_id: str) -> Dict[str, Any]:
        """Remove plugin files and state."""
        import shutil

        plugin_dir = _plugins_dir() / plugin_id
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        state = _load_state()
        state.get("enabled", []).remove(plugin_id) if plugin_id in state.get("enabled", []) else None
        state.get("disabled", []).remove(plugin_id) if plugin_id in state.get("disabled", []) else None
        state.get("installed", {}).pop(plugin_id, None)
        _save_state(state)
        self._state = state

        with self._lock:
            self._loaded.pop(plugin_id, None)

        # Remove from sys.modules
        for key in list(sys.modules.keys()):
            if key.startswith(f"plugins.{plugin_id}"):
                del sys.modules[key]

        return {
            "ok": True,
            "content": f"🗑️ Plugin '{plugin_id}' uninstalled.",
            "response": f"🗑️ Plugin '{plugin_id}' uninstalled.",
        }

    # ------------------------------------------------------------------
    # Enable / disable
    # ------------------------------------------------------------------

    def enable(self, plugin_id: str) -> Dict[str, Any]:
        plugin_py = _plugins_dir() / plugin_id / "plugin.py"
        if not plugin_py.exists():
            return {"ok": False, "error": f"Plugin '{plugin_id}' not installed"}

        state = _load_state()
        disabled = set(state.get("disabled", []))
        disabled.discard(plugin_id)
        enabled = set(state.get("enabled", []))
        enabled.add(plugin_id)
        state["enabled"] = sorted(enabled)
        state["disabled"] = sorted(disabled)
        _save_state(state)
        self._state = state

        if plugin_id not in self._loaded:
            self._load_plugin_from_file(plugin_id, plugin_py)

        return {
            "ok": True,
            "content": f"✅ Plugin '{plugin_id}' enabled.",
            "response": f"✅ Plugin '{plugin_id}' enabled.",
        }

    def disable(self, plugin_id: str) -> Dict[str, Any]:
        state = _load_state()
        enabled = set(state.get("enabled", []))
        enabled.discard(plugin_id)
        disabled = set(state.get("disabled", []))
        disabled.add(plugin_id)
        state["enabled"] = sorted(enabled)
        state["disabled"] = sorted(disabled)
        _save_state(state)
        self._state = state

        with self._lock:
            self._loaded.pop(plugin_id, None)

        return {
            "ok": True,
            "content": f"⏸ Plugin '{plugin_id}' disabled.",
            "response": f"⏸ Plugin '{plugin_id}' disabled.",
        }

    # ------------------------------------------------------------------
    # Search (semantic matching against plugin descriptions/actions)
    # ------------------------------------------------------------------

    def search(self, query: str) -> List[Dict[str, Any]]:
        """
        Find plugins matching a natural language query.
        Searches plugin names, descriptions, and action names.
        Returns registry entries sorted by relevance.
        """
        q = (query or "").strip().lower()
        if not q:
            return []

        q_words = set(q.split())
        scored: List[tuple] = []

        for entry in self.list_available():
            score = 0.0
            pid = str(entry.get("id", "")).lower()
            name = str(entry.get("name", "")).lower()
            desc = str(entry.get("description", "")).lower()
            actions = [str(a).lower() for a in entry.get("actions", [])]
            all_text = f"{pid} {name} {desc} {' '.join(actions)}"

            # Exact id/name match
            if q == pid or q == name:
                score += 10.0
            # Query is substring of name or description
            if q in name:
                score += 5.0
            if q in desc:
                score += 3.0
            # Word overlap
            text_words = set(all_text.split())
            overlap = q_words & text_words
            if overlap:
                score += len(overlap) * 2.0
            # Partial word matching (e.g. "timer" matches "pomodoro timer")
            for qw in q_words:
                if any(qw in tw for tw in text_words):
                    score += 1.0

            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored]

    def get_all_actions(self) -> Dict[str, List[str]]:
        """Return {plugin_id: [ACTION, ...]} for all loaded plugins."""
        result: Dict[str, List[str]] = {}
        # From loaded plugins
        for pid, plugin in self._loaded.items():
            actions = list(plugin.actions.keys()) if hasattr(plugin, "actions") else []
            result[pid] = [a.upper() for a in actions]
        # Supplement with registry data for installed but not loaded
        for entry in self.list_available():
            pid = entry.get("id", "")
            if pid and pid not in result:
                acts = entry.get("actions", [])
                if acts:
                    result[pid] = [a.upper() for a in acts]
        return result

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute(self, plugin_id: str, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        plugin = self._loaded.get(plugin_id)
        if plugin is None:
            return {"ok": False, "error": f"Plugin '{plugin_id}' not loaded"}
        try:
            result = plugin.execute(action.lower().replace(f"{plugin_id.upper()}_", "").lower(), args)
            if "content" not in result:
                result["content"] = str(result.get("response", result.get("data", "")))
            if "response" not in result:
                result["response"] = result["content"]
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc), "content": str(exc), "response": str(exc)}

    def get(self, plugin_id: str) -> Optional[Plugin]:
        return self._loaded.get(plugin_id)

    def all_loaded(self) -> Dict[str, Plugin]:
        return dict(self._loaded)


# ---------------------------------------------------------------------------
# Builtin stub generator
# ---------------------------------------------------------------------------

def _make_builtin_stub(entry: Dict) -> str:
    """Generate a minimal working stub for builtin plugins that have no source URL."""
    pid = entry["id"]
    name = entry["name"]
    desc = entry.get("description", "")
    actions = entry.get("actions", [])

    action_methods = ""
    action_map = {}
    for action in actions:
        method_name = action.lower().replace(f"{pid}_", "").replace("-", "_")
        action_map[action.lower().replace(f"{pid}_", "")] = method_name
        action_methods += f"""
    def {method_name}(self, args: dict) -> dict:
        return {{"ok": True, "content": "{action} executed (stub)", "response": "{action} executed (stub)"}}
"""

    action_dict_str = ", ".join(f'"{k}": self.{v}' for k, v in action_map.items())

    return f'''# Auto-generated builtin stub for plugin: {pid}
from eli.plugins.base.base import Plugin



from eli.utils.log import get_logger
log = get_logger(__name__)

class {name.replace(" ", "")}Plugin(Plugin):
    name = "{pid}"
    description = "{desc}"

    def __init__(self):
        self.actions = {{{action_dict_str}}}
        super().__init__()
{action_methods}
'''


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: Optional[PluginManager] = None
_manager_lock = threading.Lock()


def get_manager() -> PluginManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = PluginManager()
    return _manager
