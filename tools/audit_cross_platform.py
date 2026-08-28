#!/usr/bin/env python3
"""Scan ELI source for unguarded Linux-only paths/subprocess patterns.

Exit 0 when clean, 1 when potential cross-platform regressions are found.
Used in CI smoke and locally before release.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (ROOT / "eli", ROOT / "api")
SKIP_PARTS = {"/tests/", "/test_", ".pyc", "audit_cross_platform.py"}

PATTERNS = (
    (re.compile(r'"/usr/share/sounds/'), "hardcoded Linux sound path — use bundled_asset_path/play_alarm_sound"),
    (re.compile(r'play_sound\(\s*"/'), "hardcoded absolute play_sound path"),
    (re.compile(r'"/usr/share/applications"(?!,)'), "hardcoded desktop path outside portable_app_control"),
    (re.compile(r'subprocess\.(run|Popen|call)\(\[\s*"wmctrl"'), "direct wmctrl call — prefer portable_app_control"),
    (re.compile(r'subprocess\.(run|Popen|call)\(\[\s*"xdotool"'), "direct xdotool call — gate with LINUX or use portable_app_control"),
    (re.compile(r'subprocess\.(run|Popen|call)\(\[\s*"pactl"'), "direct pactl call — prefer platform_compat"),
)

ALLOWLIST = (
    "eli/system/portable_app_control.py",
    "eli/integrations/mpris/playerctl_backend.py",
    "eli/perception/os_controller.py",
    "eli/perception/audio_stt.py",
    "eli/utils/platform_compat.py",
    "eli/memory/system_index.py",
    "eli/plugins/security_scan.py",
    "eli/runtime/grounded_remediation.py",
    "eli/cognition/persona_updater.py",
    "eli/cognition/output_governor.py",
)


def _allowed(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(rel.endswith(a) or rel == a for a in ALLOWLIST)


def scan_file(path: Path) -> list[str]:
    if _allowed(path):
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[str] = []
    rel = path.relative_to(ROOT).as_posix()
    for idx, line in enumerate(text.splitlines(), 1):
        if "LINUX" in line or "platform_compat" in line:
            continue
        for pattern, reason in PATTERNS:
            if pattern.search(line):
                hits.append(f"{rel}:{idx}: {reason}")
                break
    return hits


def main() -> int:
    findings: list[str] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            s = str(path)
            if any(part in s for part in SKIP_PARTS):
                continue
            findings.extend(scan_file(path))
    if findings:
        print("Cross-platform audit findings:")
        for item in findings:
            print(f"  - {item}")
        return 1
    print("Cross-platform audit: no unguarded Linux-only patterns found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
