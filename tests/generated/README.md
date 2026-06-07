# Generated behavioural tests (ELI-assisted, Phase 4)

Tests in this folder were written by ELI (`eli/runtime/test_generator.py`) for its
own functions and are **sandbox-verified** — each was generated, run under pytest in
isolation, and only kept here because it **passed against the real implementation**.
A generated test that failed is rejected (the test guessed wrong), recorded in
`_manifest.json`, and never merged.

- These run as part of the normal suite (`pytest tests/`).
- **Review them** — they're machine-written; treat as a draft until a human confirms.
- Regenerate / extend: `python -c "from eli.runtime.test_generator import run_testgen; print(run_testgen(limit=5))"`
  or schedule "generate tests overnight" (scheduled-tasks `testgen` kind), or ask ELI
  ("generate tests for your code") via the GENERATE_TESTS action.
- `_manifest.json` records every accepted/rejected target with a reason.
- `_tmp/` (gitignored) holds in-flight candidates during verification.
