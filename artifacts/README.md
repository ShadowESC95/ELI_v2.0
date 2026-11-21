# Runtime data (not in git)

Created automatically on first launch, and by the installers: `install.sh` in a source
checkout, `./INSTALL_ELI.sh` / `./RUN_ELI.sh` in the Linux portable package.

Fresh clones also get **schema-only DB templates** from `config/templates/db/` (copied
by `install.sh` when `artifacts/db/` is empty). `python -m eli.core.init_data` then
ensures every table exists — no personal memories are written.

```
artifacts/
  db/              SQLite stores (user, agent, system_index, coding_memory, …)
  vectors/         memory search index
  runtime/         snapshots, world model
  conversations/   chat logs
  notebook/        notes ELI writes for you (ELI_NOTEBOOK_DIR overrides)
  world/           ELI's world state
  logs/
```

Portable package: lives inside the extracted folder.

Installed / frozen copy (AppImage, Setup.exe, .dmg): `~/.local/share/ELI_v2/artifacts/` on
Linux (under `$XDG_DATA_HOME` when set), `%LOCALAPPDATA%\ELI_v2\artifacts` on Windows,
`~/Library/Application Support/ELI_v2/artifacts` on macOS; settings live beside it in
`ELI_v2/config/`. A pip-installed copy that is not a source checkout uses the same folders.

Source dev checkout: `<project_root>/artifacts/` when launched from the repo tree.

`ELI_DATA_DIR` overrides the location in every case.

Factory reset (GUI Advanced → Clear Memory, or `python tools/clear_memory.py`) backs up
first, then wipes all learned state, resets `persona.auto.txt`, clears identity from
settings, and rebuilds the full DB architecture via `init_all_data`.
