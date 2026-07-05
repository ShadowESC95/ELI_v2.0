# Session 2026-06-18 — Public-Release Hardening, Distribution, and Scaling

Reference doc for the work done the day ELI MKXI went public. Two threads ran together:
**(A)** make the repo safe and clean for public distribution, and **(B)** make the whole
surface — installer, launchers, docs, model path — consistent across **platform, hardware,
and users**, scaled for the long term (**3B on a laptop → trillion-param on 8× datacenter
GPUs**), *without sacrificing ELI's ethos* (100 % local, offline-by-default, no telemetry,
model/user/hardware-agnostic, emergent persona).

---

## 1. Changelog (commits this session, on `main`)

| Commit | Summary |
|---|---|
| `a750bc3` | **ctx-tuner robustness + PII scrub + web UI.** `n_ctx_train`-aware sizing on *both* load paths; `_effective_ctx_limit = min(loaded n_ctx, n_ctx_train)`; prompt truncate-to-fit instead of crash; engine never surfaces raw `GGUF streaming failed` as a reply. Personal name/projects/research-IP genericized in code/tests/eval; personal `.desktop` untracked. FastAPI web chat UI at `/`. |
| `bdfc9d9` | **Unified launcher + hardened server.** `scripts/eli_launch.sh` (`gui`/`serve`/`both`); `scripts/eli_serve.sh` loopback-safe by default, `--lan` mints a token + prints the phone URL. Bearer-token gate on `/v1/chat` + `/v1/execute` (enforced only when LAN-exposed). |
| `cd5ef44` | **Interactive installer.** System report (CPU/RAM/GPU+VRAM/disk) → plan → confirm; auto-selects CPU/GPU build; offers a model sized to VRAM; modern summary. TTY-gated (piped/CI stays non-interactive). New flags `--yes`, `--gpu`, `--auto-model`/`--model=`/`--no-model`. |
| `2a9a5a0` | **Remove hardcoded RTX 2060** references (comments/tests/dossiers). |
| `88fee52` | **Fully hardware-agnostic** — drop *all* specific GPU/CPU/box references (GeForce/3090/4090/A6000, "this box", exact RAM). Backend identifiers (`nvidia-smi`/CUDA/Metal/MPS) kept — those are the tech stack, not a machine. |
| _(this commit)_ | **Scaling + consistency pass** — multi-GPU installer report, README scaling section, this blueprint. |

### Earlier in the session (pre-public, not all committed)
- **Context tuner** root-cause fix: the adaptive fallback loader ignored `n_ctx_train` and
  loaded a 4096-train model at 16384 ("training context overflow") → garbled output and
  `GGUF streaming failed: Requested tokens exceed context window` surfaced as a reply.
  Fixed at the loader, the sizing math, the overflow retry, and the engine output path.
- **GUI smart-fit** floors ctx at ELI's brief+gen need so a capable model is never chopped.
- **LoRA pipeline** reorg → `training/` (extract/train/merge for Qwen3-8B), `--from-db`
  voice extractor (2.5k replies from `conversation_turns`, state excluded), bad-pattern
  filter (drops error-leakage/confab/fragment replies). *(gitignored, local.)*
- **Local data wipe**: DBs/FAISS/conversations cleared, identity reset to empty → clean
  first-run instance. Backup: `~/eli_personal_backup_20260618_135332.tar.gz`.

### Later in the session (post-scaling — release polish + correctness)
- **Full DB architecture on fresh install**: new `eli/core/init_data.py` builds every store +
  table up front (user/agent/system_index/coding_memory) — schema only, **zero personal rows**;
  wired into both installers. `agent_bus.ensure_agent_tables()` added.
- **User Model split-brain fixed**: `profile_extractor._user_db()` hardcoded `<repo>/artifacts/db`
  while the reader used `paths.user_db_path()` → on an installed package the model was written and
  read from *different* files. Now both use the canonical path (round-trip verified).
- **ctx sizing**: VRAM reserve default **1500 → 250 MB**; `ELI_CTX_FRACTION` GUI default
  **0.65 → 0.9** (matched to the loader) so launch ctx isn't needlessly capped.
- **Model catalog expanded to 7** (was 3): `qwen2.5-3b`, `qwen2.5-7b` (default), `qwen3-8b`,
  `falcon3-10b`, `phi-4` (MIT), `qwen3.6-35b-a3b` (Apache-2.0), `falcon-h1-34b`. All URLs verified
  200, licences checked. **Required nomic embedder auto-installs**; vision is optional aux.
  **Multi-select download** (`--choose`) wired into both installers (pick any number, or none).
- **Habits**: smarter detection (recurrence across ≥3 distinct days, not a same-day burst);
  `CONFIRM_HABIT` runs the habit immediately if today's slot already passed.
- **Onboarding contamination fixed**: the interview consumed *every* mid-interview message as an
  answer, so user questions were stored as `identity.role` / `preference.style`. Now a
  question/command bows out instead of being captured; contaminated rows purged.
- **Test isolation fixed (was injecting false memories)**: conftest set `ELI_ARTIFACTS_DIR` but
  the user DB resolves via `ELI_USER_DB`/`ELI_MEMORY_DB`, so `store_memory()`/reflection writers
  polluted the real `user.sqlite3`. Pinned via `ELI_USER_DB` → no test can touch the real DB
  (full suite: real DB held at 10).
- **De-personalization (multi-user)**: physics-framework bias (Ξ/χ/φ, stueckelberg/lagrangian/
  scalar/fenics/openfoam/meep/tokamak) removed from 8 runtime files → generic science detection.
- **GUI declutter**: Orchestration + Test & Review **demoted to Labs sub-tabs**; Background-job
  listing unified into the **Tasks** tab (Coding tab's duplicate removed). 12 main tabs.
- **Docs**: capabilities doc regenerated (**183/183** coverage); `blueprints/ELI_USER_MANUAL.md`
  (+ PDF, with flowcharts + cognition/memory appendices); `finetuning_guide.md` made
  model-choice-first + hardware-agnostic; capabilities PDF.
- **CI**: cross-platform smoke (ubuntu/macos/windows × py3.10/3.12) green throughout.

---

## 2. Consistency audit (platform · hardware · users)

### ✅ Consistent / verified
- **Public repo carries no personal data.** `artifacts/` (DBs, conversations, FAISS,
  memories), `blueprints/`, `training/` all gitignored — 0 tracked. Verified autobuild:
  a fresh clone creates an empty 28-table `user.sqlite3` with **0 data rows**.
- **No machine/model/user hardcoded** anywhere in tracked source (swept twice).
- **Platforms covered**: Linux/CUDA, Windows (`install.bat`→`install.ps1`), macOS/Metal
  (`install.sh` Darwin branch + `requirements-macos.txt`), Android/Termux (headless,
  expert-only — honestly scoped).
- **Offline-by-default** holds: netguard fail-closes outbound; the inbound web server does
  not breach it (binding/listening ≠ connecting out).

### ⚠️ Findings — fixed this session
- **Installer showed 1 GPU** (`nvidia-smi … | head -1`) → now enumerates all GPUs and
  reports **total VRAM** (`N× <name>  (… MiB total)`).
- **Phone server bound `0.0.0.0` with no auth** → now loopback-safe by default; LAN mode
  requires a token (gates the system-action endpoint too).
- **README model recommendation drift** (Qwen2.5-7B vs the session's Qwen3-8B) → README now
  documents the scaling path + `--auto`; Qwen3-8B is the documented LoRA/quality target.

### ⚠️ Findings — documented, not yet fixed (roadmap, §4)
- **`install.ps1` (Windows) is not yet at parity** with the new interactive `install.sh`
  (system report / plan / model offer). Functional, but plainer. *Parity port pending.*
- **`requirements` pin drift**: `requirements.txt` pins `llama_cpp_python==0.3.20`,
  `requirements-full.txt` uses `>=0.3`. Harmonize to one policy (frozen lock is canonical).
- **Capability count**: README says "208 capabilities"; runtime manifest reports 208.
  Make the README pull the live number or reconcile.

---

## 3. Scaling — 3B → trillion-param (the long-term contract)

ELI is **agnostic by construction**; the *same install* must span a Raspberry-Pi-class box
to a $250k 8× datacenter-GPU server. How each axis scales today:

| Axis | Small end | Large end | Mechanism |
|---|---|---|---|
| **Context** | 4k models warned + truncated gracefully | 256k-train models capped to their real `n_ctx_train` | GGUF metadata read pre-load; `min(loaded, train)` ceiling |
| **VRAM fit** | shed layers→batch→ctx to fit 4 GB | uses summed VRAM across all GPUs | `hardware_profile` sums all GPUs; smart-fit per machine |
| **Model size** | 3B–35B built-in catalog (7 models) | any GGUF via drop-in or catalog override | `models/*.gguf` scan + `ELI_MODEL_CATALOG`/`models/catalog.json` |
| **Quantization** | Q4/Q5 on tiny cards (KV-quant <12 GB) | full precision when VRAM allows | tier-derived `cache_type_k/v` |

**The model catalog is intentionally a starter set** (1.5B / 3B / 7B with verified URLs).
Scaling beyond it is the **override mechanism** (already implemented, no code change): drop a
`.gguf` in `models/`, or supply a `catalog.json` (same schema) for mid/large/huge models.
This keeps the built-in download honest (no unverifiable large-model URLs baked in) while
making any scale reachable.

### Ethos at every tier (non-negotiable)
Local-first does **not** weaken as hardware grows — an 8×GPU server is *on-prem*, not cloud.
Offline-by-default, no telemetry, emergent persona, and your-data-on-your-hardware hold
identically from 3B to trillion. Scaling up is a hardware fact, never an ethos compromise.

---

## 4. Roadmap / known limits (for long-term maintainability)

1. **Multi-GPU tensor-split for a single huge model.** `select_gpu()` currently picks the
   single GPU with the most free VRAM; a trillion-param model needs llama.cpp
   `tensor_split` / device mapping across all GPUs. VRAM *totals* are already summed — wire
   the loader to pass `tensor_split`/`main_gpu` when `N>1` GPUs are present.
2. **`install.ps1` interactive parity** with `install.sh` (report → plan → model offer).
3. **Requirements harmonization** — single pin policy across `requirements*.txt`.
4. **GUI first-run welcome wizard** — guided *welcome → detected hardware → recommended
   model → one-click download (progress) → name → done*, replacing the "open Settings"
   dead-end for zero-model users. (Installer side is now interactive; GUI side pending.)
5. **Catalog tiers** — once verified, add Qwen3 (8B/14B/32B) + a large tier to the built-in
   catalog so `--auto` reaches higher without a manual `catalog.json`.
6. **Commit-history email** — older commits carry a personal gmail; current ones use the
   GitHub noreply. A `git filter-repo` rewrite would scrub history (heavy; owner's call).

---

## 5. Operational notes
- Launch: `./scripts/eli_launch.sh` (desktop) · `… serve --lan` (phone web app) · `… both`.
- Server is loopback+tokenless by default; `--lan` exposes to the network *with* a token.
- Personal backup (restore the wiped local instance): the tarball in `$HOME`.
- `blueprints/` and `training/` remain gitignored (local-only reference + tooling).
