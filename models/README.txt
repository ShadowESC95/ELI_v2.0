ELI MKXI organized release folder

Use these folders by target platform:

Windows/
  eli-mkxi-1.0.0-windows-portable.zip
  Extract on Windows, then run install.bat or install.ps1 from inside the extracted folder.
  The zip includes README.md, .env.example, .env.full.example, requirements files, and an offline Windows wheelhouse for Python 3.11/3.12 CPU installs.

Linux/
  eli-mkxi_1.0.0_amd64.deb
  Install on Debian/Ubuntu with: sudo apt install ./eli-mkxi_1.0.0_amd64.deb

  eli-mkxi-1.0.0-x86_64-portable.tar.gz
  Extract on Linux and run the included launcher/install scripts from inside the extracted folder.

macOS/
  ELI_MKXI-1.0.0-macos-app.tar.gz
  Extract on macOS. This is an app bundle tarball; producing a .dmg still requires running the macOS packaging script on a macOS host.

Python/
  eli_mkxi-1.0.0-py3-none-any.whl
  Install into an existing Python environment with: python -m pip install eli_mkxi-1.0.0-py3-none-any.whl

Docs/
  Full instruction document if available.

Checksums/
  SHA256SUMS.txt contains checksums for the canonical artifacts in the project dist/ folder.
  SHA256SUMS_ORGANIZED.txt in this folder contains checksums for this organized Desktop copy.

Portability notes:
  Paths inside the app are intended to resolve relative to the project/install tree or environment variables such as ELI_PROJECT_ROOT.
  Android support targets Termux/headless operation. Full desktop-control and GUI feature parity is not realistic on Android.
  Windows/macOS/Linux desktop-control features still depend on OS permissions, installed helper tools, drivers, microphone/speaker access, and available model files.
