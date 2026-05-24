"""
Base classes and loader for the ELI plugin system.
Each plugin should define a class that inherits from `Plugin` and implement:
- `name`: str – unique plugin identifier
- `description`: str – human‑readable description
- `actions`: dict – mapping from action name to handler method

Plugins are automatically discovered in the `eli.plugins` package.
"""

import importlib
import pkgutil
import inspect
from typing import Dict, Any, Callable, List, Optional


from eli.utils.log import get_logger
log = get_logger(__name__)

class Plugin:
    """Base class for all ELI plugins."""
    name: str = None
    description: str = ""
    actions: Dict[str, Callable] = {}

    def __init__(self):
        if self.name is None:
            raise ValueError("Plugin must define a 'name' attribute.")
        self._validate_actions()

    def _validate_actions(self):
        for action_name, handler in self.actions.items():
            if not callable(handler):
                raise ValueError(f"Action '{action_name}' handler is not callable.")
            # Ensure the handler is bound to the instance (if it's a method)
            # This will be fixed when we instantiate the plugin.

    def register(self, registry: Dict[str, Dict[str, Any]]):
        """Register this plugin's actions with the capability registry."""
        from eli.tools.registry.capability_registry import register
        for action_name, handler in self.actions.items():
            full_action = f"{self.name.upper()}_{action_name.upper()}"
            # Bind the handler to this instance
            bound_handler = handler.__get__(self, type(self))
            register(full_action, {"description": f"{self.description}: {action_name}", "handler": bound_handler})

    def execute(self, action: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a plugin action by name."""
        if action not in self.actions:
            return {"ok": False, "error": f"Unknown action '{action}' for plugin {self.name}"}
        handler = self.actions[action].__get__(self, type(self))
        return handler(args)

# ------------------------------------------------------------------
# Plugin loader
# ------------------------------------------------------------------
_plugins = None

def load_plugins() -> Dict[str, Plugin]:
    """Discover and instantiate all plugins in the eli.plugins package."""
    global _plugins
    if _plugins is not None:
        return _plugins

    plugins = {}
    _seen_classes: set = set()
    package = importlib.import_module("eli.plugins")
    for finder, name, ispkg in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        try:
            module = importlib.import_module(name)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if inspect.isclass(attr) and issubclass(attr, Plugin) and attr is not Plugin:
                    if id(attr) in _seen_classes:
                        continue
                    _seen_classes.add(id(attr))
                    instance = attr()
                    plugins[instance.name] = instance
                    log.debug(f"[PLUGIN] Loaded: {instance.name} – {instance.description}")
        except Exception as e:
            log.debug(f"[PLUGIN] Failed to load {name}: {e}")
    _plugins = plugins
    return plugins

def get_plugin(name: str) -> Optional[Plugin]:
    """Get a plugin instance by name."""
    return load_plugins().get(name)

def register_all_plugins():
    """Register all plugin actions with the capability registry."""
    for plugin in load_plugins().values():
        plugin.register({})
