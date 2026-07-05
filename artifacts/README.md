# Runtime data (not in git)

Created automatically on `INSTALL_ELI.sh`, `./RUN_ELI.sh`, or first `eli` launch.

```
artifacts/
  db/              SQLite stores (user, agent, …)
  vectors/         memory search index
  runtime/         snapshots, world model
  conversations/   chat logs
  logs/
```

Portable package: lives inside the extracted folder. Installed copy: `~/.local/share/eli/`.
