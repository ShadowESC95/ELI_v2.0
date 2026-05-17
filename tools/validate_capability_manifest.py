#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from collections import Counter, defaultdict


MANIFEST_PATH = Path("capability_manifest.json")


# Deliberately internal executor/admin/diagnostic actions.
# These may be dispatch-backed but not user-routable.
INTENTIONAL_INTERNAL_ACTIONS = {
    "ANALYZE_PDF_FOLDER",
    "CANCEL_PENDING_REMEDIATION",
    "CHECK_TARGET_STATUS",
    "CONFIRM_PENDING_REMEDIATION",
    "EXPLAIN_LAST_FAILURE",
    "LISTEN_FOR_COMMAND",
    "PLUGIN_STATUS",
    "PREPARE_REMEDIATION",
    "SET_USER_NAME",
    "SKIP_YOUTUBE_AD",
    "STT_DIAGNOSTICS",
    "USER_INFO_REPORT",
    "VOICE_DIAGNOSTICS",
}


def main() -> int:
    if not MANIFEST_PATH.exists():
        print("FAIL: capability_manifest.json not found")
        return 1

    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    caps = data.get("capabilities", [])

    failures = []
    warnings = []
    info = []

    by_action = defaultdict(list)

    for cap in caps:
        action = str(cap.get("action") or "").upper()
        by_action[action].append(cap)

        active = bool(cap.get("active"))
        routable = bool(cap.get("routable"))
        in_dispatch = bool(cap.get("in_dispatch"))
        in_supported = bool(cap.get("in_supported_list"))
        source = cap.get("source")
        plugin = cap.get("plugin")

        if active and routable and not in_dispatch:
            failures.append(
                f"{action}: routable=true but in_dispatch=false. Router can select it, but executor cannot handle it."
            )

        if active and routable and not in_supported:
            warnings.append(
                f"{action}: routable=true but in_supported_list=false. It works internally but may be hidden from help/capability output."
            )

        if active and in_supported and not routable and plugin is not None:
            warnings.append(
                f"{action}: plugin capability is supported/dispatchable but not router-routable. Natural language may not trigger it."
            )

        if active and source == "executor" and not routable and not in_supported:
            if action in INTENTIONAL_INTERNAL_ACTIONS:
                info.append(
                    f"{action}: intentional internal executor/admin/diagnostic action."
                )
            else:
                warnings.append(
                    f"{action}: executor-only action is neither routable nor supported. Classify as internal or expose it properly."
                )

    for action, entries in by_action.items():
        if len(entries) > 1:
            warnings.append(f"{action}: duplicate manifest entries: {len(entries)}")

    print("=== Capability Manifest Validation ===")
    print(f"generated_at: {data.get('generated_at')}")
    print(f"declared_total: {data.get('total')}")
    print(f"actual_entries: {len(caps)}")

    print()
    print("=== Summary ===")
    print(f"failures: {len(failures)}")
    print(f"warnings: {len(warnings)}")
    print(f"info: {len(info)}")

    if failures:
        print()
        print("=== FAILURES ===")
        for item in failures:
            print(f"FAIL: {item}")

    if warnings:
        print()
        print("=== WARNINGS ===")
        for item in warnings:
            print(f"WARN: {item}")

    if info:
        print()
        print("=== INFO ===")
        for item in info:
            print(f"INFO: {item}")

    print()
    print("=== Counts by source ===")
    for source, count in Counter(c.get("source") for c in caps).most_common():
        print(f"{source}: {count}")

    print()
    print("=== Counts by plugin ===")
    for plugin, count in Counter(c.get("plugin") or "core" for c in caps).most_common():
        print(f"{plugin}: {count}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
