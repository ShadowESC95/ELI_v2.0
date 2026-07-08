#!/usr/bin/env bash
# ELI v2.0 — master release builder.
#
# Drives the per-platform builders under packaging/<platform>/ and emits
# checksums + RELEASE_NOTES.md alongside the artifacts in dist/.
#
# Usage:
#   bash build_packages.sh                  # build everything available
#   bash build_packages.sh wheel            # build only the wheel
#   bash build_packages.sh wheel deb        # subset
#
# Targets:
#   wheel    Python wheel + sdist
#   wheelhouse Windows dependency wheelhouse staged under dist/wheelhouse
#   deb      Debian .deb       (requires dpkg-deb; runs build-deb.sh)
#   appimage Linux AppImage    (requires appimagetool; falls back to tar.gz)
#   macos    macOS .app/.dmg   (use on macOS for the .dmg; tar.gz elsewhere)
#   windows      Windows portable zip with offline wheelhouse (large)
#   windows-lean Windows portable zip — source + wheel only (online pip install)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$PROJECT_ROOT/dist"
VERSION=$(grep -E '^version' "$PROJECT_ROOT/pyproject.toml" | head -1 | awk -F'"' '{print $2}')

mkdir -p "$DIST"

ALL_TARGETS=("wheel" "wheelhouse" "deb" "appimage" "macos" "windows" "windows-lean")
if [ "$#" -eq 0 ]; then
    TARGETS=("${ALL_TARGETS[@]}")
else
    TARGETS=("$@")
fi

echo "================================================="
echo "  ELI v2.0 release builder — version ${VERSION}"
echo "  Targets: ${TARGETS[*]}"
echo "================================================="

build_python_artifacts() {
    if ( cd /tmp && python3 -c 'import build.__main__' >/dev/null 2>&1 ); then
        ( cd /tmp && python3 -m build "$PROJECT_ROOT" --wheel --sdist --outdir "$DIST/" )
    else
        echo "[wheel] python-build frontend not installed; building wheel via pip wheel (sdist skipped)."
        python3 -m pip wheel --no-deps "$PROJECT_ROOT" -w "$DIST/"
    fi
}

build_windows_wheelhouse() {
    echo "[wheelhouse] Building Windows dependency wheelhouse..."
    WHEELHOUSE="$DIST/wheelhouse"
    WHEELHOUSE_PLATFORM="${WHEELHOUSE_PLATFORM:-win_amd64}"
    WHEELHOUSE_PYTHON_VERSIONS="${WHEELHOUSE_PYTHON_VERSIONS:-311 312}"
    mkdir -p "$WHEELHOUSE"

    for pyver in $WHEELHOUSE_PYTHON_VERSIONS; do
        abi="cp${pyver}"
        echo "[wheelhouse] Target: ${WHEELHOUSE_PLATFORM} cp${pyver}"
        while IFS= read -r req; do
            [ -n "$req" ] || continue
            extra_download_args=()
            case "$req" in
                PyAutoGUI*|pyautogui*) continue ;;
                accelerate*) extra_download_args=(--no-deps) ;;
            esac
            if ! python3 -m pip download \
                    --dest "$WHEELHOUSE" \
                    --platform "$WHEELHOUSE_PLATFORM" \
                    --python-version "$pyver" \
                    --implementation cp \
                    --abi "$abi" \
                    --only-binary=:all: \
                    --prefer-binary \
                    "${extra_download_args[@]}" \
                    "$req"; then
                echo "[wheelhouse] Missing binary wheel for cp${pyver}: $req"
            fi
        done < <(
            sed -e 's/[[:space:]]#.*$//' "$PROJECT_ROOT/requirements-windows.txt" |
            awk 'NF && $1 !~ /^#/'
        )

        if ! python3 -m pip download \
                --dest "$WHEELHOUSE" \
                --platform "$WHEELHOUSE_PLATFORM" \
                --python-version "$pyver" \
                --implementation cp \
                --abi "$abi" \
                --only-binary=:all: \
                --prefer-binary \
                torch \
                --index-url https://download.pytorch.org/whl/cpu; then
            echo "[wheelhouse] Missing CPU PyTorch wheel for cp${pyver}."
        fi
    done

    echo "[wheelhouse] Building pure-Python automation wheels..."
    if ! python3 -m pip wheel \
            --wheel-dir "$WHEELHOUSE" \
            "PyAutoGUI>=0.9.54"; then
        echo "[wheelhouse] Missing pure-Python automation wheels for PyAutoGUI."
    fi

    ( cd "$WHEELHOUSE" && ls -1 > "$DIST/WHEELHOUSE.txt" 2>/dev/null || true )
}

_stage_windows_common() {
    local STAGING="$1"
    rm -rf "$STAGING"
    mkdir -p "$STAGING/dist"
    (cd "$PROJECT_ROOT" && git archive --format=tar HEAD -- ':!:models/**' ':!:tts_piper/**') | tar -xf - -C "$STAGING"
    cp "$PROJECT_ROOT/install.bat" "$PROJECT_ROOT/install.ps1" "$PROJECT_ROOT/eli.bat" "$STAGING/"
    cp "$PROJECT_ROOT/requirements-windows.txt" "$STAGING/requirements.txt"
    cp "$PROJECT_ROOT/requirements-windows.txt" "$STAGING/"
    for extra in requirements-full.txt requirements-macos.txt requirements-android.txt pyproject.toml README.md .env.example; do
        [ -f "$PROJECT_ROOT/$extra" ] && cp "$PROJECT_ROOT/$extra" "$STAGING/" 2>/dev/null || true
    done
    if [ -d "$PROJECT_ROOT/packaging/windows" ]; then
        mkdir -p "$STAGING/installers"
        cp -r "$PROJECT_ROOT/packaging/windows/." "$STAGING/installers/"
    fi
    if ls "$DIST"/eli_v2_0-*.whl >/dev/null 2>&1; then
        cp "$DIST"/eli_v2_0-*.whl "$STAGING/dist/"
    fi
    cat > "$STAGING/ELI_Setup.bat" <<'BAT_EOF'
@echo off
title ELI Setup
cd /d "%~dp0"
echo ELI v2.0 setup — first run may take several minutes.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Yes
if errorlevel 1 ( echo Setup failed. & pause & exit /b 1 )
echo Setup complete. Run eli.bat to launch ELI.
pause
BAT_EOF
    cat > "$STAGING/README_INSTALL.txt" <<EOF
ELI v2 — Windows portable (${2:-lean})

1. Extract this folder
2. Run install.bat  (or: powershell -ExecutionPolicy Bypass -File install.ps1)
3. Run eli.bat

Model pack: GitHub release tag local-assets-v2.1 or python scripts/restore_github_asset_files.py
EOF

    # cmd.exe's goto-label lookup fails intermittently on LF-only .bat (byte-offset
    # dependent), so force CRLF on every Windows script in the staged package.
    find "$STAGING" -type f \( -name '*.bat' -o -name '*.cmd' -o -name '*.ps1' \) \
        -exec sed -i 's/\r*$/\r/' {} + 2>/dev/null || true

    # Remove Linux/macOS entry points from the WINDOWS package — a customer double-clicking
    # install.sh or an .desktop file on Windows is pure user-error bait. The Python source
    # stays (source-available); only the POSIX launchers/installers are pruned.
    rm -f "$STAGING/install.sh" "$STAGING/eli.sh" "$STAGING/ELI_Setup.sh" \
          "$STAGING/build_packages.sh" "$STAGING"/*.desktop 2>/dev/null || true
    rm -rf "$STAGING/bin" 2>/dev/null || true
    for _s in eli_launch.sh eli_serve.sh eli_setup.sh eli_startup.sh eli_term.sh \
              eli_uninstall.sh install_desktop_apps.sh; do
        rm -f "$STAGING/scripts/$_s" 2>/dev/null || true
    done

    # Pre-generate the capability manifest into the package (it's gitignored, so the
    # git-archive source carries none) — the installer's offline fallback copy.
    ( cd "$STAGING" && PYTHONPATH="$STAGING" python3 -c \
      "from eli.tools.registry.capability_updater import update_capability_manifest; update_capability_manifest()" ) \
      >/dev/null 2>&1 || true
}

# ── Pre-flight: tests must pass before producing artifacts ──────────────
echo ""
echo "[pre-flight] Compiling the codebase…"
# This is a MAINTAINER build tool. If it's run from an unpacked release (no .git),
# fall back to a plain file walk instead of `git ls-files` so it doesn't error out.
if git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    ( cd "$PROJECT_ROOT" && python3 -m py_compile $(git ls-files '*.py') )
else
    echo "[pre-flight] not a git checkout — this is the maintainer release builder;"
    echo "             to USE ELI run ./ELI_Setup.sh (or ./RUN_ELI.sh). Skipping compile."
    ( cd "$PROJECT_ROOT" && find eli api -name '*.py' -print0 2>/dev/null | xargs -0 python3 -m py_compile 2>/dev/null || true )
fi

if [ -z "${SKIP_TESTS:-}" ]; then
    echo "[pre-flight] Running pytest (set SKIP_TESTS=1 to skip)…"
    ( cd "$PROJECT_ROOT" && pytest -q tests/ )
fi

# ── Targets ─────────────────────────────────────────────────────────────
for target in "${TARGETS[@]}"; do
    case "$target" in
        wheel)
            echo ""
            echo "[wheel] Building Python distribution artifacts…"
            build_python_artifacts
            ;;
        wheelhouse)
            echo ""
            build_windows_wheelhouse
            ;;
        deb)
            echo ""
            if [ -f "$PROJECT_ROOT/packaging/debian/build-deb.sh" ]; then
                echo "[deb] Invoking packaging/debian/build-deb.sh…"
                bash "$PROJECT_ROOT/packaging/debian/build-deb.sh" "$VERSION" || \
                    echo "[deb] build-deb.sh failed (probably missing dpkg-deb / fakeroot)."
            else
                echo "[deb] No .deb builder yet (packaging/debian/ does not exist)."
                echo "[deb] Use the portable tarball or AppImage instead: bash build_packages.sh appimage"
            fi
            ;;
        appimage)
            echo ""
            echo "[appimage] Invoking packaging/linux/build-appimage.sh…"
            bash "$PROJECT_ROOT/packaging/linux/build-appimage.sh" "$VERSION" || \
                echo "[appimage] build-appimage.sh failed."
            ;;
        macos)
            echo ""
            if [ -f "$PROJECT_ROOT/packaging/macos/build-macos-app.sh" ]; then
                echo "[macos] Invoking packaging/macos/build-macos-app.sh…"
                bash "$PROJECT_ROOT/packaging/macos/build-macos-app.sh" "$VERSION" || \
                    echo "[macos] macOS builder failed (run on macOS for a real .dmg)."
            else
                echo "[macos] No macOS builder yet (packaging/macos/ does not exist)."
                echo "[macos] macOS users: install from source — bash install.sh (Metal auto-detected)."
            fi
            ;;
        windows-lean)
            echo ""
            echo "[windows-lean] Producing lean portable zip (source + wheel)…"
            if ! ls "$DIST"/eli_v2_0-*.whl >/dev/null 2>&1; then
                build_python_artifacts
            fi
            STAGING="$PROJECT_ROOT/build/win-portable/ELI_v2-${VERSION}-windows-portable"
            _stage_windows_common "$STAGING" "lean"
            ZIP="$DIST/ELI_v2-${VERSION}-windows-portable.zip"
            rm -f "$ZIP"
            ( cd "$(dirname "$STAGING")" && zip -r -q "$ZIP" "$(basename "$STAGING")" )
            echo "[windows-lean] Portable zip: $ZIP"
            ;;
        windows)
            echo ""
            if [ "$(uname -s)" = "Darwin" ] || [ "$(uname -s)" = "Linux" ]; then
                echo "[windows] Producing full offline portable zip on $(uname -s)…"
                if ! ls "$DIST"/eli_v2_0-*.whl >/dev/null 2>&1; then
                    build_python_artifacts
                fi
                if ! find "$DIST/wheelhouse" -maxdepth 1 -name '*.whl' -print -quit 2>/dev/null | grep -q .; then
                    build_windows_wheelhouse
                fi
                STAGING="$PROJECT_ROOT/build/win-portable/ELI_v2-${VERSION}-windows-portable-full"
                _stage_windows_common "$STAGING" "full offline"
                if [ -d "$DIST/wheelhouse" ]; then
                    cp -r "$DIST/wheelhouse" "$STAGING/wheelhouse"
                fi
                ZIP="$DIST/ELI_v2-${VERSION}-windows-portable-full.zip"
                rm -f "$ZIP"
                ( cd "$(dirname "$STAGING")" && zip -r -q "$ZIP" "$(basename "$STAGING")" )
                echo "[windows] Full portable zip: $ZIP"
                echo "[windows] To produce a .exe / .msi installer: run packaging/windows/build-windows.ps1 on a Windows host."
            else
                powershell.exe -ExecutionPolicy Bypass -File "$PROJECT_ROOT/packaging/windows/build-windows.ps1" \
                    -Version "$VERSION" || echo "[windows] windows builder failed."
            fi
            ;;
        *)
            echo "[skip] Unknown target: $target"
            ;;
    esac
done

# ── Checksums & release notes ───────────────────────────────────────────
echo ""
if [ -d "$DIST/wheelhouse" ]; then
    ( cd "$DIST/wheelhouse" && ls -1 > "$DIST/WHEELHOUSE.txt" 2>/dev/null || true )
fi

echo "[finalise] Computing SHA-256 checksums…"
( cd "$DIST" && sha256sum eli_v2_0-*.whl 2>/dev/null \
                          eli_v2_0-*.tar.gz 2>/dev/null \
                          ELI_v2-*.dmg 2>/dev/null \
                          ELI_v2-*.AppImage 2>/dev/null \
                          ELI_v2-*-Setup.exe 2>/dev/null \
                          eli-v2.0_*_amd64.deb 2>/dev/null \
                          ELI_v2-*-windows-portable*.zip 2>/dev/null \
                          ELI_v2-*-linux-portable.tar.gz 2>/dev/null \
                          ELI_v2-*-macos-app.tar.gz 2>/dev/null > SHA256SUMS.txt || true )

cat > "$DIST/RELEASE_NOTES.md" <<EOF
# ELI v2 ${VERSION}

Built on: $(date -u +"%Y-%m-%d %H:%M UTC")
Host: $(uname -s) $(uname -r) ($(uname -m))

## Artifacts
$(cd "$DIST" && ls -1 *.whl *.tar.gz *.deb *.AppImage *.dmg *.exe *.zip 2>/dev/null | sed 's/^/- /')

## Verification
\`\`\`
$(cat "$DIST/SHA256SUMS.txt" 2>/dev/null || echo "(checksum file missing)")
\`\`\`

## Install quick reference
- **pip / wheel**: \`pip install dist/eli_v2_0-${VERSION}-py3-none-any.whl[full]\`
- **Debian/Ubuntu**: \`sudo dpkg -i dist/eli-v2.0_${VERSION}_amd64.deb && sudo apt -f install\`
- **Linux portable**: extract \`dist/ELI_v2-${VERSION}-linux-portable.tar.gz\`, run \`./INSTALL_ELI.sh\`
- **Windows lean**: extract \`dist/ELI_v2-${VERSION}-windows-portable.zip\`, run \`install.bat\`
- **Windows full offline**: extract \`dist/ELI_v2-${VERSION}-windows-portable-full.zip\`, run \`install.bat\`
- **macOS**: build on a Mac host with \`bash build_packages.sh macos\`

EOF

echo ""
echo "================================================="
echo "  Release artifacts in $DIST :"
ls -lh "$DIST/" | awk 'NR==1{next} {print "  " $9 "  (" $5 ")"}'
echo "================================================="
echo "  Notes: $DIST/RELEASE_NOTES.md"
echo "  Checksums: $DIST/SHA256SUMS.txt"
echo "================================================="
