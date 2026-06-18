# ELI Server & Web App — summary and setup

ELI ships a built-in **self-hosted HTTP server** (`api/server.py`, FastAPI + Uvicorn) that
exposes a **mobile-first web chat UI** plus a small REST API. It lets you reach ELI from a
**phone, tablet, or any browser** on your network — while **all inference stays on the host
machine**. Nothing goes to the cloud; this is the same offline-first ELI, just reachable over
your own LAN.

> "Flask" is the common shorthand for this server. ELI actually uses **FastAPI** (same idea,
> async, with auto-generated API docs at `/docs`). The launchers and endpoints below are the
> real interface.

---

## 1. What you get
- A **chat UI** at `/` — open the host in any browser and talk to ELI.
- A **REST API**: `POST /v1/chat`, `POST /v1/execute`, `GET /v1/status/{user_id}`, `GET /health`.
- **Auto API docs** at `/docs` (OpenAPI/Swagger).
- **Inference on the host** — the phone is just a thin client; your GPU/CPU does the work.

## 2. Safety model (read this before exposing it)
The server is **safe by default**:
- **Loopback-only by default** — binds `127.0.0.1`, reachable *only from the host machine*,
  and runs **tokenless** for zero friction.
- **`--lan` mode** — when you explicitly expose it to the network, it binds `0.0.0.0` **and
  mints an access token**. The token gates the action endpoints (`/v1/chat` *and*
  `/v1/execute` — the latter can run system actions), so being on the same Wi‑Fi is not enough
  to drive your machine.
- **netguard unaffected** — ELI's offline-by-default outbound network guard still fail-closes;
  an inbound server does not breach it. `--lan` changes *who on your own network* can reach
  ELI, never *where your data goes* (it stays local).

## 3. Quick start

**Linux / macOS:**
```bash
./scripts/eli_serve.sh                 # local-only  -> http://127.0.0.1:8081/
./scripts/eli_serve.sh --lan           # LAN access for a phone/tablet (binds 0.0.0.0 + token)
./scripts/eli_serve.sh --lan --port 9000
```

**Windows (PowerShell):**
```powershell
.\scripts\eli_serve.ps1                 # local-only
.\scripts\eli_serve.ps1 -Lan            # LAN access (+ token)
.\scripts\eli_serve.ps1 -Lan -Port 9000
```

**Via the unified launcher (Linux/macOS):**
```bash
./scripts/eli_launch.sh serve --lan     # server only
./scripts/eli_launch.sh both --lan      # desktop GUI + server together
```

With `--lan` the launcher prints a token-protected URL:
```
http://<your-host-ip>:8081/?token=XXXXXXXX
```
Open **that** once on the phone (same network). The page captures the token, scrubs it from the
address bar, and stores it — later visits just need `http://<your-host-ip>:8081/`.

## 4. Desktop launchers (app icon, not a terminal command)
```bash
./scripts/install_desktop_apps.sh                                  # Linux .desktop / macOS .command
powershell -ExecutionPolicy Bypass -File scripts\install_desktop_apps.ps1   # Windows Start Menu
```
Installs two launchers: **ELI Pro** (the GUI) and **ELI Server (Web App)** (runs `eli_serve --lan`
in a window so the phone URL + token are visible).

## 5. Endpoints
| Method | Path | Auth (when `--lan`) | Purpose |
|---|---|---|---|
| GET  | `/` | open | The web chat UI (HTML) |
| GET  | `/api` | open | Service info (JSON) |
| GET  | `/health` | open | Liveness check |
| GET  | `/docs` | open | OpenAPI / Swagger docs |
| POST | `/v1/chat` | **token** | Send a message, get ELI's reply |
| POST | `/v1/execute` | **token** | Run a direct action (OPEN_APP, SCREENSHOT, …) |
| GET  | `/v1/status/{user_id}` | open | Runtime status (model, uptime) |

**Chat request:**
```bash
curl -X POST http://127.0.0.1:8081/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello","user_id":"me"}'
# with a LAN token, add:  -H 'Authorization: Bearer <token>'
```
Response: `{"response": "...", "session_id": "...", "user_id": "me", "timestamp": ...}`

## 6. Configuration (environment variables)
The launchers set these for you; you can also set them directly before `python -m api.server`:
| Var | Default | Meaning |
|---|---|---|
| `ELI_API_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` = LAN). |
| `ELI_API_PORT` | `8081` | Listen port. |
| `ELI_API_TOKEN` | _(unset)_ | When set, required as `Authorization: Bearer <token>` on the action endpoints. The launcher sets this in `--lan` mode. |
| `ELI_API_RELOAD` | `0` | `1` enables uvicorn auto-reload (dev only). |

Run it directly (advanced):
```bash
ELI_API_HOST=0.0.0.0 ELI_API_PORT=8081 ELI_API_TOKEN=$(python -c 'import secrets;print(secrets.token_urlsafe(16))') \
  .venv/bin/python -m api.server
```

## 7. Reaching it from a phone — the path that actually works
**Do not** try to run inference on the phone (that needs an on-device llama.cpp build). Instead:
1. Run `eli_serve --lan` on a machine that *can* do inference (your desktop / a home server).
2. From the phone browser (same Wi‑Fi), open the printed `http://<host-ip>:8081/?token=…`.
3. Chat. The model runs on the host; the phone is a thin client.

## 8. Cross-platform & dependencies
- **Server deps** (`fastapi`, `uvicorn`) are in `pyproject [full]` and every `requirements-*.txt`,
  so a normal install includes them on Linux, macOS, and Windows.
- The **web UI is plain HTML/JS** — works in any modern browser (Android, iOS, desktop), no app
  install.
- On **Android/Termux** the recommended use is as a *client* of a desktop-hosted server (above),
  not running the server on the phone.

## 9. Troubleshooting
- **Phone can't connect** → confirm same network; check the host firewall allows the port;
  use the host's LAN IP (not `127.0.0.1`).
- **401 on the phone** → the token wasn't captured; re-open the full `…/?token=…` URL.
- **Port in use** → `--port`/`-Port` to pick another.
- **Want this-machine-only** → omit `--lan` (the default); it binds loopback.

## 10. Files
- `api/server.py` — the FastAPI app + the web UI.
- `scripts/eli_serve.sh` / `scripts/eli_serve.ps1` — launchers (loopback-safe; `--lan`/`-Lan`).
- `scripts/eli_launch.sh` — unified `gui` / `serve` / `both`.
- `scripts/install_desktop_apps.{sh,ps1}` — app-menu / Start-Menu launchers for both surfaces.
