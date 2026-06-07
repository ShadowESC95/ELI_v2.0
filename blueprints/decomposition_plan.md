# God-file decomposition + monkeypatch elimination — work plan

*2026-06-07. **PLAN AND DOCUMENT ONLY — no code changes.** Grounded in a structural
scan of the actual files. Two non-negotiables: (1) **eliminate or formalise every
monkeypatch/runtime self-patch** — treated as the top priority throughout; (2)
**preserve 100% of the advanced features** and verify wiring is fully intact after
every step.*

---

## 1. The targets (measured)

| File | LOC | Internal units | Becomes |
|---|---|---|---|
| `eli/execution/executor_enhanced.py` | 13,656 | **143 action handlers** + 173 helpers + 3 install-contracts | `eli/execution/actions/` package + thin dispatcher |
| `eli/kernel/engine.py` | 12,508 | `CognitiveEngine` (≈9.6k) + 78 module fns + 1 install-guard | `eli/cognition/pipeline/` stages + slim engine |
| `eli/gui/eli_pro_audio_gui_MKI.py` | 10,849 | **18 `create_*_tab`** + window plumbing | `eli/gui/tabs/` (one module per tab) + window shell |
| `eli/execution/router_enhanced.py` | 6,608 | 90 matcher/stage fns + 2 install-wraps | `eli/execution/routing/` domain matchers + pipeline assembler |
| `eli/gui/labs_tab.py` | 5,562 | ~9 sub-tab widget classes | `eli/gui/tabs/labs/` (one module per sub-tab) |
| `eli/memory/memory.py` | 4,358 | `DBPaths`, `_MemoryModule`, `_MemoryMeta`, `Memory` | `eli/memory/core/` (paths/facade/dynamic-attr) |
| `eli/runtime/deterministic_grounding_gate.py` | 4,292 | tiered gate logic | `eli/runtime/grounding/` (tier modules) |

Total in scope: **~57k LOC across 7 files** (44% of the codebase concentrated here).

---

## 2. Monkeypatch & patch register — THE priority (disposition per item)

A full scan found **12 `globals()` runtime self-patches + 8 install-time wrappers**,
several already partially retired in prior phases (BW2 / 2c — good precedent). Each
must be eliminated or formalised as part of the move. Nothing in this register is
"just deleted" — each has an explicit disposition.

### Category A — `globals()` runtime-STATE publication (formalise → state object)
| Loc | What | Disposition |
|---|---|---|
| `gguf_inference.py:558,576-577,1233-1234` | `_live_runtime_params` / `_live_runtime_override` written to module globals | **Formalise** into a `RuntimeParams` dataclass/singleton in `cognition/runtime_state.py`; replace `globals()[...]` writes + the GUI `setattr(_gguf_runtime, …)` (`gui:2579-2580`) with its API. **Safe, isolated.** |
| `grounded_remediation.py:1222,1247` | `_PENDING` pending-confirm state to module global | **Formalise** into a small `PendingStore` (mirror the existing pending-code-fix pattern). **Safe.** |

### Category B — function SELF-WRAPPING (`globals()[fn] = wrap(fn)`) — load-bearing
| Loc | What | Disposition |
|---|---|---|
| `gguf_inference.py:1454` | `generate = _wrap_generate(generate)` | **KEEP, encapsulate.** Proven load-bearing — `generate` self-recurses for auto-reload, so a plain rebind double-wraps → `RecursionError` (reproduced). Move into the new `gguf` package as an explicit `_install_generate_wrapper()` with a one-line comment; do **not** "simplify". |
| `router_enhanced.py:4030` | `globals()[name] = voice_contract_wrap(fn)` over route callables | **Convert to decorators** at each route function's definition during the routing extraction (§3.4). Removes the loop-over-globals. |

### Category C — install-time CONTRACTS/wrappers (fold into structure on extraction)
| Loc | What | Disposition |
|---|---|---|
| `gguf_inference.py:1901` | adaptive cold-load fallback wrapper | Fold into the loader module as a normal method/branch. |
| `gguf_inference.py:2204-2209` | effective-runtime `load_model`/snapshot contract (redefines + republishes 3 names) | **Fold**: make these the canonical defs in the new `gguf` package; delete the republish. |
| `executor_enhanced.py:11812` | generated-script safety wrapper | Fold into the script-generation action module (§3.1). |
| `executor_enhanced.py:13205` | GUI_RUNTIME_AUDIT visible-result contract | Fold into the introspection action module. |
| `executor_enhanced.py:13654` | canonical middleware table install | Becomes the dispatcher's explicit middleware list (§3.1). |
| `engine.py:12457` | non-quick persona pipeline safety guard | Becomes an explicit pipeline stage (§3.2). |
| `router_enhanced.py:4802,6606` | final route wrapper + priority-pipeline install | Becomes the explicit `routing/pipeline.py` assembler (§3.4). |

### Category D — already-retired (precedent to follow, no action)
`deterministic_grounding_gate.py:4226` (CognitiveEngine.process wrappers retired);
`engine.py:2658` (UVRS monkey-patches → plain module fns); `contracts/runtime_status.py:6`
("stop stacking v10–v17 monkey patches"); router stale diagnostic shells (4513–4638).
**These prove the pattern works — replicate it for Categories A–C.**

### Category E — legitimate `setattr` on state objects (NOT monkeypatches; leave)
`engine.py:7270,7796-7800` (`setattr(working_memory, …)`) — setting fields on a
working-memory object. Leave; only the GUI `_gguf_runtime` setattr (D-row above) moves
to the `RuntimeParams` API.

### Category F — the dynamic module metaclass (flag for review)
`memory.py` `_MemoryModule`/`_MemoryMeta` make the *module itself* dynamically
attributed — a monkeypatch-adjacent pattern. **Document + assess** in §3.6; likely
replace with explicit `__getattr__`/re-exports during the memory split.

> **Priority order for the whole programme:** Category A (safe, do first) → C (folds
> naturally during each file's extraction) → B/F (careful, last). Nothing ships
> without the suite green.

---

## 3. Per-file decomposition

### 3.1 `executor_enhanced.py` → `eli/execution/actions/`
143 `if a == "X"` handlers map cleanly to the **17 capability categories** already in
`capabilities_and_actions.md`. Split into one module per category, each registering
into a dispatch table:
```
eli/execution/actions/
  __init__.py            # builds ACTION_REGISTRY from the submodules
  _helpers.py            # _save_artifact, _artifacts_dir, path resolvers, evidence hook
  _registry.py           # @action("NAME") decorator + dispatch + middleware list
  conversation.py  app_control.py  input_control.py  media.py  vision.py
  gaze.py  voice.py  files.py  generation.py  (doc/script/project — already DAG-wired)
  system_status.py  introspection.py  memory_actions.py  self_maintenance.py
  tasks.py  proactive.py  plugins.py  shell.py
```
`executor_enhanced.py` shrinks to a **thin dispatcher + back-compat re-exports**
(`execute`, `_execute_impl`, `SUPPORTED_ACTIONS`). The 3 install-contracts (C) become
the registry's explicit middleware list. **Mechanical, registry-driven, low logic risk.**

### 3.2 `engine.py` → `eli/cognition/pipeline/`
- The ~2,840 lines of pre-class module functions (already "plain module-level functions
  called directly" per the retired-monkeypatch comment) group into:
  `pipeline/prompt_assembly.py`, `persona.py`, `grounding.py`, `guards.py`,
  `verbatim.py` (the verbatim/direct action sets).
- `CognitiveEngine.process()`'s 12-stage pipeline → one module per stage under
  `pipeline/stages/`; the engine becomes the **orchestrator** that runs the stages
  (a natural fit for the DAG orchestrator later, but not required now).
- The persona-guard install (C) becomes an explicit stage.

### 3.3 `eli_pro_audio_gui_MKI.py` → `eli/gui/tabs/`
The pattern is **already started** (Labs, Report Builder, Test & Review, Orchestration
live in `labs_tab.py` and are imported by the window). Extend it: one module per
`create_*_tab` →
```
eli/gui/tabs/
  chat_tab.py  habits_tab.py  image_tab.py  self_improve_tab.py  proactive_tab.py
  quick_actions_tab.py  screen_control_tab.py  coding_tab.py  tasks_tab.py
  files_tab.py  settings_tab.py  eli_world_tab.py
  (report_builder/test_review/orchestration already factored)
```
The main window keeps `create_menu_bar`, `create_top_toolbar`, shared state, and
`send_to_chat`/`_engine_ask`; each tab is constructed from its module. **Lowest-risk
file** (tabs are already isolated widgets).

### 3.4 `router_enhanced.py` → `eli/execution/routing/`
90 matcher functions → domain matcher modules, plus an explicit pipeline assembler that
replaces the `globals()` voice-wrap loop (B) and the install markers (C):
```
eli/execution/routing/
  pipeline.py            # the explicit 33-stage priority pipeline (was the install)
  contracts.py           # voice-contract decorator (was globals()[name]=wrap)
  matchers/ system.py media.py files.py self_maintenance.py generation.py
            vision.py gaze.py voice.py tasks.py proactive.py shell.py ...
```
`route()` stays the public entry (re-exported). **Medium risk** — order of matchers is
behavioural, so extraction must preserve the exact stage sequence (the claims
activation-phrase tests guard this).

### 3.5 `labs_tab.py` → `eli/gui/tabs/labs/`
One module per sub-tab widget (`notebook.py`, `memory_conversations.py`, `jupyter.py`,
`calculator.py`, `physics.py`, `file_chat.py`, `workspaces.py`, `sim_ide.py`, plus the
already-extracted report/orchestration/test-review widgets). `labs_tab.py` becomes the
`LabsTab` assembler. Low risk.

### 3.6 `memory.py` → `eli/memory/core/`
`DBPaths` → `paths.py`; `Memory` → `store.py`; the `_MemoryModule`/`_MemoryMeta`
dynamic-module machinery (Category F) → replace with an explicit module `__getattr__`
+ re-exports in `__init__.py`. **Care needed** — this metaclass is widely depended on;
do it last in this file with the memory tests as the gate.

### 3.7 `deterministic_grounding_gate.py` → `eli/runtime/grounding/`
Split the deterministic tiers into `gate.py` (entry), `tiers.py`, `signals.py`. Pure
logic, well-tested → low risk.

---

## 4. Proposed project tree (target)
```
eli/
  execution/
    executor_enhanced.py        # thin dispatcher + back-compat re-exports
    actions/                    # 17 category handler modules + _registry + _helpers
    routing/                    # pipeline.py + contracts.py + matchers/
    router_enhanced.py          # re-exports route() from routing/
  cognition/
    engine.py                   # slim CognitiveEngine orchestrator (re-exports kept)
    pipeline/                   # prompt_assembly / persona / grounding / guards / stages/
    runtime_state.py            # RuntimeParams (formalised gguf globals)
    gguf/                       # loader + generate-wrapper + effective-runtime contract
  gui/
    eli_pro_audio_gui_MKI.py    # window shell + shared state + assembly
    tabs/                       # one module per main tab
    tabs/labs/                  # one module per Labs sub-tab
  memory/
    core/                       # paths.py / store.py
    __init__.py                 # explicit __getattr__ + re-exports (replaces metaclass)
  runtime/
    grounding/                  # gate.py / tiers.py / signals.py
    pending_store.py            # formalised grounded_remediation _PENDING
```
Every old import path (`from eli.execution.executor_enhanced import execute`, etc.)
**keeps working** via re-export shims — see §5.

---

## 5. Wiring correctness — how we guarantee 100%
1. **Façade re-exports first.** Each god-file is kept as a slim module that
   `from .new_package import *` (and explicit names). External imports never change.
2. **Move, don't rewrite.** Phase 1 of each file is a *pure relocation* (cut → paste →
   re-export). Behaviour-changing refactors come only after the move is green.
3. **The test suite is the contract.** 6,520 tests incl. the **claims suite** that
   already verifies: every module imports (`test_modules_compile`), every public symbol
   is real (`test_symbol_inventory`), all **200 capabilities** routable + handled
   (`test_capability_manifest` / `test_supported_actions`), every documented action
   reachable (`test_activation_phrases`), and blueprint refs resolve. Run **green after
   every extraction**; a broken wire shows up immediately.
4. **Per-extraction commit.** One coherent module per commit; suite green between each;
   trivially revertable.
5. **Manifest re-sync.** `capability_updater` regenerates the manifest after the
   executor split — the claims tests then re-verify all 200 actions still register.
6. **Import-cycle check.** New packages must not import the slim shim (only the reverse);
   add a claims test asserting no `actions/` module imports `executor_enhanced`.

---

## 6. Sequencing (lowest-risk first; each phase ends green + committed)
- **Phase 0 — Monkeypatch register (safe formalisations):** Category A → `RuntimeParams`
  + `PendingStore`; route the GUI `_gguf_runtime` setattr through the API. Isolated.
- **Phase 1 — GUI tabs (§3.3, §3.5):** extract `tabs/` + `tabs/labs/`. Lowest risk.
- **Phase 2 — Executor actions (§3.1):** category modules + registry; fold Category-C
  executor contracts. Mechanical.
- **Phase 3 — Router (§3.4):** domain matchers + `pipeline.py` + voice-contract decorator
  (Category B router item). Preserve stage order.
- **Phase 4 — Engine pipeline (§3.2):** stages + helper modules; persona-guard stage.
- **Phase 5 — gguf + grounding + memory (§3.6, §3.7, Category B/C/F):** the load-bearing
  `generate` wrapper (encapsulate, don't simplify), effective-runtime contract fold,
  memory metaclass → explicit `__getattr__`. Highest care, done last.

---

## 7. Advanced features to preserve (must survive every step — explicit)
DAG execution orchestrator (`core/dag.py`) + agent-bus-on-DAG; evidence planner
(parallel gather); multi-stage `report_pipeline`; grounding gates + anti-confabulation;
self-improvement → coding-agent route; LoRA pipeline (model-agnostic); scheduled/
overnight tasks (eval/testgen/lora, recurring); autonomy/self-awareness tick;
Test & Review + Orchestration tabs; vision/gaze/voice/OS-control; netguard
offline-by-default; all **200 capabilities**; the claims test-suite itself. None of
these change behaviour — they only move and get cleaner seams.

---

## 8. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Hidden ordering dependence (router stages, engine stages) | Pure-move first; activation-phrase + mode-budget claims tests guard order |
| The load-bearing `generate` wrapper | Documented; encapsulated, never "simplified" (recursion proof on record) |
| The memory metaclass is widely used | Done last; explicit `__getattr__` + memory tests as gate |
| Import cycles after splitting | One-way imports (packages never import the shim) + a claims test |
| Silent breakage | 6,520-test suite green after every commit; per-module commits |
| Scope creep into behaviour change | Hard rule: relocation ≠ refactor; refactors are separate, later PRs |

---

## 9. Effort & definition of done
- **Effort:** ~6 phases; each is hours-to-a-day of mechanical work + a green suite run.
  Phases 0–1 are quick wins; 2–3 are the bulk; 4–5 need care.
- **Definition of done:** no file > ~2,000 LOC on the core path; **zero `globals()`
  function self-patches** except the one documented load-bearing `generate` wrapper;
  runtime state behind `RuntimeParams`/`PendingStore`; all old import paths re-export;
  manifest still 200; **full suite green**; a new claims test forbids new god-files
  (>3,000 LOC) and new `globals()[fn]=` patterns.

*Companion docs: `complete_findings.md` (the original debt findings), `dag_orchestrator.md`
(the orchestration the engine pipeline can later adopt), `gui.md`, `project_overview.md`.*
