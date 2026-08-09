# ELI v2 — architecture map

**Read this before adding anything.** Its purpose is to stop the most expensive
mistake in this codebase: building something that already exists, somewhere you
did not think to look.

Every figure below was measured from the tree, not remembered. Regenerate them
with the commands in [Keeping this honest](#keeping-this-honest).

---

## 1. Scale

| | |
|---|---|
| Tracked Python (excl. tests/build) | **175,780 lines** across **473 modules** |
| Test files | **272** |
| Actions in `capability_manifest.json` | **216** |
| Live SQLite stores | **4** (`user` 39 tables · `agent` 26 · `system_index` 4 · `coding_memory` 2) |
| GGUF models on disk | 6 (~12 GB) |

The sibling repo **ELI v3** is 184,505 lines / 639 modules — the same system with
the god-files decomposed further. They share no git history; port by content
diff (`tools/repo_parity.py` shows drift).

---

## 2. Packages, by weight

| package | files | lines | what lives there |
|---|---:|---:|---|
| `eli/runtime/` | 98 | 31,781 | grounding, evidence, self-model, devices, policy, scheduling |
| `eli/execution/` | 15 | 24,653 | router + executor — all 216 actions |
| `eli/gui/` | 24 | 23,041 | PySide6 desktop app |
| `eli/cognition/` | 31 | 15,594 | agent bus, persona, inference, tone, scoring |
| `eli/kernel/` | 8 | 15,411 | the 12-stage engine |
| `eli/perception/` | 23 | 8,859 | STT, TTS, vision, gaze, screen OCR |
| `eli/core/` | 28 | 8,138 | config, paths, netguard, DAG orchestrator |
| `eli/memory/` | 13 | 7,393 | SQLite + vector store + knowledge graph |
| `eli/tools/` | 29 | 7,424 | image engine, capability registry, diagnostics |
| `eli/planning/` | 24 | 4,040 | proactive daemon, habits, scheduled tasks |
| `eli/learning/` | 12 | 3,435 | LoRA pipeline, feedback |
| `eli/plugins/` | 26 | 1,989 | calendar, media, notes, weather, web, pomodoro… |
| `eli/world/` | 26 | 1,642 | autonomy engine, goal ecology, world constitution |

Five modules carry roughly a third of the codebase:

```
15,102  eli/execution/executor_enhanced.py
13,992  eli/kernel/engine.py
12,100  eli/gui/eli_pro_audio_gui_v2_0.py
 7,627  eli/execution/router_enhanced.py
 5,694  eli/gui/labs_tab.py
```

---

## 3. How one turn flows

```
user text
   │
   ▼
router_enhanced ── deterministic contracts first
   │               then a grammar-constrained LLM resolver over 187 actions
   ▼
kernel/engine.py — 12 stages
   1  Intent
   2  Persona lock          (deferred on the quick path)
   3  HyDE                  (skipped in quick mode)
   4  Planner               (keyword / semantic / RAG / KG budgets)
   5-9 AGENT BUS  ──────────┐  parallel: memory · knowledge_graph · orchestrator
   10 Context assembly      │            critic · system · file_code · habit
   10.5 Persona handoff     │            voice · reflection · introspection
   11 LLM generation        │            proactive · self_improvement
   12 Confidence ───────────┘
   ▼
output governor → response
```

**Reasoning modes:** `quick`, `chain_of_thought`, `self_consistency`,
`tree_of_thoughts`, `constitutional_ai` — each with its own token budget,
temperature and confidence threshold.

**Entry points:** `eli.gui.app:main` (desktop, the `eli` command) and
`api/server.py` (FastAPI; the web UI and the v3 mobile app both ride `/v1`).

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
| anything about "what is true right now" | `runtime/` — see below |

`eli/runtime/` is the single biggest package and the least guessable. Its 98
modules include `evidence_arbitration`, `deterministic_grounding_gate`,
`single_pass_authority`, `typed_stage_bridge`, `packet_native_downstream`,
`self_facts`, `authority_gate`, `response_contracts`. If a question sounds like
*"how does ELI know / prove / refuse / report X"*, the answer is almost
certainly already in there.

---

## 5. Honest gaps

Not everything is built. These are real, as of this writing:

- **No GATT characteristic writes anywhere.** `BluetoothDriver.control` maps
  `on`→`connect` and `off`→`disconnect`, which is Bluetooth *link* management.
  A BLE bulb cannot be switched on by ELI; that needs a new driver with
  per-vendor GATT payloads.
- **`eli/world/`** is 26 files but only 1,642 lines — autonomy engine, goal
  ecology and world constitution are sketches next to the density of the rest.
- **The web UI is one 185 KB `app.js`.** Now real files under `api/static/`
  (`app.js` 189,122 B · `app.css` 44,274 B · `index.html` 6,901 B) rather than a
  233 KB Python string literal, but not yet split into modules.

**Not a gap:** `eli/brain/` looks empty (0 lines) and is not dead — it is the
target directory the agent wizard writes user-created agents into
(`agent_bus.py:3161`). It is empty until you create one.

---

## 6. Conventions worth knowing

- **Blueprint markdown is gitignored; the PDFs are the tracked deliverable.**
  Regenerate with `scripts/generate_blueprint_pdfs.sh` (12 PDFs, version-stamped
  from `pyproject.toml`). Docs under `docs/` — including this file — are tracked
  normally.
- **`ELI.spec` builds its data manifest from `git ls-files` only.** An untracked
  asset is silently absent from every AppImage and `.exe` while working
  perfectly from source. `api/static/` is included via the `api` prefix.
- **`conftest.py` force-mocks heavy dependencies** — PIL, pydantic and others.
  A test that imports `api.server`, or that needs real imaging, cannot run. Test
  such code by reading the artifact (e.g. parsing the `.ico` container) or by
  exec'ing the function under test in isolation.
- **Version lives in two places:** `pyproject.toml` and
  `eli/kernel/self_upgrade.py`. Releases are tag-triggered CI.
- **Several agent sessions share this checkout.** Never `git add -A`; stage by
  name. `scripts/new_worktree.sh` gives a session its own tree.

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
