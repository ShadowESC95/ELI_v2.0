# DAG orchestrator — project-wide execution engine (2026-06-07)

`eli/core/dag.py` was a pure **scheduling** primitive (Kahn topological order,
parallel layers, cycle detection, ancestors/descendants, critical-path). It was
elevated into a full **execution orchestrator** and wired through the pipeline —
additively, so every existing class/function and caller is unchanged.

## The orchestrator (`eli/core/dag.py`)
`Orchestrator` / `run_graph(tasks)` execute a set of `Task`s on their dependency DAG:

- **Parallel intra-layer execution** — independent nodes in a topological layer run
  concurrently (threads); `max_workers=1` ⇒ deterministic sequential.
- **Dependency result-passing** — each node fn gets a `NodeContext` with `results`
  (completed upstream outputs) + a shared mutable `shared` bag.
- **Conditional nodes** — `when(ctx)->bool` skips a branch dynamically.
- **Retries + backoff** — per-node `retries` with exponential `retry_backoff`.
- **Fallback** — a `fallback` fn runs if all attempts fail.
- **Per-node timeout** — total node budget (best-effort; enforced via a worker future).
- **Memoisation** — pluggable `cache` keyed by `cache_key` (status `cached`).
- **Priority scheduling** — higher-priority nodes first within a ready layer.
- **Fail-fast + global time budget** — stop scheduling after a failure / budget.
- **Auto-skip** — a node whose upstream didn't complete is skipped with a reason.
- **`critical` semantics** — a non-critical node's failure doesn't fail the run.
- **Deterministic `RunReport`** — per-node status/attempts/timing + order + layers +
  critical path + failed/skipped lists + `to_dict()` for observability.

Pure stdlib; the orchestrator does no LLM/IO — the node callables do.

## Wired through the pipeline
- **Agents (cognition):** the agent bus runs the 14 agents on the orchestrator
  (`_run_agents_orchestrated`, default `ELI_AGENT_ORCHESTRATOR=1`, falls back to the
  layered then flat paths). Dependency-ordered, intra-layer parallel, per-agent
  timeouts (mode + model-tier scaled), upstream results passed downstream, and a
  `RunReport` captured per dispatch. Behaviour-preserving: agent fns never raise out
  (errors → `ok=False`), so edges only order + pass upstream, never gate.
- **Router → executor (observability):** `ORCHESTRATION_STATUS` action
  ("orchestration status" / "show your agent dag") returns the live engine, execution
  layers, dependencies, critical path, and last-run telemetry — so ELI can explain its
  own orchestration honestly.
- **Other pipelines** already express DAG-shaped stages and can adopt `run_graph`:
  the coding planner (`coding/plan_graph.py`) and LoRA pipeline use the DAG;
  evidence_planner / report_pipeline are sequential stages that can move onto it next.

## Tests
`tests/test_dag_orchestrator.py` (14) cover every feature; existing dag/coding/agent
tests + the full suite stay green. Flags: `ELI_AGENT_ORCHESTRATOR`, `ELI_AGENT_DAG`.
