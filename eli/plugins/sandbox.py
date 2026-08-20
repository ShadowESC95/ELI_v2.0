"""Runtime capability enforcement for loaded plugins.

Everything else in this package gates a plugin *before* it runs: the manifest is
checked against the source, the download is hashed, eleven scanners look at it, and
the operator consents per capability. All of that is defeated by one fact — once a
plugin is enabled it is `exec_module`'d into ELI's own interpreter, so the
permission API is **cooperative**. A plugin that passed every check can simply
`import socket` and never call ELI's gated helpers at all.

This closes that. `sys.addaudithook` fires below the Python API, on the actual
operation: `socket.connect`, `open`, `subprocess.Popen`, `os.system`,
`ctypes.dlopen`. Raising inside the hook aborts the operation. The hook attributes
each event to a plugin by walking the stack for a frame belonging to a plugin
package, then enforces that plugin's DECLARED capabilities and the operator's
consent.

Properties worth stating precisely, because "sandbox" oversells it:

  * **It cannot be uninstalled.** CPython provides no way to remove an audit hook,
    so a plugin cannot lift it once ELI has installed it.
  * **It enforces below the API.** Importing `socket` directly does not help; the
    connect still raises.
  * **It is not a security boundary against native code.** A plugin that gets as
    far as running arbitrary machine code — through a compiled extension — is
    outside anything an in-process hook can see, which is why `ctypes.dlopen` is
    itself refused unless declared, and why the manifest checker rejects `ctypes`
    outright.
  * **It does not contain subprocesses.** A plugin granted `process_exec` spawns a
    real child, and nothing here follows it. That is the same limit netguard has,
    and it is why `process_exec` is described to the operator as unlimited access.

Only ELI's own code is exempt, and only because nothing outside a plugin directory
can be attributed to a plugin.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Dict, Optional, Set

from eli.utils.log import get_logger

log = get_logger(__name__)

_installed = False
_install_lock = threading.Lock()

# event name → capability it needs. `open` is resolved per-call from its mode.
_EVENT_CAPABILITY = {
    "socket.connect": "network",
    "socket.getaddrinfo": "network",
    "socket.gethostbyname": "network",
    "urllib.Request": "network",
    "subprocess.Popen": "process_exec",
    "os.system": "process_exec",
    "os.exec": "process_exec",
    "os.spawn": "process_exec",
    "os.posix_spawn": "process_exec",
    "os.fork": "process_exec",
    "os.forkpty": "process_exec",
    "pty.spawn": "process_exec",
    "ctypes.dlopen": "process_exec",
    "ctypes.dlsym": "process_exec",
    "os.remove": "filesystem_write",
    "os.rename": "filesystem_write",
    "os.rmdir": "filesystem_write",
    "os.mkdir": "filesystem_write",
    "os.chmod": "filesystem_write",
    "os.truncate": "filesystem_write",
    "shutil.rmtree": "filesystem_write",
    "shutil.copyfile": "filesystem_write",
    "shutil.move": "filesystem_write",
}

# Loopback is exempt from the network capability: ELI's own model server, the local
# API and MQTT all live there, and a plugin talking to them is not egress. Anything
# leaving the machine is.
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}

_plugin_roots: Dict[str, str] = {}          # resolved plugin dir -> plugin id
_declared: Dict[str, Set[str]] = {}          # plugin id -> declared capabilities
_frame_cache: Dict[int, Optional[str]] = {}  # id(code) -> plugin id or None
_session_allowed: Set[tuple] = set()         # (plugin, capability) consented this session
_cache_lock = threading.RLock()


def _refresh_roots() -> None:
    """Map every installed plugin directory to its id and declared capabilities."""
    import json
    roots: Dict[str, str] = {}
    declared: Dict[str, Set[str]] = {}
    try:
        from eli.plugins.manager import _plugin_search_dirs
        search = _plugin_search_dirs()
    except Exception:
        log.debug("[SANDBOX] could not list plugin directories", exc_info=True)
        return
    for base in search:
        try:
            if not base.is_dir():
                continue
            for child in base.iterdir():
                if not child.is_dir() or child.name in ("base", "registry", "__pycache__"):
                    continue
                roots[str(child.resolve())] = child.name
                caps: Set[str] = set()
                manifest = child / "eli_plugin.json"
                if manifest.is_file():
                    try:
                        caps = set(json.loads(manifest.read_text(encoding="utf-8"))
                                   .get("permissions") or [])
                    except Exception:
                        log.debug(f"[SANDBOX] unreadable manifest for {child.name}",
                                  exc_info=True)
                else:
                    # A bundled plugin with no manifest predates the marketplace.
                    # Treat it as fully declared rather than breaking it — it shipped
                    # with ELI and was not downloaded from a stranger.
                    caps = {"*"}
                declared[child.name] = caps
        except Exception:
            log.debug(f"[SANDBOX] could not scan {base}", exc_info=True)
    with _cache_lock:
        _plugin_roots.clear()
        _plugin_roots.update(roots)
        _declared.clear()
        _declared.update(declared)
        _frame_cache.clear()


def _plugin_for_file(filename: str) -> Optional[str]:
    if not filename:
        return None
    try:
        resolved = str(Path(filename).resolve())
    except Exception:
        resolved = filename
    for root, pid in _plugin_roots.items():
        if resolved.startswith(root + os.sep):
            return pid
    return None


def _attribute() -> Optional[str]:
    """The plugin responsible for the current call, or None for ELI's own code.

    Walks outward from the caller. The cache is keyed on the code object so the
    path resolution happens once per function, not once per call.
    """
    frame = sys._getframe(2) if hasattr(sys, "_getframe") else None
    depth = 0
    while frame is not None and depth < 40:
        code = frame.f_code
        key = id(code)
        with _cache_lock:
            cached = _frame_cache.get(key, ...)
        if cached is ...:
            pid = _plugin_for_file(code.co_filename)
            with _cache_lock:
                _frame_cache[key] = pid
            cached = pid
        if cached is not None:
            return cached
        frame = frame.f_back
        depth += 1
    return None


def _capability_for(event: str, args) -> Optional[str]:
    if event == "open":
        try:
            mode = str(args[1] or "r") if len(args) > 1 else "r"
        except Exception:
            mode = "r"
        return "filesystem_write" if any(c in mode for c in "wxa+") else "filesystem_read"
    if event == "socket.connect":
        try:
            address = args[1]
            host = address[0] if isinstance(address, (tuple, list)) else address
            if str(host) in _LOOPBACK:
                return None
        except Exception:
            # Unparseable address — fall through to requiring the network
            # capability. Failing open here would be the one bypass worth having.
            log.debug("[SANDBOX] could not read connect address", exc_info=True)
        return "network"
    return _EVENT_CAPABILITY.get(event)


def _audit(event: str, args) -> None:
    if event not in _EVENT_CAPABILITY and event != "open":
        return
    plugin = _attribute()
    if plugin is None:
        return                      # ELI's own code — not this hook's business

    capability = _capability_for(event, args)
    if capability is None:
        return

    with _cache_lock:
        declared = _declared.get(plugin)
        already = (plugin, capability) in _session_allowed
    if already:
        return
    if declared and "*" in declared:
        return                      # bundled plugin, shipped with ELI

    if declared is not None and capability not in declared:
        raise PermissionError(
            f"Plugin '{plugin}' attempted {event} which needs the '{capability}' "
            f"permission, and its manifest does not declare it. Blocked.")

    # Declared — now the operator's consent decides, once per session per capability.
    try:
        from eli.plugins.permissions import check
        verdict = check(plugin, capability, f"{event} (enforced at runtime)")
    except Exception as exc:
        raise PermissionError(
            f"Plugin '{plugin}' attempted {event} and consent could not be "
            f"established ({exc}). Blocked.") from None
    if not verdict["allowed"]:
        raise PermissionError(
            f"Plugin '{plugin}' is not permitted to {capability.replace('_', ' ')}. "
            f"{verdict['reason']}")
    with _cache_lock:
        _session_allowed.add((plugin, capability))


def install_plugin_sandbox() -> bool:
    """Install the runtime enforcement hook. Idempotent; cannot be undone.

    Returns True if it was installed by this call. Disable with
    ELI_PLUGIN_SANDBOX=0 — which is a real downgrade and should only be used to
    diagnose a plugin ELI is blocking.
    """
    global _installed
    with _install_lock:
        if _installed:
            # Already hooked, but the plugin set may have changed since — an install,
            # an uninstall, or a different plugins directory. Returning without
            # re-reading left stale roots, and a plugin the hook did not recognise is
            # a plugin it silently does not enforce.
            _refresh_roots()
            return False
        if (os.environ.get("ELI_PLUGIN_SANDBOX", "").strip().lower()
                in ("0", "false", "no")):
            log.warning("[SANDBOX] plugin runtime enforcement DISABLED by "
                        "ELI_PLUGIN_SANDBOX — plugins run unrestricted")
            _installed = True
            return False
        _refresh_roots()
        sys.addaudithook(_audit)
        _installed = True
        log.info(f"[SANDBOX] runtime capability enforcement active for "
                 f"{len(_plugin_roots)} plugin director(ies)")
        return True


def refresh() -> None:
    """Re-read plugin directories and manifests after an install or uninstall."""
    if _installed:
        _refresh_roots()


def reset_session_grants() -> None:
    with _cache_lock:
        _session_allowed.clear()


def status() -> dict:
    with _cache_lock:
        return {
            "installed": _installed,
            "plugins": dict(_plugin_roots),
            "declared": {k: sorted(v) for k, v in _declared.items()},
            "session_allowed": sorted(_session_allowed),
        }


__all__ = ["install_plugin_sandbox", "refresh", "reset_session_grants", "status"]
