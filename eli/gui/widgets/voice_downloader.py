"""Voice library browser — acquire additional Piper voices, accents and tones.

ELI ships a small pack of voices; upstream (rhasspy/piper-voices) hosts ~166 across
45 languages. ``eli.runtime.voice_assets`` could already fetch any of them, but
nothing exposed that to the user — this dialog is that missing path.

Usage (Settings ▸ VOICE / TTS):

    from eli.gui.widgets.voice_downloader import VoiceDownloadDialog
    dlg = VoiceDownloadDialog(self)
    dlg.voices_changed.connect(self._reload_voice_combos)
    dlg.exec()

Licence note surfaced in the UI: a few voices (ryan / lessac / cori) are marked
*restricted* — ELI does not redistribute them because their datasets are
non-commercial or not cleared, but the user may still download them from upstream
for their own personal use. That distinction is shown, never silently applied.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List

from eli.gui.qt_compat import Qt, pyqtSignal
from eli.gui.qt_compat import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

log = logging.getLogger(__name__)

_RESTRICTED_NOTE = (
    "Not redistributed with ELI — its dataset licence is non-commercial or "
    "not cleared for bundling. You can still download it here for personal use."
)


class VoiceDownloadDialog(QDialog):
    """Browse every obtainable Piper voice and install one on demand."""

    voices_changed = pyqtSignal()
    _rows_ready = pyqtSignal(list)
    _download_done = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Voice library — download more voices")
        self.resize(760, 520)
        self._rows: List[Dict[str, Any]] = []
        self._char_bases: Dict[str, List[str]] = {}
        self._busy = False

        root = QVBoxLayout(self)
        blurb = QLabel(
            "Voices are downloaded from the Piper voice library and stored locally. "
            "Character voices (HAL, TARS, …) layer effects on top of a base voice, "
            "so adding the ideal base improves them automatically."
        )
        blurb.setWordWrap(True)
        blurb.setStyleSheet("color:#8eaac8;")
        root.addWidget(blurb)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Language:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("English", "en")
        self.lang_combo.addItem("All languages", "")
        self.lang_combo.currentIndexChanged.connect(lambda _i: self._refresh_table())
        filters.addWidget(self.lang_combo)
        self.installed_only = QCheckBox("Installed only")
        self.installed_only.stateChanged.connect(lambda _s: self._refresh_table())
        filters.addWidget(self.installed_only)
        filters.addStretch(1)
        self.refresh_btn = QPushButton("↻ Refresh list")
        self.refresh_btn.setToolTip("Re-fetch the voice index from upstream (needs network)")
        self.refresh_btn.clicked.connect(self._refresh_index)
        filters.addWidget(self.refresh_btn)
        root.addLayout(filters)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Voice", "Accent / region", "Quality", "Size", "Status"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_select)
        try:
            self.table.horizontalHeader().setStretchLastSection(True)
            self.table.setColumnWidth(0, 250)
            self.table.setColumnWidth(1, 170)
        except Exception:
            log.debug("voice dialog: header sizing unavailable", exc_info=True)
        root.addWidget(self.table, 1)

        self.status = QLabel("Select a voice to install.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#8eaac8;")
        root.addWidget(self.status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate; sizes vary 60–115 MB
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.download_btn = QPushButton("⬇ Download")
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._download_selected)
        buttons.addWidget(self.download_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

        self._rows_ready.connect(self._apply_rows)
        self._download_done.connect(self._on_download_done)
        self._load_rows(refresh=False)

    # ── data ────────────────────────────────────────────────────────────────
    def _load_rows(self, refresh: bool) -> None:
        """Read the catalog off the GUI thread (a refresh hits the network)."""
        self._set_busy(True, "Loading voice list…" if refresh else "")

        def work() -> None:
            rows: List[Dict[str, Any]] = []
            try:
                from eli.runtime.voice_assets import list_available_voices
                rows = list_available_voices(refresh=refresh)
            except Exception:
                log.debug("voice dialog: catalog load failed", exc_info=True)
            self._rows_ready.emit(rows)

        threading.Thread(target=work, daemon=True).start()

    def _character_bases(self) -> Dict[str, List[str]]:
        """{base voice id: [character names]} so the table can point out which
        download upgrades HAL/TARS/Rick from their shipped fallback."""
        out: Dict[str, List[str]] = {}
        try:
            from eli.perception import voice_fx
            for c in voice_fx.list_characters():
                spec = voice_fx.get_preset(str(c.get("name") or "")) or {}
                base = str(spec.get("base") or "").strip()
                fallback = str(spec.get("fallback") or "").strip()
                if base and base != fallback:
                    out.setdefault(base, []).append(str(c.get("name") or "").upper())
        except Exception:
            log.debug("voice dialog: character bases unavailable", exc_info=True)
        return out

    def _apply_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._rows = list(rows or [])
        self._char_bases = self._character_bases()
        self._set_busy(False, "")
        if not self._rows:
            self.status.setText(
                "No voice list available. Click ↻ Refresh list while online to fetch it.")
        self._refresh_table()

    def _refresh_index(self) -> None:
        self._load_rows(refresh=True)

    def _visible_rows(self) -> List[Dict[str, Any]]:
        lang = self.lang_combo.currentData() or ""
        out = self._rows
        if lang:
            out = [r for r in out
                   if str(r.get("language", "")).split("_")[0] == lang]
        if self.installed_only.isChecked():
            out = [r for r in out if r.get("present")]
        return out

    def _refresh_table(self) -> None:
        rows = self._visible_rows()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            present, restricted = bool(r.get("present")), bool(r.get("restricted"))
            if present:
                state = "✅ installed"
            elif restricted:
                state = "⚠ personal use only"
            else:
                state = "available"
            size = f"{r.get('size_mb', 0):.0f} MB" if r.get("size_mb") else "—"
            chars = self._char_bases.get(str(r.get("id", "")), [])
            if chars and not present:
                state = f"upgrades {', '.join(chars)}"
            cells = [str(r.get("id", "")), str(r.get("country") or r.get("language") or ""),
                     str(r.get("quality", "")), size, state]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                tip = []
                if chars:
                    tip.append("Ideal base voice for: " + ", ".join(chars)
                               + " — they currently use a shipped stand-in.")
                if restricted:
                    tip.append(_RESTRICTED_NOTE)
                elif r.get("desc"):
                    tip.append(str(r["desc"]))
                if tip:
                    item.setToolTip("\n\n".join(tip))
                self.table.setItem(i, c, item)
        self._on_select()

    def _selected(self) -> Dict[str, Any]:
        rows = self._visible_rows()
        idx = self.table.currentRow()
        return rows[idx] if 0 <= idx < len(rows) else {}

    def _on_select(self) -> None:
        r = self._selected()
        if not r or self._busy:
            self.download_btn.setEnabled(False)
            return
        if r.get("present"):
            self.download_btn.setEnabled(False)
            self.status.setText(f"{r['id']} is already installed.")
            return
        self.download_btn.setEnabled(True)
        note = f"{r['id']} — {r.get('size_mb', 0):.0f} MB download."
        if r.get("desc"):
            note = f"{r['id']} — {r['desc']} ({r.get('size_mb', 0):.0f} MB)."
        if r.get("restricted"):
            note += f"\n⚠ {_RESTRICTED_NOTE}"
        self.status.setText(note)

    # ── download ────────────────────────────────────────────────────────────
    def _download_selected(self) -> None:
        r = self._selected()
        if not r or self._busy:
            return
        vid = str(r.get("id") or "")
        if r.get("restricted"):
            ok = QMessageBox.question(
                self, "Licence notice",
                f"{vid}\n\n{_RESTRICTED_NOTE}\n\nDownload it for personal use?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ok != QMessageBox.StandardButton.Yes:
                return
        self._set_busy(True, f"Downloading {vid} — this can take a minute…")

        def work() -> None:
            try:
                from eli.runtime.voice_assets import download_voice
                res = download_voice(vid, mirror=True)
            except Exception as e:
                log.debug("voice dialog: download failed", exc_info=True)
                res = {"ok": False, "voice": vid, "error": str(e)}
            self._download_done.emit(res)

        threading.Thread(target=work, daemon=True).start()

    def _on_download_done(self, res: Dict[str, Any]) -> None:
        self._set_busy(False, "")
        vid = str(res.get("voice") or "")
        if res.get("ok"):
            self.status.setText(f"✅ {vid} installed — it's now selectable as a voice.")
            self.voices_changed.emit()
            self._load_rows(refresh=False)
        else:
            err = str(res.get("error") or "download failed")
            self.status.setText(f"❌ {vid}: {err}")
            QMessageBox.warning(self, "Download failed", f"{vid}\n\n{err}")

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        self.download_btn.setEnabled(not busy and bool(self._selected()))
        self.refresh_btn.setEnabled(not busy)
        if message:
            self.status.setText(message)
