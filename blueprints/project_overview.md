# ELI — Full Project Breakdown & Assessment

> **Updated for v2.5.36 (November 2026).** Every CHAT mode runs the gradient
> orchestrator, retrieval is shared in `eli/memory/retrieval.py`, memory is governed by a
> storage policy (`eli/memory/policy.py`), and the S01–S12 pipeline is traced canonically.
> Installers are CI-launch-tested and published on
> [GitHub Releases](https://github.com/ShadowESC95/ELI_v2.0/releases).

A grounded read of the whole project: what ELI is, its scale and shape, the architecture
layer by layer, where it is strong, where it is weak (with measured numbers), and what
would help most. Companion to `orchestration_and_agents.md` (agent and bus detail).

> Method note: the numbers below were computed from the tree on 2026-11-20 (`wc -l` over the
> git-tracked files, an AST pass over every file under `eli/`, the capability manifest). Prose
> claims were checked against the code they describe.

---

## 1. What ELI is

A **local-first, model-agnostic personal AI**: no cloud, no telemetry, offline by default and
hard-gated at the socket boundary. Internet access is an owner-controlled, monitored opt-in;
unless the owner enables the Internet toggle, the network opens only for a task the owner
starts (a model or voice download, an update, a LAN device scan) and closes when it ends
(`netguard.allow_network`). It bundles GGUF inference (llama.cpp), a PySide6 desktop GUI, persistent
SQLite + FTS5 + FAISS memory, a knowledge graph, a 12-stage cognitive pipeline with a
parallel 15-agent bus, a deterministic grounding and evidence layer that fights
confabulation, local vision (Qwen2.5-VL hot-swap and Moondream), TTS and STT, OS control, a
plugin system, a proactive daemon, and a LoRA self-training loop.

It also has a second front end: a self-hosted **FastAPI web app and dashboard PWA**
(`api/server.py`): chat, a live telemetry dashboard, ELI's own MQTT smart-home (rooms,
scenes, automations), multi-user roles (admin, member, viewer), a hash-chained audit trail,
shared research corpora, browser voice and the monitored Internet toggle. It is launchable
in-process from the desktop GUI.

## 2. Scale and shape

**208,046 lines across 451 Python files** in `eli/`, plus `api/server.py` (2,390 lines; the
dashboard itself is in `api/static/`) and **593 test files** (`test_*.py`) under `tests/`.

| Subsystem | Lines | Files | Role |
|---|---:|---:|---|
| `runtime/` | 40.0k | 101 | grounding, evidence, introspection, surfaces, daemons |
| `execution/` | 27.6k | 14 | router and executor (action dispatch), shell gate |
| `gui/` | 26.7k | 28 | PySide6 desktop app |
| `cognition/` | 23.7k | 52 | agent bus, orchestrator, inference, persona, modes |
| `kernel/` | 19.3k | 10 | the engine (pipeline driver) |
| `core/` | 12.4k | 33 | paths, settings, hardware profile, load plan |
| `perception/` | 10.8k | 24 | vision, STT, TTS, OS control |
| `memory/` | 10.6k | 12 | SQLite, FTS5, FAISS, knowledge graph, claims, storage policy |
| `plugins/` | 6.0k | 34 | plugin manager, marketplace client, sandboxes |
| `tools/` | 6.0k | 25 | image engine, news, registry |
| `planning/` | 4.4k | 20 | proactive daemon, habits, queues |
| `learning/` | 4.3k | 14 | LoRA self-training |
| `integrations/` | 3.9k | 19 | Ollama, MCP, cross-platform media |
| `coding/` | 2.1k | 12 | the coding agent |
| `setup/`, `utils/`, `world/`, `system/`, `contracts/`, `onboarding/`, `cli/`, `scripts/`, top level | 9.5k | 53 | installer, helpers, world model, portable control |

**Five files carry about 29% of `eli/`:** `engine.py` (17.4k), `executor_enhanced.py`
(15.6k), `gui/eli_pro_audio_gui_v2_0.py` (12.5k), `router_enhanced.py` (9.3k) and
`memory/memory.py` (6.0k). Next tier: `gui/labs_tab.py` (5.7k), `agent_bus.py` (3.6k),
`deterministic_grounding_gate.py` (3.3k), `core/hardware_profile.py` (3.3k).

## 3. Architecture, layer by layer

- **Boot and hardware**: `core/hardware_profile.py` and `core/startup_hardware_optimizer.py`
  fit context, GPU layers and batch to whatever model and GPU are present. One fit
  calculation is shared by the loader and the startup dialog; the fit priority
  (balanced, max GPU, max context) is a setting.
- **Routing**: `execution/router_enhanced.py` is regex-first with an LLM-intent fallback
  and an explicit priority pipeline, resolving to one of **232 manifest capabilities**
  (192 routable, 208 in the executor's supported list, 215 in either). The full reference
  with activation phrases is `capabilities_and_actions.md`.
- **Orchestration**: `kernel/engine.py` runs the gradient orchestrator for all CHAT modes
  (Quick is light, Expert is deep); `dispatch_specialists()` composes the 15-agent
  `cognition/agent_bus.py` after shared retrieval. The bus is a fallback if orchestration
  fails. See `orchestration_and_agents.md`.
- **Inference**: `cognition/gguf_inference.py` resolves the model path from environment and
  settings (no baked model), serialises calls behind a lock, supports a live runtime
  override, and hot-swaps with vision models. Model family and chat template come from GGUF
  metadata (`model_identity.py`).
- **Memory**: `memory/retrieval.py` owns turn retrieval (a question naming a period is
  filtered by date first); `memory/memory.py` is the SQLite, FTS5, FAISS and knowledge
  graph foundation; `memory/policy.py` decides what is stored, merged, decayed and
  archived (`memory.md`).
- **Grounding and evidence**: `runtime/deterministic_grounding_gate.py`,
  `evidence_ledger.py`, `evidence_arbitration.py`, `control_contracts.py`,
  `grounded_remediation.py` and `cognition/output_governor.py`: a layered, deterministic
  anti-confabulation system around the probabilistic model.
- **Security**: `execution/shell_gate.py` reads every command in a shell line, through wrappers
  and substitutions (a denylist; the Full Control toggle lifts it); CREATE_FILE stays inside its
  allow-roots (`SecurityManager.is_path_allowed`, `ELI_ALLOW_ROOTS`) and never replaces a file
  unasked; `runtime/authority_gate.py` keeps the owner's actions (shell, code, files, screen,
  clipboard, input, ELI's own settings, plugins, MCP) from API members and viewers; the API's
  same-machine grants need a `Host` header that names this machine; a SHA-256 custom-agent
  trust registry (`cognition/agent_trust.py`, stored in `config/trusted_agents.json`); SQL
  identifier validation in `memory/memory.py`; and prompt-injection screening in the engine.
  Detail in `security.md`.
- **Self-model**: `cognition/reasoning_modes.py`: `quick`, `fast` and `balanced` all fast-path
  to quick, plus four private modes (`chain_of_thought`, `self_consistency`,
  `tree_of_thoughts`, `constitutional_ai`). Persona overlay, `runtime/self_improvement.py`
  and LoRA self-training (`learning/`).

## 4. What is genuinely strong

1. **The grounding and evidence layer.** Deterministic evidence gating around a
   probabilistic model, developed to a high degree.
2. **Local and model-agnostic.** No call-home, hardware-adaptive, swappable models.
3. **Layered gates.** A shell gate that reads every command in a line, an API that fails
   closed and keeps the owner's actions from other accounts, hash-gated custom agents,
   root-confined file creation that never overwrites unasked.
4. **Breadth, integrated.** Vision, voice, OS control, memory, knowledge graph, plugins and
   self-training in one pipeline.
5. **A large safety net.** 593 test files; the structural tests catch broken imports, stale
   action lists and unpinned routes.

## 5. Where it is weak (measured)

1. **Swallowed errors.** 4,498 handlers catch `Exception` (most log at debug level), 3 are
   bare `except:`, and 164 are a lone `pass`. A ratchet test
   (`tests/claims/test_no_silent_swallow.py`) stops the silent count rising.
2. **Large files.** The executor is an action ladder and the engine a long orchestration
   method; the regression surface is high and unit-testing is hard.
3. **Overlap in `runtime/`.** Many `personal_memory_*`, `*_surface` and `*_response` modules
   do neighbouring grounding work.
4. **Single-file GUI.** `eli_pro_audio_gui_v2_0.py` (12.5k lines) and `labs_tab.py` (5.7k).
5. **Test-suite state.** See `operations.md` for the current pass count; tests that touch
   settings and path caches are isolated from one another by fixtures in `tests/conftest.py`.
6. **Network containment is mostly Python-level.** The socket guard covers in-process code
   only. MCP servers are launched in a sandbox on Linux when one works there
   (`plugins/subprocess_sandbox.py`: bubblewrap, else `unshare`; no network unless the server
   declared it); elsewhere they, and `pip`, shell commands and generated-script test runs, are
   outside it. There is no eBPF, seccomp, landlock or firewall integration.

## 6. Verdict

**In ambition and in specific subsystems, ELI is ahead of most open local-assistant
projects:** the grounding layer, the fully local model-agnostic design and the integrated
multimodal agent. **In engineering discipline it is not finished:** the swallowed
exceptions, the large files and the overlapping modules separate an extraordinarily
ambitious solo project from software others can build on. The gap is subtraction and
observability, not more features.

## 7. Highest-leverage work

1. **Make swallowed errors observable.** Replace blanket `except Exception: pass` with scoped
   types and a single structured error log, keeping graceful degradation.
2. **Split the two largest files** along their natural seams (executor action groups behind
   the dispatch table; engine stages into modules).
3. **Fold overlapping `runtime/` surfaces** into a handful of well-named modules.
4. **Split the GUI monoliths** the way the engine is meant to be split.

## 8. Honest limits that are by design

- Refusing to claim more than was checked: a scanner engine that could not run never counts
  as a pass and the verdict says coverage was partial; an unsigned plugin is reported as
  unverified; ELI never says a community plugin is safe; the training tab says the live model
  has not changed until the adapter is merged; the MCP consent text states the containment this
  machine will actually apply to a server, including none (`mcp.network_caveat`).
- Plugins are declared, verified, scanned and permission-gated; custom agents carry a
  specification and a provenance-carrying trust chain; the LoRA trainer has a human review
  gate.
