# Redistributability Audit — v2.3.92

**Date:** 2026-09-08  
**Scope:** `eli/`, `api/`, `config/templates/`, `scripts/` (tracked source only)  
**Goal:** 100% redistributable across OSes, hardware tiers, and user locales without personal paths or silent Linux-only regressions.

---

## Executive summary

| Area | Status | Notes |
|------|--------|-------|
| Tracked source paths | **PASS** | No `/home/jay`, `/Users/`, or `C:\Users\` in committed code |
| Personal config in git | **PASS** | `config/settings.json`, `config/voices/` gitignored |
| Cross-platform audit CI | **PASS** | `tools/audit_cross_platform.py` |
| YouTube/media imports | **PASS** | No dead `YouTubeController` imports |
| Window tiling | **FIXED** | Removed Linux-only `_eli_tile_*` override; uses `portable_app_control.tile_windows()` |
| CLOSE_APP wmctrl | **FIXED** | Gated with `platform_compat.LINUX` |
| GUI file open | **FIXED** | `experimental_tab.py` uses `platform_compat.open_file()` |
| Crisis resources | **FIXED** | International options (988, 116 123, 112, findahelpline.com) |
| Generated script DB path | **FIXED** | Uses `eli.core.paths.user_db_path()` + `ELI_USER_DB` |
| Silent exceptions | **IMPROVED** | 646 → 172 (see `SILENT_EXCEPTION_AUDIT.md`) |

---

## CRITICAL — local-only (never ship)

These files exist on the dev machine but are **excluded from `git archive`** releases. Purge before any manual tarball:

| Path | Issue |
|------|-------|
| `config/settings.json` | Personal profile (hostname, GPS, GPU, voice, MQTT) |
| `config/voices/clones.json` | Absolute path to local WAV |
| `artifacts/runtime_snapshot.json` | Personal portable install path |
| `config/api_token`, `config/.audit_hmac_key` | Secrets |

**Release rule:** Build only via `scripts/package_desktop_app.sh` (`git archive HEAD`).

---

## Code fixes in v2.3.85 prep (unreleased)

1. **`executor_enhanced.py`** — Deleted ~195 lines of duplicate Linux-only tiling (`wmctrl`/`xdotool`/`xrandr`). Late `TILE_WINDOWS` wrapper now delegates to `portable_app_control.tile_windows()`.
2. **`executor_enhanced.py`** — `CLOSE_APP` wmctrl fallback gated with `platform_compat.LINUX`.
3. **`experimental_tab.py`** — Cross-platform `open_file()` instead of `xdg-open`.
4. **`crisis_guard.py`** — International crisis-line guidance in safety override text.
5. **`generated_script_guard.py`** — SQLite helper template uses canonical paths, not `~/eli/artifacts/`.
6. **`memory/memory.py`** — Six silent exception handlers converted to observable logs.

---

## HIGH — remaining for future releases

| Item | File | Recommendation |
|------|------|----------------|
| Apt-only install hints | `os_controller.py`, `playerctl_backend.py` | Add brew/winget/choco hints via `platform_compat` |
| Font paths Linux-only | `visual_core.py`, `engine.py` | Add Windows/macOS font candidates or bundle font |
| Default release repo | `self_upgrade.py`, install scripts | Document `ELI_RELEASE_REPO` override for forks |
| LAN firewall hint | `api/server.py` | Include 10.0.0.0/8 + 172.16.0.0/12 when IP detection fails |

---

## Release parity vs v2.1.15 / v2.1.16

| Asset | v2.1.x | v2.3.x pipeline |
|-------|--------|-----------------|
| Windows `.exe` + portable zip | ✓ | ✓ |
| macOS `.dmg` (arm64) | ✓ | ✓ |
| Linux AppImage | ✓ lean + full | ✓ (lean; model runtime download) |
| Linux portable `.tar.gz` | ✓ lean + full | ✓ (`linux-portable.tar.gz` in release job) |
| SHA256SUMS.txt | ✓ | ✓ |
| Piper voices bundled | ✓ | ✓ |
| GGUF models bundled | full variants only | Runtime download (by design — size) |
| Debian `.deb` | ✓ | Separate `packaging/debian/build-deb.sh` |

---

## Pre-release checklist (v2.3.85)

- [ ] All cross-platform-smoke jobs green on `main`
- [ ] Release job produces Linux + macOS + Windows artifacts
- [ ] `python3 tools/audit_cross_platform.py` → exit 0
- [ ] `pytest tests/claims/test_no_silent_swallow.py` → count ≤ CEILING (172)
- [ ] `pyproject.toml` version = tag = `self_upgrade.py` default tag
- [ ] No personal files in release workspace
- [ ] README release note accurate
- [ ] `docs/SILENT_EXCEPTION_AUDIT.md` regenerated

---

## Clean architecture (reference)

- **`eli/core/paths.py`** — canonical path resolver (`ELI_*` env overrides)
- **`eli/utils/platform_compat.py`** — OS abstraction (browser, volume, open URL/file)
- **`eli/system/portable_app_control.py`** — window/app control with guards
- **`config/templates/settings.template.json`** — empty first-run seed
