# Security Policy

## Reporting a vulnerability

**Please do _not_ open a public GitHub issue for security vulnerabilities.**

Report them privately by email to **jaybridgeman0095@gmail.com**. Please include:

- a description of the issue and its impact,
- steps to reproduce (or a proof of concept),
- the affected version / commit.

You'll receive an acknowledgement as soon as possible. Please allow reasonable
time for a fix before any public disclosure.

## Threat model

ELI is a **local host-control agent**: it can run shell commands, read files,
drive the desktop, and optionally expose a LAN web server. It is **not** a
sandboxed chat widget. Default settings are guarded, but a motivated model or
user can still cause harm on the machine ELI controls.

The machine's owner (the desktop app, and the operator of a single-token or
tokenless server) may have ELI do anything the gates below allow. In multi-user
(RBAC) mode, an API **member** or **viewer** may not have ELI carry out the
owner's actions — `eli/runtime/authority_gate.py` `owner_only()`: shell and code,
reading and writing files, the screen and clipboard, keyboard and mouse, ELI's
own settings, persona, plugins, MCP and self-patching.

ELI runs **offline-by-default**; networking opens only when settings, a scoped
`allow_network()` window, registered smart-home brokers, or **Full Control**
explicitly permit it.

## What to report

| Area | What we care about |
|---|---|
| **Shell gate (`RUN_CMD` / `SHELL_EXEC`)** | A command line that runs a denylisted program or destructive pattern while Full Control is **off** — in any part of the line, behind any wrapper |
| **`READ_FILE` / `LIST_DIR`** | Unintended path escapes beyond OS permissions (today: **no ELI path sandbox** for the owner — reads any OS-readable path) |
| **Role gate** | A member or viewer getting ELI to run an owner-only action by any route (`/v1/execute`, chat, streaming, completions, research, a chained command or an accepted offer) |
| **Custom-agent trust registry** | Loading an unregistered or tampered agent file |
| **Network guard** | Unauthorised outbound egress while offline / network disabled |
| **LAN FastAPI server** | Auth or RBAC bypass when run with `--lan` |
| **Loopback / Host-header auth** | Tokenless admin reached from a name that is not this machine's (DNS rebinding), or proxy misconfiguration (see below) |
| **MCP server** | An owner-only or control action exposed to an MCP client without `ELI_MCP_ALLOW_CONTROL=1` |

Generally **out of scope**: issues that require the user to enable **Full Control**
or to deliberately run code they already chose to run.

## LAN web server — loopback trust & deployment constraints

The FastAPI server (`api/server.py`) treats **socket loopback peers** (`127.0.0.1`,
`::1`) as the **local operator**: they may call admin endpoints **without a bearer
token**, even when the server is bound to `0.0.0.0` for LAN phone access. This is
intentional for single-user desktop use.

That grant (and tokenless serving) holds only for a request that **names this
machine** in its `Host` header: an IP address, `localhost` or `*.localhost`, the
machine's own host name (also with `.local`) or FQDN, or a name listed in
`ELI_API_ALLOWED_HOSTS` (comma-separated). A web page can point its own domain at
`127.0.0.1` (DNS rebinding); its requests then come from loopback, but carry the
page's domain as their `Host`, so they get no tokenless or loopback grant and need a
token like a LAN client. A valid token works under any name.

**Deployment footguns (document, do not ignore):**

1. **Reverse proxy on the same machine** — If nginx/Caddy/Traefik terminates TLS
   and forwards to `http://127.0.0.1:<port>`, ELI sees every client as loopback.
   When the proxy sends an IP address or one of this machine's names as the `Host`
   (many send the upstream address, `127.0.0.1:<port>`), **all remote users become
   tokenless admin.** Fix: terminate TLS on the LAN bind and use `--lan` + bearer
   tokens / RBAC, or proxy to the LAN IP (not loopback) and require tokens, or turn
   loopback admin off (below).

2. **Shared multi-user host** — Any local Unix user/process that can open
   `http://127.0.0.1:<port>` gets operator admin, **even when RBAC users are
   configured**, unless loopback admin is disabled.

**Opt-out (multi-user / hardened deployments):**

```bash
export ELI_LOOPBACK_ADMIN=0          # localhost presents a token like any LAN client
export ELI_API_ALLOW_TOKENLESS=0     # needed on a loopback-only bind, where main() turns tokenless serving on
export ELI_API_TOKEN=your-secret     # or configure RBAC users
```

Default is `ELI_LOOPBACK_ADMIN=1` (loopback operator stays admin so you never lock
yourself out on a personal machine). On a `--lan` bind, `ELI_LOOPBACK_ADMIN=0` alone
is enough; on a loopback-only bind, `main()` sets `ELI_API_ALLOW_TOKENLESS=1` unless
it is already set, so set it to `0` as well. With both off and no token or user
configured, every gated endpoint answers `401`.

## Shell execution — actual behaviour

Documentation and marketing must match this:

1. **`RUN_CMD` / `SHELL_EXEC`** (`eli/execution/shell_gate.py` `check_command`) is
   the live gate for the commands ELI is asked to run: a **denylist**. It blocks destructive regex patterns
   (`rm -rf /`, `mkfs`, `dd of=/dev/…`, `curl … | sh`, `bash -c`, `python -c`, the
   Windows and macOS equivalents, …) and dangerous program names (`bash`, `sh`,
   `python`, `perl`, `node`, `nc`, `dd`, `rm`, `shred`, `iptables`, `cmd`,
   `powershell`, `osascript`, …). It judges **every command the line runs**: after
   `;` `&&` `||` `|` `&` and newlines, inside `$( )`, `<( )`, `>( )` and backticks,
   the program behind wrappers (`sudo`, `doas`, `env` and `env -S '…'`, `nice`,
   `nohup`, `timeout`, `xargs`, `busybox`, `stdbuf`, `setsid`, `time`, …), and
   `find -delete` / `find -exec rm`. It **does not** require `ELI_ALLOWED_CMDS`:
   ordinary commands (`ls`, `git`, `curl` without `| sh`, etc.) run. **Full Control
   lifts the gate entirely.**

2. **`SecurityManager.is_command_allowed`** (`eli/runtime/security.py`) and the
   executor's `_run()` helper are an **allowlist / fail-closed** check
   (`ELI_ALLOWED_CMDS`), but nothing on the runtime path calls them — only tests do.
   They do not gate `RUN_CMD`.

3. **Programs ELI runs for its own features** do not pass through the command gate.
   Media and window control run fixed programs (`playerctl`, `wmctrl`, …) as
   argument lists. Grounded remediation (`eli/runtime/grounded_remediation.py`)
   runs its app checks and install offers as fixed command templates through the
   system shell, with the app name quoted; installs run only after you confirm. On
   Windows, app lookup runs `where` without a shell, and only plain app/package
   names are accepted.

4. **Habit rules** — the proactive daemon runs a habit rule's stored command through
   the system shell (`eli/planning/proactive_daemon.py` `execute_habit`), **not**
   through the command gate. `ELI_NO_HABIT_SHELL=1`, or the `habit_shell_enabled`
   setting set to `false`, turns shell habits off.

## Other known limits (honest)

- **Prompt-injection guard**: regex scrub of the message text at the top of
  `engine.process()` — desktop, voice and API chat turns alike — not of file
  contents, tool output, or every API field (`/v1/execute` arguments go straight to
  the action).
- **Offline enforcement**: the socket guard installs when the cognitive engine
  (and the API server) starts; some code paths use raw `urlopen` and rely on that
  guard being active. It guards ELI's own process, not programs it starts.
- **Web RBAC**: `/v1/chat`, `/v1/chat/stream`, `/v1/chat/completions`,
  `/v1/execute` and `/v1/research/query` all require the member role (read-only
  viewers are `403`'d from anything that runs the engine), and a member's turn
  still cannot reach an owner-only action. Single-operator mode (one shared token)
  has no roles: every token holder is the owner.
- **MCP server** (`eli/integrations/mcp/server.py`): without
  `ELI_MCP_ALLOW_CONTROL=1` it withholds control actions (keyboard, mouse, shell,
  code, self-update, deletes, installs, …) and every owner-only action
  (`CREATE_FILE`, `READ_FILE`, `SCREENSHOT`, `MEMORY_FORGET`, …). With it set, an MCP
  client can run anything the executor can.

## Supported versions

The latest commit on the `main` branch is supported.
