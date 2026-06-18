# Security Policy

## Reporting a vulnerability

**Please do _not_ open a public GitHub issue for security vulnerabilities.**

Report them privately by email to **jaybridgeman0095@gmail.com**. Please include:

- a description of the issue and its impact,
- steps to reproduce (or a proof of concept),
- the affected version / commit.

You'll receive an acknowledgement as soon as possible. Please allow reasonable
time for a fix before any public disclosure.

## Scope

ELI runs **entirely locally and offline-by-default**, so the threat model is
different from a hosted service. The areas most worth reporting:

- the **shell security gate** (`RUN_CMD` / `SHELL_EXEC`) — it is fail-closed and
  allowlisted; report any bypass,
- the **custom-agent trust registry** (SHA-256) — report any way to load an
  untrusted/tampered agent,
- the **network guard** (offline-by-default) — report any unauthorised egress,
- the optional **LAN-exposed FastAPI server** — report auth/token bypasses when
  run with `--lan`.

Issues that require the user to already have full control of their own machine
(e.g. running arbitrary local code they chose to run) are generally out of scope.

## Supported versions

The latest commit on the `main` branch is supported.
