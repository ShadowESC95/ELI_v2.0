# Using ELI from other apps (ELI as an MCP server)

ELI can run as an MCP server, so an editor or desktop assistant that speaks the
protocol can call ELI's actions (search notes, read the time, query memory, and so on).
Everything runs locally over stdin/stdout; nothing is opened on the network.

## Connect an app

1. Open **Settings → Marketplace → MCP servers**, pick a scope and copy the config shown
   under "Use ELI from other apps". Or print it: `python -m eli --mcp-config` (or
   `./eli.sh --mcp-config`; add `--allow-control` for the control scope below).
2. Paste it into the other app's MCP servers config. From a source install it looks like:

```json
{ "mcpServers": { "eli": { "command": "/path/to/ELI/.venv/bin/python", "args": ["-m", "eli.integrations.mcp.server"] } } }
```

The command is the Python that printed the config. `python -m eli --mcp-server`, and the
`eli-mcp` script when ELI is pip-installed, start the same server.

A frozen build (AppImage, Windows or macOS app) prints the app itself with
`"args": ["--mcp-server"]` instead; its launcher (`packaging/pyinstaller/eli_entry.py`) hands
`--mcp-server` and `--mcp-config` to `eli/__main__.py`, which starts the server.

## What is exposed

- **Default: safe actions only.** Without `ELI_MCP_ALLOW_CONTROL=1`, `tools/list` leaves out
  two groups of the executor's actions, and `tools/call` refuses them
  (`eli/integrations/mcp/server.py`, `_exposed_actions()`):
  - every action whose name starts with `COMPUTER_USE`, `KEYBOARD`, `MOUSE`, `SHELL`,
    `RUN_`, `EXECUTE`, `SELF_`, `CODE_`, `GAZE`, `SET_CLIPBOARD`, `SCHEDULE_`, `DELETE_`,
    `INSTALL`, `UNINSTALL`, `UPGRADE`, `SMART_HOME` or `SEND_`. Today that is `KEYBOARD`,
    `MOUSE_CONTROL`, `SHELL_EXEC`, `RUN_CMD`, `RUN_TESTS`, `EXECUTE_GOAL`, `SELF_ANALYZE`,
    `SELF_IMPROVE`, `SELF_IMPROVEMENT_LOG`, `SELF_PATCH`, `SELF_REPAIR_PLAYBOOK`,
    `SELF_REPORT`, `SELF_TEST`, `SELF_UPDATE`, `SELF_UPGRADE`, `CODE_SOLVE`, `CODE_CHANGES`,
    `GAZE_CALIBRATE`, `GAZE_CLICK`, `GAZE_DISABLE`, `GAZE_ENABLE`, `GAZE_STATUS`,
    `SET_CLIPBOARD`, `SCHEDULE_TASK` and `SMART_HOME`;
  - the owner-only actions, `authority_gate.owner_only()` in `eli/runtime/authority_gate.py`
    (the same list an API member or viewer is refused). Beyond the names above, that is:
    files and folders (`READ_FILE`, `CREATE_FILE`, `CREATE_FOLDER`, `LIST_DIR`,
    `SUMMARIZE_FILE`, `FILE_AUDIT`, `OPEN_FILE_SYSTEM`); PDFs, images and documents
    (`ANALYZE_PDF`, `ANALYZE_PDF_FOLDER`, `ANALYZE_IMAGE`, `OCR_IMAGE`, `CONVERT_DOCUMENT`);
    the screen and clipboard (`SCREENSHOT`, `SCREEN_READ_ANALYZE`, `SCREEN_LOCATE`,
    `GET_CLIPBOARD`); code (`GENERATE_SCRIPT`, `GENERATE_PROJECT`, `FIX_FILE`,
    `CONFIRM_CODE_FIX`, `EXAMINE_CODE`, `CODEBASE_GRAPH`, `OPEN_IDE`, `OPEN_IN_IDE`); ELI's
    own settings and persona (`PERSONA_LOCK_SET`, `PERSONA_LOCK_CLEAR`, `PERSONA_REFRESH`,
    `SET_USER_NAME`, `SET_AI_MODE`, `SET_VOICE`, `SET_TONE`, `CLEAR_TONE`,
    `SET_COMMUNICATION_STYLE`); erasing (`MEMORY_FORGET`, `REMOVE_EVENT`,
    `CLEAR_CHAT_HISTORY`); plugins (`PLUGIN_INSTALL`, `PLUGIN_UNINSTALL`, `PLUGIN_ENABLE`,
    `PLUGIN_DISABLE`); MCP (`MCP_ADD`, `MCP_REMOVE`, `MCP_CALL`); training (`LORA_TRAIN`,
    `TRAIN_VOICE`, `WAKE_SET`, `WAKE_ENROLL`, `WAKE_TRAIN`); proactive mode
    (`PROACTIVE_START`, `PROACTIVE_STOP`).

  In v2.5.39 that withholds 75 of the executor's 208 actions. If the owner-only list cannot
  be loaded, nothing is exposed. The rest — status and diagnostics, time and date, notes,
  memory recall and storage, media and window control, opening apps and URLs, timers,
  documents, web search and news (still behind ELI's network switch) — is exposed.
- **Actions that carry others stay inside the scope.** `CHAT`, `MULTI_COMMAND` and `SEQUENCE`
  are in the default scope and run other actions (`CHAT` and `MULTI_COMMAND` route their text,
  `SEQUENCE` runs the steps it is given). Without control a call runs as a role below the
  owner's (`mcp-client` in `request_context.caller_role_var`), and the executor refuses the
  withheld actions to that role however they are reached, `SEQUENCE` steps included
  (`authority_gate.check`).
- **Control actions** (mouse, keyboard, shell, self-change, smart home, files, the screen and
  the rest of the lists above) are exposed only when the client's config sets
  `"env": {"ELI_MCP_ALLOW_CONTROL": "1"}`. Choose that scope in the Marketplace tab to
  generate it. MCP calls carry no API role, so with control on a client acts as the owner.
  Only turn it on for apps you trust with your computer.
- A caller gets ELI's actions, one tool per action, not ELI's message pipeline: no tool runs
  a turn through the engine.

## Technical notes

- Transport: line-delimited JSON-RPC 2.0 on stdin/stdout, protocol version 2024-11-05,
  `initialize`, `tools/list`, `tools/call`, `ping`. Notifications get no reply; an unknown
  method is error -32601.
- Each tool is described from the capability table (`eli/tools/registry/capabilities_doc.py`):
  what the action does and an example phrase, with an open argument schema
  (`additionalProperties: true`); the action checks its own arguments.
- Stdout carries only protocol traffic; all logging and library output goes to stderr.
