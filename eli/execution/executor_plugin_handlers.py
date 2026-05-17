# eli/plugins/executor_plugin_handlers.py
"""
Drop-in executor handlers for plugin management actions.

Wire into executor_enhanced.py _execute_impl() by adding:

    from eli.execution.executor_plugin_handlers import handle_plugin_action
    ...
    # Near the top of _execute_impl's action dispatch:
    if action.startswith("PLUGIN_") or action in ("LIST_PLUGINS", "INSTALL_PLUGIN",
                                                    "UNINSTALL_PLUGIN", "ENABLE_PLUGIN",
                                                    "DISABLE_PLUGIN"):
        return handle_plugin_action(action, args)

Alternatively, the apply script will inject this automatically.
"""

from __future__ import annotations

from typing import Any, Dict


def handle_plugin_action(action: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dispatch plugin management + plugin execution actions.

    Actions handled:
        LIST_PLUGINS        - list installed plugins
        LIST_AVAILABLE_PLUGINS - list registry
        INSTALL_PLUGIN      - install by id (args: plugin_id)
        UNINSTALL_PLUGIN    - uninstall by id (args: plugin_id)
        ENABLE_PLUGIN       - enable by id (args: plugin_id)
        DISABLE_PLUGIN      - disable by id (args: plugin_id)
        PLUGIN_EXEC         - execute plugin action
                              (args: plugin_id, plugin_action, **action_args)
        REFRESH_PLUGIN_REGISTRY - re-fetch registry
    """
    try:
        from eli.plugins.manager import get_manager
        mgr = get_manager()
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Plugin manager unavailable: {exc}",
            "content": f"Plugin manager unavailable: {exc}",
            "response": f"Plugin manager unavailable: {exc}",
        }

    # ----------------------------------------------------------------
    if action == "LIST_PLUGINS":
        installed = mgr.list_installed()
        if not installed:
            msg = "No plugins installed. Say 'list available plugins' to browse the registry."
        else:
            lines = []
            for p in installed:
                status = "✅" if p["enabled"] else "⏸"
                lines.append(f"{status} {p['id']} v{p['version']} — {p['description']}")
            msg = "Installed plugins:\n" + "\n".join(lines)
        return {"ok": True, "content": msg, "response": msg, "plugins": installed}

    # ----------------------------------------------------------------
    if action == "LIST_AVAILABLE_PLUGINS":
        available = mgr.list_available()
        if not available:
            msg = "Could not fetch plugin registry. Check your connection."
            return {"ok": False, "content": msg, "response": msg}
        lines = []
        installed_ids = {p["id"] for p in mgr.list_installed()}
        for p in available:
            tag = " [installed]" if p["id"] in installed_ids else ""
            lines.append(f"• {p['id']}: {p['description']}{tag}")
        msg = "Available plugins:\n" + "\n".join(lines)
        return {"ok": True, "content": msg, "response": msg, "plugins": available}

    # ----------------------------------------------------------------
    if action == "INSTALL_PLUGIN":
        plugin_id = args.get("plugin_id") or args.get("id") or args.get("name")
        if not plugin_id:
            return {
                "ok": False,
                "content": "Please specify a plugin id. E.g. 'install weather plugin'",
                "response": "Please specify a plugin id. E.g. 'install weather plugin'",
            }
        return mgr.install(str(plugin_id).lower().strip())

    # ----------------------------------------------------------------
    if action == "UNINSTALL_PLUGIN":
        plugin_id = args.get("plugin_id") or args.get("id") or args.get("name")
        if not plugin_id:
            return {"ok": False, "content": "Specify plugin id to uninstall.", "response": "Specify plugin id to uninstall."}
        return mgr.uninstall(str(plugin_id).lower().strip())

    # ----------------------------------------------------------------
    if action == "ENABLE_PLUGIN":
        plugin_id = args.get("plugin_id") or args.get("id")
        if not plugin_id:
            return {"ok": False, "content": "Specify plugin id to enable.", "response": "Specify plugin id to enable."}
        return mgr.enable(str(plugin_id).lower().strip())

    # ----------------------------------------------------------------
    if action == "DISABLE_PLUGIN":
        plugin_id = args.get("plugin_id") or args.get("id")
        if not plugin_id:
            return {"ok": False, "content": "Specify plugin id to disable.", "response": "Specify plugin id to disable."}
        return mgr.disable(str(plugin_id).lower().strip())

    # ----------------------------------------------------------------
    if action == "REFRESH_PLUGIN_REGISTRY":
        plugins = mgr.refresh_registry()
        msg = f"Registry refreshed. {len(plugins)} plugins available."
        return {"ok": True, "content": msg, "response": msg, "count": len(plugins)}

    # ----------------------------------------------------------------
    if action == "PLUGIN_EXEC":
        plugin_id = args.get("plugin_id")
        plugin_action = args.get("plugin_action")
        if not plugin_id or not plugin_action:
            return {
                "ok": False,
                "content": "PLUGIN_EXEC requires plugin_id and plugin_action.",
                "response": "PLUGIN_EXEC requires plugin_id and plugin_action.",
            }
        exec_args = {k: v for k, v in args.items() if k not in ("plugin_id", "plugin_action")}
        return mgr.execute(str(plugin_id), str(plugin_action), exec_args)

    # ----------------------------------------------------------------
    # Unknown action starting with PLUGIN_
    return {
        "ok": False,
        "content": f"Unknown plugin action: {action}",
        "response": f"Unknown plugin action: {action}",
    }
