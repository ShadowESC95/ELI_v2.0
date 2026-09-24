# Using ELI from other apps (ELI as an MCP server)

ELI can run as an MCP server, so an editor or desktop assistant that speaks the
protocol can call ELI's actions (search notes, read the time, query memory, and so on).
Everything runs locally over stdin/stdout; nothing is opened on the network.

## Connect an app

1. Open **Marketplace, MCP servers** and copy the config shown under
   "Use ELI from other apps". Or print it: `eli --mcp-config`
   (add `--allow-control` for the control scope below).
2. Paste it into the other app's MCP servers config. It looks like:

```json
{ "mcpServers": { "eli": { "command": "/path/to/ELI.AppImage", "args": ["--mcp-server"] } } }
```

A source install uses `python -m eli.integrations.mcp.server` (or the `eli-mcp`
script) instead. The right form is chosen for you.

## What is exposed

- **Default: safe actions only.** Anything that drives the machine, runs code, changes
  ELI itself, deletes, installs or sends is withheld.
- **Control actions** (mouse, keyboard, shell, self-change, smart home, sending) are
  exposed only when the client's config sets `"env": {"ELI_MCP_ALLOW_CONTROL": "1"}`.
  Choose that scope in the Marketplace tab to generate it. Only turn it on for apps
  you trust with your computer.
- A caller gets ELI's actions, not a free-text prompt into the assistant.

## Technical notes

- Transport: line-delimited JSON-RPC 2.0 on stdin/stdout, protocol version 2024-11-05,
  `initialize`, `tools/list`, `tools/call`, `ping`.
- Stdout carries only protocol traffic; all logging and library output goes to stderr.
