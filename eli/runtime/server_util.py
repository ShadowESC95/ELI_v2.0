"""Helpers for detecting an existing ELI web server and firewall guidance."""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


def port_in_use(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 1.2) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError, OSError):
        return None


def effective_api_port() -> int:
    """The port the ELI web/API server should listen on.

    Precedence: an explicit ELI_API_PORT env (set by --port / launcher) wins; otherwise
    the user's persisted `api_port` setting; otherwise the 8081 default. This is the single
    source every launch path consults, so changing the setting moves the server everywhere
    (useful when 8081 is already taken by another service on the LAN)."""
    env = os.environ.get("ELI_API_PORT")
    if env:
        try:
            return int(env)
        except (TypeError, ValueError):
            pass
    try:
        from eli.core import config
        v = config.get("api_port")
        if v:
            return int(v)
    except Exception:
        pass
    return 8081


def probe_eli_server(port: Optional[int] = None) -> Dict[str, Any]:
    """Best-effort probe of whatever is listening on the ELI API port."""
    port = int(port or effective_api_port())
    out: Dict[str, Any] = {
        "port": port,
        "in_use": False,
        "eli_running": False,
        "health_ok": False,
        "local_url": None,
        "lan_url": None,
        "voice_url": None,
        "token": None,
        "detail": "",
    }
    if not port_in_use(port):
        return out
    out["in_use"] = True

    health = _http_json(f"http://127.0.0.1:{port}/health")
    api = _http_json(f"http://127.0.0.1:{port}/api")
    if health is not None or (api and (api.get("service") or api.get("name"))):
        out["eli_running"] = True
        out["health_ok"] = health is not None

    token = os.environ.get("ELI_API_TOKEN", "").strip()
    if not token:
        try:
            from api.api_token import get_stable_token
            token = get_stable_token()
        except Exception:
            token = ""

    headers = {"Authorization": f"Bearer {token}"} if token else None
    connect = _http_json(f"http://127.0.0.1:{port}/v1/connect", headers=headers) if token else None
    if connect and connect.get("ok"):
        out["local_url"] = f"http://127.0.0.1:{port}/#token={token}" if token else f"http://127.0.0.1:{port}/"
        out["lan_url"] = connect.get("url") or out["local_url"]
        out["voice_url"] = connect.get("voice_url")
        out["token"] = token
    else:
        out["local_url"] = f"http://127.0.0.1:{port}/"
        if token:
            out["lan_url"] = out["local_url"] + f"#token={token}"
            out["token"] = token

    if out["eli_running"]:
        out["detail"] = "ELI web server is already running on this computer."
    else:
        out["detail"] = f"Port {port} is already in use by another program."
    return out


def firewall_hint() -> Dict[str, Any]:
    try:
        from api.server import _firewall_hint
        return _firewall_hint()
    except Exception:
        return {"tool": "firewall", "commands": [], "subnet": ""}


def start_https_sidecar(host: str = "0.0.0.0", https_port: Optional[int] = None) -> Optional[int]:
    """Run HTTPS alongside HTTP (phone mic). Returns port or None on failure."""
    import threading

    try:
        import uvicorn
        from api.server import _ensure_lan_cert, app as _app
    except Exception:
        return None
    try:
        crt, key = _ensure_lan_cert()
        port = int(https_port or os.environ.get("ELI_API_HTTPS_PORT", "8443"))
        os.environ["ELI_API_HTTPS_PORT"] = str(port)
        srv = uvicorn.Server(uvicorn.Config(
            _app, host=host, port=port, log_level="warning",
            ssl_certfile=crt, ssl_keyfile=key))
        threading.Thread(target=srv.run, daemon=True).start()
        return port
    except Exception:
        os.environ.pop("ELI_API_HTTPS_PORT", None)
        return None


def qr_png_bytes(url: str) -> bytes:
    """Raw PNG bytes for a connect QR. Use with QPixmap.loadFromData() in the Qt GUI —
    QLabel rich-text does NOT render `data:` URI <img> tags, so the data-URI form below
    silently shows nothing there. This bytes form is the reliable path for the desktop app."""
    import io
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=6, border=4,
                                    dark="#06141f", light="#eafcff")
    return buf.getvalue()


def qr_png_data_uri(url: str) -> str:
    """PNG data-URI for embedding a connect QR (web / HTML contexts only, NOT Qt QLabel)."""
    import base64
    return "data:image/png;base64," + base64.b64encode(qr_png_bytes(url)).decode("ascii")
