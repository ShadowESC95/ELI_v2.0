"""Plugin manifests: what a plugin says it is, checked against what it does.

ELI's own marketplace is the community's, not the vendor's. Nobody curates it,
nobody vets uploads, and ELI must never imply otherwise. That removes the usual
first line of defence — "the store checked it" — so everything has to come from
the artifact itself:

  * the manifest DECLARES the permissions the plugin needs, in the same vocabulary
    the consent dialog speaks (`permissions.CAPABILITIES`);
  * the code is STATICALLY SCANNED for capability use, and an undeclared capability
    is a refusal, not a warning. A plugin that quietly imports `subprocess` while
    declaring nothing is the exact attack this stops;
  * everything the operator is shown — publisher, licence, price, permissions —
    comes from the manifest, and the manifest is covered by the integrity hash, so
    the listing cannot promise one thing and ship another.

The scan is deliberately conservative. It over-reports rather than under-reports:
a false "you must declare filesystem_write" costs a publisher one manifest line,
while a false negative costs an operator their files.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.plugins.permissions import ALL_CAPABILITIES, describe, risk_of

MANIFEST_NAME = "eli_plugin.json"
SCHEMA_VERSION = 1

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")
_VERSION_RE = re.compile(r"^\d+\.\d+(\.\d+)?([-+][0-9A-Za-z.-]+)?$")

REQUIRED_FIELDS = ("id", "name", "version", "description", "author", "license")

# Module/attribute use → the capability that must be declared for it. Matched
# against import names and attribute chains, so `import os` + `os.system(...)`
# is caught even though the import alone is innocuous.
_IMPORT_CAPABILITIES: Dict[str, str] = {
    "socket": "network", "http": "network", "urllib": "network",
    "requests": "network", "httpx": "network", "aiohttp": "network",
    "ftplib": "network", "telnetlib": "network", "smtplib": "network",
    "websocket": "network", "websockets": "network", "curl_cffi": "network",
    "subprocess": "process_exec", "multiprocessing": "process_exec",
    "pty": "process_exec", "pexpect": "process_exec",
    "shutil": "filesystem_write", "tempfile": "filesystem_write",
    "pyautogui": "os_control", "pynput": "os_control", "keyboard": "os_control",
    "mouse": "os_control", "pyperclip": "clipboard",
    "mss": "screen_capture", "PIL.ImageGrab": "screen_capture",
    "cv2": "camera", "picamera": "camera",
    "sounddevice": "microphone", "pyaudio": "microphone", "speech_recognition": "microphone",
}

_ATTR_CAPABILITIES: Dict[str, str] = {
    "os.system": "process_exec", "os.popen": "process_exec",
    "os.execv": "process_exec", "os.execl": "process_exec", "os.spawnv": "process_exec",
    "os.fork": "process_exec", "os.remove": "filesystem_write", "os.unlink": "filesystem_write",
    "os.rmdir": "filesystem_write", "os.rename": "filesystem_write",
    "os.makedirs": "filesystem_write", "os.mkdir": "filesystem_write",
    "os.chmod": "filesystem_write", "os.chown": "filesystem_write",
    "pathlib.Path.write_text": "filesystem_write",
    "pathlib.Path.write_bytes": "filesystem_write",
    "pathlib.Path.read_text": "filesystem_read",
    "pathlib.Path.read_bytes": "filesystem_read",
}

# Method names that imply a capability whatever the receiver is. The dotted-chain
# lookup above only fires on `pathlib.Path.read_text`-shaped code; real plugins write
# `(Path.home() / ".ssh" / "id_rsa").read_text()`, whose receiver is an expression.
_METHOD_CAPABILITIES: Dict[str, str] = {
    "read_text": "filesystem_read", "read_bytes": "filesystem_read",
    "write_text": "filesystem_write", "write_bytes": "filesystem_write",
    "unlink": "filesystem_write", "rmdir": "filesystem_write",
    "mkdir": "filesystem_write", "touch": "filesystem_write",
    "rename": "filesystem_write", "replace": "filesystem_write",
    "chmod": "filesystem_write", "rmtree": "filesystem_write",
    "urlopen": "network", "urlretrieve": "network",
    "screenshot": "screen_capture", "grab": "screen_capture",
}

# Calls that carry an unbounded escalation and cannot be declared away. A plugin
# that builds code at runtime defeats every static check above, so the scanner
# refuses it outright rather than asking the operator to judge it.
_FORBIDDEN_CALLS = {
    "eval": "builds and runs code at runtime",
    "exec": "builds and runs code at runtime",
    "compile": "builds and runs code at runtime",
    "__import__": "imports modules dynamically, hiding what it loads",
}
_FORBIDDEN_ATTRS = {
    "importlib.import_module": "imports modules dynamically, hiding what it loads",
    "marshal.loads": "loads raw code objects",
    "pickle.loads": "deserialises arbitrary objects, which can execute code",
    "ctypes.CDLL": "loads native libraries, bypassing every Python-level check",
    "ctypes.cdll": "loads native libraries, bypassing every Python-level check",
    "os.environ": None,   # noted, not forbidden — resolved below
}


def _attr_chain(node: ast.AST) -> str:
    """Dotted name for an attribute/name node ('os.path.join'), or ''."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    else:
        return ""
    return ".".join(reversed(parts))


def scan_source(source: str, *, filename: str = "plugin.py") -> Dict[str, Any]:
    """Static capability scan. Returns {ok, required, forbidden, syntax_error}."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return {"ok": False, "required": [], "forbidden": [],
                "syntax_error": f"{exc.msg} (line {exc.lineno})"}

    required: Dict[str, List[str]] = {}
    forbidden: List[Dict[str, Any]] = []

    def need(cap: str, evidence: str, line: int) -> None:
        required.setdefault(cap, [])
        item = f"{evidence} (line {line})"
        if item not in required[cap]:
            required[cap].append(item)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                cap = _IMPORT_CAPABILITIES.get(alias.name) or _IMPORT_CAPABILITIES.get(root)
                if cap:
                    need(cap, f"imports {alias.name}", node.lineno)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".")[0]
            cap = _IMPORT_CAPABILITIES.get(mod) or _IMPORT_CAPABILITIES.get(root)
            if cap:
                need(cap, f"imports from {mod}", node.lineno)
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _FORBIDDEN_CALLS:
                forbidden.append({"what": fn.id, "why": _FORBIDDEN_CALLS[fn.id],
                                  "line": node.lineno})
            chain = _attr_chain(fn)
            if chain:
                why = _FORBIDDEN_ATTRS.get(chain)
                if why:
                    forbidden.append({"what": chain, "why": why, "line": node.lineno})
                cap = _ATTR_CAPABILITIES.get(chain)
                if cap:
                    need(cap, f"calls {chain}", node.lineno)
            if isinstance(fn, ast.Attribute) and not chain:
                # Receiver is an expression, so only the method name is known.
                cap = _METHOD_CAPABILITIES.get(fn.attr)
                if cap:
                    need(cap, f"calls .{fn.attr}()", node.lineno)
                # open(..., 'w') is the common write that is not an os.* call
        elif isinstance(node, ast.Attribute):
            chain = _attr_chain(node)
            cap = _ATTR_CAPABILITIES.get(chain)
            if cap:
                need(cap, f"uses {chain}", node.lineno)

    # `open()` needs read or write depending on its mode argument.
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = "r"
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords or []:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            cap = "filesystem_write" if any(c in mode for c in "wxa+") else "filesystem_read"
            need(cap, f"calls open(mode={mode!r})", node.lineno)

    return {"ok": not forbidden, "required": required, "forbidden": forbidden,
            "syntax_error": None}


def validate_manifest(data: Any) -> Dict[str, Any]:
    """Shape and content checks. Returns {ok, problems, warnings, manifest}."""
    problems: List[str] = []
    warnings: List[str] = []

    if not isinstance(data, dict):
        return {"ok": False, "problems": ["Manifest is not a JSON object."],
                "warnings": [], "manifest": {}}

    m = dict(data)

    for field in REQUIRED_FIELDS:
        if not str(m.get(field) or "").strip():
            problems.append(f"Missing required field: {field}")

    pid = str(m.get("id") or "")
    if pid and not _ID_RE.match(pid):
        problems.append("id must be 2-48 chars, lowercase letters/digits/underscore, "
                        "starting with a letter.")

    ver = str(m.get("version") or "")
    if ver and not _VERSION_RE.match(ver):
        problems.append(f"version {ver!r} is not a valid version (expected e.g. 1.0.0).")

    perms = m.get("permissions")
    if perms is None:
        perms = []
    if not isinstance(perms, list):
        problems.append("permissions must be a list.")
        perms = []
    perms = [str(p) for p in perms]
    unknown = [p for p in perms if p not in ALL_CAPABILITIES]
    if unknown:
        # Not fatal — but described as critical to the operator, and never silently
        # dropped, because a build that does not understand a permission cannot
        # enforce it either.
        warnings.append(f"Manifest requests permissions this build does not recognise: "
                        f"{', '.join(sorted(unknown))}")
    m["permissions"] = perms

    price = m.get("price")
    if price is not None:
        try:
            if float(price) < 0:
                problems.append("price cannot be negative.")
        except Exception:
            problems.append("price must be a number (use 0 for free).")

    for field in ("source", "homepage", "publisher_url", "purchase_url"):
        url = str(m.get(field) or "")
        if url and not url.startswith(("https://", "http://")):
            problems.append(f"{field} must be an http(s) URL.")
        if url.startswith("http://"):
            warnings.append(f"{field} uses plain http — the download can be tampered with "
                            f"in transit. https is strongly preferred.")

    if m.get("sha256") and not re.fullmatch(r"[0-9a-fA-F]{64}", str(m["sha256"])):
        problems.append("sha256 must be 64 hex characters.")

    m.setdefault("schema", SCHEMA_VERSION)
    m.setdefault("pip", [])
    if not isinstance(m.get("pip"), list):
        problems.append("pip must be a list of package specifiers.")
        m["pip"] = []

    return {"ok": not problems, "problems": problems, "warnings": warnings, "manifest": m}


def verify_against_source(manifest: Dict[str, Any], source: str) -> Dict[str, Any]:
    """The core check: does the code stay inside what the manifest declared?

    Returns {ok, undeclared, over_declared, forbidden, required, problems}.
    Undeclared capability use is a refusal — that is the whole point.
    """
    scan = scan_source(source)
    declared = set(str(p) for p in (manifest.get("permissions") or []))
    required = set(scan["required"].keys())

    undeclared = sorted(required - declared)
    over_declared = sorted(declared - required)

    problems: List[str] = []
    if scan.get("syntax_error"):
        problems.append(f"Plugin source does not parse: {scan['syntax_error']}")
    for f in scan["forbidden"]:
        problems.append(f"Refused: uses {f['what']} at line {f['line']} — {f['why']}.")
    for cap in undeclared:
        evidence = "; ".join(scan["required"][cap][:3])
        problems.append(
            f"Refused: uses '{describe(cap)['title'].lower()}' without declaring "
            f"the '{cap}' permission ({evidence}).")

    return {
        "ok": not problems,
        "undeclared": undeclared,
        "over_declared": over_declared,
        "forbidden": scan["forbidden"],
        "required": scan["required"],
        "problems": problems,
        "risk": risk_of(declared | required),
    }


def load_manifest(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "problems": [f"Could not read manifest: {exc}"],
                "warnings": [], "manifest": {}}
    return validate_manifest(data)


__all__ = [
    "MANIFEST_NAME", "SCHEMA_VERSION", "REQUIRED_FIELDS",
    "scan_source", "validate_manifest", "verify_against_source", "load_manifest",
]
