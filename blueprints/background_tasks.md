> **Updated for v2.5.36.**

# ELI Background Tasks & Unified Code Generation

Two related additions:
1. **Code generation shares the verified coding agent** — `CODE_SOLVE`,
   `GENERATE_PROJECT`, a fix to a Python file and `SELF_IMPROVE`'s fix proposals run the
   plan → DAG/tree-search → execute → repair → bug-memory pipeline, and self-upgrade patches
   read its bug memory. Asking for a script (`GENERATE_SCRIPT`) is still a single model
   generation; see the table.
2. **Heavy work runs on background threads** — when a task is estimated heavy (or
   you ask), ELI starts it on a worker thread, hands back a job id immediately,
   and you check on it later.

## 1. Unified code generation

| Path | Before | Now |
|---|---|---|
| `CODE_SOLVE` | the coding agent | the coding agent (unchanged) |
| `GENERATE_SCRIPT` | inline single-shot prompt + static checks | **still a single generation.** The executor's portable script hook (`_eli_v3_generate_script`) answers GENERATE_SCRIPT / CREATE_SCRIPT / WRITE_SCRIPT before `_execute_impl` is reached: one model generation, refused when it is a stub, one standard-library-only retry when Python does not compile, saved under `scripts/`, then checked by `generated_script_guard` (a template or chatter is moved to `invalid/` and reported as failed). The branch in `_execute_impl` that routes through `eli.coding.solve` first (`ELI_GENERATE_SCRIPT_AGENT`) is never reached |
| Self-upgrade (`self_improvement.generate_code_patch`) | LLM patch + import-verify | now also **consults the coding engine's long-term bug memory**: classifies the failure and injects prior fixes for that bug class into the patch prompt |

So "implement and test X", "fix this .py file", and "improve ELI" share one engine and one
bug-memory — the same consolidation move applied to `recall_memory`; a plain "write a
script" does not.

## 2. Background task manager (`eli/runtime/background_tasks.py`)

In-process, multi-threaded (`ThreadPoolExecutor`). **Distinct** from
`eli/planning/jobqueue.py` (which runs durable *external subprocess* jobs) — this
runs live in-process Python work (agent runs) for the session.

- `BackgroundTasks.submit(name, fn, *args, kind=..., meta=...)` → integer job id; tracks
  `queued → running → done/failed/cancelled`, result, error, elapsed, note. `schedule(...)`
  holds a job as `scheduled` until its time.
- `get(id)`, `list()`, `cancel(id)` (best-effort), `wait(id)`, `stats()`.
- `adopt(name, kind=..., meta=...)` puts work that is already running elsewhere on the record as a
  running job and returns its id; `finish(id, result)` ends it like any job. The agent bus uses it
  for an action it stopped waiting for (`agent_bus._hand_over_to_job`, kind `action`, `meta.tell`):
  the action is neither dropped nor run again, and its end reaches the person below.
- Singleton `get_background_tasks()`; thread-safe.
- **What a job's status means.** A handler that returns `ok: False` failed, whatever the thread did;
  `skipped` is not a failure. `elapsed` counts from the start, so a job waiting for its time reads 0.
- **The record outlives the session.** Jobs are kept in `data_dir/runtime/background_jobs.json` for
  30 days (`cog.jobs_kept_days`); numbers carry on, and a job that was queued or running when ELI
  closed loads as `interrupted`: reported, not resumed. `work_lines` and `work_block` (this module)
  read it for job questions, and `eli/runtime/live_reads.py` puts it in front of the model for any
  message about files, folders, jobs or progress, so the model answers from the record;
  `work_targets` is what "the rest" or "them" refers to.
- **Jobs are the person's.** ELI's own housekeeping (kind `housekeeping`) stays out of `list()`, so "did
  the job finish?" is never answered about one; the Tasks tab asks for it. Sizes and windows are the
  `cog.jobs_*` tunables. Asked what a job found, the model reads its report (`latest_report`).
- **When a job ends** (`add_listener`). A failed one goes on the failure record self-analysis reads
  (`_record_failed_job`); one someone asked for reaches them by desktop notification and the proactive
  queue (`_tell_the_person`). What goes wrong after a job is kept on the job, `meta.after_job_error`.
- **Model calls from a job.** Daemons get an empty reply while a person is talking
  (`ELI_BG_DEFER_WINDOW`). A job is started by a turn, so that blanked every job: it now waits, and
  re-runs a call that a turn cut short (`gguf_inference.set_job_inference`).

### When ELI backgrounds a task (`eli/coding/cost.py`)

`should_background(task)` decides:
- **Explicit phrasing wins:** "in the background / don't wait / notify me when" →
  background; "right now / quickly / wait for it" → foreground.
- **Open-ended or research-grade problems** always go to the background.
- **Otherwise heuristic:** `estimate_cost` scores heavy-compute signals
  (simulate/monte-carlo/optimise/benchmark/train/dijkstra/parallel…),
  multi-component structure, length, and planned-step count. `heavy` (≥0.6) ⇒
  background.

`_maybe_background_codegen` (executor) applies this at the top of `CODE_SOLVE`
(the GENERATE_SCRIPT branch of `_execute_impl` calls it too, but that branch is not reached;
see §1): if heavy/explicit, it submits the same action as a background job (re-dispatched
with `_no_background` so the worker doesn't re-background) and replies that it started job
#N and that "check job N" fetches the result. Kill switch: `ELI_CODEGEN_BACKGROUND=0`.

`_maybe_background_code_work` does the same for the code actions that hold the model for a
long time: `FIX_FILE` always goes to the background unless the request asks for it now;
`EXAMINE_CODE` does for a sweep with no file named, several files, a heavy request, or when
the model runs on the CPU only; `SELF_IMPROVE` in propose mode always does. Kill switches:
`ELI_FIX_FILE_BACKGROUND=0`, `ELI_EXAMINE_CODE_BACKGROUND=0`, `ELI_SELF_IMPROVE_BACKGROUND=0`.

### Inspecting jobs

- Actions **`CHECK_JOB`** (`{job_id}` or parsed from "check job 3") and
  **`BACKGROUND_JOBS`** (list), both in `SUPPORTED_ACTIONS`.
- Router triggers: "check job N" / "job N", "background jobs" / "list jobs", and while a job runs a
  question about its progress or time left ("do you have an eta?", "is it done yet?"), which goes to
  the running job (`_JOB_PROGRESS`); "how long is the Eiffel Tower" does not.
- **Progress.** A job reports `background_tasks.report(done, total, stage)` from its own thread;
  `CHECK_JOB` and the Tasks tab show the stage, how far it has got and the time left in that stage
  at the rate measured so far (`Task.eta_s`). The folder analysis reports reading and summarising.
  Without this an ETA question got "several hours" for a ten-minute job.

## Control summary

| Knob | Default | Effect |
|---|---|---|
| `ELI_GENERATE_SCRIPT_AGENT` | on | read only by the unreached coding-agent branch of `_execute_impl`'s GENERATE_SCRIPT handler, so it has no effect (§1) |
| `ELI_CODEGEN_BACKGROUND` | on | auto-background heavy `CODE_SOLVE` (off ⇒ always foreground) |
| `ELI_FIX_FILE_BACKGROUND` / `ELI_EXAMINE_CODE_BACKGROUND` / `ELI_SELF_IMPROVE_BACKGROUND` | on | background the long code actions (off ⇒ inline) |
| `ELI_AGENT_DAG` / `ELI_CODING_DAG` | on | DAG dispatch / subtask DAG (see `dag.md`) |
| `ELI_CODING_SANDBOX` / `*_RUN_TIMEOUT` / `*_BEAM` / `*_MAX_ITERS` | — | coding-agent execution knobs |

## Scope / honesty

- **Tested deterministically** (`tests/test_background.py`): manager run/fail
  reporting, cost light-vs-heavy + explicit phrasing, and the CHECK_JOB /
  BACKGROUND_JOBS executor round-trip. No model needed.
- **Threads, not processes:** background tasks share the process; a running
  thread can't be force-killed (cancel is best-effort / cooperative). True OS
  isolation for a job uses the durable subprocess `jobqueue`: run `eli-jobs worker` and
  queue with `eli-jobs submit --cmd "..."` (jobs survive a restart; one a dead worker left
  running is marked failed on the next worker start).
- **"LLM deems longer wait":** currently a deterministic estimator (+ explicit
  phrasing). The planner's decomposition (`plan_steps`) can be fed in for an
  LLM-informed estimate — hook present, not yet auto-wired.
- **GUI:** the Tasks tab (`eli/gui/tabs/tasks_tab.py`) is the single home for background work: coding jobs and scheduled or overnight tasks (add, edit, cancel). Jobs are also reachable in chat ("check job N", "background jobs") and through the action API.
