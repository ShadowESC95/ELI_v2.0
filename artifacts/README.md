# Runtime data (not in git)

Created automatically on `INSTALL_ELI.sh`, `./RUN_ELI.sh`, or first `eli` launch.

Fresh clones also get **schema-only DB templates** from `config/templates/db/` (copied
by `install.sh` when `artifacts/db/` is empty). `python -m eli.core.init_data` then
ensures every table exists — no personal memories are written.

```
artifacts/
  db/              SQLite stores (user, agent, system_index, coding_memory, …)
  vectors/         memory search index
  runtime/         snapshots, world model
  conversations/   chat logs
  logs/
```

Portable package: lives inside the extracted folder.

Installed / frozen copy (AppImage, Setup.exe, .dmg): `~/.local/share/ELI_v2/` on Linux,
`%LOCALAPPDATA%\\ELI_v2` on Windows, `~/Library/Application Support/ELI_v2` on macOS.

Source dev checkout: `<project_root>/artifacts/` when launched from the repo tree.

Factory reset (GUI Advanced → Clear Memory, or `python tools/clear_memory.py`) wipes
all learned state, resets `persona.auto.txt`, clears identity from settings, and
rebuilds the full DB architecture via `init_all_data`.
