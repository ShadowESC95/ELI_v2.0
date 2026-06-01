# ELI Security Posture

ELI runs locally with real OS reach (shell, file, app control) plus a
user-extensible agent/plugin system — so the security model matters. It is
**fail-closed** by design. Spans `eli/runtime/security.py`, the executor gate,
the engine input sanitiser, the memory SQL validator, and the agent trust
registry.

## 1. Shell command gate (`runtime/security.py` `SecurityManager`)

- `is_command_allowed(cmd)`:
  - `ELI_FULL_CONTROL=1` → allow all.
  - `ELI_ALLOWED_CMDS` contains `*` → allow all.
  - `ELI_ALLOWED_CMDS` unset **and** no full-control → **blocked (fail-closed)**;
    logs a warning explaining how to opt in. (Always allows the project's own
    `.venv/bin/python`.)
- `safe_subprocess(cmd, timeout)` — validates `cmd[0]` against the allowlist
  before running; capture_output, timeout-bounded, never `shell=True`.
- **Defence in depth:** `executor_enhanced._shell_command_allowed_fallback`
  mirrors this exact logic, so if `SecurityManager` fails to import, the executor
  still fails **closed** (never fail-open). Explicit comment to that effect.

## 2. Filesystem & app gates (`SecurityManager`)

- `is_path_allowed(path)` — must resolve within allow-roots
  (`project_root` + `$HOME` + `ELI_ALLOW_ROOTS`). Uses `Path.resolve()` +
  `relative_to`, so `..` traversal can't escape.
- `is_app_allowed(app)` — explicit `ELI_ALLOWED_APPS`, else a curated
  default-safe set (settings, file manager, editor, calculator, terminal,
  browser, mail). `ELI_FULL_CONTROL` bypasses.

## 3. Prompt-injection guard (`kernel/engine.py`)

`_ELI_INJECTION_PATTERNS` (regex) + `_eli_sanitize_user_input`:
- Matches classic jailbreak/role-override prefixes — `### system:`,
  "ignore/disregard/forget (all) previous instructions", "you are now a
  dan/jailbreak/unrestricted/free" — and replaces the matched span with
  `[filtered]` (keeps the rest of the message).
- Strips control characters.
- Runs before the input reaches the LLM, so injected role-overrides are
  neutralised but legitimate content survives.

## 4. SQL identifier validation (`memory/memory.py`)

`_IDENTIFIER_RE = ^[A-Za-z_][A-Za-z0-9_]*$` + `_validate_identifier(name)` —
called before **any** f-string interpolation of a table/column name into SQL
(`_validate_identifier(table, "table")`, column DDL first-token check). Raises
`ValueError` on anything non-conforming. Closes the one place dynamic SQL is
unavoidable (parameterised values are used everywhere else).

## 5. Custom-agent trust registry (`cognition/agent_bus.py`)

Custom agents (GUI wizard / `$ELI_CUSTOM_AGENTS_DIR`) are **SHA-256 hash-gated**
against `config/trusted_agents.json`. Unknown or modified files are skipped with
a SECURITY debug line; approve via `eli --trust-agent <path>`. `ELI_TRUST_ALL_AGENTS=1`
bypasses for dev only. Fail-closed (missing/mismatched hash ⇒ not loaded). See
`orchestration_and_agents.md`.

## 6. "Generated" scripts are pre-vetted, not sandboxed (`runtime/generated_script_guard.py`, 1k LOC)

Important nuance: this is **not** an arbitrary-code sandbox. It's a library of
~5 hand-written, reviewed scripts (`_write_gpu_memory_watch_script`,
`_write_relative_time_function_script`, `_write_type_ia_redshift_script`,
`_write_quantum_decoherence_depth_script`, `_write_ton_618_mass_density_script`)
that ELI *writes to disk* when asked for those capabilities. So when ELI "writes
a script," it emits a vetted canned artifact rather than executing LLM-authored
code. That's a deliberately conservative posture — safe, but it means
script-generation is limited to the curated set (several are physics-domain,
reflecting the author's work).

> **Code-health flag:** `generated_script_guard` uses the same stacked-override
> pattern as the grounding gate — two `install()` definitions chained via
> `_ELI_SQLITE_SCRIPT_PREVIOUS_INSTALL`. Works, but layered rather than edited.

## Honest assessment

- **Strong:** the gates are real and **fail-closed** — shell blocked by default,
  fallback mirror prevents fail-open, path traversal contained, identifiers
  validated, agents hash-trusted, injection prefixes stripped, and "generated"
  code is actually pre-reviewed. This is well above the norm for local-AI
  projects, which routinely ship wide-open shell access.
- **Weak / watch:**
  1. The injection guard is **pattern-based** — it catches known prefixes, not
     novel/obfuscated injections (no model-side defence). Reasonable for a
     single-user local tool, insufficient if ever multi-tenant.
  2. `ELI_FULL_CONTROL=1` is a single env var that disables *all* gates at once —
     convenient, but a blunt instrument; there's no middle "allow file but not
     shell" tier beyond the per-axis env vars.
  3. The default-safe app/command sets are Linux/GNOME-flavoured; cross-platform
     redistribution needs per-OS sets.
  4. Pre-vetted-scripts approach is safe but doesn't scale — genuinely dynamic
     capability generation would need a real sandbox (resource limits, seccomp,
     subprocess isolation), which doesn't exist yet.
