#!/usr/bin/env bash
# ELI MKXI — master release builder.
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
#   windows  Windows installer (use on Windows for .exe; portable zip elsewhere)
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="$PROJECT_ROOT/dist"
VERSION=$(grep -E '^version' "$PROJECT_ROOT/pyproject.toml" | head -1 | awk -F'"' '{print $2}')

mkdir -p "$DIST"

ALL_TARGETS=("wheel" "wheelhouse" "deb" "appimage" "macos" "windows")
if [ "$#" -eq 0 ]; then
    TARGETS=("${ALL_TARGETS[@]}")
else
    TARGETS=("$@")
fi

echo "================================================="
echo "  ELI MKXI release builder — version ${VERSION}"
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

# ── Pre-flight: tests must pass before producing artifacts ──────────────
echo ""
echo "[pre-flight] Compiling the codebase…"
( cd "$PROJECT_ROOT" && python3 -m py_compile $(git ls-files '*.py') )

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
            echo "[deb] Invoking packaging/debian/build-deb.sh…"
            bash "$PROJECT_ROOT/packaging/debian/build-deb.sh" "$VERSION" || \
                echo "[deb] build-deb.sh failed (probably missing dpkg-deb / fakeroot)."
            ;;
        appimage)
            echo ""
            echo "[appimage] Invoking packaging/linux/build-appimage.sh…"
            bash "$PROJECT_ROOT/packaging/linux/build-appimage.sh" "$VERSION" || \
                echo "[appimage] build-appimage.sh failed."
            ;;
        macos)
            echo ""
            echo "[macos] Invoking packaging/macos/build-macos-app.sh…"
            bash "$PROJECT_ROOT/packaging/macos/build-macos-app.sh" "$VERSION" || \
                echo "[macos] macOS builder failed (run on macOS for a real .dmg)."
            ;;
        windows)
            echo ""
            if [ "$(uname -s)" = "Darwin" ] || [ "$(uname -s)" = "Linux" ]; then
                echo "[windows] Producing portable zip on $(uname -s)…"
                if ! ls "$DIST"/eli_mkxi-*.whl >/dev/null 2>&1; then
                    build_python_artifacts
                fi
                if ! find "$DIST/wheelhouse" -maxdepth 1 -name '*.whl' -print -quit 2>/dev/null | grep -q .; then
                    build_windows_wheelhouse
                fi
                STAGING="$PROJECT_ROOT/build/win-portable/eli-mkxi-${VERSION}-windows"
                rm -rf "$STAGING"
                mkdir -p "$STAGING/dist"
                cp -r "$PROJECT_ROOT/eli"     "$STAGING/"
                cp -r "$PROJECT_ROOT/config"  "$STAGING/" 2>/dev/null || true
                cp    "$PROJECT_ROOT/pyproject.toml" "$STAGING/"
                cp    "$PROJECT_ROOT/README.md" "$STAGING/" 2>/dev/null || true
                cp    "$PROJECT_ROOT/.env.example" "$STAGING/" 2>/dev/null || true
                cp    "$PROJECT_ROOT/.env.full.example" "$STAGING/" 2>/dev/null || true
                cp    "$PROJECT_ROOT/eli.bat" "$STAGING/"
                cp    "$PROJECT_ROOT/install.bat" "$STAGING/"
                cp    "$PROJECT_ROOT/install.ps1" "$STAGING/"
                cp    "$PROJECT_ROOT/requirements-full.txt" "$STAGING/requirements-full.txt"
                cp    "$PROJECT_ROOT/requirements-android.txt" "$STAGING/requirements-android.txt"
                cp    "$PROJECT_ROOT/requirements-macos.txt" "$STAGING/requirements-macos.txt"
                cp    "$PROJECT_ROOT/requirements-windows.txt" "$STAGING/requirements-windows.txt"
                cp    "$PROJECT_ROOT/requirements-windows.txt" "$STAGING/requirements.txt"
                cp -r "$PROJECT_ROOT/packaging/windows" "$STAGING/installers"
                if ls "$DIST"/eli_mkxi-*.whl >/dev/null 2>&1; then
                    cp "$DIST"/eli_mkxi-*.whl "$STAGING/dist/"
                fi
                if [ -d "$DIST/wheelhouse" ]; then
                    cp -r "$DIST/wheelhouse" "$STAGING/wheelhouse"
                fi
                ZIP="$DIST/eli-mkxi-${VERSION}-windows-portable.zip"
                rm -f "$ZIP"
                ( cd "$(dirname "$STAGING")" && zip -r -q "$ZIP" "$(basename "$STAGING")" )
                echo "[windows] Portable zip: $ZIP"
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
( cd "$DIST" && sha256sum eli_mkxi-*.whl 2>/dev/null \
                          eli_mkxi-*.tar.gz 2>/dev/null \
                          ELI_MKXI-*.dmg 2>/dev/null \
                          ELI_MKXI-*.AppImage 2>/dev/null \
                          ELI_MKXI-*-Setup.exe 2>/dev/null \
                          eli-mkxi_*_amd64.deb 2>/dev/null \
                          eli-mkxi-*-windows-portable.zip 2>/dev/null \
                          eli-mkxi-*-portable.tar.gz 2>/dev/null \
                          ELI_MKXI-*-macos-app.tar.gz 2>/dev/null > SHA256SUMS.txt || true )

cat > "$DIST/RELEASE_NOTES.md" <<EOF
# ELI MKXI ${VERSION}

Built on: $(date -u +"%Y-%m-%d %H:%M UTC")
Host: $(uname -s) $(uname -r) ($(uname -m))

## Artifacts
$(cd "$DIST" && ls -1 *.whl *.tar.gz *.deb *.AppImage *.dmg *.exe *.zip 2>/dev/null | sed 's/^/- /')

## Verification
\`\`\`
$(cat "$DIST/SHA256SUMS.txt" 2>/dev/null || echo "(checksum file missing)")
\`\`\`

## Install quick reference
- **pip / wheel**: \`pip install dist/eli_mkxi-${VERSION}-py3-none-any.whl[full]\`
- **Debian/Ubuntu**: \`sudo dpkg -i dist/eli-mkxi_${VERSION}_amd64.deb && sudo apt -f install\`
- **Linux AppImage**: \`chmod +x dist/ELI_MKXI-${VERSION}-x86_64.AppImage && ./dist/ELI_MKXI-${VERSION}-x86_64.AppImage\`
- **macOS**: open \`dist/ELI_MKXI-${VERSION}.dmg\`, drag ELI MKXI.app to Applications
- **Windows installer**: run \`dist/ELI_MKXI-${VERSION}-Setup.exe\` (Inno/NSIS) or extract the portable zip and run \`install.bat\`

EOF

echo ""
echo "================================================="
echo "  Release artifacts in $DIST :"
ls -lh "$DIST/" | awk 'NR==1{next} {print "  " $9 "  (" $5 ")"}'
echo "================================================="
echo "  Notes: $DIST/RELEASE_NOTES.md"
echo "  Checksums: $DIST/SHA256SUMS.txt"
echo "================================================="
