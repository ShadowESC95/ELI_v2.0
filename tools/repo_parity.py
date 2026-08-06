#!/usr/bin/env python3
"""Report state divergence between the v2 and v3 trees.

The two repos have different root commits — no shared ancestry — so git cannot
compare them. Fixes cross over by hand, and a missed port raises no error: the
construct is simply absent, and with one maintainer nobody notices.

That is not hypothetical. v2 added ``NO INVENTED SELF-MECHANISM`` on 2026-07-17;
``NO FALSE SELF-DENIAL`` followed on 2026-07-29 describing itself as "the mirror
of the rule above". The v3 port carried the mirror but not the mirrored rule —
it was scoped to the newer commit — so for eight days v3 shipped a prompt citing
a rule that was not there, and had no defence against ELI inventing internal
mechanisms about itself. The port applied its diff faithfully. **Diff-parity is
not state-parity**, and only the second one matters.

This compares the *resulting state* of named constructs in both trees and prints
what exists on one side only.

    python tools/repo_parity.py                    # auto-locates the v3 checkout
    python tools/repo_parity.py --v3 /path/to/v3
    python tools/repo_parity.py --json             # machine-readable

Divergence is often deliberate — new features default to v3. Record those in
``tools/repo_parity_allow.txt`` (one ``family:name`` per line) so the report
stays signal. Exit code is 1 only for unexplained asymmetry.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

V2 = Path(__file__).resolve().parent.parent
ALLOW_FILE = V2 / "tools" / "repo_parity_allow.txt"

_V3_CANDIDATES = [
    os.environ.get("ELI_V3_ROOT", ""),
    "~/Desktop/ELI_v3.0",
    "~/ELI_v3.0",
    "../ELI_v3.0",
]


def find_v3(explicit: str = "") -> Path | None:
    for cand in ([explicit] if explicit else []) + _V3_CANDIDATES:
        if not cand:
            continue
        p = Path(cand).expanduser()
        if (p / "eli").is_dir() and (p / "pyproject.toml").is_file():
            return p.resolve()
    return None


# ── construct families ───────────────────────────────────────────────────────
# Each returns the set of named things present in a tree. Quote-agnostic on
# purpose: v2 writes these bullets as "..." literals, v3's generated module uses
# repr(), so matching on quoting silently under-reports.

_GUARD = re.compile(r"- ([A-Z][A-Z ,/&'-]{3,45}):")
# Prose that happens to be shouty, not a named guard.
_GUARD_NOISE = {"CRITICAL", "IMPORTANT", "NOTE", "WARNING"}


def guards(root: Path) -> Set[str]:
    """Named rule bullets in whichever module carries the prompt rule block."""
    found: Set[str] = set()
    for rel in ("eli/kernel/engine.py",
                "eli/kernel/stages/prompt_rules.py",
                "eli/kernel/stages/prompt_assembly.py"):
        f = root / rel
        if not f.is_file():
            continue
        for name in _GUARD.findall(f.read_text(encoding="utf-8", errors="replace")):
            name = name.strip()
            if name not in _GUARD_NOISE:
                found.add(name)
    return found


def actions(root: Path) -> Set[str]:
    """Capability/action names from the generated manifest."""
    f = root / "capability_manifest.json"
    if not f.is_file():
        return set()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return set()
    return {c.get("action", "") for c in data.get("capabilities", []) if c.get("action")}


def modules(root: Path) -> Set[str]:
    """Module basenames under eli/ — catches a whole file that never crossed."""
    out: Set[str] = set()
    base = root / "eli"
    if not base.is_dir():
        return out
    for p in base.rglob("*.py"):
        if "__pycache__" in p.parts or p.name == "__init__.py":
            continue
        out.add(p.name)
    return out


def env_flags(root: Path) -> Set[str]:
    """ELI_* environment knobs actually read by the code."""
    out: Set[str] = set()
    pat = re.compile(r"""["'](ELI_[A-Z0-9_]{2,})["']""")
    for sub in ("eli", "api"):
        base = root / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out |= set(pat.findall(p.read_text(encoding="utf-8", errors="replace")))
    return out


FAMILIES = {
    "guard": guards,
    "action": actions,
    "module": modules,
    "env": env_flags,
}

# Families where one-sided presence is usually deliberate rather than a miss.
# Reported, but not treated as failure unless --strict.
_SOFT = {"module", "env", "action"}


def load_allow() -> Set[str]:
    if not ALLOW_FILE.is_file():
        return set()
    out = set()
    for line in ALLOW_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def compare(v2: Path, v3: Path) -> Dict[str, Tuple[List[str], List[str]]]:
    result = {}
    for family, fn in FAMILIES.items():
        a, b = fn(v2), fn(v3)
        result[family] = (sorted(a - b), sorted(b - a))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v3", default="", help="path to the v3 checkout")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--strict", action="store_true",
                    help="fail on soft families (module/env/action) too")
    args = ap.parse_args()

    v3 = find_v3(args.v3)
    if v3 is None:
        print("v3 checkout not found — set ELI_V3_ROOT or pass --v3. "
              "Nothing to compare; this is not a failure.", file=sys.stderr)
        return 0

    allow = load_allow()
    report = compare(V2, v3)

    if args.json:
        print(json.dumps({f: {"v2_only": a, "v3_only": b}
                          for f, (a, b) in report.items()}, indent=2))
        return 0

    print(f"v2: {V2}\nv3: {v3}\n")
    hard_findings = 0
    for family, (v2_only, v3_only) in report.items():
        v2_only = [x for x in v2_only if f"{family}:{x}" not in allow]
        v3_only = [x for x in v3_only if f"{family}:{x}" not in allow]
        if not v2_only and not v3_only:
            print(f"[ok]   {family}: in parity")
            continue
        tag = "warn" if family in _SOFT and not args.strict else "DRIFT"
        if tag == "DRIFT":
            hard_findings += len(v2_only) + len(v3_only)
        print(f"[{tag}] {family}: {len(v2_only)} v2-only, {len(v3_only)} v3-only")
        for x in v2_only[:20]:
            print(f"         v2 only → {x}")
        if len(v2_only) > 20:
            print(f"         … +{len(v2_only)-20} more")
        for x in v3_only[:20]:
            print(f"         v3 only → {x}")
        if len(v3_only) > 20:
            print(f"         … +{len(v3_only)-20} more")

    if hard_findings:
        print(f"\n{hard_findings} unexplained divergence(s). Port it, or record the "
              f"intentional ones in {ALLOW_FILE.relative_to(V2)}.")
        return 1
    print("\nno unexplained divergence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
