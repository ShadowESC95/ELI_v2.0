# Blueprint — ELI Full Architecture (ASCII)

> **Updated for v2.5.36.** All CHAT modes → gradient orchestrator; bus composed at S06.

The entire system in one drawing, plus the module tree and data layout. Grounded
in the real source (see `architecture.md` for prose, `diagrams.md` for the
pipeline/memory/gating close-ups). Every layer and box maps to a real path.

---

## A. Full system — layered block diagram

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                                ELI — FULL ARCHITECTURE                             ║
║                100% local  ·  offline-by-default  ·  model-agnostic                ║
║               208,046 LOC · 451 files · desktop GUI + web app server               ║
╚══════════════════════════════════════════════════════════════════════════════════╝

┌─ PRESENTATION ────────────────────────────────────────────────────────────────────┐
│  GUI (PySide6)                  CLI headless              Voice I/O                 │
│  gui/eli_pro_audio_gui_v2_0.py   cli/headless.py           perception/audio_stt (STT)│
│  gui/app.py · gui/panels/       (python -m eli -H)        perception/tts_router(TTS)│
│  labs_tab · EliWorld tab        ./eli.sh                  wake-word "computer"       │
└────────────────────────────────────────┬───────────────────────────────────────────┘
                                          │  text / command
                                          ▼
┌─ KERNEL ──────────────────────────────────────────────────────────────────────────┐
│  kernel/engine.py :: CognitiveEngine.process()   ← the orchestrating core (~17k LOC) │
│  input guard (S02) · scheduler · pipeline · state · world_model · self_upgrade      │
└────────────────────────────────────────┬───────────────────────────────────────────┘
                                          ▼  sanitised text → route() (S03)
┌─ ROUTING ─────────────────────────────────────────────────────────────────────────┐
│  execution/router_enhanced.py :: route()      regex-first PRIORITY PIPELINE         │
│  + cognition/llm_intent.py (fallback)   route_contracts ·                           │
│    execution_planner · portable_intent_contract                                     │
│  → {action, args, confidence, matched_by} → authority_gate (owner-only actions)     │
└──────┬──────────────────────────────┬───────────────────────────────┬───────────────┘
       ▼                              ▼
 ╔═════════════╗            ╔════════════════════════════════════════╗
 ║[A] FAST-PATH ║            ║[B] CHAT + NON-CHAT (gradient orchestrator)║
 ║ PHASE45      ║            ║ all modes · retrieve_for_turn → bus     ║
 ║ verbatim,    ║            ║ cognition/orchestrator.py · pipeline_trace║
 ║ NO LLM       ║            ╚═════════════════╤══════════════════════╝
 ╚══════╤══════╝                              │
        │              ┌─ COGNITION ──────────┴──────────────────────────┐
        │              │  AgentBus (15 agents, composed at S06) + CodeAgent │
        │              │  ─────────────────────────────────────────────────────────────  │
        │              │  inference_broker ─► gguf_inference  (MODEL-AGNOSTIC GGUF)        │
        │              │  reasoning_modes: quick · CoT · self-consistency · ToT · const.  │
        │              │  hyde · reranker · context_synthesiser · working_memory          │
        │              │  persona.py/_updater/_values/_hygiene  (+ persona.txt overlay)    │
        │              └────────────────────────────┬─────────────────────────────────────┘
        │                                           ▼
        │              ┌─ GROUNDING SPINE (runtime/) ── the anti-confabulation core ──────┐
        │              │  persistence_gate ░ deterministic_grounding_gate(3.3k)            │
        │              │  ░ grounding_escalation (low-conf → deeper agent tiers + retry)    │
        │              │  ░ evidence_planner (plan→gather→consume: code/web/memory/runtime) │
        │              │  ░ report_pipeline (multi-stage docs: outline→sections→review)     │
        │              │  ░ evidence_ledger/arbitration                                     │
        │              │  ░ response_contracts/policy ░ final_response_provider             │
        │              │  ░ user_visible_response_surface ░ truth_report ░ output_governor  │
        │              └────────────────────────────┬─────────────────────────────────────┘
        ▼                                           ▼
┌─ EXECUTION ───────────────────────────────────────────────────────────────────────┐
│  execution/executor_enhanced.py  208 supported actions · 232 capabilities (192 routable)  │
│  media_runtime · operator_actions · background_tasks · shell_gate                   │
│  PLUGINS(10): calendar document_reader media notes pomodoro weather                 │
│              system_stats tts web web_automation        eli/coding :: CodeAgent     │
└──────┬───────────────────┬─────────────────────┬───────────────────┬────────────────┘
       │ read / write       │                     │                   │
       ▼                    ▼                     ▼                   ▼
┌─ MEMORY ───────────┐ ┌─ PERCEPTION ────────┐ ┌─ LEARNING ──────┐ ┌─ WORLD ──────────┐
│ SQLite + FTS5      │ │ vision (VL hot-swap:│ │ LoRA self-train │ │ EliWorld         │
│ FAISS vectors      │ │   Moondream/Qwen-VL)│ │ (any family)    │ │ world_event_bus  │
│ Knowledge Graph    │ │ STT(whisper)·TTS    │ │ dataset_builder │ │ local_world_     │
│ working memory     │ │ os_controller·screen│ │ lora_trainer/   │ │   bridge         │
│ user.db + agent.db │ │ gaze·ambient_vision │ │   eval/guard    │ │ kernel/world_    │
└────────────────────┘ └─────────────────────┘ └─────────────────┘ │   model          │
                                                                    └──────────────────┘

┌─ CORE INFRA (cross-cutting — used by every layer) ────────────────────────────────┐
│  netguard (process-wide offline failsafe)   paths/portable_paths/legacy_paths/db_  │
│  runtime_settings · config   hardware_profile · startup_hardware_optimizer ·       │
│  load_plan · gguf_sizes   model_download (curated GGUF)   setup/wizard (first run)  │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ BACKGROUND DAEMONS (continuous, started at boot) ────────────────────────────────┐
│  proactive_daemon ─ pattern signals      self_improvement ─ learns from failures   │
│   └─ autonomy tick (30-min, governed): code_monitor + self-model overlay refresh   │
│      + goal/scheduler ticks → proposals (observe-only / memory-write; need approval)│
│  habits_scheduler/habits ─ routines      scheduler ─ jobs                          │
│  background_tasks ─ async heavy work     reflection loop   ambient_vision loop      │
│  scheduled_tasks (durable overnight/timed)   world_event_bus ◄─ confidence events   │
└────────────────────────────────────────────────────────────────────────────────────┘

           OUTPUT  ◄── output_governor / sanitiser ◄── inference ◄── (any path)
                         │
                         └─► TTS (Piper)  /  GUI render
```

---

## B. The 15 agents

```
 AGENT BUS  (cognition/agent_bus.py :: AgentBus.dispatch → DispatchResult)
 selects a set → runs on a dependency DAG → aggregates grounding_confidence
 ┌────────────────────┬──────────────────────────────────────────────────────┐
 │ BusMemoryAgent      │ recall: SQLite/FTS5/FAISS → context                   │
 │ KnowledgeGraphAgent │ entities/relations from the KG                        │
 │ SystemAgent         │ runs executor actions (WEB_SEARCH, RUNTIME_AUDIT, …)  │
 │ OrchestratorAgent   │ plan / coordinate grounded synthesis                  │
 │ FileCodeAgent       │ searches the codebase for code-grounded answers       │
 │ IntrospectionBus…   │ live runtime + gathers identity/awareness audits as    │
 │                     │ evidence (persona summarises — never a data dump)      │
 │ CapabilityAgent     │ capability manifest (what ELI can do)                 │
 │ ReflectionAgent     │ session reflection / insights                         │
 │ ProactiveAgent      │ proactive patterns / signals                          │
 │ HabitAgent          │ learned habits                                        │
 │ SelfImprovementAgent│ self-improvement state                                │
 │ FrontierAgent       │ frontier reasoning hooks                              │
 │ PluginAgent         │ dispatch to registered plugins                        │
 │ VoiceAgent          │ STT/TTS engine state                                  │
 │ CriticAgent         │ second-tier verifier: checks retriever agents' output │
 ├────────────────────┴──────────────────────────────────────────────────────┤
 │ + CodeAgent        │ SEPARATE pipeline: plan→search→verify→repair          │
 │   eli/coding/agent  │ (CODE_SOLVE / GENERATE_SCRIPT) — not a bus agent      │
 └─────────────────────┴─────────────────────────────────────────────────────┘
```

---

## C. Module tree (LOC · key files · role)

```
eli/  (208,046 LOC, 451 files)  ·  api/server.py  (FastAPI web app + dashboard, 2.4k)
│
├── __main__.py ················ entry dispatch (GUI | --headless | --mcp-server | --license)
│
├── kernel/            19.3k ─── the core (10 files)
│   ├── engine.py      17.4k     CognitiveEngine.process() — the spine
│   ├── scheduler.py             timed jobs
│   ├── pipeline.py · pipeline_trace.py · request_context.py
│   └── state.py · world_model.py · self_upgrade.py
│
├── execution/         27.6k ─── route → act (14 files)
│   ├── executor_enhanced.py   15.6k   207 supported / 231 manifest
│   ├── router_enhanced.py      9.3k   priority pipeline
│   ├── shell_gate.py                  every command in a line, denylist
│   ├── execution_planner.py · route_contracts.py
│   ├── operator_actions.py · operator_policy.py
│   ├── media_runtime.py · app_aliases.py
│   └── portable_intent_contract.py
│
├── cognition/         23.7k ─── think (52 files)
│   ├── agent_bus.py    3.6k   15 agents + dispatch
│   ├── orchestrator.py        12-stage deep retrieval
│   ├── gguf_inference.py 2.8k · inference_broker.py   model-agnostic inference
│   ├── reasoning_modes.py · hyde.py · reranker.py · llm_intent.py
│   ├── persona.py/_updater/_values/_status/_hygiene  (+ persona.txt, persona.auto.txt)
│   ├── context_synthesiser.py · context_budget.py · working_memory.py
│   ├── output_governor.py · query_planner.py · learning_coordinator.py
│   └── grounded_status.py · introspection_agent.py · tone_analyzer.py
│
├── runtime/           40.0k ─── grounding spine + daemons (101 files)
│   ├── deterministic_grounding_gate.py 3.3k · grounding_escalation.py
│   ├── evidence_ledger/arbitration.py
│   ├── persistence_gate.py · truth_report.py · control_contracts.py
│   ├── response_contracts/policy.py · final_response_provider.py
│   ├── user_visible_response_surface.py · personal_memory_*.py · reflection.py
│   ├── background_tasks.py · self_improvement.py · code_monitor.py
│   ├── authority_gate.py (role gate) · security.py · command_splitter.py
│   ├── capability_sync.py · pending_proposal.py · runtime_policy.py
│   └── agenda.py (calendar + reminders)
│
├── memory/            10.6k ─── remember (12 files)
│   ├── memory.py       6.0k   Memory · SQLite + FTS5 · storage policy in policy.py
│   ├── claims.py · knowledge_graph.py · retrieval.py · document_index.py
│   └── vector_store.py        FAISS index
│
├── perception/        10.8k ─── sense (24 files)
│   ├── vision.py · analyze_image/csv/pdfs.py · ambient_vision.py
│   ├── audio_stt.py · local_whisper_stt.py · voice_worker_streaming.py
│   ├── tts_router.py · os_controller.py · screen_locator.py · gaze_engine.py
│
├── planning/           4.4k ─── proactivity (20 files)
│   ├── proactive_daemon.py · habits_scheduler.py · habits.py · jobqueue_cli.py
│
├── coding/             2.1k ─── CodeAgent (plan→search→verify→repair, 12 files)
│
├── learning/           4.3k ─── LoRA self-training (14 files)
│   ├── lora_trainer/eval/guard.py · dataset_builder/filters.py
│   ├── bootstrap_phi3_base.py · base_model_resolver.py · training_preflight.py
│
├── plugins/            6.0k ─── manager + marketplace + bundled plugins (34 files)
│   ├── manager · permissions · manifest · integrity · security_scan · marketplace
│   ├── sandbox (audit hook) · subprocess_sandbox (MCP servers) · mcp
│   └── calendar · document_reader · media · notes · pomodoro · weather ·
│       system_stats · tts · web · web_automation
│
├── integrations/       3.9k ─── MCP client + server · Ollama · cross-platform media · MPRIS
│
├── world/              1.9k ─── EliWorld (world_event_bus, local_world_bridge)
│
├── core/              12.4k ─── infra (33 files)
│   ├── netguard.py            offline failsafe + allow_network()
│   ├── paths.py · portable_paths.py · legacy_paths.py · db_paths.py
│   ├── runtime_settings.py · config.py · grounding.py · full_control.py
│   ├── hardware_profile.py · startup_hardware_optimizer.py · load_plan.py
│   ├── model_download.py
│
├── gui/               26.7k ─── PySide6 desktop (28 files)
│   ├── eli_pro_audio_gui_v2_0.py 12.5k · app.py · labs_tab.py 5.7k
│   └── panels/  (startup.py: model picker + FirstBootWizard, HardwareTuningDock)
│
├── tools/              6.0k ─── image_engine · news · capability registry · code-mode api
├── contracts/ 0.8k · cli/ 0.1k · scripts/ 0.1k · system/ 1.6k · utils/ 2.1k · setup/ 1.9k · onboarding/ 0.8k
```

---

## D. On-disk data layout

```
artifacts/
├── db/
│   ├── user.sqlite3      memories · memories_archive · memory_meta · memory_lineage ·
│   │                     semantic · memory_claims · conversation_turns · conversations ·
│   │                     session_summaries · kg_entities · kg_relations · recall_log ·
│   │                     runtime_events (audit ledger) · learning_replay · observations ·
│   │                     habits/habit_events/habit_rules · user_patterns · user_model ·
│   │                     eli_stances · belief_revisions · news_articles · news_reflections ·
│   │                     working_memory_pins · emotion_events   (+ FTS5 indexes)
│   ├── agent.sqlite3     agent_dispatches · agent_metrics · improvements · failures ·
│   │                     corrections · capability_proposals · error_tracking ·
│   │                     code_patches · lessons
│   ├── system_index.sqlite3   OS index
│   ├── coding_memory.sqlite3  coding_bug_fixes
│   ├── orchestrator_audit.sqlite3   append-only orchestrator/DAG audit ledger
│   ├── capability_state.sqlite3     current state per capability
│   ├── documents.sqlite3            document index
│   └── agenda.sqlite3               calendar + reminders
├── vectors/index.faiss   semantic index   (embedder: nomic-embed-…Q4_K_M.gguf)
├── conversations/
├── runtime/ · runtime_snapshot.json        live model/runtime truth
├── world/{snapshots,ledger,journal}/
├── notes/ (every note) · scratch/ (CREATE_FILE, relative paths)
├── documents/ · scripts/ · analyze_image_*/
│
config/   settings.json (gitignored) · templates/settings.template.json ·
          templates/db/ (blank user/agent/system_index/coding_memory) ·
          settings.example.json · plugins_state.json
models/   <your>.gguf · embeddings/ · whisper/ · image/     tts_piper/  Piper voice settings
```

---

## E. The flow in one line

```
INPUT → ENGINE (input guard) → ROUTER ─┬─ FAST-PATH ────────────────► OUTPUT (verbatim)
                                       └─ ORCHESTRATOR (all CHAT modes, gradient)
                                              ├─ retrieve_for_turn() ──► MEMORY
                                              ├─ dispatch_specialists() ──► 15-agent BUS
                                              └─ broker.infer() → finalize_turn() (S12)
   GATES: netguard · authority · shell · persistence · grounding · escalation · governor
   INFERENCE (broker → gguf, model-agnostic) → OUTPUT → TTS/GUI
   BACKGROUND: proactive · self-improve · habits · learning(LoRA) · world · scheduler
```

> Companion docs: `architecture.md` (prose, every subsystem) ·
> `diagrams.md` (pipeline / memory / gating close-ups) ·
> `tools/eval/README.md` (the measurement layer).
