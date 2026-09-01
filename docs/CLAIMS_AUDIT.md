# Claims audit — what ELI v2 actually does

Written because a set of marketing claims about ELI was checked line-by-line against
the tree and a third of them described something other than what is here. This file is
the corrected version: every row is either verified against a file:line or struck.

Audited at v2.3.73 (September 2026). Current suite at **v2.3.73**:
**11,358 tests collected**, **11,300+ passed / 54 skipped / 2 xfailed**, 413 test files.
Re-run the checks with `.venv/bin/python -m pytest tests/claims/ -q`.

> Rule of thumb this file exists to enforce: **a capability ELI has, described by a
> mechanism ELI does not use, is still a false claim.** Four of the errors below were
> of exactly that kind — the feature was real, the explanation was invented.

---

## Verified — safe to claim

| Claim | Where it lives |
|---|---|
| DAG orchestrator with retries, exponential backoff and per-task fallback | `eli/core/dag.py:271-274, 361-373` (`retry_backoff * (2 ** attempt)`) |
| Layered memory: SQLite + FAISS vector index + knowledge graph | `eli/memory/vector_store.py`, `eli/memory/knowledge_graph.py`, 4 SQLite stores |
| Tamper-evident audit ledger — HMAC-SHA256 keyed hash chain | `eli/runtime/evidence_ledger.py`, `verify_chain()`; key at `config/.audit_hmac_key` (0600) or `$ELI_AUDIT_HMAC_KEY` |
| Offline by default; network access fails **closed** | `eli/core/netguard`, `should_block_network()` |
| Shell command gate (`RUN_CMD`) | **Denylist** of destructive patterns and dangerous executables — not an allowlist | `eli/execution/shell_gate.py` |
| `rm -rf /` and similar destructive patterns are blocked | `eli/execution/shell_gate.py:26` |
| Turnkey installers: Windows `.exe`, macOS `.dmg`, Linux AppImage | `.github/workflows/release.yml` orchestrates; the `.dmg` is `hdiutil create -format UDZO` + ad-hoc `codesign` in `packaging/macos/build-dmg.sh:32,53` |
| Guided first run: scans for GGUF models, suggests one that fits your VRAM, downloads in-app | `eli/core/hardware_profile.py:523` + `recommend()`; wired at `eli/gui/panels/startup.py:376`; `eli/core/model_download.py:361` |
| Scheduled jobs in natural language ("at 9am", "overnight"), surviving restarts | `eli/runtime/scheduled_tasks.py:112` (am/pm parser), nightly re-arm at `:336` |
| Drop-in plugin architecture with auto-discovery | `eli/plugins/base/base.py:20` — subclass `Plugin`, implement actions, `execute()`; `load_plugins()` discovers the package |
| Self-healing rollback after a bad self-applied patch | `eli/runtime/self_improvement.py:1019 revert_patch()`, `:979 _rollback_all()` (atomic across files) |
| Cross-platform mic auto-resolve (USB/Bluetooth/headset before built-in; live probe; Linux `PULSE_SOURCE` pin) | `eli/perception/mic_resolver.py`, `audio_stt.py`; `python -m eli.tools.mic_diag` |
| 227 capabilities | `capability_manifest.json` (`total`), enforced by `tests/claims/test_capability_manifest.py` |
| 11,358 tests collected across 413 files | Verified at v2.3.73: 11,358 collected / 11,300+ passing, 413 files. Stated as a floor, so ordinary growth keeps it true. |
| Reads txt, md, PDF, docx, **odt, epub** | `eli/plugins/document_reader/plugin.py`. `.odt`/`.epub` were advertised but not dispatched until this audit — see below. |

---

## Corrected — real capability, wrong mechanism

These were the dangerous ones: each names an implementation ELI does not contain.

| ❌ Claimed | ✅ Actual |
|---|---|
| CLIP visual anchors locate UI elements | **pytesseract OCR** — `_word_boxes_from_pytesseract`, `_score_text`. The `clip_model_path` setting is the vision-LLM **mmproj** and has nothing to do with UI targeting. |
| Rollback via `git reset --hard` | `.eli_bak` backup copy-restore. The string `git reset --hard` does not appear anywhere in the repository, and ELI never touches your git history. |
| Inherit `BaseTool`, implement `execute()`, drop into `tools/` | Inherit `Plugin` from `eli.plugins.base`, drop into `eli/plugins/`. `execute()` and auto-discovery are real; the class and directory names were not. |
| Dependencies pinned with `poetry.lock` / `uv.lock` | `requirements.lock.txt`, frozen and verified by `install.sh`. Neither Poetry nor uv is used. |
| The 12-stage pipeline is parallelised across the DAG | The pipeline is **sequential**; `eli/kernel/` never imports `eli.core.dag`. The DAG is real and drives the **agent bus** (`eli/cognition/agent_bus.py:689, 2150`) plus the coding and self-improvement paths — 8 modules. Claim the agent fleet, not the pipeline. |
| Quick mode skips the orchestrator / agent bus | Since **v2.3.37**, **all CHAT modes** including Quick run the gradient orchestrator + 15-agent bus at scaled depth. Quick uses a **single-pass reasoning algorithm**, not a pipeline bypass. |
| "12-stage retrieval pipeline" | The **12 stages are cognition** (S01–S12 in `pipeline_trace.py`). Retrieval (HyDE, vector, FTS, KG, re-rank) is work **inside** those stages — usually S06–S07 — not a separate 12-step retrieval pipeline. |
| "Each reasoning mode is genuinely multi-pass" (including Quick) | **Normal–Expert** are multi-pass (CoT, self-consistency, ToT, constitutional). **Quick** is single-pass reasoning at light orchestrator depth, with optional **background deepening** after the fact. |

---

## Struck — not in this codebase

| Claim | Finding |
|---|---|
| Progressive web app on port **8502** | The server listens on **8081** (`api/server.py:1683`). `8502` appears nowhere in the tree. |
| `pynvml` GPU telemetry | Zero occurrences; not a dependency. VRAM is read from kernel signals via `hardware_profile` — `nvidia-smi`/NVML parsing was removed deliberately so AMD and Intel Arc are first-class. |
| "Safe Mode" | Does not exist. No such setting, flag, or code path. |
| Immutable `Context` objects passed between stages via Pydantic | No `pydantic` import in `eli/kernel/` or `eli/core/`. Stages pass plain dicts; there is no immutability guarantee. |
| The full suite runs on Windows, macOS and Linux on every PR merge | Now **partly** true — see below. It was not true at all when claimed. |

### Document formats: fixed, not struck

`.odt` and `.epub` were listed as readable and were not. The failure mode was worse
than a plain gap: both are zip containers, neither was in `_TEXT_SUFFIXES`, so any such
file under the 2MB threshold fell through to the plain-text branch and returned decoded
zip bytes with `ok: True` — mojibake presented as the document's contents rather than an
honest refusal. Both are now dispatched (stdlib `zipfile` + `ElementTree`/`HTMLParser`;
no new runtime dependency), EPUB is read in spine order, and any unrecognised binary is
now refused instead of decoded. Locked by `tests/test_document_formats.py`.

---

## CI: what the gate actually is

Before this audit, **no workflow had a `pull_request` trigger**. The only cross-OS
pytest job (`cross-platform-smoke.yml`) was `workflow_dispatch` — manual — so nothing
verified a merge on Windows or macOS unless someone remembered to click the button. The
stated reason was avoiding metered Actions minutes, which does not apply: this
repository is public, and Actions on standard runners is free and unmetered for public
repos. The cost of the gate was zero and it was switched off anyway.

It now runs on every pull request and every push to `main`, across
`ubuntu-latest / macos-latest / windows-latest` × Python 3.10 and 3.12 — **verified
green on all six jobs**, not merely configured.

Turning it on immediately paid for itself. The first run failed all six jobs on two
defects that had been latent for as long as the workflow had existed, invisible
precisely because nothing ever executed it:

1. **Every pytest step used the bare `pytest` console script.** `-m` puts the working
   directory on `sys.path`; the console script does not, and the top-level `api` package
   is not installed by `pip install -e .`. So `import api.server` failed,
   `tests/test_api_server.py` hit its own module-level skip guard, and the step reported
   "collected 0 items / 1 skipped" — pytest exit code 5. Locally the two differ starkly:
   `python -m pytest` → 78 passed; bare `pytest` → exit 5. The identical mistake once
   aborted a release from `scripts/build_packages.sh`.
2. **Windows ran a bash heredoc through PowerShell.** The dashboard step is written as
   `python - <<'PY'`, which PowerShell cannot parse — a `.ps1` `ParserError`. That step
   could never have passed on Windows. The job now pins `shell: bash` so all three OSes
   execute identical commands.

Neither was a regression. Both were pre-existing, and both are exactly the class of
defect a gate that never runs cannot catch.

**Claim it accurately:** this is a curated cross-platform gate — imports, the headless
FastAPI server, all 16 dashboard read-endpoints, the 78-case API suite, first-run DB
build, and ten self-contained unit/claims files. It is **not** the full 11,067 test
suite, because most of that suite needs a GGUF model, a display, or generated artifacts
that do not exist on a runner. The honest sentence is:

> Every change is gated on Linux, macOS and Windows across two Python versions; the
> full 9,200-test suite runs locally against the packaged environment.

---

## Maintaining this file

`tests/claims/` is the enforcement layer — it examines the project against its own
claims rather than trusting prose. `tests/claims/test_readme_counts.py` fails the build
if the README's capability count drifts from the manifest, or if a document format is
advertised that the reader cannot actually open. `tests/claims/test_public_marketing_claims.py`
locks mechanism claims (15 agents, 12-stage cognition pipeline, shell denylist, port 8081,
Quick-not-bypass prose, etc.) to the code that implements them. Add a test there before
adding a claim here.
