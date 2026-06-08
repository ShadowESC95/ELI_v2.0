# Blueprint — ELI MKXI Full Architecture (ASCII)

The entire system in one drawing, plus the module tree and data layout. Grounded
in the real source (see `architecture.md` for prose, `diagrams.md` for the
pipeline/memory/gating close-ups). Every layer and box maps to a real path.

---

## A. Full system — layered block diagram

```
╔══════════════════════════════════════════════════════════════════════════════════╗
║                            ELI MKXI — FULL ARCHITECTURE                            ║
║                100% local  ·  offline-by-default  ·  model-agnostic                ║
║                      ~133.4k LOC · 352 files · single process                        ║
╚══════════════════════════════════════════════════════════════════════════════════╝

┌─ PRESENTATION ────────────────────────────────────────────────────────────────────┐
│  GUI (PySide6)                  CLI headless              Voice I/O                 │
│  gui/eli_pro_audio_gui_MKI.py   cli/headless.py           perception/audio_stt (STT)│
│  gui/app.py · gui/panels/       (python -m eli -H)        perception/tts_router(TTS)│
│  labs_tab · EliWorld tab        ./eli.sh                  wake-word "computer"       │
└────────────────────────────────────────┬───────────────────────────────────────────┘
                                          │  text / command
                                          ▼
┌─ ROUTING ─────────────────────────────────────────────────────────────────────────┐
│  execution/router_enhanced.py :: route()      regex-first PRIORITY PIPELINE         │
│  + cognition/llm_intent.py (fallback)   route_authority · route_contracts ·         │
│    execution_planner · portable_intent_contract · router_plugin_intents             │
└────────────────────────────────────────┬───────────────────────────────────────────┘
                                          ▼  {action, args, confidence, matched_by}
┌─ KERNEL ──────────────────────────────────────────────────────────────────────────┐
│  kernel/engine.py :: CognitiveEngine.process()   ← the orchestrating core (12k LOC) │
│  scheduler · task_bus · pipeline · state · world_model · self_upgrade               │
└──────┬──────────────────────────────┬───────────────────────────────┬───────────────┘
       ▼                              ▼                               ▼
 ╔═════════════╗            ╔════════════════════╗          ╔═══════════════════════╗
 ║[A] FAST-PATH ║            ║[B] ORCHESTRATOR     ║          ║[C] QUICK PATH (default)║
 ║ PHASE45      ║            ║ 12-stage (deep)     ║          ║ AgentBus.dispatch()    ║
 ║ verbatim,    ║            ║ cognition/          ║          ║                        ║
 ║ NO LLM       ║            ║ orchestrator.py     ║          ║                        ║
 ╚══════╤══════╝            ╚═════════╤══════════╝          ╚═══════════╤═══════════╝
        │                             │                                  │
        │              ┌─ COGNITION ──┴──────────────────────────────────┴──────────────┐
        │              │  AgentBus (14 agents)  +  CodeAgent (15th, eli/coding)          │
        │              │  ─────────────────────────────────────────────────────────────  │
        │              │  inference_broker ─► gguf_inference  (MODEL-AGNOSTIC GGUF)        │
        │              │  reasoning_modes: quick · CoT · self-consistency · ToT · const.  │
        │              │  hyde · reranker · context_builder/synthesiser · working_memory  │
        │              │  persona.py/_updater/_values/_hygiene  (+ persona.txt overlay)    │
        │              └────────────────────────────┬─────────────────────────────────────┘
        │                                           ▼
        │              ┌─ GROUNDING SPINE (runtime/) ── the anti-confabulation core ──────┐
        │              │  netguard ░ persistence_gate ░ deterministic_grounding_gate(4.3k) │
        │              │  ░ grounding_escalation (low-conf → deeper agent tiers + retry)    │
        │              │  ░ evidence_planner (plan→gather→consume: code/web/memory/runtime) │
        │              │  ░ report_pipeline (multi-stage docs: outline→sections→review)     │
        │              │  ░ evidence_ledger/store/arbitration                               │
        │              │  ░ response_contracts/packets/policy ░ final_response_assembly     │
        │              │  ░ user_visible_response_surface ░ truth_report ░ output_governor  │
        │              └────────────────────────────┬─────────────────────────────────────┘
        ▼                                           ▼
┌─ EXECUTION ───────────────────────────────────────────────────────────────────────┐
│  execution/executor_enhanced.py  ~166 action branches / 206 capabilities (live)    │
│  media_runtime · operator_actions · tool_execution_authority · background_tasks     │
│  PLUGINS(10): calendar document_reader media notes pomodoro smart_home              │
│              system_stats tts web web_automation        eli/coding :: CodeAgent     │
└──────┬───────────────────┬─────────────────────┬───────────────────┬────────────────┘
       │ read / write       │                     │                   │
       ▼                    ▼                     ▼                   ▼
┌─ MEMORY ───────────┐ ┌─ PERCEPTION ────────┐ ┌─ LEARNING ──────┐ ┌─ WORLD ──────────┐
│ SQLite + FTS5      │ │ vision (VL hot-swap:│ │ LoRA self-train │ │ EliWorld         │
│ FAISS vectors      │ │   Moondream/Qwen-VL)│ │ (Phi-3 base)    │ │ world_event_bus  │
│ Knowledge Graph    │ │ STT(whisper)·TTS    │ │ dataset_builder │ │ local_world_     │
│ working memory     │ │ os_controller·screen│ │ lora_trainer/   │ │   bridge         │
│ user.db + agent.db │ │ gaze·ambient_vision │ │   eval/guard    │ │ kernel/world_    │
└────────────────────┘ └─────────────────────┘ └─────────────────┘ │   model          │
                                                                    └──────────────────┘

┌─ CORE INFRA (cross-cutting — used by every layer) ────────────────────────────────┐
│  netguard (process-wide offline failsafe)   paths/portable_paths/legacy_paths/db_  │
│  runtime_settings · config   hardware_profile · startup_hardware_optimizer ·       │
│  dynamic_runtime_budget   model_download (curated GGUF)   first_run/_wizard         │
└────────────────────────────────────────────────────────────────────────────────────┘

┌─ BACKGROUND DAEMONS (continuous, started at boot) ────────────────────────────────┐
│  proactive_daemon ─ pattern signals      self_improvement ─ learns from failures   │
│   └─ autonomy tick (30-min, governed): code_monitor + self-model overlay refresh   │
│      + goal/scheduler ticks → proposals (observe-only / memory-write; need approval)│
│  habits_scheduler/habits ─ routines      scheduler · task_bus ─ jobs               │
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
 ├────────────────────┴──────────────────────────────────────────────────────┤
 │ + CodeAgent (15th)  │ SEPARATE pipeline: plan→search→verify→repair          │
 │   eli/coding/agent  │ (CODE_SOLVE / GENERATE_SCRIPT) — not a bus agent      │
 └─────────────────────┴─────────────────────────────────────────────────────┘
```

---

## C. Module tree (LOC · key files · role)

```
eli/  (~133.4k LOC, 352 files)
│
├── __main__.py ················ entry dispatch (GUI | --headless)
│
├── kernel/            13.1k ─── the core
│   ├── engine.py      12.0k     CognitiveEngine.process() — the spine ★god-file
│   ├── scheduler.py             timed jobs
│   ├── task_bus.py · pipeline.py · state.py · world_model.py · self_upgrade.py
│
├── execution/         20.5k ─── route → act
│   ├── executor_enhanced.py   12.8k   ~160 actions ★god-file
│   ├── router_enhanced.py      6.1k   priority pipeline ★god-file
│   ├── execution_planner.py · route_authority.py · route_contracts.py
│   ├── tool_execution_authority.py · operator_actions.py · operator_policy.py
│   ├── media_runtime.py · router_plugin_intents.py · executor_plugin_handlers.py
│   └── portable_intent_contract.py · execution_intent_packets.py
│
├── cognition/         12.3k ─── think
│   ├── agent_bus.py    2.4k   14 agents + dispatch ★
│   ├── orchestrator.py        12-stage deep retrieval
│   ├── gguf_inference.py 2.1k · inference_broker.py   model-agnostic inference
│   ├── reasoning_modes.py · hyde.py · reranker.py · llm_intent.py
│   ├── persona.py/_updater/_values/_status/_hygiene  (+ persona.txt, persona.auto.txt)
│   ├── context_builder.py · context_synthesiser.py · working_memory.py
│   ├── output_governor.py · response_governance.py · response_sanitizer.py
│   └── grounded_status.py · introspection_agent.py · tone_analyzer.py · chat_model.py
│
├── runtime/           18.0k ─── grounding spine + daemons (68 files)
│   ├── deterministic_grounding_gate.py 4.3k ★ · grounding_escalation.py
│   ├── evidence_ledger/store/arbitration.py · memory_evidence.py
│   ├── persistence_gate.py · truth_report.py · control_contracts.py
│   ├── response_contracts/packets/policy.py · final_response_assembly/provider.py
│   ├── user_visible_response_surface.py · personal_memory_*.py · reflection.py
│   ├── background_tasks.py · self_improvement.py · code_monitor.py
│   └── capability_sync.py · pending_proposal.py · runtime_policy.py
│
├── memory/             6.6k ─── remember (13 files)
│   ├── memory.py       4.1k   Memory · SQLite + FTS5 ★god-file
│   └── vector_store.py        FAISS index
│
├── perception/         5.4k ─── sense (18 files)
│   ├── vision.py · analyze_image/csv/pdfs/mesh.py · ambient_vision.py
│   ├── audio_stt.py · local_whisper_stt.py · voice_worker(_streaming).py · eli_listen.py
│   ├── tts_router.py · os_controller.py · screen_locator.py · gaze_engine.py
│
├── planning/           3.1k ─── proactivity (21 files)
│   ├── proactive_daemon.py · habits_scheduler.py · habits.py · jobqueue_cli.py
│
├── coding/             1.5k ─── CodeAgent (plan→search→verify→repair, 9 files)
│
├── learning/           3.1k ─── LoRA self-training (11 files)
│   ├── lora_trainer/eval/guard.py · dataset_builder/filters.py
│   ├── bootstrap_phi3_base.py · base_model_resolver.py · training_preflight.py
│
├── plugins/            1.9k ─── manager + 10 plugins
│   └── calendar · document_reader · media · notes · pomodoro · smart_home ·
│       system_stats · tts · web · web_automation
│
├── world/              1.5k ─── EliWorld (world_event_bus, local_world_bridge)
│
├── core/               4.9k ─── infra
│   ├── netguard.py            offline failsafe + allow_network()
│   ├── paths.py · portable_paths.py · legacy_paths.py · db_paths.py
│   ├── runtime_settings.py · config.py · grounding.py
│   ├── hardware_profile.py · startup_hardware_optimizer.py · dynamic_runtime_budget.py
│   ├── model_download.py · first_run.py · first_run_wizard.py
│
├── gui/               18.7k ─── PySide6 desktop
│   ├── eli_pro_audio_gui_MKI.py 10.3k ★god-file · app.py · labs_tab.py 5.1k
│   └── panels/  (startup.py: model picker + FirstBootWizard, HardwareTuningDock)
│
├── tools/              8.1k ─── image_engine · news · document tools
├── contracts/ 0.7k · cli/ 0.1k · system/ 0.3k · utils/ 0.9k
```

---

## D. On-disk data layout

```
artifacts/
├── db/
│   ├── user.sqlite3      memories(+_fts) · conversation_turns · conversations ·
│   │                     kg_entities(+_fts) · kg_relations · recall_log ·
│   │                     runtime_events · news_articles(+_fts) · news_reflections ·
│   │                     habits/habit_events/habit_rules · observations ·
│   │                     learning_replay · working_memory_pins · user_patterns ·
│   │                     session_summaries · corrections · failures
│   └── agent.sqlite3     agent_dispatches · agent_metrics · improvements ·
│                         failures · code_patches · error_tracking · observations
├── vectors/index.faiss   semantic index   (embedder: nomic-embed-…Q4_K_M.gguf)
├── conversations/  + archive/
├── runtime/users/<uuid>/user_profile…      per-user profile
├── runtime_snapshot.json                   live model/runtime truth
├── world/{snapshots,ledger,journal}/ · proactive/ · incidents/<date>.jsonl
├── documents/ · scripts/ · analyze_image_*/
│
config/   settings.json (gitignored) · templates/settings.template.json ·
          settings.example.json · plugins_state.json
models/   <your>.gguf · embeddings/ · whisper/ · image/        voices/  *.onnx (Piper)
```

---

## E. The flow in one line

```
INPUT → ROUTER → ENGINE ─┬─ FAST-PATH ──────────────────────────► OUTPUT (verbatim)
                         ├─ ORCHESTRATOR ─► retrieval ─┐
                         └─ QUICK ─► AGENT BUS ─────────┤
   MEMORY (SQL/FTS5/FAISS/KG/WM) ─► context ◄───────────┘
   GATES: netguard · persistence · grounding · escalation · confidence · governor
   INFERENCE (broker → gguf, model-agnostic) → OUTPUT → TTS/GUI
   BACKGROUND: proactive · self-improve · habits · learning(LoRA) · world · scheduler
```

> Companion docs: `architecture.md` (prose, every subsystem) ·
> `diagrams.md` (pipeline / memory / gating close-ups) ·
> `eval_harness.md` (the measurement layer).
```


---

## Update Advisory — 2026-06-07
- Module tree/LOC refreshed conceptually to 126,619 / 336. `runtime/` failure store unified; governance modules consolidated; `core/cognition_tunables.py` added.
