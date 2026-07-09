"""Generate the Windows version resource (build/version.rc) from pyproject.toml.

Keeps requirement "version numbers are read from the project, never hardcoded":
the only version source is pyproject.toml [project].version. ELI.spec imports
generate() directly; the CLI form exists for manual/CI use:

    python packaging/pyinstaller/gen_version_info.py [--out build/version.rc]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import tomllib  # py311+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "packaging" / "windows" / "version.rc.in"


def project_version(root: Path = ROOT) -> str:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise SystemExit(f"[gen_version_info] pyproject.toml not found at {pyproject}")
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+([.\-+].*)?", version):
        raise SystemExit(f"[gen_version_info] unexpected version format: {version!r}")
    return version


def generate(out: Path | None = None) -> Path:
    version = project_version()
    major, minor, patch = (int(p) for p in version.split(".")[:3])
    if not TEMPLATE.is_file():
        raise SystemExit(f"[gen_version_info] template missing: {TEMPLATE}")
    text = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("@MAJOR@", str(major))
        .replace("@MINOR@", str(minor))
        .replace("@PATCH@", str(patch))
        .replace("@VERSION@", version)
    )
    # Drop the leading '#' comment lines — PyInstaller eval()s this file.
    body = "\n".join(l for l in text.splitlines() if not l.startswith("#")) + "\n"
    out = out or (ROOT / "build" / "version.rc")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")
    print(f"[gen_version_info] wrote {out} (version {version})")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    try:
        generate(args.out)
    except KeyError as exc:
        sys.exit(f"[gen_version_info] pyproject.toml missing key: {exc}")
