# Blueprint — ELI Home Server: Frontier Roadmap (Home · Work/Enterprise · Research)

*Status: living roadmap. Updated 2026-06-28 (original 2026-06-26).*
*Framing: GAP ANALYSIS. ELI already has a local FastAPI server (`api/server.py`) with an
embedded dashboard PWA, a 12-stage cognition pipeline, a 15-agent DAG bus,
offline-enforcing `netguard`, a deterministic grounding gate, a 208-capability registry,
local STT/TTS, FAISS + hybrid RAG, an approval/risk gate, and **ELI's own MQTT smart-home
device server** (Home Assistant was removed). This document is the delta — what turns that
into a frontier (June 2026) local AI server across three audiences — not a greenfield design.*

> **Progress as of 2026-06-28:** Phases **0, 1, 3, 4, 6** have shipped (SSE streaming;
> OpenAI-compatible local API; browser voice; research corpus workspace; multi-user RBAC +
> tamper-evident HMAC'd audit trail), plus a live dashboard, ELI's own smart-home (rooms,
> scenes, real automations with conditions/multi-action/sun triggers), and the **monitored
> Internet toggle**. **MCP (Phases 2 & 5)** and the remaining **Home** polish (Phase 7:
> household profiles, pushed briefings, ambient mode) are the open frontier. See the phase
> table in §7 for the per-phase status.

---

## 0. Thesis — ELI as a private, local MCP hub

The defining 2026 shift is **MCP (Model Context Protocol)** becoming the universal
interconnect for agents and tools. Cloud assistants do this by shipping your data to a
vendor. ELI's differentiator is to do it **on-prem, offline-governed**: be both an MCP
*server* (apps/agents plug into ELI's capabilities + grounded memory) and an MCP
*client* (ELI reaches your tools), with `eli/core/netguard` as the final arbiter of
anything outbound. No cloud assistant can match the privacy; most local ones lack the
interop. That single capability serves all three audiences below.

The product line stays the same as the codebase's existing convictions: **local,
private, grounded, agentic, offline-enforced.** Every item here leans into that — none
trades it away for cloud-feature parity.

---

## 1. Is MCP DOA on a local model's token budget? (the honest answer)

**No — but only if the client side is designed frugally.** The concern is real: ELI runs
a local model at a tight context (≈12 K on an 8 GB card), and the persona/memory brief
already fills much of it. Naive MCP — dumping every tool's JSON schema into every prompt
plus verbose tool results — would blow that budget. The mitigations, all of which ELI
*already has the machinery for*:

| MCP direction | Token cost to ELI | Why |
|---|---|---|
| **ELI as MCP *server*** | **Zero** | Other clients consume ELI's tools; the schema/result tokens live in *their* model's context, not ELI's. Pure upside — **start here.** |
| **ELI as MCP *client*** | Controlled, not fatal | Only naive injection is fatal. ELI already budgets aggressively. |

**Client-side frugality (reuse, don't rebuild):**
- **Tool retrieval, not tool dump.** ELI's router + `_select_agents_for_intent` already
  pick a *minimal* set per turn. Apply the same top-K selection to MCP tools: a tool
  registry with semantic retrieval injects only the 1–3 relevant tool schemas, never all
  of them.
- **Result budgeting.** Route MCP tool results through the existing `_cap_text` evidence
  cap + the deterministic grounding gate (head/tail truncation, summarization) before they
  reach the model — the same path document/RAG evidence already takes.
- **Two-pass routing.** A cheap deterministic/no-think pass decides *which* tool; the real
  generation call then carries only that one tool's compact schema.
- **Terse schemas.** ELI controls how tool defs render; keep them minimal.

**Bottom line:** MCP token cost is a prompt-engineering discipline, and ELI is unusually
well-equipped (mode-aware evidence budgeting is already core). Server side is free; client
side is viable with retrieval + budgeting. **Not DOA.**

---

## 2. Shared foundation (modern table-stakes the server lacks today)

Status (2026-06-28): SSE streaming, the OpenAI-compatible endpoint, and multi-user RBAC
have all **shipped**; **MCP** is the one remaining item from this section. The engine
streams tokens (`yield token`) and the server now exposes it.

1. **SSE token streaming — DONE.** Exposes the engine's `yield token` over
   `text/event-stream` at `/v1/chat/stream`. Killed the silent 60–280 s waits. Smallest
   effort, biggest UX win, benefits every audience.

2. **ELI local API (drop-in shape) — DONE.** `/v1/chat/completions` (+ streaming) speaks
   the *de-facto industry request/response shape* most local-AI tools already send. **This
   is NOT OpenAI and nothing leaves the box** — it's ELI's local model behind a
   widely-understood plug, so existing local-AI tools (IDE assistants, notebooks, MCP
   bridges) can point at `http://localhost:8081` and run on ELI with no code changes. The
   point is to pull tools *off* the cloud and onto your local model — not to add a cloud.

3. **MCP (server first, then client)** — map the 208-capability registry → MCP tools
   (start read-only + smart-home), expose an MCP server endpoint; later, consume external
   MCP servers through the approval gate + `netguard`.

4. **Browser voice — DONE.** Browser mic → ELI's **local** whisper STT, **local** Piper TTS
   back. "Talk to ELI" from any phone, inference on the host, gated by `netguard`.

---

## 3. Home

Build on: **ELI's own MQTT device server** (`eli/runtime/device_server.py` — Home Assistant
removed), the proactive daemon + `MORNING_REPORT`, the Home/System web tabs, `self_status`.

- **Natural-language scene/automation authoring — DONE.** "dim the lights at sunset" → a
  native ELI scene/automation: real trigger types (time / sunrise-sunset / device-state),
  **conditions** (all must hold), **multi-action**, and a **location picker** for sun
  triggers. mDNS device discovery + usage learning turn patterns into suggested automations
  surfaced by the proactive daemon. *(Runs on ELI's own server, not HA.)*
- **Household profiles** *(open — Phase 7)* — per-resident memory/voice/profile (ELI already
  models "you" and now has per-member auth via RBAC; make the memory/voice multi-resident).
- **Pushed proactive briefings** *(open — Phase 7)* — proactive daemon + `MORNING_REPORT` →
  web push to phones (morning brief, reminders, "laundry's done").
- **Ambient dashboard mode** *(open — Phase 7)* — the Overview/Home tabs as an always-on
  wall display, auto-refreshing (the live dashboard already auto-refreshes).

---

## 4. Work / Enterprise

Build on: `approval_engine` (risk gate), `runtime_snapshot` (provenance), the code agent
+ RAG, `netguard` (egress control).

- **On-prem MCP to internal tools** — tickets, wikis, repos, databases via MCP client.
  The data never leaves the box; `netguard` governs every reach. This is the actual
  enterprise unlock (privacy + interop without a vendor).
- **Multi-user + tamper-evident audit trail** — per-user isolation, and a log of *which
  agent ran what action with what approval* (surface the existing `approval_engine` +
  `runtime_snapshot` as compliance/audit).
- **Codebase / document workspaces** — point the code agent + hybrid RAG at a repo or doc
  set; grounded, cited answers, fully local (no code uploaded to any vendor).
- **ELI local API (from §2)** = drop-in private LLM for existing internal tooling that
  speaks the standard request shape — the data stays on-prem.

---

## 5. Research (worked example — privacy-preserving local research stack)

This lane maps almost 1:1 onto the example stack you gave; here it is in ELI terms,
reusing what exists (`ANALYZE_PDF_FOLDER`, FAISS, hybrid merge + rerank, the evidence
planner, background jobs, `SCHEDULE_TASK`, research mode).

1. **Centralise knowledge → text.** Ingest papers/PDFs/scans/notes into a searchable
   corpus. *Reuse* `ANALYZE_PDF_FOLDER` (already a background job) + an OCR pass → Markdown/
   plain text → FAISS index. (Your 191-PDF physics corpus is the test case.)
2. **Host the model locally — ELI *is* the host.** No Ollama/Wyoming proxy needed: ELI's
   local API (§2) makes ELI itself the private brain your research stays in front of — the
   same standard request shape those proxies expose, but it's ELI's local model on your
   hardware. (ELI can still *proxy* to Ollama if you prefer a different engine.)
3. **MCP for control + tools.** Connect ELI (MCP client) to **Home Assistant's official
   MCP server** to control lights/temperature/media by research workload ("focus mode →
   dim, mute notifications"), and to a **web-search MCP tool** (netguard-gated) for live
   referencing — private environment, controlled egress.
4. **Grounded Q&A with provenance** — query the corpus; answers carry *which source, which
   model, which params* (`runtime_snapshot` + the grounding gate). Reproducible by design.
5. **Long-running research agents** — `SCHEDULE_TASK` + research mode → overnight
   literature/experiment runs that emit a sourced report.
6. **Research analytics** — connect a data-science env (Python/Jupyter) directly to ELI's
   local SQLite stores (and HA's SQLite via its Data Science Portal) to track research
   habits + home-lab performance over time — all on local data.

---

## 6. Security guardrails (carried forward — non-negotiable)

- **No raw executor over HTTP.** The full `_execute_impl` is never web-exposed (the hole
  closed earlier). MCP/web tools are an *allowlist*, not the whole dispatcher.
- **Every new surface token-gated** (`Depends(_require_token)`); non-loopback binds fail
  closed (the bind guard already added).
- **MCP client calls + tool actions gated through `approval_engine`**; risky actions need
  confirmation.
- **`netguard` remains the final arbiter** of anything outbound — MCP client reaches,
  web-search tools, and model proxying all route through it.
- **The privacy story IS the product.** No feature is worth trading it.

---

## 7. Phased roadmap

| Phase | Ships | Status | Audience |
|---|---|---|---|
| **0** | SSE streaming (`/v1/chat/stream`) | ✅ **DONE** | all |
| **1** | ELI local API `/v1/chat/completions`-shape (+stream) — standard plug, local model | ✅ **DONE** | work, research |
| **2** | MCP **server** (read-only + smart-home tool subset) | ⬜ open (the free-token frontier bet) | all |
| **3** | Browser voice (mic → local whisper STT → reply → local Piper TTS) | ✅ **DONE** | home |
| **4** | Research corpus workspace (ingest → FAISS → grounded Q&A + provenance) | ✅ **DONE** | research |
| **5** | MCP **client** with tool-retrieval + result budgeting (§1) + web-search MCP | ⬜ open | all |
| **6** | Multi-user (RBAC) + tamper-evident HMAC'd audit trail | ✅ **DONE** | work/enterprise |
| **7** | Household profiles, pushed briefings, ambient dashboard | ◑ partial (live dashboard + native automations done) | home |
| **+** | Live dashboard, ELI's own smart-home (rooms/scenes/automations), **monitored Internet toggle** | ✅ **DONE** (beyond the original plan) | all |

Sequencing logic: §0–2 are small and unlock everyone; the MCP *server* (Phase 2) is the
free-token frontier bet; the research workspace (Phase 4) is the most defensible "wow";
multi-user+audit (Phase 6) is the most monetizable. The token-sensitive MCP *client*
(Phase 5) lands only after the retrieval + budgeting discipline from §1 is in place.

---

## 8. Why this is "frontier" and not buzzword parity

Every cloud assistant streams and speaks OpenAI. **None** can offer: your home, your work
tools, and your research corpus connected through one agent that **provably never leaks**
(socket-level offline enforcement), **grounds every answer in real evidence** (the
grounding gate), and **runs entirely on hardware you own**. MCP is the connective tissue;
ELI's existing privacy/grounding/agent machinery is what makes the local version credible.
That combination — local + private + grounded + agentic + standards-interoperable — is the
2026 frontier position no vendor can take from the user.
