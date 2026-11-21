# ELI Server & Web App — summary and setup

ELI ships a built-in **self-hosted HTTP server** (`api/server.py`, FastAPI + Uvicorn) that
exposes a **mobile-first web chat UI** plus a REST API. It lets you reach ELI from a
**phone, tablet, or any browser** on your network — while **all inference stays on the host
machine**. Nothing goes to the cloud; this is the same offline-first ELI, just reachable over
your own LAN.

> The sidebar **Home** tab (`devices`) is ELI’s **native MQTT / device** console — it is
> **not** Home Assistant. Pair phones via **Connect**; manage MQTT devices under Home.

> "Flask" is the common shorthand for this server. ELI actually uses **FastAPI** (same idea,
> async, with auto-generated API docs at `/docs`). The launchers and endpoints below are the
> real interface.

**v2.4.24:** LAN IP resolution works on Windows (UDP + `Get-NetIPAddress`); GUI Stop clears a
stale `ELI_API_PORT`; HTTPS sidecar can be stopped; Windows firewall hints include port 8443.

**v2.5.36:** the tokenless and same-machine grants hold only when the request's `Host` header
names this machine (a reverse proxy's name goes in `ELI_API_ALLOWED_HOSTS`), and in multi-user
mode the owner's actions are refused to members and viewers (§2 says where, and what is not
covered yet).

---

## 1. What you get
- A **chat UI** at `/` — open the host in any browser and talk to ELI.
- A **REST API** (§5): chat (plain, streamed, and the drop-in completions shape), direct
  actions (`POST /v1/execute`), status and telemetry, and the dashboard's device, research,
  voice and admin endpoints. `GET /health` answers without a token.
- **Auto API docs** at `/docs` (OpenAPI/Swagger).
- **Inference on the host** — the phone is just a thin client; your GPU/CPU does the work.

## 2. Safety model (read this before exposing it)
The server is **safe by default**:
- **Loopback-only by default** — binds `127.0.0.1`, reachable *only from the host machine*,
  and runs **tokenless** for zero friction (`main()` sets `ELI_API_ALLOW_TOKENLESS=1` for a
  loopback bind and for nothing else).
- **`--lan` mode** — when you explicitly expose it to the network, it binds `0.0.0.0` **and
  requires a token**: the one given with `--token` / `ELI_API_TOKEN`, else a stable token
  saved in ELI's config folder (`api_token`), so a paired phone stays paired across restarts
  (the desktop app's Settings → Web Server → Rotate token replaces it). Every `/v1/` endpoint
  needs it from another device, so being on the same Wi‑Fi is not enough to drive your
  machine. A browser on the host itself (socket peer `127.x` / `::1`) is let in without one;
  `ELI_LOOPBACK_ADMIN=0` turns that off.
- **Fails closed** — an ASGI-direct launch (`uvicorn api.server:app`, Docker, systemd) never
  runs `main()`, so nothing opts in to tokenless serving: other devices get 401 on every `/v1/`
  endpoint until a token or a user is configured (a caller on the host itself is still the
  owner unless `ELI_LOOPBACK_ADMIN=0`). The page, `/api`, `/health`, `/docs` and the PWA files
  stay open.
- **The name in the request (DNS-rebinding defence)** — the tokenless and same-machine grants
  hold only when the request's `Host` header names this machine: an IP address, `localhost` or
  `*.localhost`, this machine's own host name (also as `<name>.local` and its full name), or a
  name listed in `ELI_API_ALLOWED_HOSTS`. A web page that points its own domain at 127.0.0.1
  reaches the server from loopback, but it names its own domain, so it gets 401 like any LAN
  client. A valid token works whatever name is used.
- **Roles (RBAC)** — with no users defined the API is single-operator: whoever authenticates
  is the owner (`operator`, admin). Add users (`python -m eli.runtime.api_users add <id>
  [admin|member|viewer]`, or the web Admin tab) and every bearer token maps to one user and
  role: a **viewer** reads, a **member** also acts (chat, execute, devices, research, voice),
  an **admin** also gets the Admin console, user management, settings, the model and internet
  switches, the saved port and driver installs (§5). In this mode only users' tokens are
  accepted — the single `ELI_API_TOKEN` no longer is — while a tokenless caller on the host
  that names this machine stays admin, so the owner cannot lock themselves out. Actions are
  attributed to the authenticated user, not to the `user_id` a client sends.
- **Owner-only actions** — a member or viewer cannot have ELI carry out what only the
  machine's owner may (`authority_gate.owner_only()` in `eli/runtime/authority_gate.py`):
  running commands or code, generating or fixing code, reading, writing, listing or analysing
  files, PDFs, documents and images, the screen and the clipboard, keyboard and mouse, opening
  the IDE or file manager, ELI's own settings and persona, forgetting memories, removing
  events, clearing chat history, plugins, MCP, self-patching and updating, training (LoRA,
  voice, wake word), gaze control and proactive mode. `POST /v1/execute` answers 403 when the
  action it is asked to run is one of them. In `/v1/execute`, `/v1/chat`, `/v1/chat/stream`,
  `/v1/chat/completions` and `/v1/research/query` the caller's role goes with the turn: the
  engine's authority check, the executor's entry check and the check on each `SEQUENCE` step
  refuse those actions whatever a message, a `CHAT` text or a `MULTI_COMMAND` command routes
  to. Queuing a task (`POST /v1/tasks`, `/v1/tasks/remove`) is the owner's (admin), because a
  queued job runs later as ELI's own work. Work ELI starts by itself (its daemons, the
  scheduler) carries no caller and runs as the owner.
- **netguard unaffected** — ELI's offline-by-default outbound network guard still fail-closes;
  an inbound server does not breach it. `--lan` changes *who on your own network* can reach
  ELI, never *where your data goes* (it stays local).

## 3. Quick start

**From the GUI (recommended):** Settings → **Web Server** → Start (this computer) or
Start (phone / Wi-Fi). Prefer this over launching a second process next to a loaded model.
If another program (ELI v3 among them) already holds the port, Start moves to the next free
one.

**Linux / macOS (source / portable):**
```bash
./scripts/eli_serve.sh                 # local-only  -> http://127.0.0.1:8081/
./scripts/eli_serve.sh --lan           # LAN access for a phone/tablet (binds 0.0.0.0 + token)
./scripts/eli_serve.sh --lan --https   # + HTTPS on 8443 for the phone microphone
./scripts/eli_serve.sh --lan --port 9000
./scripts/eli_serve.sh --lan --token <secret>
```

**Windows (source install with a `.venv`):** `scripts\eli_serve.ps1` with `-Lan`, `-Https`,
`-Port <n>`, `-Token <s>`. With `-Lan` and no `-Token` it mints a fresh token on every launch.

**Frozen builds:** **ELI-Server.exe** (Start Menu: "ELI Server (phone and web)"),
`ELI.exe --server`, or `<ELI AppImage> --server`. These start the same `api.server` and bind
loopback unless you add `--lan`.

**Via the unified launcher (Linux/macOS source):**
```bash
./scripts/eli_launch.sh serve --lan     # server only
./scripts/eli_launch.sh both --lan      # desktop GUI + server together
```

With `--lan` the server prints a token-protected URL:
```
http://<your-host-ip>:8081/#token=XXXXXXXX
```
Open **that** once on the phone (same network). The page captures the token, scrubs it from the
address bar, and stores it — later visits just need `http://<your-host-ip>:8081/`. The token
rides in the URL fragment (`#token=`), which the browser never sends to the server, so it stays
out of the access log; `?token=` is also accepted.

## 4. Desktop launchers (app icon, not a terminal command)
```bash
./scripts/install_desktop_apps.sh                                  # Linux .desktop / macOS .command
powershell -ExecutionPolicy Bypass -File scripts\install_desktop_apps.ps1   # Windows Start Menu
```
Installs launchers for the GUI (**ELI v2.0**) and the server (**ELI Server (phone & web)** on
Linux, **ELI Server (Web App)** on macOS and Windows), plus Setup and Uninstall entries
(Windows: Uninstall only). The server launcher runs `eli_serve.sh --lan --https` (Linux,
macOS) or `eli_serve.ps1 -Lan` (Windows) in a window so the phone URL and token are visible.

## 5. Endpoints
Roles: **open** — no token. **viewer** — any authenticated caller. **member** — member or
admin (a viewer gets 403). **admin** — admin only. In single-operator mode every authenticated
caller is admin, so the role column only bites once users are defined.

| Method | Path | Role | Purpose |
|---|---|---|---|
| GET  | `/` | open | The web chat UI (HTML; its CSS/JS under `/static/`) |
| GET  | `/api` | open | Service info (JSON): product `eli_v2`, version |
| GET  | `/health` | open | Liveness check |
| GET  | `/docs` | open | OpenAPI / Swagger docs |
| GET  | `/manifest.webmanifest`, `/sw.js`, `/icon.svg`, `/icon.png`, `/icon-192.png`, `/icon-512.png`, `/apple-touch-icon.png`, `/favicon.ico` | open | Installable-app (PWA) shell and icons |
| GET  | `/v1/me` | viewer | The caller's user id and role |
| POST | `/v1/chat` | member | Send a message, get ELI's reply |
| POST | `/v1/chat/stream` | member | Same, streamed token-by-token (SSE) |
| POST | `/v1/chat/completions` | member | Drop-in local-model endpoint (de-facto chat shape) |
| GET  | `/v1/models` | viewer | The one local model, in the standard list shape |
| POST | `/v1/execute` | member | Run a direct action (OPEN_APP, …); owner-only actions are admin-only (§2) |
| GET  | `/v1/status/{user_id}` | viewer | Runtime status (model, uptime) |
| GET  | `/v1/capabilities` | viewer | The command catalogue (Commands tab) |
| GET  | `/v1/system` | viewer | Measured GPU/CPU/RAM/model telemetry |
| GET / POST | `/v1/net`, GET `/v1/net/egress` | viewer / admin | The internet switch and the outbound connections netguard allowed; flipping the switch (POST) is admin-only |
| GET / POST | `/v1/settings` | viewer / admin | The curated settings and their schema; writing them |
| GET / POST | GET `/v1/models/installed`, POST `/v1/model` | viewer / admin | Installed chat models; switch and hot-reload |
| GET / POST | GET `/v1/connect`, `/v1/connect/qr.svg`; POST `/v1/connect/port` | viewer / admin | Phone-connect URL, QR and firewall hint; the saved port |
| GET  | `/v1/audit` | viewer | Tamper-evident (HMAC-SHA-256 chained) action trail + chain verification |
| GET / POST | `/v1/admin/*` | admin | Enterprise console: `overview`, `user` (drill-down), `users/add`, `users/remove` |
| GET / POST | `/v1/devices/*` | viewer (GET) / member (POST); `driver/install` admin | ELI's MQTT device server (no Home Assistant). GET: `/v1/devices` (list), `status`, `rooms`, `names`, `drivers`, `mqtt/guide`, `bluetooth/known`. POST: `mqtt/test`, `config`, `connect`, `setup`, `disconnect`, `discover` (mDNS + Bluetooth), `register`, `room`, `room/control`, `remove`, `control`, `name`, `bluetooth`, `add-discovered`, `pair`, `driver/install` |
| GET / POST | `/v1/connectivity/*` | viewer (GET) / member (POST) | `status`, `wifi/networks`, `wifi/connect`, `audio/outputs`, `audio/default`, `audio/alias` |
| GET / POST | `/v1/home/*` | viewer (GET) / member (POST) | Home AI: `state`, `mesh/ping`, `mesh/status`, `mesh/config`, `mesh/takeover`, `suggestions` (+`accept`), `automations` (+`add`, `remove`, `toggle`, `create`), `scenes` (+`add`, `remove`, `activate`), `location`, `sun` |
| GET / POST | GET `/v1/media`, POST `/v1/media/control` | viewer / member | Now playing across local MPRIS players; play/pause/next/volume |
| GET / POST | `/v1/ui/prefs` | viewer / member | Per-user dashboard layout |
| GET  | `/v1/cognition/orchestration`, `/v1/autonomy/goals` | viewer | The live agent graph; ELI's own goals |
| GET / POST | `/v1/tasks`, POST `/v1/tasks/remove` | viewer (GET) / admin (POST) | Scheduled (overnight) tasks |
| GET / POST | `/v1/research/*` | viewer (GET) / member (POST) | Shared, collaborative corpora: `corpora`, `documents`, `activity`; `ingest`, `note`, `remove`, `query` (grounded, cited, attributed) |
| GET  | `/v1/voice/voices` | viewer | List local Piper voices + the active one |
| POST | `/v1/voice/stt` | member | Transcribe an audio clip (raw body) with the local whisper model |
| POST | `/v1/voice/tts` | member | Render text to WAV with the local Piper voice (returned, not played on host) |

**Chat request:**
```bash
curl -X POST http://127.0.0.1:8081/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello","user_id":"me"}'
# with a LAN token, add:  -H 'Authorization: Bearer <token>'
```
Response: `{"response": "...", "session_id": "...", "user_id": "me", "timestamp": ...}`

## 6. Configuration (environment variables)
The launchers set these for you; you can also set them directly before `python -m api.server`.
`<config dir>` and `<data dir>` are `config/` and `artifacts/` in a source checkout, and the
`config/` and `artifacts/` folders under the per-user `ELI_v2` folder in an installed copy
(see `artifacts/README.md`).
| Var | Default | Meaning |
|---|---|---|
| `ELI_API_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` = LAN). |
| `ELI_API_PORT` | `8081` | Listen port. Precedence: `--port`, then this, then the port saved with `POST /v1/connect/port` (`api_port`), then 8081. |
| `ELI_API_TOKEN` | _(unset)_ | The single-operator token, sent as `Authorization: Bearer <token>`. `--lan` uses it when set, else the stable token in `<config dir>/api_token`. Not accepted once RBAC users exist. |
| `ELI_API_ALLOW_TOKENLESS` | _(unset)_ | Permits tokenless serving (to a request that names this machine). **The gate fails closed without it** — `main()` sets it to `1` only on a loopback bind and removes it for a LAN bind, so an ASGI-direct launch (uvicorn/Docker) that skips `main()` stays locked down to other devices. |
| `ELI_LOOPBACK_ADMIN` | `1` | A caller on this machine that names this machine is the owner without a token, even in `--lan` mode. `0` makes it present a token like anyone else. To require a token on a loopback bind, set `ELI_LOOPBACK_ADMIN=0` **and** `ELI_API_ALLOW_TOKENLESS=0`, with an `ELI_API_TOKEN`. |
| `ELI_API_ALLOWED_HOSTS` | _(unset)_ | Extra comma-separated host names that count as this machine for the tokenless and same-machine grants (a reverse proxy's name, say). IP addresses, `localhost` / `*.localhost` and the machine's own names always count. |
| `ELI_API_USERS_FILE` | `<config dir>/api_users.json` | RBAC user store (admin/member/viewer; tokens kept only as SHA-256 hashes, each shown once at creation). Manage with `python -m eli.runtime.api_users add <id> [admin\|member\|viewer]`, `remove <id>`, `list`, or the Admin tab. The last admin cannot be removed. With no users defined, the API stays single-operator. |
| `ELI_RESEARCH_ROOT` | `<data dir>/research/_sources/` | The only directory `/v1/research/ingest` may read documents from. Paths outside it are rejected. |
| `ELI_RESEARCH_MAX_FILES` / `ELI_RESEARCH_MAX_BYTES` | `2000` / `512 MB` | Caps on a single research ingest (directory-walk DoS guard). |
| `ELI_API_HTTPS` / `ELI_API_HTTPS_PORT` | _(unset)_ / `8443` | `1` (or `--https`) also serves HTTPS with a local self-signed certificate on its own port, for the phone microphone. Plain HTTP stays the main address. |
| `ELI_API_NO_BROWSER` | _(unset)_ | `1` stops `main()` opening the page in this machine's browser. |
| `ELI_API_RELOAD` | `0` | `1` enables uvicorn auto-reload (dev only). |

Run it directly (advanced):
```bash
ELI_API_HOST=0.0.0.0 ELI_API_PORT=8081 ELI_API_TOKEN=$(python -c 'import secrets;print(secrets.token_urlsafe(16))') \
  .venv/bin/python -m api.server
```
`python -m api.server` also takes `--lan`, `--host`, `--port`, `--token`, `--https` and
`--reload`; a flag wins over the matching variable.

## 7. Reaching it from a phone — the path that actually works
**Do not** try to run inference on the phone (that needs an on-device llama.cpp build). Instead:
1. Run `eli_serve --lan` on a machine that *can* do inference (your desktop / a home server).
2. From the phone browser (same Wi‑Fi), open the printed `http://<host-ip>:8081/#token=…`.
3. Chat. The model runs on the host; the phone is a thin client.

## 8. Cross-platform & dependencies
- **Server deps** (`fastapi`, `uvicorn`, and `segno` for the Connect QR) are in pyproject's
  `[server]` extra (part of `[full]`) and in `requirements.txt` and the `-full`, `-windows`,
  `-macos` and `-android` lists, so a normal install includes them on Linux, macOS, and
  Windows. `cryptography` (the HTTPS certificate) is listed in `[server]` and in the `-full`,
  `-windows` and `-macos` lists.
- The **web UI is plain HTML/JS** (`api/static/`) — works in any modern browser (Android, iOS,
  desktop), no app install.
- On **Android/Termux** the recommended use is as a *client* of a desktop-hosted server (above),
  not running the server on the phone.

## 9. Troubleshooting
- **Phone can't connect** → confirm same network; check the host firewall allows the port
  (the server prints the exact allow command); use the host's LAN IP (not `127.0.0.1`).
- **401 on the phone** → the token wasn't captured; re-open the full `…/#token=…` URL. With
  RBAC users defined, the phone needs a user's token — the single LAN token is not accepted.
- **401 through a reverse proxy or a custom host name, even on this machine** → add that name
  to `ELI_API_ALLOWED_HOSTS`, or send the token.
- **403** → the account's role is below what the endpoint or the action needs (§2, §5).
- **Port in use** → `--port`/`-Port` to pick another (the GUI's Start moves on by itself).
- **Want this-machine-only** → omit `--lan` (the default); it binds loopback.

## 10. Files
- `api/server.py` — the FastAPI app, its auth and its endpoints.
- `api/static/` — the web UI (`index.html`, `app.css`, `app.js`).
- `api/api_token.py` — the stable LAN token.
- `eli/runtime/api_users.py` — RBAC users and roles (and its CLI).
- `eli/runtime/authority_gate.py` — the owner-only actions.
- `scripts/eli_serve.sh` / `scripts/eli_serve.ps1` — launchers (loopback-safe; `--lan`/`-Lan`).
- `scripts/eli_launch.sh` — unified `gui` / `serve` / `both`.
- `scripts/install_desktop_apps.{sh,ps1}` — app-menu / Start-Menu launchers for both surfaces.
