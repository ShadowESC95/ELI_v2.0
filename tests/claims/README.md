# Claims-verification suite (`tests/claims/`)

A dedicated suite (15 files, 74 test functions, most of them parametrized per item) that
examines the **project against its claims** — the capability manifest, the executor's
action surface, the blueprint documents, the README, the release pipeline and the module
tree — and asserts they actually line up. Everything is *generated from real artifacts*,
so the number of cases scales with the project and the assertions are grounded, not
invented.

Run: `pytest tests/claims/ -q`

A session bootstrap in `conftest.py` runs `tools/bootstrap_claims_artifacts.py`: it seeds
blank DB stores (each store missing from the database folder in force, `paths.db_dir()`, is
copied from `config/templates/db/`, then `init_all_data`; under pytest that folder is the
run's own sandbox in the system temp folder, removed when the run ends) and regenerates `capability_manifest.json` only when it is missing or
lists fewer than 200 capabilities, so a run never rewrites a valid tracked manifest — no
manual step needed on a fresh clone.

**Note:** Git tracks the Markdown blueprints (`blueprints/*.md`) as well as their PDFs.
`capabilities_and_actions.md` is generated from the manifest and the curated catalogue —
regenerate it with `python -m eli.tools.registry.capabilities_doc` after manifest changes.
`test_blueprint_refs.py` reads the tracked `blueprints/*.md` and skips when no blueprint
Markdown is present.

## What it checks (per-item, parametrized)

| File | Examines | Test functions |
|---|---|---|
| `test_modules_compile.py` | every `eli/**/*.py` compiles and has no merge markers (one case per file for each), and the load-bearing core modules import | 3 |
| `test_capability_manifest.py` | `capability_manifest.json` is exactly what the code discovers now (regenerate with `python -m eli.tools.registry.capability_updater`), its `in_supported_list` flags match the live `SUPPORTED_ACTIONS`, and it ships nothing measured on one machine (health, reachability, verification counts) | 3 |
| `test_supported_actions.py` | every `SUPPORTED_ACTION` has an executor dispatch branch, and no action's branch sits behind an earlier one that always answers that action (code that can never run) | 2 |
| `test_documented_actions.py` | every action in the curated catalogue (`capabilities_doc._C`, rendered as `capabilities_and_actions.md`) is in the manifest and is routable, supported or plugin-backed (one case per action for each) | 2 |
| `test_activation_phrases.py` | each router-routable documented action is reached by ≥1 of its documented phrases or a documented equivalent (one case per action), and every quoted phrase in the catalogue reaches its action through the router and the control contract | 2 |
| `test_blueprint_refs.py` | every `*.py` path and `eli.x.y` module the blueprints name exists / resolves (one case per reference) | 2 |
| `test_license_reachable.py` | the Apache-2.0 licence and its NOTICE are reachable from every download — `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md` present, `LICENSE` is the Apache-2.0 text and `NOTICE` names it, ELI.spec ships them, dmg/AppImage stage them, Inno shows a licence pane, `--license` works on both entry points and resolves at runtime, and who made ELI is read from `NOTICE` | 13 |
| `test_structural_claims.py` | 15 bus agents (one case per agent, plus a floor), 5 reasoning modes, 13 main tabs, 4 SQLite stores (and that the bootstrap seeds each missing one), and the load-bearing callables exist + key behavioural claims (netguard fail-closed, evidence channels, pipeline enabled) | 10 |
| `test_public_marketing_claims.py` | README/persona mechanism claims: 15 agents (and the persona's count matches), 12-stage pipeline, 5 reasoning modes, shell denylist, netguard socket guard, port 8081, no pynvml, Piper 166/45 anchor, wake-word training, gender-matched TTS fallback, custom agents, HyDE, LoRA, no Quick-orchestrator bypass prose, no "12-stage retrieval" prose, the document formats README names are dispatched | 17 |
| `test_readme_counts.py` | README's capability count equals the manifest total and is stated consistently, its "N+" floors still hold, and it names no document format the reader cannot open | 4 |
| `test_symbol_inventory.py` | every public function, class and method in every safely importable `eli` module is callable with a usable signature (one case per symbol; GUI, image-engine and other side-effecting modules skipped), and the inventory has not collapsed | 2 |
| `test_agents_contract.py` | every bus agent has a name and a callable `run()`, and on an irrelevant input returns an `AgentResult` that self-gates rather than inventing evidence (one case per agent for each) | 2 |
| `test_release_assets.py` | the release workflow builds and publishes the source artifacts (wheel, deb, wheelhouse, release notes, the full Windows portable), and GPU packs refresh on version tags | 8 |
| `test_repo_parity.py` | `tools/repo_parity.py` exists and, when a v3 checkout is on the machine, finds no unexplained v2/v3 divergence and no prompt guard missing from v3 (skips otherwise) | 3 |
| `test_no_silent_swallow.py` | Ratchet: the silent `except: pass` count (`CEILING`) and the log-only catch-all count (`LOG_ONLY_CEILING`) in `eli/` must not grow (observability) | 1 |

## Findings surfaced by the examination

Mismatches it found and **fixed**: 2 stale blueprint file refs (`tools/…` → `eli/tools/…`).

**Known routing gaps (marked `xfail` — recorded, non-blocking).** None at present:
`_KNOWN_GAPS` in `test_activation_phrases.py` is empty. The ones this examination first
found — `SELF_TEST`, `SELF_ANALYZE`, `PROACTIVE_START` and `EXECUTE_GOAL` reaching the
wrong action — were fixed (self-improvement guard matchers), and a bare "left click" goes
to `GAZE_CLICK` by design (gaze-cursor), so it is no longer listed for `MOUSE_CONTROL`. A
new gap is recorded there as an `xfail`; fixing it flips its test to `xpass`.

**Legitimately routed elsewhere (not gaps), encoded in `_EXEMPT`/`_ACCEPTABLE`:** plugin-backed
actions dispatch at execution (not routing); aliases emit a canonical action (`GET_TIME`→`TIME`);
settings/hubs generalise to `OPEN_APP`; identity/awareness/cognition/memory queries route to
CHAT on purpose so the persona summarises gathered evidence (gather-then-summarise);
shell is security-gated.

## Note on the engine eval harness
The model-free **router** eval cases (`tools/eval/cases.yaml`, 59 of its 93 cases) run
automatically under pytest (`tests/test_eval_cases.py`). The 13 **executor** cases are
model-free too but are not part of pytest — run them with
`python tools/eval/run_eval.py --target executor`. The 21 **engine** cases need a loaded
model and are NOT auto-run — run them with
`python tools/eval/run_eval.py --target engine --json results.json`.
