# Session — 2026-06-28: web app, ELI's smart-home, security hardening, routing & grounding

A consolidation of the work landed for the week ending 2026-06-28. All on `main`;
full suite green at **7,019 passed / 42 skipped / 2 xfailed** (the 5 remaining reds are
the in-progress `smart_home` plugin removal + one stale blueprint ref — pre-existing,
fail identically on a clean tree). Nothing in this work touches the inference path or
the resident model — every change is *around* inference, by design.

## 1. A local-first web app + dashboard (`api/server.py`)
- FastAPI server with an embedded **dashboard PWA**: chat (markdown + code, sessions,
  history, stop, regenerate, SSE streaming on the same local GGUF + pipeline), a live
  **Overview** (measured GPU/CPU/RAM vitals, model, uptime, audit integrity, devices,
  recent activity), modern responsive UI (design tokens, light/dark, motion, mobile),
  install-as-an-app (manifest + service worker), and **run-in-process** from the desktop
  GUI's Settings.
- **OpenAI-compatible** `/v1/chat/completions` so any standard client connects to the
  local model.

## 2. ELI's own smart-home — Home Assistant removed
- **ELI's own MQTT device server** (`eli/runtime/device_server.py`) replaces the Home
  Assistant dependency end-to-end; the HA plugin was deleted and voice SMART_HOME
  repoints to the native server.
- **Rooms** (group + per-room control), **scenes**, and **real automations** with trigger
  types time / sunrise-sunset / device-state, **conditions** (all must hold),
  **multi-action**, and a **location picker** for sun triggers.
- **mDNS device discovery**, **usage learning**, and learned patterns turned into
  **suggested automations** surfaced through the proactive daemon.

## 3. Identity, roles, audit
- **RBAC** — admin / member / **viewer (read-only)**; authenticated identity; role-gated
  endpoints; an **enterprise admin console** (audit integrity, per-user activity,
  approval/risk-gate policy).
- **Tamper-evident, hash-chained audit trail** (Phase 6); the chain is **HMAC-keyed**
  and live-verifiable; metadata only, never message content.

## 4. Research collaboration & browser voice
- Shared **corpora** with attribution, notes, an activity feed; local ingest → FAISS →
  grounded, cited Q&A.
- **Local** whisper STT in / **local** Piper TTS out in the browser — gated by netguard.

## 5. Security hardening
- **Secret files born locked (0600, atomic)** — new `eli/core/secure_io.py`
  (mkstemp → write → fsync → `os.replace`) is the single owner of race-free secret
  writes; routed the **audit HMAC key**, the **API token store**, **settings**, and the
  **agent-trust registry** through it. Closes the brief world-readable TOCTOU window the
  old write-then-chmod pattern left.
- **HMAC-keyed audit chain**, **fail-closed API auth** gate, **sandboxed** research ingest.
- **Monitored Internet toggle + egress oversight** — offline-by-default and the socket-level
  failsafe (`netguard`) stay; the owner can deliberately enable internet (desktop `🌐 Net`
  toggle or `POST /v1/net`, **admin-only**). Both flips are audited (the desktop toggle now
  audits too, not just the web one). Crucially, while on, the socket chokepoint **records
  every allowed outbound connection** (host:port) to an in-memory live tail
  (`GET /v1/net/egress`) and, throttled, to the tamper-evident audit ledger (`net_egress`).
  This closes the gap where "monitored" previously meant only the flip was logged — egress
  itself is now on the record. Best-effort, off the hot path (background writer), kill-switch
  `ELI_EGRESS_LEDGER=0`.

## 6. Routing & grounding fixes
- **Proof-of-reading challenges** ("prove you actually read the file", "timestamps as
  proof that you read it") route to a grounded audit by reading the *whole utterance* for
  the challenge frame; the imperative "read the data in that file and prove it's right"
  does **not** (it's about the data's correctness, not ELI's action).
- **Target threading** — the referenced file flows into the audit, so it follows the path
  the user named; a follow-up with no path uses the conversational **current-file**
  (anchored on SUMMARIZE_FILE / EXAMINE_CODE / FIX_FILE).
- **Grounded file audit** derives its target from the referenced path (AST-grounded
  structural read) instead of a hardcoded GUI file.
- **SUMMARIZE_FILE never truncates** — whole-file read + hierarchical map-reduce sized to
  the model's real context (was capped at the first ~8 KB, the cause of "incomplete"
  summaries).
- **Verified, already-landed:** foreground-priority broker **preemption**; reasoning-model
  **empty-turn salvage** (no-think retry on broker + streaming path); **real** SELF_ANALYZE
  root-cause inference (grounded signatures → capped no-think LLM → per-failure description).

## Net effect
ELI became a two-front local-first product: the desktop cognitive assistant plus a
self-hosted web app with its own smart-home, multi-user roles, a tamper-evident audit
trail, collaborative research, browser voice, and a deliberate, logged, owner-gated path
to the internet — all local, all under the user's control. See `state_snapshot.md` for the
authoritative current numbers and `security.md` for the security surface.
