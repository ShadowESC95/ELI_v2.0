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

## 6. Code generation & self-modification — three paths

ELI has **three** distinct codegen paths, with escalating capability and
matching safeguards:

1. **Pre-vetted canned library** (`runtime/generated_script_guard.py`, 1k LOC) —
   ~5 hand-written, reviewed scripts (`_write_gpu_memory_watch_script`,
   `_write_type_ia_redshift_script`, `_write_ton_618_mass_density_script`, …)
   that ELI *writes to disk* on request. No LLM code is executed; safe but fixed
   to the curated set (several physics-domain).
2. **`GENERATE_SCRIPT`** (`execution/executor_enhanced.py`) — *real* LLM codegen.
   Detects language/intent, prompts for frontier-quality code, then gates it:
   - `_verify_python_module_apis` — imports the referenced libraries and confirms
     `module.attr` references actually exist (catches hallucinated APIs).
   - `_quality_reject_reason` — rejects refusals, stubs, too-short, no-real-compute,
     missing-plot, `required=True`-without-default, SyntaxError.
   - **`_sandbox_run_python` (added)** — executes the candidate in a bounded,
     isolated subprocess (temp cwd, scrubbed env, `MPLBACKEND=Agg` so `plt.show()`
     can't block, wall-clock timeout `ELI_GENSCRIPT_RUN_TIMEOUT`=20s, generous
     `RLIMIT_CPU`; **no `RLIMIT_AS`** — it breaks numpy/scipy). A genuine
     unhandled traceback is fed back as repair feedback into a **3-attempt
     regenerate loop**; timeouts / signal kills / missing-optional-deps are
     tolerated (never reject legit heavy scientific scripts). Disable with
     `ELI_GENSCRIPT_VERIFY_RUN=0`.
3. **Self-patching** (`runtime/self_improvement.py` `SelfImprovementEngine`) —
   ELI modifies its *own* source for recurring failures. Gated behind
   `auto_patch_enabled` (**default off**), ≤2 patches/cycle. Safeguards:
   verbatim-`old`-match → `ast.parse` → timestamped backup (+ canonical
   `.eli_bak`) → write → `py_compile` → **differential import smoke-test
   (added)**: the patched module is imported in an isolated subprocess and
   **auto-reverted** if it no longer loads, but only when the module imported
   cleanly *before* the patch (so missing optional deps don't cause false
   reverts). Project-root-confined, `.py`-only, logged to the `code_patches`
   table.

> **Code-health flag:** `generated_script_guard` uses the same stacked-override
> pattern as the grounding gate — two `install()` definitions chained via
> `_ELI_SQLITE_SCRIPT_PREVIOUS_INSTALL`. Works, but layered rather than edited.

> **Possible next step (not done):** the self-patch loop verifies the module
> still *imports*; it does not yet re-run the original failing input to confirm
> the patch actually *fixes* the failure. A behavioural/test re-run would close
> that last gap.

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


---

## Update Advisory — 2026-06-01
- Code generation (GENERATE_SCRIPT/CODE_SOLVE) and self-upgrade now route through the coding agent, whose sandbox (`eli/coding/sandbox.py`) bounds execution (temp cwd, scrubbed env, timeout, RLIMIT_CPU, Agg). §6 (three codegen paths) reflects this.
- New: in-process background task threads (`eli/runtime/background_tasks.py`) — threads share the process (no OS isolation); a running thread cannot be force-killed. For untrusted heavy work prefer the subprocess `jobqueue`.


---

## Update Advisory — 2026-06-07
- Posture unchanged (fail-closed). Clarification: web is a **toggle-gated first-class capability** — when the Net toggle (`network_enabled`) is on, web search / news / weather all work; when off, `netguard`'s process-wide socket guard fail-closes. ‘No external APIs’ means no paid third-party SDKs/OAuth, not ‘no network’.

---

## Update Advisory — 2026-06-08 (ELI Full Control master override)
- New `eli/core/full_control.py` — a single master override, **default OFF**, whose **sole
  source of truth is the `full_control` setting** (the GUI toggle; **no environment
  variable**, so nothing can conflict). When ON, every gate that calls `is_full_control()`
  steps aside: netguard network gating, `approval_engine` autonomy approval, the
  self-improvement auto-patch gate, and the executor/`security.py` command-safety floor (the
  destructive-pattern block + `_DENIED_EXECUTABLES` denylist + the `is_command_allowed` /
  `is_app_allowed` allowlists). OFF = the documented fail-closed behaviour, unchanged. The
  pre-existing `ELI_FULL_CONTROL` env reads were all converted to the setting. Each gate
  checks at its own point — no hidden global state — so toggling OFF restores everything at
  once. GUI: a red "Full Control" toggle by the Net toggle, behind a confirmation dialog.
