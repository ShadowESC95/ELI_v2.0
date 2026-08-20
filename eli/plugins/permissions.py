"""Android-style consent for plugins: allow always, allow once, reject.

Until now a plugin was ordinary Python executed inside ELI's own process
(`manager._load_plugin_from_file` → `exec_module`). Whatever the interpreter could
do, the plugin could do: read every conversation, reach the network, drive the
mouse, spawn processes. Nothing declared intent and nothing asked the operator.
That is survivable while every plugin ships with ELI. It is not survivable the
moment strangers can publish one.

This module is the gate. A plugin DECLARES the capabilities it needs in its
manifest; the operator is asked, in plain language, before any of them are used;
and the answer is remembered or not according to which answer it was.

Three rules hold everywhere:

  * Fail closed. No prompt handler registered (headless, API server, a scheduled
    task at 3am) means DENY, never a silent allow. A plugin cannot escalate by
    running somewhere nobody is watching.
  * Nothing is granted by installing. Install consent and use consent are separate
    acts — Android learned this the hard way with install-time permissions.
  * Every decision is written to an audit ledger the operator can read back.

The capability names here are the vocabulary the manifest, the marketplace listing
and the consent dialog all speak, so a listing cannot promise one thing and request
another.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# ── decisions ──────────────────────────────────────────────────────────────────
ALLOW_ALWAYS = "allow_always"
ALLOW_ONCE = "allow_once"
DENY_ONCE = "deny_once"
DENY_ALWAYS = "deny_always"

DECISIONS = (ALLOW_ALWAYS, ALLOW_ONCE, DENY_ONCE, DENY_ALWAYS)
_PERSISTED = (ALLOW_ALWAYS, DENY_ALWAYS)

RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL = "low", "medium", "high", "critical"

# ── the capability vocabulary ──────────────────────────────────────────────────
# Wording matters more than it looks: this text is what the operator reads at the
# moment they decide. It says what the plugin can DO to them, not which API it calls.
CAPABILITIES: Dict[str, Dict[str, Any]] = {
    "network": {
        "title": "Connect to the internet",
        "detail": "Send and receive data over the internet.",
        "why_risky": "Anything this plugin can read, it can also send somewhere else.",
        "risk": RISK_HIGH,
    },
    "filesystem_read": {
        "title": "Read your files",
        "detail": "Open and read files on this computer.",
        "why_risky": "Documents, keys and saved passwords are files too.",
        "risk": RISK_HIGH,
    },
    "filesystem_write": {
        "title": "Create and change your files",
        "detail": "Write, modify or delete files on this computer.",
        "why_risky": "A mistake or a malicious plugin can destroy data that is not backed up.",
        "risk": RISK_CRITICAL,
    },
    "process_exec": {
        "title": "Run other programs",
        "detail": "Start other programs or shell commands on this computer.",
        "why_risky": "This is effectively unlimited access — a launched program is not "
                     "bound by any of ELI's own limits.",
        "risk": RISK_CRITICAL,
    },
    "os_control": {
        "title": "Control your mouse and keyboard",
        "detail": "Move the pointer, click, and type as if it were you.",
        "why_risky": "Anything you can do at this desk, it can do without asking again.",
        "risk": RISK_CRITICAL,
    },
    "screen_capture": {
        "title": "See your screen",
        "detail": "Take screenshots of what is currently displayed.",
        "why_risky": "Whatever is on screen — messages, banking, private documents — is captured.",
        "risk": RISK_HIGH,
    },
    "camera": {
        "title": "Use your camera",
        "detail": "Capture images or video from a connected camera.",
        "why_risky": "Recording can happen without an obvious indicator.",
        "risk": RISK_CRITICAL,
    },
    "microphone": {
        "title": "Use your microphone",
        "detail": "Record audio from a connected microphone.",
        "why_risky": "Recording can happen without an obvious indicator.",
        "risk": RISK_CRITICAL,
    },
    "memory_read": {
        "title": "Read your conversations and memories",
        "detail": "Read what you have said to ELI and what ELI has remembered about you.",
        "why_risky": "This is the most personal data ELI holds.",
        "risk": RISK_HIGH,
    },
    "memory_write": {
        "title": "Change what ELI remembers",
        "detail": "Add to or alter ELI's stored memories about you.",
        "why_risky": "A plugin that writes memory can change how ELI treats you afterwards.",
        "risk": RISK_HIGH,
    },
    "model_access": {
        "title": "Use ELI's language model",
        "detail": "Send prompts to the local model and read its replies.",
        "why_risky": "Uses your GPU and can shape what ELI says.",
        "risk": RISK_MEDIUM,
    },
    "clipboard": {
        "title": "Read and change your clipboard",
        "detail": "Access whatever you have copied.",
        "why_risky": "Copied passwords pass through the clipboard.",
        "risk": RISK_HIGH,
    },
    "notifications": {
        "title": "Show you notifications",
        "detail": "Display desktop notifications.",
        "why_risky": "Can be used to impersonate messages from ELI or the system.",
        "risk": RISK_LOW,
    },
    "audio_playback": {
        "title": "Play sound",
        "detail": "Play audio through your speakers.",
        "why_risky": "Low risk on its own.",
        "risk": RISK_LOW,
    },
}

ALL_CAPABILITIES = tuple(CAPABILITIES)


def describe(capability: str) -> Dict[str, Any]:
    """Human-readable description of a capability, including unknown ones.

    An unrecognised capability is reported as critical rather than ignored — a
    manifest asking for something this build has never heard of is exactly the case
    that must not be waved through.
    """
    known = CAPABILITIES.get(capability)
    if known:
        return {"id": capability, **known}
    return {
        "id": capability,
        "title": f"Unrecognised permission: {capability}",
        "detail": "This build of ELI does not know what this permission does.",
        "why_risky": "A permission ELI cannot explain cannot be judged. Treat with suspicion.",
        "risk": RISK_CRITICAL,
    }


def risk_of(capabilities) -> str:
    """The highest risk level among the requested capabilities."""
    order = [RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL]
    worst = RISK_LOW
    for cap in capabilities or ():
        r = describe(cap)["risk"]
        if order.index(r) > order.index(worst):
            worst = r
    return worst


# ── storage ────────────────────────────────────────────────────────────────────

def _grants_path() -> Path:
    from eli.core.paths import config_dir
    return Path(config_dir()) / "plugin_permissions.json"


def _audit_path() -> Path:
    from eli.core.paths import logs_dir
    return Path(logs_dir()) / "plugin_permissions_audit.jsonl"


class PermissionStore:
    """Persistent allow/deny decisions, plus session-only 'allow once' grants."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._persistent: Dict[str, Dict[str, Any]] = self._load()
        # Session grants die with the process — that is what "once" means.
        self._session: Dict[str, set] = {}

    def _load(self) -> Dict[str, Dict[str, Any]]:
        p = _grants_path()
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data.get("grants", {}) if isinstance(data, dict) else {}
        except Exception:
            log.debug("[PLUGIN-PERM] unreadable grant file; starting empty", exc_info=True)
            return {}

    def _save(self) -> None:
        p = _grants_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(
                {"version": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "grants": self._persistent}, indent=2), encoding="utf-8")
            tmp.replace(p)
        except Exception:
            log.debug("[PLUGIN-PERM] could not persist grants", exc_info=True)

    # ── queries ───────────────────────────────────────────────────────────────
    def stored_decision(self, plugin_id: str, capability: str) -> Optional[str]:
        with self._lock:
            return (self._persistent.get(plugin_id, {}).get(capability) or {}).get("decision")

    def has_session_grant(self, plugin_id: str, capability: str) -> bool:
        with self._lock:
            return capability in self._session.get(plugin_id, set())

    def grants_for(self, plugin_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._persistent.get(plugin_id, {}))

    def all_grants(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._persistent.items()}

    # ── mutation ──────────────────────────────────────────────────────────────
    def record(self, plugin_id: str, capability: str, decision: str,
               detail: str = "") -> None:
        if decision not in DECISIONS:
            raise ValueError(f"unknown decision: {decision!r}")
        with self._lock:
            if decision in _PERSISTED:
                self._persistent.setdefault(plugin_id, {})[capability] = {
                    "decision": decision,
                    "detail": detail,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                self._save()
            elif decision == ALLOW_ONCE:
                self._session.setdefault(plugin_id, set()).add(capability)
        self._audit(plugin_id, capability, decision, detail)

    def revoke(self, plugin_id: str, capability: Optional[str] = None) -> None:
        """Take a permission back. The operator must always be able to undo consent."""
        with self._lock:
            if capability is None:
                self._persistent.pop(plugin_id, None)
                self._session.pop(plugin_id, None)
            else:
                self._persistent.get(plugin_id, {}).pop(capability, None)
                self._session.get(plugin_id, set()).discard(capability)
            self._save()
        self._audit(plugin_id, capability or "*", "revoked", "")

    def clear_session(self, plugin_id: Optional[str] = None) -> None:
        with self._lock:
            if plugin_id is None:
                self._session.clear()
            else:
                self._session.pop(plugin_id, None)

    # ── audit ─────────────────────────────────────────────────────────────────
    def _audit(self, plugin_id: str, capability: str, decision: str, detail: str) -> None:
        try:
            p = _audit_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "plugin": plugin_id, "capability": capability,
                    "decision": decision, "detail": detail,
                }, ensure_ascii=False) + "\n")
        except Exception:
            log.debug("[PLUGIN-PERM] could not append to the audit ledger", exc_info=True)

    def audit_tail(self, limit: int = 200) -> list:
        p = _audit_path()
        if not p.is_file():
            return []
        try:
            lines = p.read_text(encoding="utf-8").splitlines()[-int(limit):]
            return [json.loads(l) for l in lines if l.strip()]
        except Exception:
            return []


_STORE: Optional[PermissionStore] = None
_STORE_LOCK = threading.Lock()


def store() -> PermissionStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = PermissionStore()
        return _STORE


# ── the prompt handler ─────────────────────────────────────────────────────────
# The GUI registers a real dialog. Everything else (API server, scheduled tasks,
# headless CLI) leaves it unset, and an unset handler denies.
_PROMPT: Optional[Callable[[Dict[str, Any]], str]] = None


def set_prompt_handler(fn: Optional[Callable[[Dict[str, Any]], str]]) -> None:
    """Register the consent UI. Passing None restores fail-closed behaviour."""
    global _PROMPT
    _PROMPT = fn


def has_prompt_handler() -> bool:
    return _PROMPT is not None


def check(plugin_id: str, capability: str, detail: str = "",
          *, interactive: bool = True) -> Dict[str, Any]:
    """Decide whether `plugin_id` may use `capability` right now.

    Returns {allowed, decision, reason, prompted}. Order of precedence:

      1. A stored DENY_ALWAYS — never re-asked; the operator already said no.
      2. A stored ALLOW_ALWAYS — proceeds silently, as the operator asked.
      3. A session ALLOW_ONCE already given this session.
      4. Otherwise ask, if there is anybody to ask. If not, deny.
    """
    s = store()

    stored = s.stored_decision(plugin_id, capability)
    if stored == DENY_ALWAYS:
        return {"allowed": False, "decision": DENY_ALWAYS, "prompted": False,
                "reason": "You previously rejected this permission for this plugin."}
    if stored == ALLOW_ALWAYS:
        return {"allowed": True, "decision": ALLOW_ALWAYS, "prompted": False,
                "reason": "You previously allowed this permission for this plugin."}
    if s.has_session_grant(plugin_id, capability):
        return {"allowed": True, "decision": ALLOW_ONCE, "prompted": False,
                "reason": "Allowed for this session."}

    if not interactive or _PROMPT is None:
        # Fail closed. A plugin must not gain a permission by running where nobody
        # can be asked — the 3am scheduled task is exactly when this matters.
        s._audit(plugin_id, capability, DENY_ONCE, "no consent UI available")
        return {"allowed": False, "decision": DENY_ONCE, "prompted": False,
                "reason": ("This plugin asked for a permission while nothing could ask you. "
                           "Denied automatically — open the Marketplace to decide.")}

    info = describe(capability)
    request = {
        "plugin_id": plugin_id,
        "capability": capability,
        "title": info["title"],
        "detail": detail or info["detail"],
        "why_risky": info["why_risky"],
        "risk": info["risk"],
    }
    try:
        answer = _PROMPT(request)
    except Exception as exc:
        log.debug(f"[PLUGIN-PERM] consent UI failed: {exc}", exc_info=True)
        s._audit(plugin_id, capability, DENY_ONCE, f"consent UI error: {exc}")
        return {"allowed": False, "decision": DENY_ONCE, "prompted": True,
                "reason": f"Could not ask you ({exc}); denied."}

    if answer not in DECISIONS:
        answer = DENY_ONCE
    s.record(plugin_id, capability, answer, detail)
    allowed = answer in (ALLOW_ALWAYS, ALLOW_ONCE)
    return {"allowed": allowed, "decision": answer, "prompted": True,
            "reason": f"You chose {answer.replace('_', ' ')}."}


def require(plugin_id: str, capability: str, detail: str = "") -> None:
    """check() as an assertion — raises PermissionError when refused."""
    verdict = check(plugin_id, capability, detail)
    if not verdict["allowed"]:
        raise PermissionError(
            f"Plugin '{plugin_id}' is not permitted to {describe(capability)['title'].lower()}. "
            f"{verdict['reason']}")


__all__ = [
    "ALLOW_ALWAYS", "ALLOW_ONCE", "DENY_ONCE", "DENY_ALWAYS", "DECISIONS",
    "CAPABILITIES", "ALL_CAPABILITIES", "describe", "risk_of",
    "PermissionStore", "store", "set_prompt_handler", "has_prompt_handler",
    "check", "require",
]
