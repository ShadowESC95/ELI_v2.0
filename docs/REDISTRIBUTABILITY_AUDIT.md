# Redistributability Audit — v2.3.92, re-checked at v2.5.36 (bundle licences at v2.5.37)

**Date:** 2026-09-08; re-checked against the v2.5.36 tree on 2026-11-20; the bundle-licence rows against v2.5.37 on 2026-11-21  
**Scope:** `eli/`, `api/`, `config/templates/`, `scripts/` (tracked source only), plus what the release builds bundle  
**Goal:** 100% redistributable across OSes, hardware tiers, and user locales without personal paths or silent Linux-only regressions — and, since v2.5.36, clear about which licence each redistributed part carries.

---

## Executive summary

| Area | Status | Notes |
|------|--------|-------|
| Tracked source paths | **PASS** | No `/home/<user>`, `/Users/`, or `C:\Users\` in committed code (`tests/test_shipped_assets_are_blank_and_current.py` checks every tracked text file) |
| Personal config in git | **PASS** | `config/settings.json`, `config/voices/` gitignored |
| Cross-platform audit CI | **PASS** | `tools/audit_cross_platform.py` (run by `cross-platform-smoke.yml`) |
| YouTube/media imports | **PASS** | No dead `YouTubeController` imports |
| Window tiling | **FIXED** | Removed Linux-only `_eli_tile_*` override; uses `portable_app_control.tile_windows()` |
| CLOSE_APP wmctrl | **FIXED** | Gated with `platform_compat.LINUX` |
| GUI file open | **FIXED** | `eli/gui/tabs/experimental_tab.py` uses `platform_compat.open_file()` |
| Crisis resources | **FIXED** | International options (988, 116 123, 112, findahelpline.com) |
| Generated script DB path | **GONE** | v2.5.36 removed the pre-written scripts `generated_script_guard.py` used to return, the SQLite helper template among them; it now only validates and quarantines generated scripts |
| Silent exceptions | **IMPROVED** | 646 → 163 (`tests/claims/test_no_silent_swallow.py`, ceiling 163) |
| Licences of what ships | **DOCUMENTED** | ELI's code is Apache-2.0; bundles also carry LGPL, GPL and non-commercial third-party parts — see [Licences of what is redistributed](#licences-of-what-is-redistributed-v2536) |

---

## CRITICAL — local-only (never ship)

These files exist on the dev machine but are **excluded from `git archive`** releases (all gitignored). Purge before any manual tarball:

| Path | Issue |
|------|-------|
| `config/settings.json` | Personal profile (hostname, GPS, GPU, voice, MQTT) |
| `config/voices/clones.json` | Absolute path to local WAV |
| `artifacts/runtime_snapshot.json` | Personal portable install path |
| `config/api_token`, `config/.audit_hmac_key` | Secrets |

**Release rule:** Build only via `scripts/package_desktop_app.sh` (`git archive HEAD`).

---

## Code fixes in v2.3.85 prep

1. **`executor_enhanced.py`** — Deleted ~195 lines of duplicate Linux-only tiling (`wmctrl`/`xdotool`/`xrandr`). Late `TILE_WINDOWS` wrapper now delegates to `portable_app_control.tile_windows()`.
2. **`executor_enhanced.py`** — `CLOSE_APP` wmctrl fallback gated with `platform_compat.LINUX`.
3. **`experimental_tab.py`** — Cross-platform `open_file()` instead of `xdg-open`.
4. **`crisis_guard.py`** — International crisis-line guidance in safety override text.
5. **`generated_script_guard.py`** — SQLite helper template used canonical paths, not `~/eli/artifacts/`. (The template itself was removed in v2.5.36.)
6. **`memory/memory.py`** — Six silent exception handlers converted to observable logs.

---

## HIGH — remaining for future releases

| Item | File | Recommendation |
|------|------|----------------|
| Apt-only install hints | `eli/integrations/mpris/playerctl_backend.py` | Add brew/winget/choco hints via `platform_compat` (`os_controller.py` no longer has them) |
| Font paths Linux-only | `eli/tools/image_engine/image_engine/visual_core.py` | Add Windows/macOS font candidates or bundle font |
| Default release repo | `eli/kernel/self_upgrade.py`, install scripts | The `ELI_RELEASE_REPO` override exists in code; document it for forks |
| LAN firewall hint | `api/server.py` (`_lan_subnet`) | Falls back to `192.168.0.0/16` when IP detection fails; include 10.0.0.0/8 + 172.16.0.0/12 |
| openWakeWord's speech-embedding model in the bundles | `ELI.spec` (`openwakeword` data) | Since v2.5.37 the builds carry only the two feature-extractor files ELI loads (`melspectrogram.onnx`, `embedding_model.onnx`) and none of the CC BY-NC-SA wake-word models. `embedding_model.onnx` is openWakeWord's re-implementation of Google's speech_embedding model (Apache-2.0, per openWakeWord's README), while its licence note puts "all of the included pre-trained models" under CC BY-NC-SA 4.0 without saying whether that covers this one: confirm with upstream, or build the extractor from Google's Apache-2.0 module |

---

## Release parity vs v2.1.15 / v2.1.16

| Asset | v2.1.x | v2.5.x pipeline |
|-------|--------|-----------------|
| Windows `.exe` + portable zip | ✓ | ✓ |
| Windows on ARM portable zip | — | ✓ (lean, experimental) |
| macOS `.dmg` (arm64) | ✓ | ✓ |
| Linux AppImage | ✓ lean + full | ✓ (lean; model runtime download) |
| Linux portable `.tar.gz` | ✓ lean + full | ✓ (`linux-portable.tar.gz` in release job) |
| Wheel, sdist, wheelhouse | — | ✓ |
| SHA256SUMS.txt | ✓ | ✓ |
| Piper voices bundled | ✓ | ✓ (the twelve voices of `local-assets-v2.1`) |
| GGUF models bundled | full variants only | Runtime download (by design — size); the nomic embedder is bundled |
| Debian `.deb` | ✓ | ✓ (built in the release job by `packaging/debian/build-deb.sh`) |

---

## Licences of what is redistributed (v2.5.37)

From v2.5.36 ELI's own code is **Apache-2.0** (`LICENSE`, `NOTICE`); v2.5.35 and
earlier were PolyForm Noncommercial. Apache-2.0 lets anyone use, change and
redistribute that code, commercially too, as long as the licence and `NOTICE` go
with it and changed files say so. It does not relicense anything else in a
download. Each redistributed part keeps its own terms:

| Part | Where it ships | Licence | What a redistributor has to do |
|------|----------------|---------|--------------------------------|
| ELI's own code | every artifact | Apache-2.0 | Keep `LICENSE` and `NOTICE`; mark changed files |
| PySide6 / shiboken6 (Qt) | frozen builds | LGPL-3.0 | Loaded as separate shared libraries (dynamic linking), which the LGPL allows from Apache code; keep them replaceable and pass on the LGPL terms and the directions to their source: `LGPL_SOURCES.md` in each release's `ELI_v2-<version>-gpl-sources.tar.gz` names the PySide6 and Qt versions the builds carry and where each version's source is |
| piper-tts 1.4 + espeak-ng | frozen builds | GPL-3.0-or-later | ELI imports it in-process. From v2.5.37 each release attaches `ELI_v2-<version>-gpl-sources.tar.gz`, the exact source of every GPL package the builds carry (`packaging/gpl_sources.py`); pass it on with any bundle you redistribute. On the FSF's reading the bundle as a whole is then under GPL-3.0's terms, which Apache-2.0 code permits |
| MouseInfo, PyMsgBox, python3-Xlib (via PyAutoGUI) | frozen builds | GPLv3+ / GPLv3+ classifier with BSD text / GPLv2, per their metadata | As for piper-tts |
| zeroconf, chardet, python-xlib | frozen builds | LGPL-2.1-or-later | Pass on the LGPL terms; `LGPL_SOURCES.md` (as above) gives each version's source on PyPI |
| openWakeWord's feature extractor (`melspectrogram.onnx`, `embedding_model.onnx`) | frozen builds (package data) | Code Apache-2.0; the embedding model is a re-implementation of Google's Apache-2.0 model, and openWakeWord's note puts all its included pre-trained models under CC BY-NC-SA 4.0 | Unclear for the embedding model (see HIGH). The wake-word models themselves (CC BY-NC-SA 4.0) are left out from v2.5.37 |
| Piper voices (twelve, from `local-assets-v2.1`) | frozen builds, portable tarball, model pack | Per voice (see `models/MODEL_LICENSES.md`) | `ru_RU-ruslan-medium` is CC BY-NC-SA 4.0 (non-commercial); `zh_CN-huayan-x_low` has no stated licence; others are CC0, public domain, CC BY 4.0, CC BY-SA 4.0 or "see URL" |
| nomic-embed-text-v1.5 | frozen builds, portable tarball, model pack | Apache-2.0 | Keep its licence |
| Starter chat GGUFs | model pack only | Apache-2.0 / MIT | See `models/MODEL_LICENSES.md` |
| Catalog models (downloaded by the user) | not redistributed | Per model; Qwen2.5-3B is non-commercial (Qwen Research License) | Nothing for ELI's distributor; the user accepts the upstream terms |
| GPU packs (downloaded on first start) | not in the installers | llama-cpp-python MIT; CUDA runtime under NVIDIA's terms | — |

The full component list is in `THIRD_PARTY_NOTICES.md`, the model and voice list in
`models/MODEL_LICENSES.md`. This table describes the licences; it is not legal
advice.

---

## Pre-release checklist (v2.5.36)

- [ ] All cross-platform-smoke jobs green on `main`
- [ ] Release job produces Linux + macOS + Windows artifacts, and its whole-suite test job passes
- [ ] `python3 tools/audit_cross_platform.py` → exit 0
- [ ] `pytest tests/claims/test_no_silent_swallow.py` → count ≤ CEILING (165)
- [ ] `pyproject.toml` version = tag = `self_upgrade.py` default tag (`_DEFAULT_RELEASE_TAG`)
- [ ] No personal files in release workspace
- [ ] README release note accurate
- [ ] `docs/SILENT_EXCEPTION_AUDIT.md` regenerated

---

## Clean architecture (reference)

- **`eli/core/paths.py`** — canonical path resolver (`ELI_*` env overrides)
- **`eli/utils/platform_compat.py`** — OS abstraction (browser, volume, open URL/file)
- **`eli/system/portable_app_control.py`** — window/app control with guards
- **`config/templates/settings.template.json`** — empty first-run seed
