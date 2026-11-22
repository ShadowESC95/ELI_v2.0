# ELI Security Posture

> **Updated for v2.5.36.** The live command gate (`execution/shell_gate.py`) reads every command
> in a line; API members and viewers cannot have ELI run the owner's actions
> (`runtime/authority_gate.py`, now a role gate), and the same-machine grants need a `Host`
> header that names this machine; ELI's MCP server withholds the owner's actions; CREATE_FILE
> never replaces an existing file unless told to; scripts are no longer pre-written.

ELI runs locally with real OS reach (shell, file, app control) plus a
user-extensible agent/plugin system — so the security model matters. It spans
`eli/execution/shell_gate.py` (the command gate), `eli/runtime/authority_gate.py` (who may have
ELI do what), the API server's authentication (`api/server.py`), the network guard
(`eli/core/netguard.py`), the engine input sanitiser, the memory SQL validator, the agent trust
registry and the plugin marketplace's checks. Where a check cannot decide, most of these deny:
the API's authentication, the network guard, the engine's authority check on side-effecting
actions and the plugin permission prompt all fail closed. The shell gate is the exception: it is
a denylist, so a command it does not recognise as harmful runs.

## 1. Shell command gate (`execution/shell_gate.py` `check_command`)

RUN_CMD and SHELL_EXEC (its alias, which runs the line through the OS shell) are refused when
`check_command(cmd)` returns a block result. It reads **every command the line runs**, not only
its first word:

- The line is split into commands at `;`, `&&`, `||`, `|`, `&` and newlines, and what runs
  inside `$( )`, `<( )`, `>( )` and backticks is read as commands of its own (`_commands_in`).
- Wrappers are looked through to what they run (`_what_runs`): `sudo`, `doas`, `env`, `nice`,
  `nohup`, `timeout`, `command`, `exec`, `builtin`, `xargs`, `busybox`, `stdbuf`, `setsid`,
  `time`, `ionice`, `chrt`, `taskset`, `unbuffer`, `caffeinate`, `start`, with their options and
  any `VAR=value` prefixes skipped. `env -S '...'` (`--split-string`) is read as the line its
  string holds.
- A command is refused when the program it runs is on `_DENIED_EXECUTABLES` — shells and script
  interpreters, netcat, disk and firewall tools, `rm`/`shred`/`wipe`, and the Windows and macOS
  equivalents (`cmd`, `powershell`, `cscript`, `mshta`, `diskpart`, `bcdedit`, `vssadmin`,
  `osascript` …), matched on the base name with any directory and `.exe`/`.com`/`.bat`/`.cmd`
  dropped — or when it is `find` with `-delete`, or with `-exec`/`-execdir`/`-ok`/`-okdir`
  running a denied program.
- The whole line is also matched against `_BLOCKED_PATTERNS`: destructive POSIX commands
  (`rm -rf /`, `mkfs`, `dd of=/dev/`, `chmod 777 /`, a fork bomb, shutdown/reboot,
  `curl … | sh`, `bash -c`, `python -c`, redirects into `/etc` or `/boot`, password, sudoers and
  crontab changes), their Windows forms (recursive `del`/`rd`, `format X:`,
  `Remove-Item -Recurse`, `reg delete`, deleting shadow copies or backups, `bcdedit`,
  `cipher /w`, `iex`, `cmd /c`, `powershell -c`/`-enc`) and macOS ones (`diskutil erase`,
  `csrutil disable`, `spctl --master-disable`).
- An argv list is one command (no shell reads it), so only its own words are judged.

It is a **denylist**: a command that matches none of this runs, with the user's rights. RUN_CMD
runs an argv with `shell=False`; SHELL_EXEC hands the line to `/bin/sh -c` (`cmd.exe /d /s /c`
on Windows) after the gate has read all of it. **ELI Full Control** on → no block at all.

`shell_gate.py` is on self-improvement's protected list (`self_improvement._PROTECTED_PATCH_PATHS`),
so a self-patch cannot strip it. The intent model is never offered RUN_CMD or SHELL_EXEC
(`llm_intent._EXPLICIT_ONLY_ACTIONS`), a model that names one as the orchestrator's next ReAct
tool or as the alternative to a failed action is not followed (`llm_intent.model_may_choose`),
and ELI does not carry out a promise in its own reply that names one (`engine._followthrough_may_run`).

**No command allowlist.** `ELI_ALLOWED_CMDS` is read by nothing. The allowlist that read it
(`SecurityManager.is_command_allowed` and `safe_subprocess` in `runtime/security.py`, the executor's
`_run` helper with its fallback `_shell_command_allowed_fallback`) was called only by tests and has
been removed, together with the log line it wrote each time one was built, "shell commands are BLOCKED",
which was never true of this gate.

> **ELI Full Control has no environment variable — deliberately.** The single
> source of truth is the `full_control` setting flipped by the GUI toggle, read
> live via `core/full_control.py` `is_full_control()`; nothing in the process
> environment can turn it on, so no stray export can silently unlock the gates,
> and flipping the toggle off restores every gate at once without a restart. It
> lifts these barriers together: network gating (netguard), self-code patching, autonomy
> approval (`approval_engine`), this command gate, CREATE_FILE's allow-roots (§2), and
> in-process code-mode programs (`coding/restricted_exec.py` runs them only with it on). It does
> not touch the API's authentication or roles (§7) or what ELI's MCP server withholds (§17).

## 2. Filesystem & app gates

- **CREATE_FILE allow-roots** — `SecurityManager.is_path_allowed(path)`, all that is left of
  `runtime/security.py`, built once per setting (`get_security_manager`). The target must resolve
  inside the project root (`ELI_ROOT`, else the source tree), `$HOME`, an `ELI_ALLOW_ROOTS` entry
  (separated by the OS path separator: `:` on Linux and macOS, `;` on Windows) or
  the system temp folder. Uses `Path.resolve()` + `relative_to`, so `..` traversal and symlinks
  can't escape. A relative path is placed under `<data dir>/scratch/`. Anywhere else is refused
  unless Full Control is on.
- **CREATE_FILE never replaces a file.** If the target exists it is not written unless the call
  carries `overwrite`, which the router sets only when the user says "overwrite" or "replace"
  (`router_enhanced`, `fs.create_file`). A model or an MCP client choosing CREATE_FILE cannot
  write over an existing file such as a shell profile.
- Reading files and listing folders (`READ_FILE`, `LIST_DIR`) have no allow-roots. For an API
  member or viewer and for MCP clients they are owner-only (§7, §17).
- **Apps:** there is no app allowlist; `ELI_ALLOWED_APPS` is read by nothing (its readers,
  `SecurityManager.is_app_allowed` and the executor's `_allowed_apps_set`, were never called
  and have been removed). When an app will not open, ELI checks whether it is installed and offers to install
  it (`runtime/grounded_remediation.py`): on Windows the name must be a plain program or package
  name (`_PACKAGE_NAME`) before it reaches `where`, winget or Chocolatey, and `where` runs without
  a shell; POSIX lookups quote it with `shlex.quote`.

## 3. Prompt-injection guard (`kernel/engine.py`)

`_ELI_INJECTION_PATTERNS` (regex) + `_eli_sanitize_user_input`:
- Matches role tokens and role-override prefixes — `[INST]`, `<|im_start|>system`, `<<SYS>>`,
  `### system:` / `### instruction:` / `### context:`, `SYSTEM:` before ignore/override/disregard,
  "ignore/disregard/forget (all) previous/prior/above instructions", "you are now a
  dan/jailbreak/unrestricted/free", `OVERRIDE:`, "act as (if you were) a human/person/
  unrestricted" — and replaces the matched span with `[filtered]` (keeps the rest of the
  message).
- Strips control characters (keeps newlines and tabs).
- Fits the message to what the loaded model can read (`_eli_max_input_chars`: the context window
  less the reply's room; `ELI_MAX_INPUT_LEN` overrides). A longer message keeps its start and its
  end, with the middle marked as left out (`_eli_fit_input`).
- Runs at the top of `CognitiveEngine.process()`, before the router and the LLM see the input,
  so injected role-overrides are neutralised but legitimate content survives.

## 4. SQL identifier validation (`memory/memory.py`)

`_IDENTIFIER_RE = ^[A-Za-z_][A-Za-z0-9_]*$` + `_validate_identifier(name)` —
called before **any** f-string interpolation of a table/column name into SQL
(`_validate_identifier(table, "table")`, column DDL first-token check). Raises
`ValueError` on anything non-conforming. Closes the one place dynamic SQL is
unavoidable (parameterised values are used everywhere else).

## 5. Custom-agent trust chain (`cognition/agent_trust.py`)

Custom agent code is **SHA-256 gated** and fail-closed: unknown, modified or revoked
files are not loaded. `ELI_TRUST_ALL_AGENTS=1` bypasses for dev only.

Rebuilt in 2.3.7. The previous registry stored `{basename: sha256}` in
`config/trusted_agents.json`, which had three defects that look fine until they
don't:

- **Keyed on the basename.** Two files called `helper.py` in different directories
  shared one entry, so approving either silently authorised the other. Identity is
  now the **resolved absolute path**; the basename is kept for display only.
- **No provenance.** A bare hash cannot answer *who approved this, when, and what
  did it look like then* — the questions asked after something goes wrong. A grant
  now records the timestamp, the approver, the file size, the static-analysis
  verdict at approval, and the spec hash the code was paired with.
- **Nothing looked at the code.** The gate proved a file was unchanged since
  approval; it never asked whether approving it was reasonable. `grant()` now runs
  the same engines as the plugin marketplace and **refuses outright** on a malicious
  verdict (overridable with `force=True`, which is itself recorded).

Revocation is real: a revoked entry is *kept and marked revoked* rather than
deleted, so re-adding the same file does not silently re-trust it. A v1 registry is
migrated rather than discarded, with migrated entries flagged `legacy` so it stays
visible that they predate these checks.

**Most custom agents need none of this.** An `AgentSpec` is data — objective, system
prompt, triggers, success criteria — so a spec-driven agent executes no arbitrary
code and never touches the trust gate. See `orchestration_and_agents.md`.

## 6. Code generation & self-modification — three paths

ELI writes code for the user (GENERATE_SCRIPT) and for itself (self-patching), and a guard
checks what generation leaves behind:

1. **`GENERATE_SCRIPT`** (`execution/executor_enhanced.py`) — *real* LLM codegen, written for
   the request in front of it. Detects language/intent, prompts for frontier-quality code, then
   gates it:
   - `_verify_python_module_apis` — imports the referenced libraries and confirms
     `module.attr` references actually exist (catches hallucinated APIs).
   - `_quality_reject_reason` — rejects refusals, stubs, too-short, no-real-compute,
     missing-plot, `required=True`-without-default, SyntaxError.
   - **`_sandbox_run_python`** — runs the candidate through `coding/sandbox.run_code`: a
     separate process with a temp working folder, an environment without variables whose names
     hold KEY/TOKEN/SECRET/PASSWORD, `MPLBACKEND=Agg` so `plt.show()` can't block, a wall-clock
     timeout (`ELI_GENSCRIPT_RUN_TIMEOUT`, 20 s) and on POSIX a generous `RLIMIT_CPU`; **no
     `RLIMIT_AS`** — it breaks numpy/scipy. A genuine unhandled traceback is fed back as repair
     feedback into a **3-attempt regenerate loop**; timeouts / signal kills /
     missing-optional-deps are tolerated (never reject legit heavy scientific scripts). Disable
     the run with `ELI_GENSCRIPT_VERIFY_RUN=0` (`ELI_CODING_SANDBOX=0` turns sandbox execution
     off entirely). This is process isolation, not containment: the run has the user's files
     and, since netguard lives only in ELI's own interpreter, the network.
2. **What generation leaves behind is checked** (`runtime/generated_script_guard.py`). Its
   `install()` wraps the executor's `execute`: a generated script that is a template or the
   model's chatter (`TODO`, "Add code here", a prompt echo, a shell file holding Python function
   definitions) is moved to an `invalid/` folder beside it with the reason, and reported as
   failed; a generated document is filed under the documents folder and refused when it carries
   stub markers or is under 240 characters. It no longer answers any request with a pre-written
   script (until 2.5.36 it picked one of six canned scripts by keywords).
3. **Self-patching** (`runtime/self_improvement.py` `SelfImprovementEngine`) —
   ELI modifies its *own* source for recurring failures. Gated behind
   `auto_patch_enabled` (**default off**) or Full Control, ≤2 patches/cycle, only for
   high-recurrence failures with a file traceback. A candidate goes live only when a copy of the
   tree shows it fixes something (`apply_autonomously`): it is applied to a working copy whose
   files are hard-linked, and the same test command is run on the copy and on the untouched tree
   (`verify_in_workspace` → `compare_runs`) — the failure capsule's reproducer when the action is
   safe to replay, else the tests matching the module's name. Only `fixed` (something that failed
   now passes and nothing new fails) is applied; every candidate stays in the `code_patches`
   table with its verdict and cost. Applying runs verbatim-`old`-match → `ast.parse` →
   timestamped backup (+ canonical `.eli_bak`) → write → `py_compile` → **differential import
   smoke-test**: the patched module is imported in an isolated subprocess and **auto-reverted**
   if it no longer loads, but only when it imported cleanly *before* the patch. A patch whose
   actions are watched stays probationary and is adopted or rolled back on their record.
   Project-root-confined and `.py`-only. Protected, never patched: `shell_gate.py`,
   `authority_gate.py`, `security.py`, `netguard.py`, `full_control.py`, `approval_engine.py`,
   `self_improvement.py`, `deterministic_grounding_gate.py`, `persistence_gate.py`,
   `evidence_ledger.py`, `lessons.py`, `failure_taxonomy.py`, and `tests/`, `tools/eval/`,
   `conftest.py`, `pytest.ini` (`ELI_PROTECTED_PATCH_PATHS` adds more).
   `ELI_SELFPATCH_UNPROVEN=1` restores applying without proof.

> **Code-health flag:** `generated_script_guard` is now a single `install()` wrapper (the chained
> second definition is gone), but the executor's `execute` is still layered: several wrappers
> (document defaults, the voice contract, the portable-action layer, this guard, the middleware
> table) each wrap the one before. The owner-only check (§7) sits in the outermost `execute`,
> the one the engine, the API and the MCP server import.

> **Limit:** without a replayable capsule a candidate is judged by `pytest tests/ -k <module>`;
> a module with no matching tests gives an inconclusive verdict, and the candidate is kept in
> the archive unapplied.

## Honest assessment

- **Strong:** the shell gate reads every command a line runs, through wrappers and
  substitutions; CREATE_FILE is root-confined and never overwrites unasked; identifiers are
  validated; custom agent code is hash-trusted with provenance; injection prefixes are
  neutralised; generated Python scripts are run before they are handed over and templates are
  quarantined; self-patches must prove a fix on a copy of the tree first.
- **Weak / watch:**
  1. The shell gate is a **denylist** — anything it does not name runs with the user's rights.
     (`ELI_ALLOWED_CMDS` is read by nothing; there is no allowlist behind it.)
  2. The injection guard is **pattern-based** — it catches known prefixes, not
     novel/obfuscated injections (no model-side defence). Reasonable for a
     single-user local tool, insufficient if ever multi-tenant.
  3. **ELI Full Control** is a single toggle that lifts the shell gate, the network gate,
     CREATE_FILE's roots, self-patching and approval at once — convenient, but a blunt
     instrument; there is no middle "allow file but not shell" tier.
  4. Child processes are not contained by netguard: shell commands, generated-code test runs,
     `pip` and plugins granted `process_exec` have the user's network and files. Only MCP servers
     are launched in a sandbox, and only on Linux (§17).
  5. `READ_FILE` and `LIST_DIR` are not root-confined for the owner.

---

## RUN_CMD terminal is real; mock leak fenced
- **RUN_CMD uses a real `subprocess.run`** (the RUN_CMD handler in `executor_enhanced.py` — an
  argv with `shell=False`, capture_output, timeout default 30 s; SHELL_EXEC runs the line through
  the OS shell) behind `shell_gate.check_command` (§1). The gate is lifted only when
  **Full Control** is on. There is **no production mock path**.
- **The `<MagicMock …>` failure rows were test leakage, not runtime.** They came from
  `tests/test_shell_security_gate.py` patching `subprocess.run`; the executor's
  `(p.stdout or "") + (p.stderr or "")` concat then yields a MagicMock repr, which slipped into
  the live `agent.sqlite3` via a test-isolation gap. A guard in
  `SelfImprovementEngine.log_failure` now **drops any error/input carrying a Mock/MagicMock
  repr** at the write source, so a test isolation slip can no longer pollute real failures.

---

## Web app & multi-user security

ELI ships a self-hosted FastAPI web app (`api/server.py`). It is local-first and inherits the
gates above: the model is the same local GGUF behind netguard, and what a web turn runs passes
the same shell gate and CREATE_FILE rules. The web surface adds:

### 7. Authenticated identity + RBAC (`eli/runtime/api_users.py`, `api/server.py`)
- **Three roles** — `viewer` (read-only) < `member` (acts) < `admin` (console, user management).
  Endpoints are dependency-gated (`require_viewer` / `require_member` / `require_admin`;
  `_require_token` admits any authenticated caller). Chat, streaming, chat completions,
  `/v1/execute`, research and device control need a member; user management, the Net switch,
  settings, model switching, driver installs and the server port need an admin.
- **Two modes.** With no users defined (single-operator mode) `ELI_API_TOKEN`, or a same-machine
  grant below, authenticates the local operator as admin. Once one user exists in
  `config/api_users.json`, RBAC is enforced: each bearer token resolves to a user and role, and
  actions are attributed to the authenticated user, not to a `user_id` the client sends.
- **Fail-closed auth gate** — an unauthenticated call is answered 401 and an under-privileged one
  403, never silently downgraded. Tokenless serving needs `ELI_API_ALLOW_TOKENLESS`, which
  `main()` sets only for a loopback bind, so a bare `uvicorn api.server:app` asks every caller for
  a token. A request from this machine (loopback peer) with no token is the owner unless
  `ELI_LOOPBACK_ADMIN=0`; `--lan` binds `0.0.0.0` and requires a token from every other device.
- **The name the request uses (DNS-rebinding defence).** The tokenless and same-machine grants
  hold only when the request's `Host` header names this machine (`_named_as_this_machine`): an IP
  address, `localhost` or `*.localhost`, the machine's own host names, or a name listed in
  `ELI_API_ALLOWED_HOSTS` (a reverse proxy's, say). A web page that points its own domain at
  127.0.0.1 reaches the server from loopback but sends its own domain as `Host`, so it gets no
  grant and must present a token like a LAN client. A valid token works by any name.
- **Owner-only actions** (`runtime/authority_gate.py`, a role gate since 2.5.36). In RBAC mode a
  member or viewer cannot have ELI run `authority_gate.owner_only()`: shell commands, code
  generation and fixes, reading, writing, listing and converting files, PDFs and images,
  screenshots and screen reading, the clipboard, keyboard and mouse, opening the IDE or the file
  manager, and everything ELI's intent model is never offered (`llm_intent._EXPLICIT_ONLY_ACTIONS`:
  persona and settings changes, forgetting memories, plugins, MCP, self-patching and upgrades,
  training, wake word and gaze, proactive start/stop). `/v1/execute` checks the caller's role and
  answers 403; `/v1/chat`, `/v1/chat/stream`, `/v1/chat/completions` and `/v1/research/query`
  put the role on the turn (`request_context.caller_role_var`), and the executor's `execute`
  checks it at entry, so no path a turn takes — a chain of commands, an agreed offer, a tool
  loop — reaches one. The desktop app and ELI's own daemons carry no role and are the owner; in
  single-operator mode every caller is the admin operator.
- **Tokens at rest.** The RBAC store holds only SHA-256 hashes of tokens, compared in constant
  time; a token is shown once, at creation. The single-operator LAN token is kept as written, in
  a `0600` file (see "Stable phone token" below), because the server prints it for pairing.

### 8. Tamper-evident, HMAC-keyed audit trail (`eli/runtime/evidence_ledger.py`)
- API chat and execute calls, Net switch flips, settings changes and model switches are recorded
  into a **hash-chained** ledger (`runtime_events` in the user database) as who / what / outcome,
  **without message content**. The same ledger also holds research-corpus activity and the
  engine's own rows — each executed action and each final reply, with its text — and
  `/v1/audit` returns only the metadata columns. Any edited/deleted/reordered row is detected
  by `verify_chain()` and surfaced in the Audit tab + admin console.
- The chain is **HMAC-keyed** (`$ELI_AUDIT_HMAC_KEY`, else a `0600` key file beside the
  config), so the integrity check can't be forged by recomputing plain hashes.

### 9. Secret files born locked — TOCTOU closed (`eli/core/secure_io.py`)
- The old `write_text(...)` then `chmod(0o600)` pattern left a brief window where, on a
  typical umask, the file was born `0644` (world-readable) before the chmod landed — a real
  (if narrow) TOCTOU on a multi-user box, on exactly the files that matter most.
- **`secure_io.secure_write_text/bytes`** is now the single owner of secret writes:
  `tempfile.mkstemp` (born `0600`) → write → fsync → `os.replace` (atomic). The destination
  **never exists world-readable for any instant**, and readers see old-or-new, never partial.
- Routed through it: the **audit HMAC key**, the **API user store**, the **LAN API token**, the
  LAN HTTPS **private key**, **settings** (may hold broker passwords/tokens) and the
  **agent-trust registry** (`trusted_agents.json`, the integrity anchor for §5). Before 2.5.38
  the registry was written atomically but with the default file mode, readable by other users.

### 10. Sandboxed research ingest
- Corpus ingest for the research workspace reads only inside one folder
  (`research_corpus.research_source_root()`: `artifacts/research/_sources`, or
  `ELI_RESEARCH_ROOT`). Absolute paths outside it, `..` and symlinks that lead out are refused
  after `resolve()`, and the walk is capped (`ELI_RESEARCH_MAX_FILES`, `ELI_RESEARCH_MAX_BYTES`),
  so a client cannot have the server read and echo back other files on the host.

### 11. Monitored Internet toggle + egress oversight (`eli/core/netguard.py` + `api/server.py`)
- ELI is **offline-by-default** and hard-gated at the **socket boundary** — the process-wide
  failsafe raises `OfflineError` on any non-loopback connect while the toggle is off, even
  from code that forgot the helpers (fail-closed; loopback/LAN-registered services allowed).
- The guard covers **all four** ways an outbound connection actually happens, cross-platform:
  `socket.socket.connect` (raises) and `socket.create_connection` (raises) — sync + the
  selector asyncio loop / urllib / requests; `socket.socket.connect_ex` — the **non-raising
  sibling** used by probes and health-checks, which is made to **return `ENETUNREACH`** when
  blocked (no socket is opened) so it can't silently bypass the block or the recorder; and a
  **best-effort patch of the Windows `ProactorEventLoop`** (`IocpProactor.connect`, overlapped
  `ConnectEx`), which never touches `socket.socket.connect`. The allowed path of each records
  egress identically (below); the Proactor patch is a no-op on non-Windows.
- The owner can deliberately **enable internet**: from the desktop GUI (`🌐 Net` toggle) or the
  web dashboard (`GET /v1/net` token-gated read + `POST /v1/net` **admin-only**), persisted via
  `network_enabled`. **Both flips are written to the audit ledger** (`net_toggle`,
  warning-severity on enable) — the web *and* the desktop toggle. The `ELI_OFFLINE` environment
  variable overrides the setting (`core/config.network_allowed`): `1`, `true`, `yes` or `on`
  keeps ELI offline and `0`, `false`, `no` or `off` turns the network on; any other value, an
  empty one included, is read as unset (the setting decides, and the log says the value was not
  understood). Before 2.5.38 every value but `1`, `true` and `yes` turned the network on. Full
  Control lifts the offline barrier too.
- **Egress is genuinely monitored, not a blind hole.** While network is on, the same socket
  chokepoint that enforces offline mode also **records every allowed non-loopback connection**
  (host:port + timestamp): into an **in-memory ring** (live tail; `GET /v1/net/egress` + the
  Overview widget) and, throttled to one row per host:port per window (`ELI_EGRESS_LOG_WINDOW`,
  default 300s), into the **tamper-evident audit ledger** as `net_egress` events. The ledger
  write is best-effort and runs on a background thread, so monitoring never delays or breaks a
  connection. Disable the ledger leg (keep the live ring) with `ELI_EGRESS_LEDGER=0`.
- The toggle changes *policy*; the socket failsafe still governs every actual connection, and
  every connection it allows is now on the record.
- **No library reports to its maker** (2.5.14). Usage telemetry built into the libraries ELI
  carries is switched off when the `eli` package loads (`ORT_DISABLE_TELEMETRY`,
  `HF_HUB_DISABLE_TELEMETRY`, `GRADIO_ANALYTICS_ENABLED`, `DO_NOT_TRACK`, `OTEL_SDK_DISABLED`,
  `ANONYMIZED_TELEMETRY`, `SCARF_NO_ANALYTICS`). onnxruntime's sends from native code, which the
  socket guard cannot see, so its switch is the only thing that stops it. Hosts that exist only to
  collect telemetry or crash reports (`netguard.REPORTING_HOSTS`) never resolve, even with the Net
  switch on (`tests/test_netguard_socket_guard.py`).
- Rationale: internet is "the final frontier to make ELI's world bigger" — available, but
  monitored (per-connection) and under the user's control, not a permanent lockout.

### Honest assessment — web tier
- **Strong:** fail-closed auth, role separation that reaches every path a turn takes, a
  same-machine grant a rebinding page cannot borrow, a tamper-evident HMAC'd audit trail,
  born-locked secret files, and a monitored (not absent) network path.
- **Watch:** RBAC is token-based and single-tenant-shaped: a member still drives everything
  that is not owner-only (devices, media, web search while the network is on). The injection
  guard (§3) is still pattern-based, and ELI Full Control remains one blunt switch for the
  local gates.
  These matter more once the web app is exposed beyond the owner's machine — keep it bound to
  trusted networks.

## Stable phone token, admin-gated model switch

Two web-tier changes this cycle, both verified against the code:

- **Stable LAN token + rotate.** The phone's bearer token now **persists** across server
  restarts (`api/api_token.py`: env → a `0600` file under the config dir → generate-and-save),
  so a paired phone is no longer stranded every time the server bounces. The desktop **Web
  Server panel's Rotate token** button issues a fresh token and saves it; a server running inside
  the desktop app reads the token live, and one running as a separate process that serves the
  saved token re-reads its file, so old links stop working at once either way (a server started
  with an explicit `--token` other than the saved one keeps that token). It is the manual
  override for a lost/compromised phone. `/health` stays tokenless by design.

- **Model switching is admin-gated and allowlist-bound.** The dashboard's model dropdown posts
  to `POST /v1/model`, which requires an **admin** principal and only accepts a path already in
  the installed-models list (`GET /v1/models/installed`). A dropdown of real files can't strand
  the runtime on a bad path, and a non-admin can't switch the model. (The list endpoint was
  moved off `/v1/models` to `/v1/models/installed` so it no longer collides with the
  OpenAI-compatible route.)

Neither weakens the existing posture — the socket failsafe, the shell gate, and the audit
ledger all still apply.

## Token moved to the URL fragment; test reds cleared

- **Token in the URL fragment, never the query string.** Every emitter of the phone link
  builds `…/#token=…` instead of `…/?token=…`: the server's printed URLs and its Connect-tab
  link (`_connect_url`) *and* the desktop **Web Server panel** (`_eli_server_start`,
  `_eli_server_start_subprocess`, `_eli_server_rotate_token` in
  `eli/gui/eli_pro_audio_gui_v2_0.py`). The launchers (`scripts/eli_serve.sh`,
  `scripts/eli_serve.ps1`) print the address without the token and leave the token link to the
  server. A query string reaches the server — it lands in **uvicorn's access log** before any
  client-side strip can run — whereas a **fragment is never sent to the server**, so the token
  can't leak into the log. The page reads it from
  `location.hash`, stores it, and clears the address bar; it still accepts `?token=` for old
  links, so the transition breaks nothing. (An earlier commit fixed only the web tab + printed
  URL, leaving the GUI/launcher paths — most real usage — still leaking; this closed them.)

- **The five standing test reds of that cycle were cleared.** The deprecated `smart_home` plugin
  was removed, 113 silent `except: pass` swallows were made observable, and stale blueprint
  references were fixed. Not a security change per se. The ratchet that keeps silent swallows
  from growing is `tests/claims/test_no_silent_swallow.py`.


## Community plugin marketplace: consent, verification, scanning

ELI ships a marketplace **client** and two registries, both switched on: the built-in
entry (the bundled offline index of ELI's own plugins) and **ELI Marketplace**
(`plugins.geteli.tech`), which is curated — every listing on it is reviewed and signed with
the maintainer's key (`eli-marketplace`), and the client refuses a listing there that is not
validly signed by that key. Registries an operator adds belong to the community: nobody
reviews them, so for their listings the usual first line of defence — "the store checked
it" — does not exist, and ELI must never imply otherwise. Everything below therefore comes
from the artifact itself, whichever registry listed it, and every screen says exactly what
was checked and what was not.

### 12. Runtime permissions (`eli/plugins/permissions.py`)

A plugin was previously ordinary Python `exec_module`'d inside ELI's process:
whatever the interpreter could do, the plugin could do — read every conversation,
reach the network, drive the mouse — with nothing declared and nobody asked.

Plugins now **declare** capabilities in their manifest and the operator is asked, in
plain language, before any of them is used. Fourteen capabilities
(`network`, `filesystem_read/write`, `process_exec`, `os_control`, `screen_capture`,
`camera`, `microphone`, `memory_read/write`, `model_access`, `clipboard`,
`notifications`, `audio_playback`), each with a risk level and a sentence on why it
is risky, phrased as what it can do *to you*.

Four answers — **Allow once · Always allow · Not now · Never allow**. Only the two
permanent ones persist; "once" is session-scoped and dies with the process. "Never"
is remembered and the plugin is **never asked again**, which is what stops nagging.

Three rules hold everywhere:

- **Fail closed.** No prompt handler registered — headless, API server, a scheduled
  task at 3am — means DENY, never a silent allow. A plugin cannot escalate by
  running where nobody is watching. A crashed or unresponsive dialog also denies.
- **Nothing is granted by installing.** Install consent and use consent are separate
  acts; Android learned this the hard way with install-time permissions.
- **Every decision is audited** to a JSONL ledger the operator can read back, and
  any grant can be revoked from Settings ▸ Marketplace ▸ Permissions.

An unrecognised capability is reported as **critical**, not ignored — a build that
cannot explain a permission cannot enforce it either.

### 13. Manifest vs. code (`eli/plugins/manifest.py`)

The manifest declares; the code is statically checked against it, and **undeclared
capability use is a refusal, not a warning**. A plugin that quietly imports
`subprocess` while declaring nothing is exactly the case this stops.

Some constructs cannot be declared away and are refused outright, because they
defeat every static check above: `eval`, `exec`, `compile`, `__import__`,
`importlib.import_module`, `marshal.loads`, `pickle.loads`, `ctypes.CDLL`.

The scan is deliberately conservative — it over-reports rather than under-reports.
A false "you must declare filesystem_write" costs a publisher one manifest line; a
false negative costs an operator their files.

### 14. Integrity and publisher identity (`eli/plugins/integrity.py`)

Two narrow promises, both verifiable on the operator's own machine:

- **You got what the listing described.** The listing carries a sha256; the download
  is hashed *before* it is written to disk. A mismatch is a hard refusal — this is
  what stops a compromised mirror, a man-in-the-middle on a plain-http source, or a
  publisher swapping the file under an unchanged listing.
- **It came from a publisher you chose to trust.** Optional ed25519 signatures
  verified against keys the **operator** added. Not a key the ELI author holds —
  there is no central authority here by design. There is deliberately no
  trust-on-first-use shortcut: TOFU would make the first plugin from anyone trusted
  forever, which is the same as no check.

An unsigned community plugin is **not blocked** — it is reported as unverified,
loudly. A *failed* signature is blocked. Hash checking is mandatory and
dependency-free; signature checking needs `cryptography`, and where it is absent the
plugin is reported as **unverifiable rather than verified**.

### 15. Malware scanning (`eli/plugins/security_scan.py`)

Eleven independent engines, run on the operator's machine as well as by whatever the
registry did upstream — a scan you did not run yourself is a claim, not a result.

| Engine | Looks for |
|---|---|
| `static_ast` | capability use, runtime code construction, dynamic imports |
| `obfuscation` | decode chains, char-code string building, large encoded literals |
| `ioc_patterns` | reverse shells, miners, hardcoded C2, paste/tunnel hosts, destructive commands |
| `credentials` | ssh keys, cloud credentials, browser stores, wallets, keychains, shell history |
| `persistence` | LD_PRELOAD, DYLD injection, process injection, cron, systemd, launchd, Run keys, shell rc files |
| `anti_analysis` | VM/debugger/sandbox detection — deliberate evasion |
| `entropy` | packed or encrypted blobs carried inside source |
| `dependencies` | typosquatted pip names, URL installs, installer-code warning |
| `hash_blocklist` | known-bad artifacts (local, community-updatable) |
| `clamav` | full antivirus, if `clamscan`/`clamdscan` is installed |
| `yara` | custom rules, if `yara-python` and a ruleset are present |

Two rules the scoring obeys:

- **An engine that could not run never counts as a pass.** It is named as
  unavailable and the verdict says coverage was partial. A scanner that quietly
  downgrades to "clean" when ClamAV is missing is worse than no scanner.
- **Findings are evidence, not proof.** Each carries the line and the matched
  construct, so a publisher can argue with it and an operator can look.

Scoring is capped per category, so twenty matches of one pattern cannot outweigh
three different kinds of evidence — breadth is the stronger signal. Any critical
finding, or a score ≥ 45, or three high findings ⇒ **malicious**, and the install is
refused.

### 16. The install path (`eli/plugins/marketplace.py`)

Deliberately slow, and ordered so nothing dangerous happens before the operator has
seen the result:

1. validate the listing → 2. licence gate for paid plugins → 3. download **to
memory** → 4. verify hash + signature → 5. static check against the manifest →
6. run every scanner → 7. show the operator everything → 8. only then write.

What is written arrives **switched off with no permissions granted**. The disabled
flag is written straight to state rather than through `get_manager().disable()`,
because constructing the manager runs `_auto_load()`, which would import and execute
the freshly downloaded module before it could be marked off. Module-level code in a
downloaded plugin must not run at install time.

`pip` dependencies need a **separate** approval: package installers run their own
code in a child process and reach the network outside anything ELI can gate.

Registries are a **list, not a constant** — operators add the community sources they
want and can switch off or remove any of them, the two shipped ones included (kept as
`"disabled"` / `"removed"` in `plugin_registries.json`). The curated ELI Marketplace is one
entry on that list, not the gate: a community source an operator adds installs exactly as
it does, minus the curation.

Downloaded plugins are written to the **user data dir**, not `eli/plugins/` inside
the installation. The old `_plugins_dir()` returned the source tree, which is a
read-only mount on a packaged build and also mixed a stranger's code in with ELI's
own shipped plugins.

### 17. MCP servers — and the limit of netguard (`eli/plugins/mcp.py`)

**Stated plainly because it matters:** `netguard`'s socket guard is a monkeypatch of
`socket.socket.connect` **inside ELI's own interpreter**. An MCP server is a separate
OS process — usually `npx` or `uvx`, often Node or Go — whose network stack never
touches Python's socket module. Demonstrated directly: with `ELI_OFFLINE=1` and the
guard installed, the parent process is correctly refused with `OfflineError` while a
child process, inheriting the same environment, connects straight out.

So an MCP server is launched through `eli/plugins/subprocess_sandbox.py` — at install
(`mcp.probe()`) and in use (`eli/integrations/mcp/client.py`) alike — which applies the strongest
containment this machine has, counted only once it has been probed to work here:

- **Linux with bubblewrap (`bwrap`):** a server that did not declare the `network` permission
  gets no network at all (`--unshare-net`). The root is mounted read-only, `$HOME` and `/tmp`
  are replaced by empty tmpfs mounts, and only the program's own runtime, the paths named on
  its command line and the paths it declared (`read_paths`, `write_paths`, its `cwd`) are bound
  back; it also gets its own PID, UTS and IPC namespaces, `--die-with-parent` and
  `--new-session`.
- **Linux with only `unshare`:** the network is isolated; the filesystem is not.
- **No usable sandbox** (macOS, Windows, or a host that forbids user namespaces): the server
  runs with the account's full rights and network, ELI logs a warning, and the consent text says
  so.
- Every launch drops environment variables whose names contain TOKEN, SECRET, PASSWORD or
  API_KEY; on POSIX the child gets CPU-time and open-file limits, and on Linux
  `PR_SET_NO_NEW_PRIVS`.

There is **no eBPF, seccomp, landlock or firewall integration**, and `pip`, shell commands,
generated-code test runs and plugins granted `process_exec` are **not** launched in this
sandbox: ELI's offline switch cannot stop them, and ELI cannot see what they send. Containing a
child on Windows or macOS would need that platform's own egress control (WFP, a network
extension); that work does not exist yet.

- **In-process Python plugins** are covered by netguard at the socket boundary, plus
  the permission gate above. (A `ctypes` native call would bypass it, which is why
  `ctypes.CDLL` is refused outright by the manifest checker.)

`mcp.network_caveat()` returns the sentence every MCP consent screen must carry, derived from
what `subprocess_sandbox` will actually apply on this machine, so no UI can imply a containment
that does not exist.

What the MCP layer *does* guarantee is that a configured server actually works:
there is **one** config file ELI owns, installing runs a runtime preflight then a
real `initialize` + `tools/list` handshake, and an entry is written **only after a
server has answered**. A missing runtime or a process that is not an MCP server is
refused before the config is touched.

**ELI as an MCP server** (`eli/integrations/mcp/server.py`, `eli-mcp` / `--mcp-server`) is the
other direction: a client gets ELI's action surface (the executor's supported actions), never a
free-text prompt into the engine. Unless `ELI_MCP_ALLOW_CONTROL=1`, it withholds every action
that starts with a control prefix (`COMPUTER_USE`, `KEYBOARD`, `MOUSE`, `SHELL`, `RUN_`,
`EXECUTE`, `SELF_`, `CODE_`, `GAZE`, `SET_CLIPBOARD`, `SCHEDULE_`, `DELETE_`, `INSTALL`,
`UNINSTALL`, `UPGRADE`, `SMART_HOME`, `SEND_`) and every owner-only action
(`authority_gate.owner_only()`, §7), so CREATE_FILE, READ_FILE, SCREENSHOT and MEMORY_FORGET are
not exposed; if that list cannot be loaded it exposes nothing. A call to a withheld action is
refused before the executor is reached.


### 18. Fetching from sources the operator does not own (`eli/core/netguard.py`)

`guarded_urlopen` answers one question — is the network switch on? That is the right
question for ELI's own calls and the wrong one for a URL that came from a community
registry. urllib follows redirects silently and the socket guard permits loopback
unconditionally, so a hostile listing could aim a marketplace fetch at ELI's own API
server or a LAN device: server-side request forgery, with ELI as the confused deputy.
Demonstrated at the time — a 302 to `http://127.0.0.1/...` was followed and the body
handed back to the caller.

`safe_fetch` is what third-party content now goes through:

- **Scheme pinned** to http/https. `file:`, `ftp:` and `data:` can read local
  resources through the very same call.
- **Addresses filtered.** The host is resolved and refused if it lands on loopback,
  private, link-local (169.254.0.0/16 — cloud metadata), multicast or reserved
  space. `allow_private=True` exists for an operator running their own LAN registry
  and is never inferred from the URL, because that is what an attacker controls.
- **Every redirect hop re-validated.** Checking only the URL the caller passed is
  worth little; the interesting address is the last one, and the server picks it.
- **Body capped while reading** (32 MiB default, 8 MiB for a plugin), so a server
  omitting `Content-Length` cannot stream unbounded data into memory.
- **`Accept-Encoding: identity`** so a compressed response cannot expand past the cap,
  and an explicit verifying TLS context.

Stated rather than papered over: the host is resolved for validation and resolved
again by the connection, so DNS rebinding between the two can still land on a private
address. Closing that needs connecting to the validated IP while preserving SNI,
which the stdlib opener does not expose cleanly.

A registry whose URL is private is recorded as `allow_private` **at add time**, with a
warning. "Does not resolve" is a distinct error from "resolves somewhere private" —
conflating them once made an unreachable public registry look like a deliberate LAN
one and silently granted it local-network access.

### 19. Runtime capability enforcement (`eli/plugins/sandbox.py`)

Everything above gates a plugin *before* it runs. All of it is defeated by one fact:
an enabled plugin is `exec_module`'d into ELI's own interpreter, so the permission API
is **cooperative**. A plugin that passed the manifest check, the hash, the signature
and eleven scanners can simply `import socket` and never call a gated helper.

`sys.addaudithook` fires below the Python API, on the operation itself —
`socket.connect`, `open`, `subprocess.Popen`, `os.system`, `ctypes.dlopen` — and
raising inside the hook aborts it. The hook attributes each event to a plugin by
walking the stack for a frame inside a plugin package, then enforces that plugin's
**declared** capabilities and the operator's consent.

Verified directly: a plugin declaring only `notifications` had raw `socket.connect`,
raw `open()` and raw `subprocess.run` all blocked, while ELI's own file access was
untouched.

Properties, stated precisely because "sandbox" oversells it:

- **It cannot be uninstalled.** CPython exposes no way to remove an audit hook.
- **It enforces below the API.** Importing `socket` directly does not help.
- **It is not a boundary against native code.** A plugin running arbitrary machine
  code through a compiled extension is outside anything in-process — which is why
  `ctypes.dlopen` needs `process_exec` and the manifest checker refuses `ctypes.CDLL`
  outright.
- **It does not contain subprocesses.** A plugin granted `process_exec` spawns a real
  child and nothing here follows it. Same limit as netguard, which is why that
  capability is described to the operator as unlimited access.
- Loopback is exempt from `network`: ELI's own model server and local API live there.
- Plugins that shipped with ELI and have no manifest are treated as fully declared —
  breaking them to enforce a contract they never had would be a regression.

Installed before the first plugin is loaded, so no plugin's module-level code runs
ahead of it. `ELI_PLUGIN_SANDBOX=0` disables it, which is a real downgrade and logs a
warning.

### 20. One-click install — where consent is and is not implied

The quick path verifies, scans and installs on a single click, and stops for a full
review when there is genuinely something to decide. Getting that line wrong is bad in
both directions: block on ambient conditions and the quick path never fires, so the
operator learns to click through the review dialog without reading it; block on
nothing and the click is consent theatre.

**Blocks** (each a judgement only the operator can make): a non-clean scan; no
checksum in the listing, so the file cannot be matched to what was described;
requested permissions; PyPI dependencies; a price with no licence key entered; a plain-http
download URL.

**Does not block, reported instead**: ClamAV/YARA/blocklist not installed (partial
coverage) and the plugin being unsigned — both the normal state of a community
marketplace.

Even on the quick path the plugin arrives **switched off with no permissions**;
enabling is a separate, explicit answer.


### 21. Hosting a registry (and why GitHub Pages fits)

A registry is one static file — `index.json` over HTTPS. That is the whole hosting
requirement, which is deliberate: it keeps the marketplace something a community can
run for free, and keeps ELI's author out of the position of owning, moderating, or
being answerable for what strangers publish.

GitHub Pages happens to satisfy every constraint `safe_fetch` enforces — HTTPS with a
valid certificate, a public address, no redirect games — so it passes without any
special-casing. `tools/marketplace/registry_template/` is a working skeleton and
`tools/marketplace/publish.py` generates listings.

The publisher-side failures worth designing against, because each one lands on *users*
rather than the publisher:

| Mistake | What every user sees |
|---|---|
| stale `sha256` | a hard integrity refusal — reads as "this publisher ships broken plugins" |
| no `sha256` | the one-click install stops on every machine |
| plain-http `source` | the one-click install stops on every machine |
| under-declared `permissions` | the client refuses the plugin outright |

`publish.py` catches all four at publish time: it validates the manifest, checks the
code against the declared permissions, runs the same eleven scanners the user's
machine will run, computes the hash, and **refuses to emit a listing that would be
rejected on the other end**. Signing is optional (`--new-key` / `--sign-key`); an
unsigned plugin is reported as unverified rather than blocked, which is the honest
default when nobody is curating.

Reviewing listings as pull requests gives a public record of who added what, with CI
able to run `publish.py` over each change — without the registry operator hosting
anything beyond a static file.
