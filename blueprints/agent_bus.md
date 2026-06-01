# ELI Agent Bus — How the 14 Agents Run

Source of truth: `eli/cognition/agent_bus.py`. This documents the multi-agent
dispatch layer: the roster, execution model, timeouts, selection/access, and
known sharp edges. Read-only reference — nothing here changes behaviour.

## Roster

There are **14 agents** in `_ALL_AGENTS` (`agent_bus.py:2179`), each a
`_BaseAgent` subclass (`agent_bus.py:570`) with a `name`, a `timeout_s`, an
`_enabled` flag, and an abstract `run()`.

| #  | `name`             | declared `timeout_s` | what it accesses                                            |
|----|--------------------|----------------------|------------------------------------------------------------|
| 1  | `memory`           | 5.0                  | SQLite + FTS5 + FAISS hybrid recall; self-gates via `_eli_memory_should_run` |
| 2  | `system`           | 8.0                  | direct action execution (`SYSTEM_ACTIONS`) — the only LLM-skipping path |
| 3  | `habit`            | 3.0                  | `user_patterns` / habit tables                             |
| 4  | `self_improvement` | 3.0                  | LoRA / self-tuning introspection                           |
| 5  | `proactive`        | 3.0                  | suggestion / anticipation surface                          |
| 6  | `frontier`         | 5.0                  | frontier / awareness model                                 |
| 7  | `plugin`           | 6.0                  | plugin registry (`PLUGIN_ACTIONS`)                         |
| 8  | `capability`       | 6.0                  | capability manifest                                        |
| 9  | `voice`            | 5.0                  | TTS / voice subsystem                                      |
| 10 | `orchestrator`     | 3.0                  | cross-agent synthesis (runs on almost every path)          |
| 11 | `file_code`        | 4.0                  | source tree / code introspection                           |
| 12 | `reflection`       | 4.0                  | reflection log / insights                                  |
| 13 | `introspection`    | 4.0                  | runtime / cognition self-inspection                        |
| 14 | `knowledge_graph`  | 3.0                  | entity / relation graph                                    |

## Execution model (`dispatch`, lines 1533–1598)

1. **Selective fan-out, not always-14.** Each request computes `action`, then:
   - **Tiny chat** (`CHAT`, ≤3 tokens, filler regex like "ok/yes/thanks") →
     only `{memory, orchestrator}` (line 1562). Avoids spawning 14 futures that
     just return `skipped=True`.
   - **Non-chat actions** → `_select_agents_for_intent()` (line 470) returns a
     *minimal* set per action family. Examples:
     - `RUNTIME_STATUS` → `{system, introspection, orchestrator}` (+`file_code`/
       `capability`/`memory`/`reflection` only if the text mentions those).
     - `SELF_REPORT` → `{system, memory, reflection, introspection, orchestrator}`
       (+`knowledge_graph`/`capability`/`file_code` on keyword).
     - `MEMORY_*` → `{system, memory, orchestrator}` (+kg/reflection on keyword).
     - Identity summaries (`USER_IDENTITY_SUMMARY`, `PERSONAL_MEMORY_*`)
       deliberately **exclude** `file_code` (code snippets inflate context
       without helping "who am I" answers).
   - **Plain CHAT** → `_select_agents_for_intent` returns `None` → **broad
     fan-out** across all `_enabled` agents.
2. `active_agents` = agents in `_ALL_AGENTS` that are `_enabled` **and** in the
   selected set (line 1567).
3. **True parallelism.** Each agent is `self._pool.submit(agent.run, …)` into a
   `ThreadPoolExecutor` (line 1572). Pool size defaults to **one thread per
   agent** (`len(_ALL_AGENTS)`), or `runtime_policy.budget("agent_workers",
   floor=4, ceiling=32)` on constrained machines (lines 1517–1530). No agent
   waits in a queue behind another.
4. **Timeouts are enforced two ways** (lines 1580–1598):
   - Outer: `as_completed(futures, timeout=max_timeout + 1.0)` where
     `max_timeout` is the slowest selected agent.
   - Inner, the real guarantee: `future.result(timeout=agent.timeout_s)` —
     **per-agent hard cap**. On `FuturesTimeout` it appends
     `AgentResult(ok=False, error="timeout")`; on any exception,
     `ok=False, error=str(e)`. A slow or crashing agent therefore **degrades to
     a failed result and never blocks the response.**

## Are the timeouts "correct"?

The declared values are sane (action/`system` gets the most headroom at 8s;
pure synthesis agents 3s). Two things to know:

- **They're overridable at runtime.** Lines 2196–2204 loop over every agent and
  replace `timeout_s` with `runtime_policy.timeout("agent_<name>", default)`. So
  the table above is the *default*; a runtime policy / hardware profile can
  tighten or loosen any of them. Intentional (slow-machine adaptation), not a bug.
- **Thread-timeout caveat (known limitation, not a defect):**
  `future.result(timeout)` only stops *waiting* — Python can't kill the thread.
  A timed-out agent's `run()` keeps executing in the background and its result is
  discarded. For read-only agents that's harmless; for write-capable agents
  (memory/habit), a late write can still land after its result was dropped. This
  is inherent to thread-pool timeouts, not specific to ELI.

## Access / trust

- **All 14 built-ins** are imported at module load and are always present — no
  trust gate; they're first-party.
- **Custom agents** (GUI wizard → `eli/brain/agents/custom/`, or
  `eli/cognition/custom/`, or `$ELI_CUSTOM_AGENTS_DIR`) are **hash-gated**
  (lines 2254–2309): each `.py` must have a matching SHA-256 in
  `config/trusted_agents.json` or it's skipped with a SECURITY debug line.
  `ELI_TRUST_ALL_AGENTS=1` bypasses this for dev/test only. The gate is
  fail-closed (missing/mismatched hash → not loaded). Approve with
  `eli --trust-agent <path>`.

## Summary

14 agents, all wired and reachable, all with per-agent hard timeouts, parallel
via a thread pool, selectively dispatched per intent, with first-party agents
trusted-by-default and custom agents hash-verified. The only genuine sharp edge
is the standard one — a timed-out agent's thread isn't actually cancelled, so a
write-capable agent could complete its write after its result was discarded.
