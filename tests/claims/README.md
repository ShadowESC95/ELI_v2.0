# Claims-verification suite (`tests/claims/`)

A dedicated suite (**2360 tests**) that examines the **project against its claims** —
the capability manifest, the executor's action surface, the blueprint documents, and
the module tree — and asserts they actually line up. Everything is *generated from
real artifacts*, so the count scales with the project and the assertions are
grounded, not invented.

Run: `pytest tests/claims/ -q`

## What it checks (per-item, parametrized)

| File | Examines | ~Tests |
|---|---|---|
| `test_modules_compile.py` | every `eli/**/*.py` compiles, has no merge markers; core modules import | ~730 |
| `test_capability_manifest.py` | every manifest capability is active, well-formed, and its `in_supported_list` flag matches the live `SUPPORTED_ACTIONS` | ~776 |
| `test_supported_actions.py` | every `SUPPORTED_ACTION` is in the manifest and is actually handled (dispatch branch or pre-dispatch) | ~310 |
| `test_documented_actions.py` | every action in `capabilities_and_actions.md` is a real, reachable manifest capability | ~328 |
| `test_activation_phrases.py` | each router-routable action is reachable by ≥1 of its documented activation phrases (or a documented equivalent) | ~120 |
| `test_blueprint_refs.py` | every `*.py` / `eli.x.y` reference in the blueprints resolves | ~36 |
| `test_structural_claims.py` | 14 bus agents, 5 reasoning modes, 12 main tabs, 4 SQLite stores, and the load-bearing callables exist + key behavioural claims (netguard fail-closed, evidence channels, pipeline enabled) | ~70 |

## Findings surfaced by the examination

Mismatches it found and **fixed**: 2 stale blueprint file refs (`tools/…` → `eli/tools/…`).

**Known routing gaps (marked `xfail` — recorded, non-blocking).** The activation-phrase
examination found these documented capabilities are not reached by their natural phrase
through the router (the keyword is captured by a more general matcher). Fixing any flips
its test to `xpass`:
- `SELF_TEST` → routes to `OPEN_APP` ("self test" read as an app name)
- `PROACTIVE_START` → routes to `OPEN_APP` ("proactive mode" read as an app name)
- `SELF_ANALYZE` → routes to `MEMORY_RECALL`
- `EXECUTE_GOAL` → routes to `SHELL_EXEC` ("execute …" read as a shell command)
- `MOUSE_CONTROL` → bare "left click" → `GAZE_CLICK`/`CHAT` without an explicit mouse verb

**Legitimately routed elsewhere (not gaps), encoded in `_EXEMPT`/`_ACCEPTABLE`:** plugin-backed
actions dispatch at execution (not routing); aliases emit a canonical action (`GET_TIME`→`TIME`);
settings/hubs generalise to `OPEN_APP`; identity/awareness/cognition/memory queries route to
CHAT on purpose so the persona summarises gathered evidence (gather-then-summarise);
shell is security-gated.

## Note on the engine eval harness
The model-free **router** eval cases (`tools/eval/cases.yaml`, 38 cases) run automatically
under pytest (`tests/test_eval_cases.py`). The **3 engine cases** need a loaded model and are
NOT auto-run — run them with `python tools/eval/run_eval.py --target engine --json results.json`.
