# ELI Full Runtime Truth Audit

Generated: 2026-05-04T20:55:00+0100

## Immediate truth flags

- Compile errors: 0
- Missing internal import targets: 2
- Missing external top-level imports: 56
- Duplicate definitions within same file: 96
- Assignment hooks / wrapper-style route-execute overrides: 11
- Wrapper/contract/compatibility markers: 710
- Absolute/user path hits: 4
- Target-app hardcode hits: 479
- Stub/template/placeholder hits: 82
- Silent broad except hits: 898

## Main files to inspect first

1. `eli/kernel/engine.py`
2. `eli/execution/router_enhanced.py`
3. `eli/execution/executor_enhanced.py`
4. `eli/execution/portable_intent_contract.py`
5. `eli/system/portable_app_control.py`
6. `eli/cognition/context_synthesiser.py`
7. `eli/cognition/gguf_inference.py`
8. `eli/gui/eli_pro_audio_gui_MKI.py`
9. `eli/gui/labs_tab.py`

## Why ELI gave inconsistent answers

1. Runtime self-report appears to read requested/preloaded settings rather than effective loaded llama runtime.
2. Grounded diagnostic routes still fall through to GGUF generation.
3. Agent confidence is being reported as answer confidence.
4. Some agent contributions are named even when evidence says `files_scanned=0` or no snippets.
5. Memory count questions are not using direct SQLite/vector counts.
6. Long introspection answers are capped/truncated by small `max_tokens`.
7. Router action and agentbus action may diverge for memory/introspection routes.
8. Direct-execution commands and cognitive response generation are not cleanly separated.

## Output files

- `compile_errors.json`
- `missing_internal_imports.json`
- `missing_external_imports.json`
- `duplicate_defs_same_file.json`
- `assign_hooks.json`
- `wrapper_markers.json`
- `runtime_truth.json`
- `memory_db_report.json`
- `vector_store_report.json`
- `router_matrix.json`
- `targeted_engine_action_scan.json`
- `full_runtime_truth_audit.json`
