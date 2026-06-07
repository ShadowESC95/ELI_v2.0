# ELI — What It Can Actually Do

*A complete capability showcase, for the layman and the tech-savvy alike. Every
capability listed here is real and present in the code — nothing is aspirational
or embellished. This is the "what you get" document.*

---

## What ELI is considered to be

Not a chatbot. ELI is a **private, local, model-agnostic personal cognitive
runtime** — a complete AI assistant + operator that runs entirely on your own
computer. It talks, remembers, sees, listens, acts on your machine, writes and
fixes code, builds documents, creates images, looks after itself, and adapts to
you over time — with nothing leaving your device unless you explicitly allow it.

Think **"a JARVIS you actually own"**: an embodied desktop operator with ~110
distinct capabilities, a 14-agent reasoning bus, persistent memory, and full
voice/vision/gaze control — 126,600 lines of Python, one machine, your data.

---

## The 60-second pitch (plain language)

You talk to ELI — by typing or by voice — and it *does things*. It opens your
apps, plays your music, reads your screen, answers your questions, remembers your
projects, writes your reports from your own files, fixes your code, and even
installs missing software for you. It learns your patterns and offers to automate
them. It gets more thoughtful the deeper a conversation goes. And it does all of
this **offline by default** — there's a single switch for going online, and you
hold it. No account, no subscription, no telemetry, no cloud reading over your
shoulder.

---

## What makes ELI genuinely advanced (for the tech-savvy)

These are real, verified mechanisms — the parts that put ELI ahead of typical
local assistants:

- **A 14-agent reasoning bus on a dependency DAG** with *calibrated, weight-free*
  confidence fusion — each agent's contribution is weighted by evidence quality ×
  payload density × a calibration value *learned from its own track record*.
- **A 12-stage retrieval pipeline** — HyDE query expansion → vector (FAISS) +
  keyword (FTS5) + knowledge-graph multi-hop + RAG → cross-encoder rerank.
- **5 genuinely multi-pass reasoning modes** — chain-of-thought, self-consistency
  (N samples + consensus), tree-of-thoughts (branch/prune), constitutional
  (draft→critique→revise), and quick — and it **auto-escalates** through them as a
  conversation deepens, without you asking.
- **Deterministic self-honesty** — when you ask ELI about itself, it answers from
  *live measurement of its own runtime*, not from the model's imagination.
- **A self-verifying coding agent** — plan → DAG decompose → UCB tree-search →
  run → test → repair, with a long-term (bug→fix) memory.
- **It improves itself** — safely patches its own source (verify + auto-revert)
  and can **fine-tune its own model on your conversations**, locally.
- **It heals its environment** — detects a missing app and installs it for you
  (apt/snap/flatpak) on confirmation.
- **Model-agnostic** — no model is hardcoded; swap in any local GGUF and ELI gets
  smarter for free, plus auto-tunes context/GPU-layers/batch to your hardware.

---

## A day with ELI

- **Morning:** a brief — what happened, what it noticed, a consolidated news
  digest matched to your interests, and anything needing your attention.
- **Working:** *"open my project and Spotify"* → done. *"what's on my screen?"* →
  it looks and tells you. *"click that"* → it clicks where your eyes are resting.
  *"summarise these three PDFs"* → done, locally.
- **Deep work:** *"draft a technical report from these sources"* → it writes a
  structured document grounded in your files. *"write me a script that does X"* →
  it plans, writes, runs, tests and repairs it. *"there's a bug in this file"* →
  it scans, shows you what it found, and fixes it after you confirm.
- **Hands-free:** speak to it across the room — it ducks your music to hear you,
  waits for the full command, and never mistakes its own voice for yours.
- **Quietly:** it remembers your name, projects and preferences, adapts its tone
  to you, and offers to automate routines it notices — only ever with your yes.

---

## The full capability map

### 🗣️ Talk & think
Natural conversation with persistent memory of you. **Five reasoning modes —
Quick · Normal · Advanced · Research · Expert** — each genuinely multi-pass
(self-consistency samples, tree-of-thoughts branches, draft→critique), with the
mode **auto-selected by how deep the conversation gets**. When evidence is weak,
ELI **autonomously deepens**: it re-gathers harder and escalates the mode one
tier at a time to raise its confidence *before* answering — and for a Quick reply
it can keep working in the **background** and surface a better, more-grounded
answer afterwards in the Proactive panel. Plus an emergent, consistent persona;
multi-part questions answered as multiple answers; tone that adapts over time.

### 🖥️ Run your computer
Open / close / focus / hide / minimise / maximise apps and windows; tile windows;
switch workspaces; next/previous window; open system / audio / power / file /
communication / media / network settings hubs; open your IDE (optionally at a
file); open URLs and the browser. App-launch is backed by an index of **7,843
executables** — and if an app isn't installed, ELI **offers to install it for you**.

### 🎯 Gaze control (webcam)
Eye-tracking via MediaPipe with calibration and smoothing — *"open/click that"*
moves the cursor to where you're looking and clicks. A genuine hands-free and
accessibility capability.

### 🎙️ Voice (hands-free)
Always-listening with a wake word; it **ducks your media volume** to hear you,
**waits for incomplete commands** to finish, **ignores its own spoken output**,
and learns a **per-user voice profile**. Dictation, transcription, and a spoken
voice (Piper TTS) that never voices garbled fragments.

### 👁️ See & understand
Local vision-language models describe any image or your live screen; OCR pulls
text out of pictures; *"find the button that says X"* locates UI elements on
screen; optional ambient glances keep rolling awareness — all local, no APIs.

### 🎨 Create images
A from-scratch **procedural renderer** with 10+ scene types (landscape, space,
city, poster, emblem, abstract, product, …), composition planning, palettes,
atmosphere and post-processing — no model needed. Plus optional SSD-1B diffusion
with VRAM hot-swap, and matplotlib plotting from your data.

### 🎵 Media
Play a song or playlist on the platform you name (Spotify playlist-tab,
YouTube Mix-radio); play / pause / stop / next / previous / repeat / shuffle via
MPRIS — honest about reachability, and an explicitly-named platform never drifts
to another.

### 🌐 Web & news (toggle-gated)
Flip the Net switch on and ELI fetches web answers, weather, and **synthesised
news** (a rolling 3-hourly digest matched to your interests — not raw headlines).
Switch it off and it's sealed at the network socket.

### 📁 Files & documents
Create / read / list files and folders; summarise any file; analyse CSVs, PDFs
(single or whole folders), and images. **Convert any document** to PDF, PDF via
LuaLaTeX, .docx, .doc, .odt, .rtf, HTML, Markdown, .tex, EPUB or .txt — from the
Files tab (pick a file → format → Convert) or by asking ("convert report.md to
pdf"); backed by pandoc + a LibreOffice fallback. Two standout tools:

- **📊 Report Builder** *(now its own main tab)* — drop in your sources (PDFs,
  data, code, notebooks, projects) and ELI writes a full document (report, paper,
  proposal, audit, simulation write-up) **grounded in your evidence**, with
  per-genre standards and strict discipline: every claim is tied to a source or
  marked `[source needed]` — no fabricated citations or numbers.
- **💬 File Chat** — open a file or folder and have a conversation *about it* —
  ask questions, get explanations, all from the actual contents.

Even a quick *"generate a document about X"* in chat now runs a **multi-stage
grounded pipeline** — it first gathers evidence with the right agents (code, web,
memory, runtime), plans an outline, drafts section-by-section against that
evidence, then does a review→revise pass — instead of one shallow pass. If the
evidence comes back thin, low confidence triggers a deeper re-gather across more
agent tiers before it commits to writing.

### 💻 Code
A frontier-grade coding agent: describe a task and it plans it, decomposes it into
a dependency graph, writes it, runs it in a sandbox, tests it, and repairs its own
bugs — remembering fixes for next time. Plus examine-and-fix on your existing
files (tiered scan → offer → verified, auto-reverting patch), project generation,
diffs, and a built-in Sim-IDE.

### 🧠 Remember you
A four-store memory (vector + full-text + knowledge graph + working memory) that
keeps a **living, versioned profile** of you — and is *dynamic*: active projects
stay fresh, abandoned ones fade, so its picture of you reflects *now*.

### 🔧 Look after itself
Logs its own failures and runs a self-repair cycle (generate → verify → apply →
auto-revert); runs maintenance (update, rebuild indexes, refresh capabilities);
audits its own runtime honestly with live health probes; and can **train a LoRA
adapter on your own conversations**, locally.

### 🎯 Be proactive & self-aware
A background daemon notices your patterns, **offers** to automate routines (never
silently), builds your morning report, and surfaces things worth your attention —
through a governed, approval-gated mission layer. On a 30-minute beat it also runs
a **self-awareness/autonomy tick**: it watches its own code for changes, refreshes
its self-model, and advances goals into proposals for your approval (observe-only /
memory-write — nothing destructive runs unattended). Ask it about itself — *"what
are you aware of"*, *"audit your identity"*, *"how does your cognition work"* — and
the agents run the real audits and ELI **summarises** the grounded results, rather
than dumping a report or guessing.

---

## The workspace — your 12 main tabs

| Tab | What it's for |
|---|---|
| 💬 **Chat** | The main conversation + voice, with reasoning-mode and Net toggles. |
| 🎯 **Proactive** | 6 sub-tabs: Suggestions, Summaries, Insights, Habits, Self-Improve, Memory. |
| 🖼️ **Images** | Generate images (procedural or diffusion). |
| ⚡ **Quick Actions** | A drag-and-drop board of one-click actions. |
| 🖥️ **Screen** | Screen control, capture, and analysis. |
| 📂 **Files** | Browse, act on, and **convert** files (any format). |
| 🔬 **Labs** | Scientific workspace — 8 sub-tabs: Notebook, Memory & Conversations, Jupyter, Calculator, Physics, File Chat, Workspaces, Sim/IDE. |
| 🧩 **Coding** | Write, run, and have ELI fix/explain code. |
| 🗓️ **Tasks** | Scheduled / overnight / background jobs (add, edit, cancel). |
| 📄 **Report Builder** | Evidence-grounded, multi-stage document generation (promoted from Labs). |
| 🌍 **Eli's World** | The live embodied self-model — ELI's avatar moving through cognitive "rooms" as it reasons. |
| ⚙️ **Settings** | 5 sub-tabs: Agents, Models, Cognition, Plugins, Self-Upgrade. |

---

## Make it yours — customisability

ELI is built to be shaped by *you*:

- **Swap the brain.** Model-agnostic — drop in any local GGUF model; ELI detects
  how to talk to it and auto-tunes to your hardware. No vendor lock-in; it
  improves as local models do.
- **Tune the mind.** A dedicated **🧠 Cognition** settings panel exposes every
  knowledge-gathering limit (memories, KG facts, rerank depth, the synthesis
  budget), the **per-mode time budgets** (how hard each of Quick→Expert works),
  and the **background-deepening** toggle — all live sliders, deeper or leaner to
  taste.
- **Extend it.** A real plugin system (weather, web, calendar, notes, pomodoro,
  smart-home, document-reader, web-automation, system-stats, media, TTS) with
  install/enable/disable — and you can **create your own custom agents** through a
  guided dialog (validated and trust-gated before they run, then live-registered).
- **Teach it routines.** ELI proposes habits it notices; you approve, edit, or
  add your own — scheduled and run automatically.
- **Control the boundary.** One Net toggle decides whether it can touch the
  internet at all, enforced at the network socket itself.

---

## The thing that makes all of it matter: it's yours

Every capability above runs **on your machine, with your data, under your
control.** No account, no subscription, no telemetry, no cloud. Offline by
default and enforced at the socket; private by construction; honest about itself
by design. ELI trades the raw horsepower of a giant cloud model for something a
cloud assistant structurally cannot offer — **a complete, capable, embodied AI
that is wholly, permanently yours, and that gets better every time local models
do.**

---

## Who it's for

Anyone who lives on their computer and wants a genuinely capable assistant they
fully own and control — especially people working on sensitive or personal
material they'd never paste into someone else's website. It's most at home with a
technical user on Linux today, but the capability surface — voice, vision, gaze,
control, memory, coding, documents, images, proactivity, self-improvement — is
broad enough to be a daily companion, not a demo.

---

*Honest companion reading (the limits + engineering verdict, deliberately kept
separate from this capability showcase): `complete_findings.md`,
`project_overview.md`. Exhaustive technical map: `capability_catalogue.md`.*


---

## Update Advisory — 2026-06-07
- Created this session as the capability-showcase / selling document (strengths
  only, no shortcomings — those live in `complete_findings.md`). Every capability
  is verified present in the code; no embellishment. Cross-checked against
  `capability_catalogue.md`.
- **Revised (same day):** Report Builder promoted to a main tab (12 main tabs;
  Labs now 8 sub-tabs); Files tab gained a Convert-document control (lualatex/pdf/
  doc/docx/odt/rtf/html/md/tex/epub/txt). Chat "generate a document" now runs the
  multi-stage grounded pipeline (`runtime/report_pipeline.py`: evidence → plan →
  sections → review→revise) with a confidence-driven deeper-tier re-gather. The
  autonomy/self-awareness tick now actually runs (proactive daemon, governed).
  Self-awareness queries gather-then-summarise (no data dumps). Tab table corrected
  to the real main tabs.
