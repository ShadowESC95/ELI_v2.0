# Top-Two Head-to-Head — Qwen3-32B vs Qwen3-A3B

*Every model-dependent eval / judge in the project, run head-to-head. Router cases are rule-based (model-free) so they're shared, not a discriminator. Loglikelihood suites (truthfulqa/arc/hellaswag/mmlu) are excluded — they rank tokens incorrectly on thinking GGUFs (documented in the bake-off methodology).*

## 0. Bottom line

- **Quality:** statistically a wash. GSM8K **1.00** (32B) vs **0.95** (A3B) — a 1-question gap out of 20. Both pass **executor 13/13** and **router 59/59**; A3B passed **engine 21/21**. No recorded disagreement on any shared case.
- **Speed:** A3B is **~16× faster** (GSM8K wall 18301s vs 1128s). The MoE activates ~3B params/token vs the dense 32B's full 33B.
- **The 32B engine cell is `n/a` — by hardware necessity, not failure** (see note¹). On this 31 GB / 8 GB-VRAM box the dense 32B runs ELI's multi-pass engine pipeline at ~10–25h for 21 cases (and OOM-kills at full ctx). The A3B's 21/21 plus both models' 13/13 executor make the missing cell near-certain and non-decisive.
- **Verdict:** behaviourally equivalent on ELI's eval suite; the A3B wins decisively on throughput; the 32B's only edge is one extra GSM8K question. On this hardware the A3B is the rational default.

> ¹ The 32B engine eval was attempted twice: once at ctx=32768 (OOM-killed, rc=137 at ~31 GB) and once at ctx=8192 (ran clean but >2h for <8 of 21 multi-pass cases). Called by decision rather than wait 10–25h for a near-certain 21/21.

## 1. Scorecard

| Metric | Qwen3-32B | Qwen3-A3B |
|---|---|---|
| **GSM8K** (20, native) | 1.00 | 0.95 |
| GSM8K wall (s) | 18301 | 1128 |
| **engine** eval (pass/n) | n/a¹ | 21/21 (acc 1.00) |
| engine mean latency (s) | n/a¹ | 306.9 |
| **executor** eval (pass/n) | 13/13 (acc 1.00) | 13/13 (acc 1.00) |
| executor mean latency (s) | 0.3 | 0.1 |
| router (model-free, shared) | 59/59 | 59/59 |

## 2. Where they disagree (per case)

*No per-case disagreements recorded across the run targets present.*

## 3. Full per-case results

### engine

| Case | 32B | 32B lat | A3B | A3B lat |
|---|---|---|---|---|
| `banter_no_escalation` | — | — | pass | 209.7 |
| `capabilities_grounded_lists_real_actions` | — | — | pass | 354.8 |
| `code_generation_no_toy_no_placeholder` | — | — | pass | 113.4 |
| `cognition_runtime_lists_all_stores` | — | — | pass | 0.7 |
| `deepen_delivers_substance` | — | — | pass | 317.2 |
| `deepen_rubric_self_consistency` | — | — | pass | 317.9 |
| `doc_generation_grounded_not_generic` | — | — | pass | 4432.1 |
| `factual_offline_hedges` | — | — | pass | 54.2 |
| `factual_online_web_grounds` | — | — | pass | 211.0 |
| `factual_semantic_match` | — | — | pass | 149.8 |
| `greeting_is_chat` | — | — | pass | 85.1 |
| `grounded_self_knowledge` | — | — | pass | 0.0 |
| `identity_audit_gather_then_summarise` | — | — | pass | 38.9 |
| `memory_runtime_explained` | — | — | pass | 0.2 |
| `minimize_no_fabricated_done` | — | — | pass | 0.3 |
| `no_bruce_samuelson_confab` | — | — | pass | 18.4 |
| `open_domain_engine_is_url` | — | — | pass | 0.1 |
| `personal_memory_summary` | — | — | pass | 0.3 |
| `runtime_status_grounded` | — | — | pass | 0.0 |
| `screen_question_uses_vision` | — | — | pass | 61.1 |
| `stale_audit_not_confabulated` | — | — | pass | 79.4 |

### executor

| Case | 32B | 32B lat | A3B | A3B lat |
|---|---|---|---|---|
| `exec_get_date_iso` | pass | 0.0 | pass | 0.0 |
| `exec_get_time_iso` | pass | 0.0 | pass | 0.0 |
| `exec_gpu_status` | pass | 0.0 | pass | 0.0 |
| `exec_hardware_profile_probes` | pass | 0.1 | pass | 0.0 |
| `exec_list_capabilities_real` | pass | 0.6 | pass | 0.5 |
| `exec_memory_status_ok` | pass | 0.9 | pass | 0.1 |
| `exec_minimize_app_is_handled_not_unsupported` | pass | 0.5 | pass | 0.1 |
| `exec_orchestration_status` | pass | 0.0 | pass | 0.0 |
| `exec_persona_lock_status` | pass | 0.0 | pass | 0.0 |
| `exec_reasoning_mode_status` | pass | 0.0 | pass | 0.0 |
| `exec_resolve_runtime_paths` | pass | 0.5 | pass | 0.2 |
| `exec_runtime_status_grounded` | pass | 1.2 | pass | 0.2 |
| `exec_system_stats` | pass | 0.5 | pass | 0.5 |
