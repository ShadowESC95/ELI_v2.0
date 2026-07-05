# Session — 2026-07-01: Web/News Hardening, Test Coverage & Code-Health Pass

Complete record of everything run and produced this session. Numbers are measured
on the real interpreter (`.venv/bin/python`); coverage is reproducible via
`scripts/coverage_full.sh`. Companion: [COVERAGE methodology](../docs/COVERAGE.md).

---

## 1. Fixes shipped (web / news / learning)

| Commit | Fix |
|--------|-----|
| `826e97d` | **Stable LAN API token + Rotate button** — token persisted under `config_dir()` (0600) and reused across restarts, so a paired phone is no longer stranded on a 401 each restart; explicit rotate to retire devices. |
| `85d292c` | **Dataset builder reads the real DBs** — `USER_DB`/`AGENT_DB` resolve from `paths.db_dir()`, not a hardcoded `artifacts/db` path (was opening empty DBs on any per-user install). |
| `e57812b` | **Self-healing PWA fetch** — retries a connection-establishment failure (Wi-Fi power-save wake) with backoff, scoped so a streamed reply can't be double-delivered. |
| `c6cab51` | **News freshness disclosure** — offline/stale read now states it's cached with the age, forbidden from implying "today". |
| `1ddf4de` | **News interest recency gate** — the "relevant to you" half drops matches older than the window (no more 2-week-old arXiv shown as current). |
| `436426a` | **Second interest path gated** — `interest_news_block` recency-gated too. |

---

## 2. Test coverage — new suites (per-module before → after)

13 suites, **143 test functions (~200 cases)**, all green, all asserting the code's
real contracts (bias toward security/privacy-critical paths). Two lanes run
un-mocked (`--noconftest`) because the fast suite mocks pydantic/llama_cpp; both
self-skip under the mocked suite so they never break it.

| Suite | Target | Before | After |
|-------|--------|:------:|:-----:|
| `test_api_server.py` | `api/server.py` (auth/RBAC + endpoints) | 0% | **53%** |
| `test_engine_integration_live.py` | full pipeline, real GGUF (live lane) | — | 19% of `eli/` |
| `test_deterministic_grounding.py` | `deterministic_grounding_gate` | 11% | **24%** |
| `test_news_synthesis.py` | `news_synthesis` | 14% | **33%** |
| `test_executor_helpers.py` | executor helpers — fail-closed shell gate | — | security lines |
| `test_control_contracts.py` | `control_contracts` (anti-confab guard) | 49% | ↑ |
| `test_response_surface.py` | `user_visible_response_surface` | 30% | **58%** |
| `test_live_introspection.py` | `live_introspection` | 32% | **58%** |
| `test_grounded_remediation.py` | remediation yes/no + state gate | 18% | ↑ |
| `test_memory_evidence.py` | `memory_evidence` | 12% | **77%** |
| `test_deterministic_introspection.py` | diagnostic-action classifier | 53% | ↑ |
| `test_context_synthesiser.py` | persona handoff builder | 54% | ↑ |
| `test_operator_policy.py` | autonomy governance gate | 42% | **88%** |

**Security/privacy-critical coverage (what an auditor checks first):** bearer/RBAC
auth + every `_resolve_principal` branch + the 401/403/200 live gate; the
fail-closed shell allowlist (nothing runs without Full Control or `ELI_ALLOWED_CMDS`);
the hardcoded-user-path + merge-marker scanners; the anti-confabulation guards
(`output_violates_evidence`, the deterministic renderer, grounding-into-context);
DB-path isolation.

---

## 3. Coverage infrastructure

- **`.coveragerc`** — parallel/combinable config.
- **`scripts/coverage_full.sh`** — one command runs all three lanes (mocked unit +
  real-FastAPI web + real-GGUF live engine) and combines them into one report.
- **`docs/COVERAGE.md`** — methodology + security-critical coverage + the JUSTIFIED
  exclusions (interactive GUI / hardware I/O / per-backend GPU) for external review.

---

## 4. Combined coverage progression (measured)

| Checkpoint | Combined (all) | Testable (ex-GUI) |
|-----------|:--------------:|:-----------------:|
| Baseline (single mocked lane) | 35% | — |
| After web + live-engine lanes | 38.0% | 45.8% |
| + grounding + news | 39.0% | 46.5% |
| + executor + control-contracts | 39.1% | 46.6% |
| + response-surface + live-introspection + memory-evidence + remediation | 39.5% | 47.1% |
| + introspection + context-synth + operator-policy | 39.5% | 47.1% |

Final measured this session: **39.5% combined / 47.1% testable** — unit lane **7,193
passed** / 5 known `smart_home` reds, web lane 72, live lane 15. The per-module
gains (e.g. `operator_policy` → 88%, `memory_evidence` → 77%) land on top of
coverage the live lane already contributes, so the headline moves less than the
module deltas suggest.

**Why the combined % moves slowly:** `eli/gui` is 12,662 statements at 0.6% — ~26%
of all uncovered lines — and is the documented can't-run-headless exclusion. The
**testable surface (ex-GUI)** is the metric that reflects the work; the cognitive
core / coding agent sit at 50–85%.

---

## 5. Code-health analysis (god files: engine.py, executor_enhanced.py)

Read-only scan feeding the comment-trim + refactor pass:

- **Comment clutter:** 184 banner/`PHASE`/`_V1` marker lines (132 engine / 52
  executor) + 81 long "narrated" block comments — iterative-AI residue to trim.
- **Dead code (vulture, high-confidence):** 10 unused imports in the executor
  (`IntrospectionAgent`, `copy_to_clipboard`, `LINUX`, `MACOS`, `_SPath`×4, `_dsp`,
  `_get_memory`) + 1 unused variable (`compact_override`, engine.py).
- **Refactor targets:** ~24 version/phase-suffixed patch helpers to consolidate;
  the 8-override `render_action` chain in `deterministic_grounding_gate`. No true
  top-level duplicate function names.

---

## 6. Attribution & housekeeping

- Commits authored **ShadowESC95** with `Co-authored-by: Claude Opus 4.8` (per the
  2026-07-01 preference change).
- README landing page rewritten in a plainer first-person voice; scale/test numbers
  refreshed across the living blueprints; PDFs regenerated.

---

## 6a. Code-health cleanup — done so far

- **Dead code removed** (`02b8b0d`): 6 unused executor imports (`IntrospectionAgent`,
  `copy_to_clipboard`, `LINUX`, `MACOS`, `_SPath`×4, `_dsp`, `_get_memory`).
- **Scaffolding stripped** (`f4bf535`): 38 `# === PHASE.. ===` / `# === ELI_.._V1 ===`
  / `END` marker labels (36 engine, 2 executor). No behaviour change; suites green.
- **Finding (not removed):** `compact_override` is passed `=True` by 4 callers of
  `_synthesize_answer` but never read in the body — a dead parameter / possible
  latent bug (either wire it up or drop it at all call sites). Left for a decision.

## 7. Pending (next)

- Humanise the verbose "narrated" comment blocks (judgment pass, per block); trim
  the remaining `# ===` divider rules where they add nothing.
- Same pass on the other god files (GUI, grounding-gate, labs_tab).
- Consolidate the version-suffixed patch helpers + the `render_action` chain.
- Resolve the `compact_override` finding.
- Continue driving testable coverage (executor handlers via the live lane,
  remaining `eli/runtime` + `eli/tools`).
