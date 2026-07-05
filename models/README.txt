ELI v2.0 release artifacts (organised copy)

Use these folders by target platform:

Windows/
  eli-mkxi-2.0.0-windows-portable.zip
  Extract, then run install.bat or install.ps1 inside the folder.

Linux/
  ELI_MKXI_v2.0_PRO-2.0.0-linux-portable.tar.gz
  Extract, then ./INSTALL_ELI.sh and ./RUN_ELI.sh
  (Best tested on Linux x86_64 + NVIDIA.)

  eli-mkxi_2.0.0_amd64.deb
  sudo apt install ./eli-mkxi_2.0.0_amd64.deb

macOS/
  ELI_MKXI-2.0.0-macos-app.tar.gz
  Extract on macOS; .dmg requires building on a Mac host.

Python/
  eli_mkxi-2.0.0-py3-none-any.whl
  python -m pip install eli_mkxi-2.0.0-py3-none-any.whl

Model / voice packs/
  Distributed separately via GitHub Release assets (too large for git).
  Restore after install: ./RUN_ELI.sh --with-github-assets

Checksums/
  SHA256SUMS.txt alongside builds in dist/
