# ELI — Common Errors & Fixes

A quick reference for the gremlins that actually come up when running ELI. Each one is
symptom → cause → the exact fix. Add new ones as they surface.

---

## Clicking a link opens no browser page
**Symptom:** the server prints the URLs fine and copy-paste works, but Ctrl/right-click →
"Open Link" opens nothing.
**Cause:** broken **snap Firefox** — a `mesa-2404` auto-refresh leaves Firefox's GPU
content-mount stale (`/snap/firefox/…/gpu-2404-provider-wrapper` goes missing), so
*launching* a fresh Firefox fails silently while an already-open window still works.
**Fix:**
```bash
pkill -9 firefox
sudo snap disconnect firefox:gpu-2404
sudo snap connect firefox:gpu-2404 mesa-2404:gpu-2404
# if it's still stuck:
sudo snap refresh firefox
sudo snap refresh mesa-2404
```
Reopen Firefox once, then relaunch the server — clicks (and the auto-open) work again.
*(Nothing wrong with ELI — the URLs and server are fine; it's the snap.)*

---

## Wrong / tiny model loads instead of your usual one
**Symptom:** ELI boots on a small model (e.g. tinyllama-1B) even though settings point at
your 35B A3B.
**Cause:** a stray `ELI_GGUF_MODEL_PATH` / `ELI_MODEL_PATH` env var in your shell
**overrides config** (it wins over everything).
**Fix:**
```bash
echo $ELI_GGUF_MODEL_PATH        # if this prints a model path, that's the culprit
unset ELI_GGUF_MODEL_PATH ELI_MODEL_PATH
```
Or just switch live from the dashboard: **Settings → Model**.

---

## Server won't start / "address already in use"
**Cause:** a previous instance is still bound to the port.
**Fix:**
```bash
pkill -f "api/server.py"      # or find it: ss -ltnp | grep 8081
```
Then relaunch. ELI's web port is **8081**, HTTPS **8443**.

---

## Phone can't connect after a restart
**Symptom:** a paired phone gets 401 / "can't access the server."
**Cause:** it's carrying an old token (server restarted, or you rotated the token).
**Fix:** the token now **persists** across restarts — just re-open the current link/QR from
the **Connect** tab. To deliberately kick a lost phone off, hit **rotate** and re-pair.

---

## Phone can't connect at all (fresh pairing)
**Cause:** the firewall is blocking the port.
**Fix:** run the exact `sudo ufw allow …` lines the server prints on startup, and make sure
the phone is on the **same Wi-Fi**.

---

## Phone microphone / voice doesn't work
**Cause:** browsers block the mic (`getUserMedia`) on a plain `http://LAN-IP` page.
**Fix:** start with `--https` and open the `https://…:8443/` link on the phone; accept the
one-time self-signed "not private" warning.

---

## Model dropdown in the dashboard is empty
**Cause:** the list endpoint was being shadowed by the OpenAI-compatible `/v1/models` route.
**Fix:** already fixed — the list lives at `/v1/models/installed`. If a fork regresses it,
make sure the dashboard fetches that path, not `/v1/models`.

---

## News shows old stories as "the latest"
**Cause:** the interest-matched half wasn't recency-gated.
**Fix:** already fixed (a freshness gate drops stale niche matches). If it recurs, say
`refresh the news`.

---

## Terminal shows escape-code junk around a URL (`^[]8;;…`)
**Cause:** you're looking at a **log file** or `cat -v` output — those *always* render raw
escape codes. A live terminal renders the link normally. Not a bug.

---

## `git push` → "Could not resolve host github.com"
**Cause:** a transient DNS/network blip (ELI is offline-by-default, but git is separate).
**Fix:** just retry the push.

---

## Vision / CLIP segfaults on the GPU
**Cause:** the CLIP/vision path can segfault on some GPUs.
**Fix:** CLIP runs on **CPU** by design; keep it there. Main-model + vision hot-swap handle
VRAM automatically — don't force CLIP onto the GPU.

---

*House rule: when a new error bites, add it here — symptom, cause, and the **exact** commands
that fixed it. Future-you will thank present-you.*
