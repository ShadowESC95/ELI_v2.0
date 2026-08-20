#!/usr/bin/env python3
"""Evaluate a quarantined marketplace submission and print a verdict.

ELI's marketplace is curated: nothing is listed until the maintainer approves and
signs it. This is the step in between — it runs, on the submission, every check a
user's machine would run on the download, and reports what it found.

Deliberately, it does NOT approve anything. It sorts submissions into "this can be
rejected without a human reading it" and "a human now has to read this", because
those are the two useful outcomes. Auto-approval is the one outcome that would
defeat the point: if a scanner could decide, the review would not be worth doing,
and the signature would attest to nothing but the scanner's opinion.

Two properties worth stating, since both are easy to assume the other way:

  * **An unavailable engine is never a pass.** If ClamAV or YARA is not installed,
    that is reported as reduced coverage, not as a clean result. A review run on a
    machine missing scanners is a weaker review and says so.
  * **Findings are advisory, absence of findings is not a clearance.** A plugin
    with no findings is one no scanner objected to. That is worth knowing and is
    not the same as safe.

Usage
-----
    review.py SUBMISSION_DIR [--json] [--strict]

SUBMISSION_DIR holds the plugin source and its eli_plugin.json — the layout a
pull request to the registry repo produces.

Exit codes (for CI):
    0  no blocking findings — ready for a human to read
    1  rejected: malicious, or the manifest does not match the code
    2  could not evaluate (bad submission layout, unreadable files)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

VERDICT_REJECT = "REJECT"
VERDICT_HUMAN = "NEEDS_HUMAN_REVIEW"


def _find_submission(d: Path):
    """Locate the manifest and the single plugin source in a submission dir."""
    manifest = d / "eli_plugin.json"
    if not manifest.is_file():
        found = sorted(d.glob("**/eli_plugin.json"))
        if not found:
            return None, None, "No eli_plugin.json found in the submission."
        manifest = found[0]
    d = manifest.parent
    sources = [p for p in sorted(d.glob("*.py")) if p.name != "__init__.py"]
    if not sources:
        return None, None, f"No .py source beside {manifest.name}."
    if len(sources) > 1:
        names = ", ".join(p.name for p in sources)
        return None, None, (
            f"Expected one plugin source, found {len(sources)} ({names}). A submission "
            f"is one plugin; split it or declare a package.")
    return manifest, sources[0], ""


def review(directory: str) -> dict:
    from eli.plugins import integrity, security_scan
    from eli.plugins.manifest import validate_manifest, verify_against_source
    from eli.plugins.permissions import describe, risk_of

    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        return {"ok": False, "verdict": VERDICT_REJECT, "stage": "layout",
                "problems": [f"{d} is not a directory."], "warnings": []}

    manifest_path, source_path, err = _find_submission(d)
    if err:
        return {"ok": False, "verdict": VERDICT_REJECT, "stage": "layout",
                "problems": [err], "warnings": []}

    try:
        listing = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "verdict": VERDICT_REJECT, "stage": "manifest",
                "problems": [f"{manifest_path.name} is not valid JSON: {exc}"],
                "warnings": []}

    raw = source_path.read_bytes()
    try:
        source = raw.decode("utf-8")
    except Exception:
        return {"ok": False, "verdict": VERDICT_REJECT, "stage": "source",
                "problems": ["The plugin source is not valid UTF-8 text."], "warnings": []}

    out = {
        "plugin": listing.get("id") or source_path.stem,
        "name": listing.get("name") or "",
        "version": listing.get("version") or "",
        "author": listing.get("author") or "",
        "source_file": str(source_path.relative_to(d)) if source_path.is_relative_to(d)
                       else str(source_path),
        "sha256": integrity.sha256_of(raw),
        "problems": [], "warnings": [], "notes": [],
    }

    check = validate_manifest(listing)
    out["problems"].extend(check["problems"])
    out["warnings"].extend(check["warnings"])
    if not check["ok"]:
        out.update(ok=False, verdict=VERDICT_REJECT, stage="manifest")
        return out
    m = check["manifest"]

    declared = list(m.get("permissions") or [])
    out["permissions"] = declared
    out["risk"] = risk_of(declared)
    out["permission_detail"] = [describe(c) for c in declared]

    # The check that matters most: does the CODE stay inside what the manifest
    # declares? An undeclared capability is a refusal, not a note — the consent
    # dialog a user sees is generated from the manifest, so code that reaches
    # past it is asking for something the user was never shown.
    code = verify_against_source(m, source)
    if code.get("undeclared"):
        out["problems"].append(
            "Uses capabilities its manifest does not declare: "
            + ", ".join(code["undeclared"])
            + ". The consent dialog is built from the manifest, so this would ask "
              "the user for less than the code actually takes.")
    if code.get("over_declared"):
        out["warnings"].append(
            "Declares permissions the code does not appear to use: "
            + ", ".join(code["over_declared"])
            + ". Not evidence of bad intent, but a plugin should ask for the least "
              "it needs — worth querying with the author.")
    out["code_check"] = code

    scan = security_scan.scan(raw, m, deep=True)
    out["scan"] = {
        "verdict": scan["verdict"],
        "summary": scan["summary"],
        "engines_run": scan.get("engines_run") or [],
        "engines_unavailable": scan.get("engines_unavailable") or [],
        "findings": scan.get("findings") or [],
    }
    unavailable = out["scan"]["engines_unavailable"]
    if unavailable:
        out["notes"].append(
            "Reduced coverage — these engines were unavailable on this machine: "
            + ", ".join(unavailable)
            + ". An engine that did not run is not a pass; install them, or treat "
              "this review as weaker than a user's own scan.")

    if scan["verdict"] == security_scan.MALICIOUS:
        out["problems"].append(scan["summary"])
        out.update(ok=False, verdict=VERDICT_REJECT, stage="malware")
        return out
    for f in out["scan"]["findings"]:
        out["warnings"].append(f"[{f.get('severity')}] {f.get('title')} — {f.get('detail')}")

    if out["problems"]:
        out.update(ok=False, verdict=VERDICT_REJECT, stage="code")
        return out

    out.update(ok=True, verdict=VERDICT_HUMAN, stage="review")
    out["notes"].append(
        "No blocking findings. This is NOT an approval: nothing here establishes "
        "what the plugin is for, whether the author is who they say, or whether "
        "the permissions it asks for are reasonable for what it claims to do. "
        "Read it, then sign it with tools/marketplace/publish.py --sign-key.")
    return out


def _render(r: dict) -> str:
    L = []
    head = f"{r.get('name') or r.get('plugin')} {r.get('version') or ''}".strip()
    L.append(f"=== {head} ===")
    if r.get("author"):
        L.append(f"author:  {r['author']}")
    if r.get("sha256"):
        L.append(f"sha256:  {r['sha256']}")
    if r.get("permissions") is not None:
        L.append(f"asks for: {', '.join(r['permissions']) or 'nothing'}  "
                 f"(risk: {r.get('risk', '?')})")
    L.append("")
    L.append(f"VERDICT: {r['verdict']}")
    for label, key in (("BLOCKING", "problems"), ("REVIEW", "warnings"), ("NOTE", "notes")):
        for item in r.get(key) or []:
            L.append(f"  [{label}] {item}")
    scan = r.get("scan") or {}
    if scan.get("engines_run"):
        L.append(f"\nengines run: {', '.join(scan['engines_run'])}")
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("submission", help="directory holding the plugin and its manifest")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true",
                    help="also fail when there are non-blocking review findings")
    a = ap.parse_args(argv)

    try:
        r = review(a.submission)
    except Exception as exc:
        print(f"could not evaluate the submission: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(r, indent=2) if a.json else _render(r))
    if r.get("stage") == "layout":
        return 2
    if not r.get("ok"):
        return 1
    if a.strict and r.get("warnings"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
