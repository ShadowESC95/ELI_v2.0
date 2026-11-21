# Claims audit — what ELI v2 actually does

Written because a set of marketing claims about ELI was checked line-by-line against
the tree and a third of them described something other than what is here. This file is
the corrected version: every row is either verified against a file:line or struck.

Re-audited at v2.5.36 (2026-11-20); file:line references are to that tree. The suite at
**v2.5.36**: **593 test files** (`tests/**/test_*.py`, 15 of them in `tests/claims/`)
defining **5,591 test functions** before parametrisation — counted from the source; the
collected and passing totals are only known by running the suite.
Re-run the checks with `.venv/bin/python -m pytest tests/claims/ -q`.

> Rule of thumb this file exists to enforce: **a capability ELI has, described by a
> mechanism ELI does not use, is still a false claim.** Four of the errors below were
> of exactly that kind — the feature was real, the explanation was invented. A fifth was
> found in this file itself (the `pynvml` row): the correction named a mechanism that
> was never removed.

---

## Verified — safe to claim

| Claim | Where it lives |
|---|---|
| DAG orchestrator with retries, exponential backoff and per-task fallback | `eli/core/dag.py:256-259` (`Task.retries`, `retry_backoff`, `fallback`), `:346-363` (attempt loop; `retry_backoff * (2 ** attempt)` at `:358`, fallback at `:359-363`) |
| Layered memory: SQLite + FAISS vector index + knowledge graph | `eli/memory/vector_store.py` (FAISS), `eli/memory/knowledge_graph.py` (its tables live in `user.sqlite3`, `eli/core/paths.py` `knowledge_graph_db_path()`); the SQLite stores are seeded from the four templates in `config/templates/db/` (user, agent, coding_memory, system_index) |
| Forgetting reaches what was derived from it | Forgotten memories are compacted out of the vector index files (`eli/memory/vector_store.py:315` `compact_tombstones()`, also run in the daily upkeep); claims resting only on them are deleted; the keyword fallback skips them |
| Tamper-evident audit ledger — HMAC-SHA256 keyed hash chain | `eli/runtime/evidence_ledger.py:79-98` (key: `$ELI_AUDIT_HMAC_KEY`, else `config/.audit_hmac_key` written 0600), `:109` (HMAC-SHA256), `:398` `verify_chain()` |
| Offline by default; network access fails **closed** | `eli/core/netguard.py:78-94` (`_net_allowed()`: denies when the policy cannot be read), `:97` `should_block_network()`, `:485` `install_socket_guard()` |
| Shell command gate (`RUN_CMD` / `SHELL_EXEC`): a **denylist** of destructive patterns and dangerous executables — not an allowlist — judging every command in the line | `eli/execution/shell_gate.py:28` `_BLOCKED_PATTERNS`, `:71` `_DENIED_EXECUTABLES`, `:105` `_WRAPPERS` (sudo, env, nice, timeout, xargs, busybox …), `:136` `_commands_in()` (`;` `&&` `\|\|` `\|` `&`, newlines, `$( )`, `<( )`, backticks), `:158` `_what_runs()` (incl. `env -S`), `:188` `_refused_part()` (incl. `find -delete` / `-exec rm`), `:204` `check_command()`; called from `eli/execution/executor_enhanced.py:5922`. Not gated by it: habit-rule commands (`eli/planning/proactive_daemon.py` `execute_habit`, shell, off with `ELI_NO_HABIT_SHELL=1`) |
| `rm -rf /` and similar destructive patterns are blocked | `eli/execution/shell_gate.py:29` |
| API members/viewers cannot have ELI run the owner's actions | `eli/runtime/authority_gate.py` `owner_only()` / `check()`; checked at the executor entry (`eli/execution/executor_enhanced.py:15604-15614`) and on `/v1/execute` (`api/server.py:1033-1038`); the API sets the caller's role for each turn (`api/server.py:269` `_turn_for()`) |
| Tokenless / loopback admin only for a request that names this machine (DNS-rebinding defence) | `api/server.py:154` `_named_as_this_machine()` (IP address, `localhost`, the machine's own names, `ELI_API_ALLOWED_HOSTS`), applied in `:181` `_resolve_principal()` |
| Turnkey installers: Windows `.exe`, macOS `.dmg`, Linux AppImage | `.github/workflows/release.yml` orchestrates; the `.dmg` is ad-hoc `codesign` + `hdiutil create -format UDZO` in `packaging/macos/build-dmg.sh:32,53` |
| Guided first run: scans for GGUF models, suggests one that fits your VRAM, downloads in-app | `eli/core/hardware_profile.py:1195` `detect_hardware()`, `:1739` `discover_models()`, `:2484` `recommend()`; wired at `eli/gui/panels/startup.py:976-1008`; in-app download `startup.py:1444` → `eli/core/model_download.py:359` `download_model()` |
| Scheduled jobs in natural language ("at 9am", "overnight"), surviving restarts | `eli/runtime/scheduled_tasks.py:104` `parse_when()` (am/pm at `:116`), re-armed on boot by `:507` `restore_scheduled_tasks()`, recurring jobs re-armed at `:442-446` |
| Drop-in plugin architecture with auto-discovery | `eli/plugins/base/base.py:20` — subclass `Plugin`, implement actions, `execute()` (`:47`); `load_plugins()` (`:59`) discovers the package |
| Self-healing rollback after a bad self-applied patch | `eli/runtime/self_improvement.py:1497` `revert_patch()`, `:1311` `_rollback_all()` (atomic across files) |
| Cross-platform mic auto-resolve (USB/Bluetooth/headset before built-in; live probe; Linux `PULSE_SOURCE` pin) | `eli/perception/mic_resolver.py`, `audio_stt.py`; `python -m eli.tools.mic_diag` |
| 232 capabilities | `capability_manifest.json` (`total`), enforced by `tests/claims/test_capability_manifest.py`, which rebuilds the list from the code (`CapabilitySync`) and compares |
| 593 test files, 5,591 test functions | Counted from the source at v2.5.36 (`tests/**/test_*.py`; module-level `test_*` functions and `Test*` class methods). Parametrised cases make the collected count larger; it is only known by running the suite. |
| Reads txt, md, PDF, docx, **odt, epub** | `eli/plugins/document_reader/plugin.py:170-186`. `.odt`/`.epub` were advertised but not dispatched until this audit — see below. |

---

## Corrected — real capability, wrong mechanism

These were the dangerous ones: each names an implementation ELI does not contain.

| ❌ Claimed | ✅ Actual |
|---|---|
| CLIP visual anchors locate UI elements | **pytesseract OCR** — `_word_boxes_from_pytesseract` (`eli/perception/screen_locator.py:95`), `_score_text` (`:75`). The only `clip_model_path` in the tree is llama.cpp's keyword for the vision model's **mmproj** projector (`eli/perception/vision.py:508`) and has nothing to do with UI targeting. |
| Rollback via `git reset --hard` | `.eli_bak` backup copy-restore (`eli/runtime/self_improvement.py:1127-1130`, `:1304-1305`). No code runs `git reset --hard`, and self-patch rollback never touches git. (The separate `SELF_UPGRADE` action on a source checkout runs `git pull --ff-only`, `eli/kernel/self_upgrade.py:490`.) |
| Inherit `BaseTool`, implement `execute()`, drop into `tools/` | Inherit `Plugin` from `eli.plugins.base`, drop into `eli/plugins/`. `execute()` and auto-discovery are real; the class and directory names were not. |
| Dependencies pinned with `poetry.lock` / `uv.lock` | `requirements.lock.txt`: `install.sh` installs from it by default on Linux (`requirements-macos.txt` on macOS, the ranges with `--latest`) and falls back to the ranges where a pin cannot be met on that Python; release builds take their constraints from it (`packaging/lock_constraints.py`). Neither Poetry nor uv manages dependencies (`scripts/eli_env.py` only looks for Pythons that uv or pyenv installed). |
| The 12-stage pipeline is parallelised across the DAG | The pipeline is **sequential**; `eli/kernel/` never imports `eli.core.dag`. The DAG is real and drives the **agent bus** (`eli/cognition/agent_bus.py:731, 2257`) plus the coding, self-improvement, test-generation/review, command-dependency and evidence-planning paths — 10 modules. Claim the agent fleet, not the pipeline. |
| Quick mode skips the orchestrator / agent bus | Since **v2.3.37**, **all CHAT modes** including Quick run the gradient orchestrator + 15-agent bus at scaled depth; Quick fans out a lean set (system, orchestrator and critic, plus file_code for code questions — `eli/cognition/reasoning_modes.py:660` `mode_chat_agent_profile()`). Quick uses a **single-pass reasoning algorithm**, not a pipeline bypass. |
| "12-stage retrieval pipeline" | The **12 stages are cognition** (S01–S12 in `pipeline_trace.py`). Retrieval (HyDE, vector, FTS, KG, re-rank) is work **inside** those stages — usually S06–S07 — not a separate 12-step retrieval pipeline. |
| "Each reasoning mode is genuinely multi-pass" (including Quick) | **Normal–Expert** are multi-pass (CoT, self-consistency, ToT, constitutional). **Quick** is single-pass reasoning at light orchestrator depth, with optional **background deepening** after the fact. |

---

## Struck — not in this codebase

| Claim | Finding |
|---|---|
| Progressive web app on port **8502** | The server listens on **8081** by default (`eli/runtime/server_util.py:53`; `--port` > `ELI_API_PORT` > the saved `api_port` setting > 8081, bound at `api/server.py:2276`; the GUI moves to the next free port when another program holds it). `8502` appears in no code — only as a token id in `models/phi-3-mini-base/tokenizer.json` and in the claims test that checks for it. |
| `pynvml` GPU telemetry | Zero occurrences in the code and the dependency files; not a dependency. NVIDIA VRAM is read by running **`nvidia-smi`** (`eli/core/hardware_profile.py:392` `nvidia_smi_path()`, used by `:1195` `detect_hardware()`); AMD, Intel and Qualcomm GPUs on Linux are found through the kernel's DRM sysfs (`:643`, `/sys/class/drm`). An earlier version of this row said `nvidia-smi` parsing had been removed; it never was. |
| "Safe Mode" | Not a mode of the app, only a start flag: `scripts/eli_startup.sh --safe-mode` (`RUN_ELI.sh --safe-mode`) sets `ELI_SAFE_MODE=1`, and ELI then starts no proactive daemon and loads no plugin at start (`eli.core.config.safe_mode()`). Nothing else changes, and there is no setting for it. |
| Immutable `Context` objects passed between stages via Pydantic | No `pydantic` import in `eli/kernel/` or `eli/core/`. Stages pass plain dicts; per-turn values live in `contextvars` (`eli/kernel/request_context.py`); there is no immutability guarantee. |
| The full suite runs on Windows, macOS and Linux on every PR merge | Now **partly** true — see below. It was not true at all when claimed. |

### Document formats: fixed, not struck

`.odt` and `.epub` were listed as readable and were not. The failure mode was worse
than a plain gap: both are zip containers, neither was in `_TEXT_SUFFIXES`, so any such
file under the 2MB threshold fell through to the plain-text branch and returned decoded
zip bytes with `ok: True` — mojibake presented as the document's contents rather than an
honest refusal. Both are now dispatched (stdlib `zipfile` + `ElementTree`/`HTMLParser`;
no new runtime dependency), EPUB is read in spine order, and an unrecognised binary (NUL
bytes in its first 4 KB) is now refused instead of decoded
(`eli/plugins/document_reader/plugin.py:170-186`). Locked by `tests/test_document_formats.py`.

---

## CI: what the gate actually is

Before this audit, **no workflow had a `pull_request` trigger**. The only cross-OS
pytest job (`cross-platform-smoke.yml`) was `workflow_dispatch` — manual — so nothing
verified a merge on Windows or macOS unless someone remembered to click the button. The
stated reason was avoiding metered Actions minutes, which does not apply: this
repository is public, and Actions on standard runners is free and unmetered for public
repos. The cost of the gate was zero and it was switched off anyway.

It now runs on every pull request and every push to `main` that changes code (changes
to only `*.md`, `*.pdf`, `blueprints/` or `docs/` are skipped), across
`ubuntu-latest / macos-latest / windows-latest` × Python 3.10, 3.12 and 3.13 — nine jobs.
The ceiling is 3.13, not the newest CPython: `faiss-cpu` had no 3.14 wheel for Windows
when `3.x` resolved to it. All nine were green on the last push checked (2026-11-03).

Turning it on immediately paid for itself. The first run failed all six jobs (two Python
versions then) on two defects that had been latent for as long as the workflow had
existed, invisible precisely because nothing ever executed it:

1. **Every pytest step used the bare `pytest` console script.** `-m` puts the working
   directory on `sys.path`; the console script does not, and the top-level `api` package
   is not installed by `pip install -e .`. So `import api.server` failed,
   `tests/test_api_server.py` hit its own module-level skip guard, and the step reported "collected 0 items / 1 skipped" — pytest exit code 5.
   Locally the two differed starkly: `python -m pytest` → 78 passed (the file's count
   then); bare `pytest` → exit 5. The identical mistake once aborted a release from
   `scripts/build_packages.sh`.
2. **Windows ran a bash heredoc through PowerShell.** The dashboard step is written as
   `python - <<'PY'`, which PowerShell cannot parse — a `.ps1` `ParserError`. That step
   could never have passed on Windows. The job now pins `shell: bash` so all three OSes
   execute identical commands.

Neither was a regression. Both were pre-existing, and both are exactly the class of
defect a gate that never runs cannot catch.

**Claim it accurately:** this is a curated cross-platform gate — imports, the headless
FastAPI server, all 16 dashboard read-endpoints, the API suite (`tests/test_api_server.py`,
81 cases), first-run DB build, the blank-template check, the cross-platform audit, 33
self-contained unit files, five claims files, the router eval cases and the marketing-claims
file. It is **not** the full suite, because most of that suite needs a GGUF model, a
display, or generated artifacts that do not exist on a runner. The whole suite does run
in CI before every release: the release workflow's "test suite (real libraries)" job runs
it on Linux against the libraries the release is built from, and nothing is published
unless it passes. The honest sentence is:

> Every code change is gated on Linux, macOS and Windows across Python 3.10, 3.12 and
> 3.13; the whole suite runs on Linux before every release publishes, and locally.

---

## Maintaining this file

`tests/claims/` is the enforcement layer — it examines the project against its own
claims rather than trusting prose. `tests/claims/test_readme_counts.py` fails the build
if the README's capability count drifts from the manifest, or if a document format is
advertised that the reader cannot actually open. `tests/claims/test_public_marketing_claims.py`
locks mechanism claims (15 agents, 12-stage cognition pipeline, shell denylist, port 8081,
Quick-not-bypass prose, etc.) to the code that implements them. Add a test there before
adding a claim here.
