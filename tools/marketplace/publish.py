#!/usr/bin/env python3
"""Generate a marketplace listing for a plugin — correct by construction.

A registry index is static JSON, so the hard part of publishing is not hosting it,
it is getting the listing *right*. Two fields decide how ELI treats a plugin, and
both are easy to get wrong by hand:

  * **sha256** — a listing without one blocks the one-click install (ELI cannot say
    the file is the one described), and a stale one is a hard refusal on every
    machine that tries. It must be regenerated on every change to the source.
  * **permissions** — undeclared capability use is a refusal, not a warning, so a
    manifest that under-declares produces a plugin nobody can install.

This tool computes the hash, validates the manifest, runs the same scanners the
client will run, and prints the entry to paste into `index.json`. It refuses to
emit a listing for something that would be rejected on the other end — better a
publisher finds out here than every user finds out separately.

Usage:
    python tools/marketplace/publish.py plugin.py \\
        --manifest eli_plugin.json \\
        --source-url https://acme.github.io/eli-registry/plugins/thing.py
    python tools/marketplace/publish.py plugin.py --sign-key ed25519.key --publisher acme
    python tools/marketplace/publish.py --new-key ed25519.key
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _new_key(path: Path) -> int:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except Exception:
        print("Signing needs the 'cryptography' package: pip install cryptography",
              file=sys.stderr)
        return 1
    key = Ed25519PrivateKey.generate()
    path.write_bytes(key.private_bytes_raw())
    try:
        path.chmod(0o600)
    except Exception:
        pass
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    print(f"Private key written to {path} (keep it secret, keep it backed up).\n")
    print("Publish this public key so operators can trust you:\n")
    print(f"  publisher_id: <your-id>")
    print(f"  public_key:   {pub}\n")
    print("An operator adds it once, then every plugin you sign verifies for them.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plugin", nargs="?", help="the plugin.py to publish")
    ap.add_argument("--manifest", help="eli_plugin.json (defaults to one beside the plugin)")
    ap.add_argument("--source-url", help="where the plugin.py will be served from (https)")
    ap.add_argument("--sign-key", help="ed25519 private key file to sign with")
    ap.add_argument("--publisher", help="publisher id the signature is attributed to")
    ap.add_argument("--new-key", help="generate a signing key at this path and exit")
    ap.add_argument("--allow-findings", action="store_true",
                    help="emit the listing even if the scan is not clean (it will still "
                         "stop every operator's one-click install)")
    args = ap.parse_args(argv)

    if args.new_key:
        return _new_key(Path(args.new_key))
    if not args.plugin:
        ap.error("a plugin file is required (or use --new-key)")

    plugin_path = Path(args.plugin)
    if not plugin_path.is_file():
        print(f"No such file: {plugin_path}", file=sys.stderr)
        return 1
    raw = plugin_path.read_bytes()

    manifest_path = Path(args.manifest) if args.manifest else plugin_path.with_name(
        "eli_plugin.json")
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path}. Every listing needs one — it is what "
              f"declares the permissions.", file=sys.stderr)
        return 1

    from eli.plugins.integrity import sha256_of
    from eli.plugins.manifest import validate_manifest, verify_against_source
    from eli.plugins.security_scan import scan

    check = validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    if not check["ok"]:
        print("Manifest problems:", file=sys.stderr)
        for problem in check["problems"]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    manifest = check["manifest"]
    for warning in check["warnings"]:
        print(f"warning: {warning}", file=sys.stderr)

    source = raw.decode("utf-8", "replace")
    code = verify_against_source(manifest, source)
    if not code["ok"]:
        print("This plugin would be refused by every client:", file=sys.stderr)
        for problem in code["problems"]:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    if code["over_declared"]:
        print("note: declares permissions the code does not appear to use: "
              + ", ".join(code["over_declared"])
              + " — ask for the least you need.", file=sys.stderr)

    report = scan(raw, manifest, deep=True)
    if report["verdict"] != "clean" and not args.allow_findings:
        print(f"Scan verdict: {report['verdict']} — refusing to publish.", file=sys.stderr)
        for finding in report["findings"][:10]:
            line = f" (line {finding['line']})" if finding.get("line") else ""
            print(f"  [{finding['severity']}] {finding['title']}{line}", file=sys.stderr)
        print("\nFix these, or pass --allow-findings if you are certain "
              "(it will still stop one-click installs).", file=sys.stderr)
        return 1
    if not report["complete"]:
        print("note: your scan coverage was partial ("
              + ", ".join(report["engines_unavailable"])
              + "). Installing ClamAV and a YARA ruleset gives publishers the same "
                "view their users get.", file=sys.stderr)

    listing = {
        "id": manifest["id"],
        "name": manifest["name"],
        "version": manifest["version"],
        "description": manifest["description"],
        "author": manifest["author"],
        "license": manifest["license"],
        "permissions": manifest.get("permissions") or [],
        "pip": manifest.get("pip") or [],
        "sha256": sha256_of(raw),
        "source": args.source_url or manifest.get("source") or "https://REPLACE-ME",
        "price": manifest.get("price", 0),
    }
    for optional in ("homepage", "purchase_url", "currency", "kind", "mcp"):
        if manifest.get(optional):
            listing[optional] = manifest[optional]

    if args.sign_key:
        if not args.publisher:
            print("--sign-key needs --publisher (the id operators will trust).",
                  file=sys.stderr)
            return 1
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            key = Ed25519PrivateKey.from_private_bytes(Path(args.sign_key).read_bytes())
        except Exception as exc:
            print(f"Could not load the signing key: {exc}", file=sys.stderr)
            return 1
        listing["publisher_id"] = args.publisher
        listing["signature"] = base64.b64encode(key.sign(raw)).decode()

    if not str(listing["source"]).startswith("https://"):
        print("warning: the source URL is not https. Plain http stops the one-click "
              "install on every machine, because the download can be altered in "
              "transit.", file=sys.stderr)

    print(json.dumps(listing, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
