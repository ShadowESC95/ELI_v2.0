#!/usr/bin/env python3
"""ELI memory / identity factory-reset — CLI.

Thin wrapper over eli.core.memory_reset (the reusable core, also used by the GUI
Advanced settings page). Clears every store ELI keeps learned state + user
identity in, while preserving all DB schema and install config. Backs up first.

Stores cleared (see eli/core/memory_reset.py for the authoritative list):
  artifacts/db/*.sqlite3 · vectors/index.faiss · runtime/users/**/user_profile
  · config/settings.json identity fields · runtime/world_model.json · state.json
  · conversations/*.json · persona.auto.txt · runtime residue caches
  Then rebuilds full DB architecture (init_all_data).

Usage:
  python tools/clear_memory.py                 # show plan, confirm, back up, wipe
  python tools/clear_memory.py --yes           # no confirmation prompt
  python tools/clear_memory.py --dry-run       # show the plan, change nothing
  python tools/clear_memory.py --keep-conversations
  python tools/clear_memory.py --keep-profile  # wipe memory but keep your name/profile
  python tools/clear_memory.py --no-backup     # skip backup (not recommended)

Run with ELI NOT running (VACUUM/space-reclaim is skipped under a DB lock).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eli.core import memory_reset as R  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ELI memory / identity factory-reset")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    ap.add_argument("--keep-conversations", action="store_true")
    ap.add_argument("--keep-profile", action="store_true",
                    help="keep the learned name/profile (wipe only memory)")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    base, config = R.bases()
    t = R.discover(base, config, args.keep_conversations, args.keep_profile)

    print(f"\n  ELI memory reset   (data: {base})")
    print("  " + "─" * 56)
    labels = {
        "dbs": "DBs (rows wiped, schema kept)",
        "faiss": "FAISS index files",
        "profile": "profile files",
        "name_caches": "name-cache files (name fields blanked)",
        "runtime_wipe": "runtime caches (world model, traces, …)",
        "settings": "settings.json identity fields",
        "conversations": "conversation logs",
        "persona_overlay": "persona.auto.txt overlay",
    }
    for k, lbl in labels.items():
        print(f"    {len(t.get(k, [])):>4}  {lbl}")
    if args.keep_profile:
        print("    (--keep-profile: name/profile/settings name retained)")
    if args.keep_conversations:
        print("    (--keep-conversations: transcripts retained)")

    if args.dry_run:
        print("\n  DRY RUN — nothing changed.\n")
        return 0

    if not args.yes:
        try:
            resp = input("\n  This is destructive (backed up first). Type 'wipe' to proceed: ")
        except EOFError:
            resp = ""
        if resp.strip().lower() != "wipe":
            print("  aborted.\n")
            return 1

    s = R.run_reset(keep_profile=args.keep_profile,
                    keep_conversations=args.keep_conversations,
                    do_backup=not args.no_backup)
    print("  " + "─" * 56)
    print(f"  ✓ wiped {s['db_rows']} DB rows · reset {s['faiss_reset']} FAISS file(s) · "
          f"removed {s['profiles_removed']} profile file(s)")
    print(f"  ✓ blanked {s['name_fields_blanked']} name field(s) · "
          f"settings identity {'cleared' if s.get('settings_identity_cleared') else 'unchanged'} · "
          f"deleted {s['conversations_removed']} conversation log(s)")
    if s.get("persona_overlay_reset"):
        print("  ✓ persona.auto.txt reset to blank template")
    rb = s.get("rebuild") or {}
    if rb.get("init_steps"):
        print(f"  ✓ rebuilt DB architecture ({rb['init_steps']} init steps)")
    if s.get("backup"):
        print(f"  restore from: {s['backup']}")
    if s.get("errors"):
        print(f"  ! errors: {s['errors']}")
    print("  Schemas intact. Restart ELI for a clean slate (will ask your name).\n")
    return 0 if s.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
