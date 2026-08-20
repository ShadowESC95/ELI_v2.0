"""Multi-engine malware scanner for community plugins.

Nobody curates the marketplace, so this is the backend that does the curating —
run over every upload before a listing is trusted, and again on the operator's own
machine before a download is written to disk. Checking twice matters: a registry
can be compromised, and a scan you did not run yourself is a claim, not a result.

Engines, each independent and each degrading to "not available" rather than to a
false clean:

  static_ast      structure: capability use, code built at runtime, dynamic imports
  obfuscation     payloads hidden behind encoding, char arithmetic, decode chains
  ioc_patterns    reverse shells, miners, hardcoded C2 addresses, paste sites
  credentials     reads of ssh keys, wallets, browser stores, keychains
  persistence     autostart, cron, systemd, registry Run keys, LD_PRELOAD, launchd
  anti_analysis   VM/debugger/sandbox detection, a strong signal of deliberate evasion
  entropy         packed or encrypted blobs carried inside source
  dependencies    typosquatted or newly-registered pip names
  hash_blocklist  known-bad artifacts (local list, community-updatable)
  clamav          full antivirus, if clamscan/clamdscan is installed
  yara            custom rules, if the yara module and a ruleset are present

Two rules the scoring obeys:

  * An engine that could not run NEVER counts as a pass. It is reported as
    unavailable and the verdict says coverage was partial. A scanner that quietly
    downgrades to "clean" when ClamAV is missing is worse than no scanner.
  * Findings are evidence, not proof. Every one carries the line and the matched
    construct so a publisher can argue with it and an operator can look.
"""
from __future__ import annotations

import ast
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

INFO, LOW, MEDIUM, HIGH, CRITICAL = "info", "low", "medium", "high", "critical"
_WEIGHT = {INFO: 0, LOW: 5, MEDIUM: 15, HIGH: 35, CRITICAL: 60}

CLEAN, SUSPICIOUS, MALICIOUS = "clean", "suspicious", "malicious"


def _f(engine: str, severity: str, category: str, title: str, detail: str,
       line: Optional[int] = None) -> Dict[str, Any]:
    return {"engine": engine, "severity": severity, "category": category,
            "title": title, "detail": detail, "line": line}


# ── engine: static AST ─────────────────────────────────────────────────────────

def _engine_static_ast(source: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    from eli.plugins.manifest import verify_against_source, scan_source

    findings: List[Dict[str, Any]] = []
    scan = scan_source(source)
    if scan.get("syntax_error"):
        return {"ran": True, "findings": [
            _f("static_ast", HIGH, "malformed", "Source does not parse",
               scan["syntax_error"])]}

    for item in scan["forbidden"]:
        findings.append(_f("static_ast", CRITICAL, "dynamic_code",
                           f"Runtime code construction: {item['what']}",
                           item["why"], item.get("line")))

    check = verify_against_source(manifest, source)
    for cap in check["undeclared"]:
        evidence = "; ".join(check["required"].get(cap, [])[:2])
        findings.append(_f("static_ast", HIGH, "undeclared_capability",
                           f"Uses '{cap}' without declaring it",
                           f"The manifest does not request this permission. {evidence}"))
    return {"ran": True, "findings": findings}


# ── engine: obfuscation ────────────────────────────────────────────────────────

_DECODERS = ("b64decode", "b32decode", "b16decode", "a85decode", "b85decode",
             "decompress", "unhexlify", "fromhex", "rot13", "decrypt")


def _engine_obfuscation(source: str) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"ran": False, "error": "source does not parse"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
            if name in _DECODERS:
                findings.append(_f("obfuscation", HIGH, "encoded_payload",
                                   f"Decodes data at runtime with {name}()",
                                   "Encoded payloads are how malicious code hides from "
                                   "source review.", node.lineno))
            if name == "join" and isinstance(node.func, ast.Attribute):
                # "".join(chr(x) for x in [...]) — classic string reconstruction
                src_seg = ast.get_source_segment(source, node) or ""
                if "chr(" in src_seg:
                    findings.append(_f("obfuscation", HIGH, "string_building",
                                       "Builds strings from character codes",
                                       "Hides literal strings from inspection.", node.lineno))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if len(v) > 200 and re.fullmatch(r"[A-Za-z0-9+/=\s]+", v):
                findings.append(_f("obfuscation", MEDIUM, "encoded_payload",
                                   f"Large base64-looking literal ({len(v)} chars)",
                                   "May be an embedded payload.", node.lineno))
            elif len(v) > 200 and re.fullmatch(r"[0-9a-fA-F\s]+", v):
                findings.append(_f("obfuscation", MEDIUM, "encoded_payload",
                                   f"Large hex literal ({len(v)} chars)",
                                   "May be an embedded payload.", node.lineno))
    return {"ran": True, "findings": findings}


# ── engine: IOC patterns ───────────────────────────────────────────────────────

_IOC = [
    (CRITICAL, "reverse_shell", r"socket\s*\.\s*socket[\s\S]{0,200}?(dup2|/bin/(ba)?sh|cmd\.exe)",
     "Reverse shell pattern: a socket wired to a shell."),
    (CRITICAL, "reverse_shell", r"(dup2\s*\(\s*\w+\s*\.\s*fileno\s*\(\s*\)\s*,\s*[012]\s*\))",
     "Redirects standard streams onto a socket — a reverse shell."),
    (CRITICAL, "reverse_shell", r"pty\s*\.\s*spawn\s*\(",
     "Spawns an interactive pseudo-terminal, typical of shell payloads."),
    (HIGH, "c2", r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
     "Hardcoded IP address URL — legitimate services use names."),
    (HIGH, "c2", r"\b[a-z2-7]{16,56}\.onion\b", "Tor hidden service address."),
    (MEDIUM, "c2", r"\b(pastebin\.com|paste\.ee|hastebin|transfer\.sh|0x0\.st|termbin)\b",
     "Paste/drop site — commonly used to fetch a second stage."),
    (MEDIUM, "c2", r"\b(ngrok\.io|serveo\.net|localtunnel|duckdns\.org|no-ip\.(com|org))\b",
     "Tunnel or dynamic-DNS host — commonly used for command and control."),
    (CRITICAL, "miner", r"\b(stratum\+tcp|xmrig|minerd|cryptonight|randomx)\b",
     "Cryptocurrency miner."),
    (HIGH, "download_exec", r"(urlopen|requests\.get|curl|wget)[\s\S]{0,120}?(exec|eval|system|Popen)",
     "Downloads content and executes it."),
    (HIGH, "destructive", r"(rm\s+-rf\s+[/~]|shutil\.rmtree\s*\(\s*['\"]?[/~]|format\s+c:)",
     "Recursive deletion of a filesystem root or home directory."),
    (HIGH, "destructive", r"\b(mkfs|dd\s+if=/dev/(zero|urandom)\s+of=/dev/)",
     "Overwrites a block device."),
    (MEDIUM, "ransom", r"\b(AES\.new|Fernet|encrypt_file|\.encrypted\b|ransom)\b",
     "File encryption routine — benign in a backup tool, the core of ransomware."),
    (HIGH, "privilege", r"\b(sudo\s|pkexec|runas|ShellExecuteW?\s*\([^)]*runas)",
     "Attempts to escalate privileges."),
    (MEDIUM, "keylog", r"\b(on_press|GetAsyncKeyState|pynput\.keyboard|keylog)\b",
     "Keyboard capture."),
    (MEDIUM, "screen", r"\b(ImageGrab\.grab|mss\(\)|pyscreenshot)\b",
     "Screen capture."),
]


def _engine_ioc(source: str) -> Dict[str, Any]:
    findings = []
    lines = source.splitlines()
    source = source + "\n" + _flatten_paths(source)
    for severity, category, pattern, why in _IOC:
        for m in re.finditer(pattern, source, re.IGNORECASE):
            line = source[:m.start()].count("\n") + 1
            snippet = (lines[line - 1].strip() if 0 < line <= len(lines) else "")[:120]
            findings.append(_f("ioc_patterns", severity, category,
                               why, f"matched: {snippet!r}", line))
    return {"ran": True, "findings": findings}


# ── engine: credential access ──────────────────────────────────────────────────

_CRED_PATHS = [
    (r"\.ssh/(id_[a-z0-9]+|authorized_keys|known_hosts)", "SSH private keys"),
    (r"\.aws/credentials", "AWS credentials"),
    (r"\.docker/config\.json", "Docker registry credentials"),
    (r"\.kube/config", "Kubernetes credentials"),
    (r"\.gnupg", "GPG keyring"),
    (r"(Login Data|Cookies|Web Data|Local State)", "Browser credential store"),
    (r"(wallet\.dat|keystore|MetaMask|Exodus|Electrum)", "Cryptocurrency wallet"),
    (r"(Keychains?|login\.keychain)", "macOS keychain"),
    (r"/etc/(passwd|shadow|sudoers)", "System account files"),
    (r"(NTDS\.dit|SAM|SYSTEM)\b", "Windows credential hives"),
    (r"\.netrc|_netrc", "Stored network logins"),
    (r"(\.env\b|credentials\.json|secrets?\.ya?ml)", "Application secrets"),
    (r"(id_rsa|private_key|\.pem\b|\.pfx\b)", "Private key material"),
    (r"(history|\.bash_history|\.zsh_history)", "Shell history"),
]


def _flatten_paths(source: str) -> str:
    """Rejoin paths that were split across string literals.

    `Path.home() / ".aws" / "credentials"` and `os.path.join(".aws", "credentials")`
    both hide the literal path from a naive regex. Collapsing the separators between
    adjacent string literals puts it back, so one obvious evasion stops working.
    """
    return re.sub(r"""['"]\s*[/+,]\s*['"]""", "/", source)


def _engine_credentials(source: str) -> Dict[str, Any]:
    findings = []
    lines = source.splitlines()
    haystack = source + "\n" + _flatten_paths(source)
    for pattern, what in _CRED_PATHS:
        for m in re.finditer(pattern, haystack):
            line = haystack[:m.start()].count("\n") + 1
            if line > len(lines):          # matched in the flattened copy
                line = line - len(lines) - 1
            snippet = (lines[line - 1].strip() if 0 < line <= len(lines) else "")[:120]
            findings.append(_f("credentials", HIGH, "credential_access",
                               f"References {what}",
                               f"A plugin has no ordinary reason to touch these. "
                               f"matched: {snippet!r}", line))
    return {"ran": True, "findings": findings}


# ── engine: persistence / rootkit indicators ───────────────────────────────────

_PERSIST = [
    (CRITICAL, r"LD_PRELOAD", "Sets LD_PRELOAD — injects code into other processes."),
    (CRITICAL, r"(DYLD_INSERT_LIBRARIES)", "Injects a library into other macOS processes."),
    (CRITICAL, r"(SetWindowsHookEx|CreateRemoteThread|VirtualAllocEx|WriteProcessMemory)",
     "Windows process injection."),
    (CRITICAL, r"(ptrace\s*\(|PTRACE_ATTACH)", "Attaches to another running process."),
    (HIGH, r"(crontab|/etc/cron\.|/var/spool/cron)", "Installs a scheduled job."),
    (HIGH, r"(systemd/system|\.service\b|systemctl\s+enable)", "Installs a systemd service."),
    (HIGH, r"(LaunchAgents|LaunchDaemons|launchctl\s+load)", "Installs a macOS launch agent."),
    (HIGH, r"(CurrentVersion\\\\Run|HKEY_CURRENT_USER.*Run|winreg\.SetValue)",
     "Writes a Windows autostart registry key."),
    (HIGH, r"(\.bashrc|\.bash_profile|\.zshrc|\.profile)\b", "Modifies shell startup files."),
    (HIGH, r"(autostart|Startup\\\\|XDG_CONFIG_HOME.*autostart)", "Adds a desktop autostart entry."),
    (MEDIUM, r"(insmod|modprobe|/dev/kmem|/proc/kcore)", "Touches kernel modules or memory."),
    (HIGH, r"(chattr\s+\+i|attrib\s+\+h|hidden\s*=\s*True)", "Hides or locks files from the user."),
]


def _engine_persistence(source: str) -> Dict[str, Any]:
    findings = []
    lines = source.splitlines()
    for severity, pattern, why in _PERSIST:
        for m in re.finditer(pattern, source, re.IGNORECASE):
            line = source[:m.start()].count("\n") + 1
            snippet = (lines[line - 1].strip() if 0 < line <= len(lines) else "")[:120]
            findings.append(_f("persistence", severity, "persistence", why,
                               f"matched: {snippet!r}", line))
    return {"ran": True, "findings": findings}


# ── engine: anti-analysis ──────────────────────────────────────────────────────

_ANTI = [
    (r"(VMware|VirtualBox|QEMU|Xen|vboxguest|hypervisor)", "Detects virtual machines."),
    (r"(sys\.gettrace|sys\.settrace|__debug__\s*==|IsDebuggerPresent)", "Detects debuggers."),
    (r"(sandbox|cuckoo|wireshark|procmon|ida64|x64dbg)", "Detects analysis tooling."),
    (r"(/proc/self/status[\s\S]{0,80}TracerPid)", "Checks whether it is being traced."),
]


def _engine_anti_analysis(source: str) -> Dict[str, Any]:
    findings = []
    for pattern, why in _ANTI:
        for m in re.finditer(pattern, source, re.IGNORECASE):
            line = source[:m.start()].count("\n") + 1
            findings.append(_f("anti_analysis", HIGH, "evasion", why,
                               "Code that hides from inspection is doing so for a reason.",
                               line))
    return {"ran": True, "findings": findings}


# ── engine: entropy ────────────────────────────────────────────────────────────

def _shannon(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _engine_entropy(source: str) -> Dict[str, Any]:
    findings = []
    for i, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if len(stripped) < 120:
            continue
        e = _shannon(stripped)
        if e > 4.8:
            findings.append(_f("entropy", MEDIUM, "packed",
                               f"High-entropy line ({e:.2f} bits/char, {len(stripped)} chars)",
                               "Consistent with compressed, encrypted or packed data "
                               "embedded in the source.", i))
    if len(findings) > 6:
        findings = findings[:6] + [_f("entropy", HIGH, "packed",
                                      f"{len(findings)} high-entropy lines in total",
                                      "The file appears to be largely packed data rather "
                                      "than readable source.")]
    return {"ran": True, "findings": findings}


# ── engine: dependency risk ────────────────────────────────────────────────────

_POPULAR = {"requests", "numpy", "pandas", "urllib3", "pillow", "cryptography",
            "setuptools", "beautifulsoup4", "flask", "django", "pytest", "scipy",
            "matplotlib", "torch", "transformers", "aiohttp", "pyyaml", "click"}


def _levenshtein(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _engine_dependencies(manifest: Dict[str, Any]) -> Dict[str, Any]:
    findings = []
    for spec in (manifest.get("pip") or []):
        name = re.split(r"[<>=!\[~ ]", str(spec).strip())[0].lower()
        if not name:
            continue
        if name in _POPULAR:
            continue
        for popular in _POPULAR:
            if _levenshtein(name, popular) <= 1:
                findings.append(_f("dependencies", HIGH, "typosquat",
                                   f"Dependency '{name}' is one character from '{popular}'",
                                   "Typosquatted package names are a standard supply-chain "
                                   "attack."))
                break
        if re.search(r"(https?://|git\+|file:)", str(spec)):
            findings.append(_f("dependencies", HIGH, "unpinned_source",
                               f"Dependency '{spec}' installs from a URL",
                               "Bypasses the package index entirely; the content can change "
                               "at any time."))
    if manifest.get("pip"):
        findings.append(_f("dependencies", MEDIUM, "installer_code",
                           f"Installs {len(manifest['pip'])} package(s) from PyPI",
                           "Package installers run their own code in a child process, "
                           "outside anything ELI can gate."))
    return {"ran": True, "findings": findings}


# ── engine: hash blocklist ─────────────────────────────────────────────────────

def blocklist_path() -> Path:
    from eli.core.paths import config_dir
    return Path(config_dir()) / "plugin_blocklist.json"


def _engine_blocklist(raw: bytes) -> Dict[str, Any]:
    p = blocklist_path()
    if not p.is_file():
        return {"ran": False, "error": "no blocklist installed"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        blocked = {str(k).lower(): v for k, v in (data.get("sha256") or {}).items()}
    except Exception as exc:
        return {"ran": False, "error": f"unreadable blocklist: {exc}"}
    import hashlib
    digest = hashlib.sha256(raw).hexdigest()
    if digest in blocked:
        return {"ran": True, "findings": [
            _f("hash_blocklist", CRITICAL, "known_bad",
               "This exact file is on the blocklist",
               str(blocked[digest] or "Previously reported as malicious."))]}
    return {"ran": True, "findings": []}


# ── engine: ClamAV ─────────────────────────────────────────────────────────────

def _engine_clamav(raw: bytes, timeout: float = 60) -> Dict[str, Any]:
    exe = shutil.which("clamdscan") or shutil.which("clamscan")
    if not exe:
        return {"ran": False, "error": "ClamAV is not installed"}
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as fh:
            fh.write(raw)
            tmp = Path(fh.name)
        args = [exe, "--no-summary", str(tmp)]
        if exe.endswith("clamdscan"):
            args.insert(1, "--fdpass")
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 1:
            sig = out.split(":", 1)[-1].replace("FOUND", "").strip() or "unknown signature"
            return {"ran": True, "findings": [
                _f("clamav", CRITICAL, "known_bad",
                   f"ClamAV detected: {sig}", out.strip()[:400])]}
        if proc.returncode not in (0, 1):
            return {"ran": False, "error": f"ClamAV error: {out.strip()[:200]}"}
        return {"ran": True, "findings": []}
    except subprocess.TimeoutExpired:
        return {"ran": False, "error": "ClamAV timed out"}
    except Exception as exc:
        return {"ran": False, "error": f"ClamAV failed: {exc}"}
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except Exception:
                log.debug("[SCAN] could not remove ClamAV temp file", exc_info=True)


# ── engine: YARA ───────────────────────────────────────────────────────────────

def yara_rules_path() -> Path:
    from eli.core.paths import config_dir
    return Path(config_dir()) / "plugin_yara_rules.yar"


def _engine_yara(raw: bytes) -> Dict[str, Any]:
    try:
        import yara  # type: ignore
    except Exception:
        return {"ran": False, "error": "yara-python is not installed"}
    rules_file = yara_rules_path()
    if not rules_file.is_file():
        return {"ran": False, "error": "no YARA ruleset installed"}
    try:
        rules = yara.compile(filepath=str(rules_file))
        matches = rules.match(data=raw)
    except Exception as exc:
        return {"ran": False, "error": f"YARA failed: {exc}"}
    return {"ran": True, "findings": [
        _f("yara", CRITICAL, "known_bad", f"YARA rule matched: {m.rule}",
           f"tags: {', '.join(getattr(m, 'tags', []) or []) or 'none'}")
        for m in matches]}


# ── orchestration ──────────────────────────────────────────────────────────────

def scan(source: Any, manifest: Optional[Dict[str, Any]] = None, *,
         deep: bool = True, timeout: float = 60) -> Dict[str, Any]:
    """Run every available engine and return one verdict.

    `deep` adds the external scanners (ClamAV, YARA) which are slower and optional.
    Coverage is always reported: an engine that could not run is named, and the
    verdict says the scan was partial rather than implying a clean bill of health.
    """
    started = time.time()
    manifest = dict(manifest or {})
    raw = source if isinstance(source, bytes) else str(source).encode("utf-8", "replace")
    text = raw.decode("utf-8", "replace")

    engines: Dict[str, Dict[str, Any]] = {
        "static_ast": _engine_static_ast(text, manifest),
        "obfuscation": _engine_obfuscation(text),
        "ioc_patterns": _engine_ioc(text),
        "credentials": _engine_credentials(text),
        "persistence": _engine_persistence(text),
        "anti_analysis": _engine_anti_analysis(text),
        "entropy": _engine_entropy(text),
        "dependencies": _engine_dependencies(manifest),
        "hash_blocklist": _engine_blocklist(raw),
    }
    if deep:
        engines["clamav"] = _engine_clamav(raw, timeout=timeout)
        engines["yara"] = _engine_yara(raw)

    findings: List[Dict[str, Any]] = []
    for res in engines.values():
        findings.extend(res.get("findings") or [])

    # Score. Capped per category so twenty matches of one pattern cannot outweigh
    # three different kinds of evidence — breadth is the stronger signal.
    by_category: Dict[str, int] = {}
    for f in findings:
        by_category[f["category"]] = max(by_category.get(f["category"], 0),
                                         _WEIGHT.get(f["severity"], 0))
    score = min(100, sum(by_category.values()))

    critical = [f for f in findings if f["severity"] == CRITICAL]
    high = [f for f in findings if f["severity"] == HIGH]

    if critical:
        verdict = MALICIOUS
    elif score >= 45 or len(high) >= 3:
        verdict = MALICIOUS
    elif score >= 15 or high:
        verdict = SUSPICIOUS
    else:
        verdict = CLEAN

    unavailable = sorted(k for k, v in engines.items() if not v.get("ran"))
    ran = sorted(k for k, v in engines.items() if v.get("ran"))

    order = {CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3, INFO: 4}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["engine"]))

    if verdict == MALICIOUS:
        summary = (f"Malicious indicators found — {len(critical)} critical, "
                   f"{len(high)} high. Do not install.")
    elif verdict == SUSPICIOUS:
        summary = (f"Suspicious: {len(findings)} finding(s) worth reading before you "
                   f"install this.")
    else:
        summary = "No malicious indicators found."
    if unavailable:
        summary += (f" Coverage was partial — {', '.join(unavailable)} could not run, "
                    f"so this is not a clean bill of health.")

    return {
        "verdict": verdict,
        "score": score,
        "summary": summary,
        "findings": findings,
        "engines": {k: {"ran": bool(v.get("ran")), "error": v.get("error"),
                        "findings": len(v.get("findings") or [])}
                    for k, v in engines.items()},
        "engines_ran": ran,
        "engines_unavailable": unavailable,
        "complete": not unavailable,
        "duration_s": round(time.time() - started, 3),
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def scan_file(path: Any, manifest: Optional[Dict[str, Any]] = None, **kw) -> Dict[str, Any]:
    p = Path(str(path))
    try:
        raw = p.read_bytes()
    except Exception as exc:
        return {"verdict": MALICIOUS, "score": 100, "summary": f"Could not read {p}: {exc}",
                "findings": [], "engines": {}, "complete": False}
    if manifest is None:
        mf = p.parent / "eli_plugin.json"
        if mf.is_file():
            try:
                manifest = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
    return scan(raw, manifest, **kw)


__all__ = ["scan", "scan_file", "CLEAN", "SUSPICIOUS", "MALICIOUS",
           "blocklist_path", "yara_rules_path"]
