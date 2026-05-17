from __future__ import annotations

from pathlib import Path
from datetime import datetime

ROOT = Path("/home/jay/Desktop/ELI_MKXI-main_MAY_NEWEST")
GUI = ROOT / "eli/gui/eli_pro_audio_gui_MKI.py"

src = GUI.read_text(encoding="utf-8")
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = GUI.with_suffix(f".py.bak_eli_world_{stamp}")
backup.write_text(src, encoding="utf-8")

METHOD = r'''
    def create_eli_world_tab(self):
        """Create Eli's World tab: local embodied autonomy/world-state HMI."""
        try:
            from eli.gui.tabs.eli_world_tab import EliWorldTab
            self._eli_world_widget = EliWorldTab(parent=self)
            self.tabs.addTab(self._eli_world_widget, "🌍 Eli's World")
            print("[EliWorld] tab loaded")
        except Exception as _eli_world_err:
            print(f"[EliWorld] failed to load: {_eli_world_err}")
            try:
                fallback = QWidget()
                QVBoxLayout(fallback).addWidget(QLabel(f"Eli's World unavailable: {_eli_world_err}"))
                self.tabs.addTab(fallback, "🌍 Eli's World")
            except Exception as _fallback_err:
                print(f"[EliWorld] fallback tab failed: {_fallback_err}")
'''

if "def create_eli_world_tab(self):" not in src:
    marker = "\n    def create_labs_tab(self):"
    if marker not in src:
        raise SystemExit("Could not find create_labs_tab insertion marker.")
    src = src.replace(marker, "\n" + METHOD + marker, 1)

if "self.create_eli_world_tab()" not in src:
    marker = "        self.create_labs_tab()\n"
    if marker not in src:
        raise SystemExit("Could not find self.create_labs_tab() call marker.")
    src = src.replace(marker, marker + "        self.create_eli_world_tab()\n", 1)

GUI.write_text(src, encoding="utf-8")

print(f"[OK] patched {GUI}")
print(f"[OK] backup {backup}")
