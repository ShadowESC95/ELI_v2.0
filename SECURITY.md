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

ELI runs **offline-by-default**; networking opens only when settings, a scoped
`allow_network()` window, registered smart-home brokers, or **Full Control**
explicitly permit it.

## What to report

| Area | What we care about |
|---|---|
| **Shell gate (`RUN_CMD`)** | Bypass of the destructive-pattern / dangerous-executable **denylist** while Full Control is **off** |
| **`READ_FILE` / `LIST_DIR`** | Unintended path escapes beyond OS permissions (today: **no ELI path sandbox** — reads any OS-readable path) |
| **Custom-agent trust registry** | Loading an unregistered or tampered agent file |
| **Network guard** | Unauthorised outbound egress while offline / network disabled |
| **LAN FastAPI server** | Auth or RBAC bypass when run with `--lan` |
| **Loopback / reverse-proxy auth** | Tokenless admin via loopback trust, or proxy misconfiguration (see below) |

Generally **out of scope**: issues that require the user to enable **Full Control**
or to deliberately run code they already chose to run.

## LAN web server — loopback trust & deployment constraints

The FastAPI server (`api/server.py`) treats **socket loopback peers** (`127.0.0.1`,
`::1`) as the **local operator**: they may call admin endpoints **without a bearer
token**, even when the server is bound to `0.0.0.0` for LAN phone access. This is
intentional for single-user desktop use.

**Deployment footguns (document, do not ignore):**

1. **Reverse proxy on the same machine** — If nginx/Caddy/Traefik terminates TLS
   and forwards to `http://127.0.0.1:<port>`, ELI sees every client as loopback.
   **All remote users become tokenless admin.** Fix: terminate TLS on the LAN bind
   and use `--lan` + bearer tokens / RBAC, or proxy to the LAN IP (not loopback)
   and require tokens.

2. **Shared multi-user host** — Any local Unix user/process that can open
   `http://127.0.0.1:<port>` gets operator admin, **even when RBAC users are
   configured**, unless loopback admin is disabled.

**Opt-out (multi-user / hardened deployments):**

```bash
export ELI_LOOPBACK_ADMIN=0   # require bearer token for localhost too
export ELI_API_TOKEN=your-secret   # or configure RBAC users
```

Default is `ELI_LOOPBACK_ADMIN=1` (loopback operator stays admin so you never lock
yourself out on a personal machine).

## Shell execution — actual behaviour (three paths)

Documentation and marketing must match this:

1. **`RUN_CMD` / `SHELL_EXEC`** (`eli/execution/shell_gate.py`): **denylist**.
   Blocks destructive regex patterns and dangerous `argv[0]` names (`bash`,
   `python -c`, `dd`, `rm`, …). **Does not** require `ELI_ALLOWED_CMDS`.
   Many ordinary commands (`ls`, `git`, `curl` without `| sh`, etc.) are
   allowed through. **Full Control bypasses the denylist entirely.**

2. **`_run()` helper** (`eli/runtime/security.py`): **allowlist / fail-closed**.
   If `ELI_ALLOWED_CMDS` is unset or empty, commands are blocked (unless Full
   Control is on).

3. **Desktop automation `_run_argv()`**: **fail-open** when `ELI_ALLOWED_CMDS`
   is unset — used for `playerctl`, `wmctrl`, etc.

## Other known limits (honest)

- **Prompt-injection guard**: regex scrub on direct user chat input in
  `engine.process()` only — not on file contents, tool output, or all API fields.
- **Offline enforcement**: socket guard installs when the cognitive engine
  starts; some code paths use raw `urlopen` and rely on that guard being active.
- **Web RBAC**: `/v1/chat`, `/v1/chat/stream`, and `/v1/chat/completions` all
  enforce the member role (read-only viewers are `403`'d from anything that runs
  the engine).

## Supported versions

The latest commit on the `main` branch is supported.
