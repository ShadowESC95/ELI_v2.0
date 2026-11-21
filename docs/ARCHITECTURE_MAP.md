# ELI v2 — architecture map

**Read this before adding anything.** Its purpose is to stop the most expensive
mistake in this codebase: building something that already exists, somewhere you
did not think to look.

Every figure below was measured from the tree (2026-11-20, v2.5.36), not remembered.
Regenerate them with the commands in [Keeping this honest](#keeping-this-honest).

---

## 1. Scale

| | |
|---|---|
| Tracked Python (excl. tests/build) | **227,946 lines** across **542 modules** |
| `eli/` Python | **207,284 lines** across **451 modules** |
| Test files | **593** (`test_*.py` under `tests/`, 572 of them at its top level) |
| Actions in `capability_manifest.json` | **231** (190 router-routable; 214 routable or in the supported list; 207 `SUPPORTED_ACTIONS`) |
| SQLite stores | **8** under `artifacts/db/`: four seeded from `config/templates/db/` (`user` 28 tables + 3 FTS5 indexes · `agent` 2 · `system_index` 4 · `coding_memory` 1, more added at run time) and four created on first use (`orchestrator_audit`, `capability_state`, `documents`, `agenda`) |
| GGUF model catalogue | 7 chat models + 3 auxiliary files (embedder, vision model and projector) in `eli/core/model_download.py` |

The sibling repo **ELI v3** is 255,513 lines / 685 modules (tracked Python excl.
tests/build) — the same system with the god-files decomposed further. They share no
git history; port by content diff (`tools/repo_parity.py` shows drift).

---

## 2. Packages, by weight

| package | files | lines | what lives there |
|---|---:|---:|---|
| `eli/runtime/` | 101 | 40,038 | grounding, evidence, self-model, devices, policy, scheduling, role gate |
| `eli/execution/` | 14 | 27,638 | router + executor — all 231 manifest actions; the shell gate |
| `eli/gui/` | 28 | 26,712 | PySide6 desktop app |
| `eli/cognition/` | 52 | 23,693 | agent bus, persona, inference, tone, scoring |
| `eli/kernel/` | 10 | 19,269 | the 12-stage engine |
| `eli/core/` | 33 | 12,372 | config, paths, netguard, load plan, DAG orchestrator |
| `eli/perception/` | 24 | 10,795 | STT, TTS, vision, gaze, screen OCR |
| `eli/memory/` | 12 | 10,584 | SQLite + vector store + knowledge graph + claims |
| `eli/plugins/` | 34 | 6,045 | calendar, media, notes, weather, web, pomodoro… + marketplace and sandboxes |
| `eli/tools/` | 25 | 6,040 | image engine, capability registry, news, diagnostics |
| `eli/planning/` | 20 | 4,354 | proactive daemon, habits, goals, job and proposal queues |
| `eli/learning/` | 14 | 4,271 | LoRA pipeline, feedback |
| `eli/integrations/` | 19 | 3,862 | MCP client and server, Ollama, cross-platform media, MPRIS |
| `eli/utils/` | 5 | 2,127 | logging, platform compatibility |
| `eli/coding/` | 12 | 2,104 | the coding agent, its sandbox, code mode |
| `eli/setup/` | 9 | 1,935 | installer back end, hardware policy, first-run wizard |
| `eli/world/` | 26 | 1,867 | autonomy engine, goal ecology, world constitution |

Five modules carry over a quarter of the tracked Python (60,946 of 227,946 lines):

```
17,431  eli/kernel/engine.py
15,645  eli/execution/executor_enhanced.py
12,534  eli/gui/eli_pro_audio_gui_v2_0.py
 9,328  eli/execution/router_enhanced.py
 6,008  eli/memory/memory.py
```

---

## 3. How one turn flows (v2.3.37+)

```
user text
   │
   ▼
kernel/engine.py — canonical S01–S12 (pipeline_trace.py)
   S01 PERCEIVE_INGEST
   S02 INPUT_GUARDS         injection filter, message fitted to the window, role gate
   S03 ROUTER               router_enhanced: deterministic contracts first, then a
                            grammar-constrained LLM resolver over 165 of the 207 actions
   S04 GROUNDING_GATE
   S05 PLANNER              (mode-aware: fast → deep)
   S06 AGENT_BUS            retrieve_for_turn() + dispatch_specialists()
   S07 CONTEXT_ASSEMBLY     heuristic rerank
   S08 INFERENCE_BROKER
   S09 REASONING_SYNTHESIS  (private mode algo)
   S10 OUTPUT_GOVERNOR
   S11 RESPONSE_DELIVERY
   S12 LEARNING_STATE_UPDATE  (learning_coordinator.finalize_turn)
   ▼
output governor → response
```

The LLM resolver is never offered ELI's internal actions or the ones that need the user's
own words (`llm_intent._INTERNAL_ACTIONS`, `_EXPLICIT_ONLY_ACTIONS`: the shell, settings,
plugins, MCP, self-patching, forgetting …).

**All CHAT modes** (Quick … Expert) run the orchestrator at scaled depth — Quick no
longer skips to a bare bus dispatch. The bus is composed inside S06 or used as a
fallback if orchestration fails.

**Reasoning modes:** `quick`, `chain_of_thought` (Normal), `self_consistency`
(Advanced), `tree_of_thoughts` (Research), `constitutional_ai` (Expert) — each
with its own token budget, temperature and confidence threshold.

**Entry points:** `eli/__main__.py` (`python -m eli` and the `eli` command: the GUI, or
`--headless`, `--mcp-server`, `--license` …), `eli.gui.app:main` (the `eli-gui` window) and
`api/server.py` (FastAPI; the web UI and API clients use `/v1`).

---

## 4. Before you build: where to look first

Five features were nearly rebuilt from scratch in a single session because the
search used the *builder's* vocabulary rather than the code's. Grepping for
"alias" never finds a module that says *role*, *candidate*, `first_available`.

**Read the subsystem, not your own feature name.**

| if you are about to build… | it already exists in |
|---|---|
| device discovery (mDNS / SSDP / Bluetooth) | `runtime/device_server.py` — `discover()`, verified live |
| per-OS app names (Windows/macOS/KDE/XFCE/Android) | `utils/platform_compat.py` — `normalize_app_name()`, `first_available()` |
| launching / closing / focusing apps | `system/portable_app_control.py` — discovery + fuzzy match |
| screen OCR, locating a label to click | `perception/screen_locator.py` |
| home UI: rooms, scenes, automations, onboarding | the Devices tab's **nine** panes in `api/static/app.js` |
| MQTT broker setup, guided | `runtime/mqtt_setup.py` + the MQTT Setup pane |
| switching a BLE bulb | `runtime/ble_light.py` — GATT writes after reading the bulb's characteristics |
| anything about "what is true right now" | `runtime/` — see below |

`eli/runtime/` is the single biggest package and the least guessable. Its 101
modules include `evidence_arbitration`, `deterministic_grounding_gate`,
`grounding_escalation`, `truth_report`, `persistence_gate`, `self_facts`,
`authority_gate`, `response_contracts`. If a question sounds like
*"how does ELI know / prove / refuse / report X"*, the answer is almost
certainly already in there.

---

## 5. Honest gaps

Not everything is built. These are real, as of this writing:

- **BLE bulbs: three protocols.** `BluetoothDriver.control` maps `on`→`connect` and
  `off`→`disconnect`, which is Bluetooth *link* management, so the device server sends a
  light whose id is a BLE address to `runtime/ble_light.py` instead. That connects, reads
  the characteristics the bulb exposes and writes to one of the protocols it knows
  (`triones`, `elk-bledom`, `zengge`); a bulb matching none is reported as unsupported with
  its characteristic list. These bulbs give no read-back, so ELI reports the write it made,
  never that the light changed.
- **`eli/world/`** is 26 files but only 1,867 lines — autonomy engine, goal
  ecology and world constitution are sketches next to the density of the rest.
- **The web UI is one 185 KB `app.js`.** Now real files under `api/static/`
  (`app.js` 189,122 B · `app.css` 44,274 B · `index.html` 6,901 B) rather than a
  233 KB Python string literal, but not yet split into modules.

**Not a gap:** `eli/brain/` is not in the repository. Custom agents are kept in the data
folder: a code agent under `<data dir>/agents/custom` (`ELI_CUSTOM_AGENTS_DIR` adds one
more), and the agent wizard's specifications under `<data dir>/agents`
(`ELI_AGENT_SPECS_DIR` overrides). `eli/cognition/custom` and `eli/brain/agents/custom`
are still searched for older agents (`agent_bus._custom_agent_dirs`).

---

## 6. Conventions worth knowing

- **Blueprint markdown and its PDFs are both tracked** (`.gitignore` admits
  `blueprints/*.md` and `blueprints/*.pdf`). Regenerate the 12 customer-facing PDFs with
  `scripts/generate_blueprint_pdfs.sh` (version-stamped from `pyproject.toml`). Docs under
  `docs/` — including this file — are tracked normally.
- **`ELI.spec` builds its data manifest from `git ls-files` only.** An untracked
  asset is silently absent from every AppImage and `.exe` while working
  perfectly from source. `api/static/` is included via the `api` prefix.
- **`tests/conftest.py` keeps a test run off this machine, not off the real
  libraries.** The real libraries load (tests import `api.server` directly); what is
  cut off is the machine: an offscreen Qt platform, no display or session bus, stub
  `xdg-open`/`gio`/`open` launchers, a null audio device, proxies pointed at a closed
  local port so an unstubbed request fails at once, and every artifact and database
  write redirected to `artifacts/_pytest/`.
- **Version lives in two places:** `pyproject.toml` and
  `eli/kernel/self_upgrade.py`. Releases are tag-triggered CI.
- **Several agent sessions share this checkout.** Never `git add -A`; stage by
  name. `git worktree add` gives a session its own tree.

---

## Keeping this honest

```bash
# scale
git ls-files '*.py' | grep -vE '^tests/|^build/' | xargs wc -l | tail -1

# per-package
for d in eli/*/; do
  echo "$(git ls-files "$d*.py" | xargs wc -l 2>/dev/null | tail -1 | awk '{print $1}') $d"
done | sort -rn

# largest modules
git ls-files '*.py' | grep -vE '^tests/|^build/' | xargs wc -l | sort -rn | head -20

# actions
python3 -c "import json;print(json.load(open('capability_manifest.json'))['total'])"
```

If a number here disagrees with the tree, the tree is right — update this file.
