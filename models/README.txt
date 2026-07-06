ELI v2.0 release artifacts (organised copy)

Artifact names follow the builders' output pattern: ELI_v2-<version>-<target>.
Current version: 2.0.9 (canonical source: pyproject.toml).

Windows/
  ELI_v2-2.0.9-windows-portable.zip
  Extract, then double-click ELI_Setup.bat (or run install.bat / install.ps1).

  ELI_v2-2.0.9-Setup.exe
  Windows installer (built on Windows with Inno Setup).

Linux/
  ELI_v2-2.0.9-linux-portable.tar.gz
  Extract, then ./ELI_Setup.sh (guided) — or ./INSTALL_ELI.sh and ./RUN_ELI.sh
  (Best tested on Linux x86_64 + NVIDIA.)

  ELI_v2-2.0.9-x86_64.AppImage
  chmod +x, then double-click or run directly.

Python/
  eli_v2_0-2.0.9-py3-none-any.whl
  python -m pip install eli_v2_0-2.0.9-py3-none-any.whl

Model / voice packs/
  Distributed separately via GitHub Release assets (too large for git),
  tag: local-assets-v2.1. Restore after install:
  ./RUN_ELI.sh --with-github-assets

Checksums/
  SHA256SUMS.txt alongside builds in dist/
