"""Settings ▸ Plugins ▸ Marketplace — browse, scan, install, and revoke.

Four panes, matching the four decisions an operator actually makes:

  Browse      what the community registries are offering, with the verification
              state and permission risk shown BEFORE anything is downloaded
  Installed   what is on this machine, what it may do, and a switch to turn it off
  Permissions every grant given, and a way to take any of them back
  Registries  which community sources this machine trusts at all

The install path is deliberately slow. A listing is downloaded to memory, hashed,
signature-checked, statically analysed against its own manifest, and run through
every malware engine available — and only then is the operator shown a summary and
asked. Nothing is written to disk before that answer, and what is written arrives
switched OFF with no permissions granted.

Threading: scanning and downloading happen on a QThread and reach the GUI through
signals only. QTimer.singleShot from a worker never fires.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from eli.gui.panels._qt import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QLineEdit, QComboBox, QTabWidget, QSplitter,
    QAbstractItemView, QHeaderView, QMessageBox, QDialog, QFormLayout,
    QProgressBar, QInputDialog, Qt, QThread, QObject, pyqtSignal,
)
from eli.utils.log import get_logger

log = get_logger(__name__)

_OK = "#a3be8c"
_WARN = "#ebcb8b"
_BAD = "#bf616a"
_DIM = "#6c7086"
_RISK = {"low": _OK, "medium": _WARN, "high": "#d08770", "critical": _BAD}


class _Worker(QObject):
    """Runs a blocking marketplace call off the GUI thread."""
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:
            log.debug("marketplace worker failed", exc_info=True)
            self.failed.emit(str(exc))


class MarketplaceTab(QWidget):
    def __init__(self, parent_window=None):
        super().__init__()
        self._parent_window = parent_window
        self._listings: List[Dict[str, Any]] = []
        self._thread: Optional[QThread] = None
        self._worker: Optional[_Worker] = None
        self._build()
        self._refresh_installed()
        self._refresh_permissions()
        self._refresh_registries()
        self._refresh_mcp()

    # ── shell ─────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)

        banner = QLabel(
            "<b>Community marketplace.</b> <span style='color:#6c7086'>These plugins are "
            "written by other people, not by ELI, and nobody vets them. ELI checks what it "
            "can — the file matches the listing, who signed it, and a malware scan — then "
            "shows you the result and lets you decide.</span>")
        banner.setWordWrap(True)
        banner.setStyleSheet("padding:6px;background:#2e3440;border-radius:4px;")
        v.addWidget(banner)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._page_browse(), "🛒 Browse")
        self._tabs.addTab(self._page_installed(), "📦 Installed")
        self._tabs.addTab(self._page_permissions(), "🔐 Permissions")
        self._tabs.addTab(self._page_mcp(), "🔌 MCP servers")
        self._tabs.addTab(self._page_registries(), "🌐 Sources")
        v.addWidget(self._tabs, 1)

    # ── browse ────────────────────────────────────────────────────────────────
    def _page_browse(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        top = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search plugins…")
        self._search.returnPressed.connect(self._do_browse)
        top.addWidget(self._search, 1)
        b = QPushButton("Refresh")
        b.clicked.connect(self._do_browse)
        top.addWidget(b)
        v.addLayout(top)

        self._browse_status = QLabel("Press Refresh to load community registries.")
        self._browse_status.setStyleSheet(f"color:{_DIM};")
        self._browse_status.setWordWrap(True)
        v.addWidget(self._browse_status)

        self._busy = QProgressBar()
        self._busy.setRange(0, 0)
        self._busy.setVisible(False)
        v.addWidget(self._busy)

        split = QSplitter(Qt.Orientation.Vertical)
        self._browse_table = QTableWidget(0, 7)
        self._browse_table.setHorizontalHeaderLabels(
            ["Name", "Type", "Publisher", "Version", "Price", "Permissions", "Verified"])
        self._browse_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._browse_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._browse_table.itemSelectionChanged.connect(self._show_listing)
        self._browse_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        split.addWidget(self._browse_table)

        self._browse_detail = QTextEdit()
        self._browse_detail.setReadOnly(True)
        split.addWidget(self._browse_detail)
        split.setSizes([260, 240])
        v.addWidget(split, 1)

        row = QHBoxLayout()
        self._install_btn = QPushButton("⬇ Install")
        self._install_btn.setToolTip(
            "Download, verify, scan and install. Stops to ask only if there is "
            "something to decide — permissions, a scan finding, or a paid listing.")
        self._install_btn.setStyleSheet("font-weight:bold;")
        self._install_btn.clicked.connect(self._quick_install_selected)
        row.addWidget(self._install_btn)
        self._inspect_btn = QPushButton("🔍 Check this plugin")
        self._inspect_btn.setToolTip("Download to memory, verify, and run every malware "
                                     "scanner. Installs nothing.")
        self._inspect_btn.clicked.connect(self._inspect_selected)
        row.addWidget(self._inspect_btn)
        self._licence_btn = QPushButton("Enter licence key…")
        self._licence_btn.clicked.connect(self._enter_licence)
        row.addWidget(self._licence_btn)
        row.addStretch(1)
        v.addLayout(row)
        return w

    def _set_busy(self, busy: bool) -> None:
        self._busy.setVisible(busy)
        self._inspect_btn.setEnabled(not busy)
        if hasattr(self, "_install_btn"):
            self._install_btn.setEnabled(not busy)

    def _run_async(self, fn, on_done) -> None:
        if self._thread is not None:
            return
        self._set_busy(True)
        self._thread = QThread(self)
        self._worker = _Worker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        def _finish(result):
            self._teardown()
            on_done(result)

        def _fail(msg):
            self._teardown()
            self._browse_status.setText(f"<span style='color:{_BAD}'>{msg}</span>")

        self._worker.done.connect(_finish)
        self._worker.failed.connect(_fail)
        self._thread.start()

    def _teardown(self) -> None:
        self._set_busy(False)
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def _do_browse(self) -> None:
        from eli.plugins.marketplace import browse
        q = self._search.text().strip()
        self._browse_status.setText("Loading…")
        self._run_async(lambda: browse(), lambda res: self._fill_browse(res, q))

    def _fill_browse(self, res: Dict[str, Any], query: str) -> None:
        items = res["listings"]
        if query:
            ql = query.lower()
            items = [m for m in items if ql in str(m.get("name", "")).lower()
                     or ql in str(m.get("description", "")).lower()]
        self._listings = items

        self._browse_table.setRowCount(len(items))
        for r, m in enumerate(items):
            perms = m.get("permissions") or []
            risk = m.get("risk", "low")
            price = float(m.get("price") or 0)
            if m.get("signed"):
                verified, colour = "signed", _OK
            elif m.get("pinned"):
                verified, colour = "checksum only", _WARN
            else:
                verified, colour = "unverified", _BAD
            cells = [
                str(m.get("name", m.get("id", "?"))),
                "MCP" if m.get("kind") == "mcp" else "plugin",
                str(m.get("author", "unknown")),
                str(m.get("version", "?")),
                ("free" if price <= 0 else f"{price:g} {m.get('currency', 'EUR')}"),
                (f"{len(perms)} ({risk})" if perms else "none"),
                verified,
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 5 and perms:
                    item.setToolTip("\n".join(perms))
                self._browse_table.setItem(r, c, item)

        errs = res.get("errors") or []
        msg = f"{len(items)} plugin(s) from {len(set(m.get('registry') for m in items))} source(s)."
        if errs:
            offline = any(e.get("offline") for e in errs)
            msg += ("  " + ("ELI is offline — only built-in plugins are listed."
                            if offline else
                            "Some sources failed: "
                            + "; ".join(f"{e['registry']}: {e['error']}" for e in errs[:2])))
        self._browse_status.setText(msg)

    def _selected_listing(self) -> Optional[Dict[str, Any]]:
        r = self._browse_table.currentRow()
        if r < 0 or r >= len(self._listings):
            return None
        return self._listings[r]

    def _show_listing(self) -> None:
        m = self._selected_listing()
        if not m:
            return
        from eli.plugins.permissions import describe
        perms = m.get("permissions") or []
        lines = [
            f"<h3>{m.get('name')}</h3>",
            f"<p>{m.get('description', '')}</p>",
            f"<p><b>Publisher:</b> {m.get('author', 'unknown')} &nbsp; "
            f"<b>Licence:</b> {m.get('license', '?')} &nbsp; "
            f"<b>Source:</b> {m.get('registry_label', m.get('registry'))}</p>",
        ]
        if perms:
            lines.append("<p><b>Requests permission to:</b></p><ul>")
            for p in perms:
                d = describe(p)
                lines.append(f"<li><span style='color:{_RISK.get(d['risk'], _BAD)}'>"
                             f"{d['title']}</span> — {d['detail']}</li>")
            lines.append("</ul>")
        else:
            lines.append("<p>Requests no special permissions.</p>")
        if m.get("listing_problems"):
            lines.append(f"<p style='color:{_BAD}'><b>Listing problems:</b> "
                         + "; ".join(m["listing_problems"]) + "</p>")
        if m.get("listing_warnings"):
            lines.append(f"<p style='color:{_WARN}'>"
                         + "; ".join(m["listing_warnings"]) + "</p>")
        lines.append(f"<p style='color:{_DIM}'>Nothing has been downloaded yet. "
                     f"Use “Check this plugin” to verify and scan it.</p>")
        self._browse_detail.setHtml("".join(lines))

    def _enter_licence(self) -> None:
        m = self._selected_listing()
        if not m:
            return
        from eli.plugins.marketplace import set_licence_key
        key, ok = QInputDialog.getText(
            self, "Licence key",
            f"Licence key for '{m.get('name')}'.\n\n"
            f"ELI does not process payments and cannot confirm a purchase — the key is "
            f"passed to the publisher's own server when downloading.")
        if ok and key.strip():
            set_licence_key(m["id"], key.strip())
            QMessageBox.information(self, "Marketplace", "Licence key saved.")

    def _quick_install_selected(self) -> None:
        """One click. Verification and scanning still happen — they just do not
        require the operator to drive them when there is nothing to decide."""
        m = self._selected_listing()
        if not m:
            return
        if m.get("kind") == "mcp":
            self._install_mcp(m)
            return
        from eli.plugins.marketplace import quick_install
        self._browse_status.setText(
            f"Verifying and scanning {m.get('name')} — nothing is written to disk "
            f"until that finishes…")
        self._run_async(lambda: quick_install(m), lambda r: self._after_quick(m, r))

    def _after_quick(self, listing: Dict[str, Any], result: Dict[str, Any]) -> None:
        if result.get("review_needed"):
            # Not a failure — just something the operator has to see.
            self._browse_status.setText(
                "Needs your decision: " + "; ".join(result["reasons"]))
            dlg = InstallReviewDialog(listing, result["preview"], parent=self)
            if dlg.exec() and dlg.approved:
                self._do_install(listing, allow_pip=dlg.allow_pip)
            return
        if not result.get("ok"):
            problems = (result.get("result") or {}).get("problems") or ["Install failed."]
            QMessageBox.warning(self, "Marketplace", "\n\n".join(problems))
            return

        self._browse_status.setText("Installed.")
        self._refresh_installed()
        pid = (result.get("result") or {}).get("plugin_id") or listing.get("id")
        notes = result.get("notes") or []
        note_text = ("\n\nWorth knowing:\n  · " + "\n  · ".join(notes)) if notes else ""
        enable = QMessageBox.question(
            self, "Installed",
            f"'{listing.get('name')}' matches the checksum in its listing, scanned "
            f"clean, and asks for no permissions.{note_text}\n\n"
            f"It is installed but switched OFF. Enable it now?")
        if enable == QMessageBox.StandardButton.Yes:
            try:
                from eli.plugins.manager import get_manager
                get_manager().enable(pid)
                self._refresh_installed()
            except Exception as exc:
                QMessageBox.warning(self, "Marketplace", f"Could not enable: {exc}")

    def _install_mcp(self, listing: Dict[str, Any]) -> None:
        """MCP servers install differently: there is no source for ELI to scan, so
        what gets checked is that the runtime exists and the server really answers."""
        from eli.plugins.mcp import network_caveat
        spec = listing.get("mcp") or {}
        proceed = QMessageBox.question(
            self, "Add MCP server",
            f"Add '{listing.get('name')}'?\n\n"
            f"Command: {spec.get('command', '?')} {' '.join(spec.get('args') or [])}\n\n"
            f"{network_caveat()}\n\n"
            f"ELI will check the required runtime is installed and that the server "
            f"answers before saving anything.")
        if proceed != QMessageBox.StandardButton.Yes:
            return
        from eli.plugins.marketplace import install_mcp
        self._browse_status.setText(f"Starting {listing.get('name')} to verify it…")
        self._run_async(lambda: install_mcp(listing), self._after_mcp)

    def _after_mcp(self, result: Dict[str, Any]) -> None:
        if not result.get("ok"):
            QMessageBox.warning(
                self, "MCP server",
                "\n\n".join(result.get("problems") or ["Could not add the server."]))
            self._browse_status.setText("MCP server not added.")
            return
        tools = ", ".join(t["name"] for t in (result.get("tools") or [])[:8]) or "none"
        QMessageBox.information(
            self, "MCP server",
            f"{result.get('response')}\n\nTools offered: {tools}")
        self._browse_status.setText("MCP server added.")
        self._refresh_mcp()

    def _inspect_selected(self) -> None:
        m = self._selected_listing()
        if not m:
            return
        from eli.plugins.marketplace import preview_install
        self._browse_status.setText(f"Downloading and scanning {m.get('name')}…")
        self._run_async(lambda: preview_install(m), lambda p: self._show_preview(m, p))

    def _show_preview(self, listing: Dict[str, Any], preview: Dict[str, Any]) -> None:
        self._browse_status.setText("Scan complete.")
        dlg = InstallReviewDialog(listing, preview, parent=self)
        if dlg.exec() and dlg.approved:
            self._do_install(listing, allow_pip=dlg.allow_pip)

    def _do_install(self, listing: Dict[str, Any], *, allow_pip: bool) -> None:
        from eli.plugins.marketplace import install
        res = install(listing, confirm=lambda _p: True, allow_pip=allow_pip)
        if res.get("ok"):
            QMessageBox.information(self, "Marketplace", res["response"])
            self._refresh_installed()
        else:
            QMessageBox.warning(self, "Marketplace",
                                "\n\n".join(res.get("problems") or ["Install failed."]))

    # ── installed ─────────────────────────────────────────────────────────────
    def _page_installed(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self._inst_table = QTableWidget(0, 5)
        self._inst_table.setHorizontalHeaderLabels(
            ["Plugin", "Version", "Enabled", "Verification", "Granted permissions"])
        self._inst_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._inst_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._inst_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._inst_table, 1)

        row = QHBoxLayout()
        for label, slot in (("Enable", self._enable), ("Disable", self._disable),
                            ("Rescan", self._rescan), ("Uninstall", self._uninstall)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        r = QPushButton("Refresh")
        r.clicked.connect(self._refresh_installed)
        row.addWidget(r)
        v.addLayout(row)
        return w

    def _refresh_installed(self) -> None:
        try:
            from eli.plugins.manager import get_manager, _plugins_dir
            from eli.plugins.permissions import store
            rows = get_manager().list_installed()
        except Exception as exc:
            log.debug(f"[MARKET] could not list installed plugins: {exc}", exc_info=True)
            return
        from pathlib import Path
        grants = store().all_grants()
        self._inst_table.setRowCount(len(rows))
        for r, p in enumerate(rows):
            pid = p["id"]
            integrity = "built-in"
            try:
                f = Path(_plugins_dir()) / pid / ".integrity.json"
                if f.is_file():
                    d = json.loads(f.read_text(encoding="utf-8"))
                    integrity = f"{d.get('status', '?')} · scan {d.get('scan_verdict', '?')}"
            except Exception:
                log.debug("[MARKET] unreadable integrity sidecar", exc_info=True)
            allowed = [c for c, g in (grants.get(pid) or {}).items()
                       if g.get("decision") == "allow_always"]
            for c, text in enumerate([pid, p.get("version", "?"),
                                      "yes" if p.get("enabled") else "no",
                                      integrity,
                                      ", ".join(allowed) or "none"]):
                self._inst_table.setItem(r, c, QTableWidgetItem(str(text)))
        self._inst_table.resizeColumnsToContents()
        self._inst_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.Stretch)

    def _selected_installed(self) -> Optional[str]:
        r = self._inst_table.currentRow()
        item = self._inst_table.item(r, 0) if r >= 0 else None
        return item.text() if item else None

    def _enable(self) -> None:
        pid = self._selected_installed()
        if not pid:
            return
        if QMessageBox.question(
                self, "Marketplace",
                f"Enable '{pid}'?\n\nIt will run inside ELI. It still has to ask before "
                f"using any permission.") != QMessageBox.StandardButton.Yes:
            return
        from eli.plugins.manager import get_manager
        get_manager().enable(pid)
        self._refresh_installed()

    def _disable(self) -> None:
        pid = self._selected_installed()
        if not pid:
            return
        from eli.plugins.manager import get_manager
        get_manager().disable(pid)
        self._refresh_installed()

    def _rescan(self) -> None:
        pid = self._selected_installed()
        if not pid:
            return
        from pathlib import Path
        from eli.plugins.manager import _plugins_dir
        from eli.plugins.security_scan import scan_file
        path = Path(_plugins_dir()) / pid / "plugin.py"
        if not path.is_file():
            QMessageBox.warning(self, "Marketplace", f"No source found for '{pid}'.")
            return
        res = scan_file(path, deep=True)
        ScanReportDialog(pid, res, parent=self).exec()

    def _uninstall(self) -> None:
        pid = self._selected_installed()
        if not pid:
            return
        if QMessageBox.question(
                self, "Marketplace",
                f"Uninstall '{pid}' and forget its permissions?") \
                != QMessageBox.StandardButton.Yes:
            return
        from eli.plugins.manager import get_manager
        from eli.plugins.permissions import store
        get_manager().uninstall(pid)
        store().revoke(pid)
        self._refresh_installed()
        self._refresh_permissions()

    # ── permissions ───────────────────────────────────────────────────────────
    def _page_permissions(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Every permission you have granted or refused. Revoking one means the plugin "
            "will be asked about again the next time it needs it."))
        self._perm_table = QTableWidget(0, 4)
        self._perm_table.setHorizontalHeaderLabels(["Plugin", "Permission", "Decision", "When"])
        self._perm_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._perm_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._perm_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._perm_table, 1)

        row = QHBoxLayout()
        rb = QPushButton("Revoke selected")
        rb.clicked.connect(self._revoke)
        row.addWidget(rb)
        ab = QPushButton("View activity log")
        ab.clicked.connect(self._show_audit)
        row.addWidget(ab)
        row.addStretch(1)
        r = QPushButton("Refresh")
        r.clicked.connect(self._refresh_permissions)
        row.addWidget(r)
        v.addLayout(row)
        return w

    def _refresh_permissions(self) -> None:
        from eli.plugins.permissions import store, describe
        grants = store().all_grants()
        rows = [(pid, cap, g.get("decision", "?"), g.get("at", ""))
                for pid, caps in grants.items() for cap, g in caps.items()]
        self._perm_table.setRowCount(len(rows))
        for r, (pid, cap, decision, at) in enumerate(rows):
            cells = [pid, describe(cap)["title"], decision.replace("_", " "), at]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if c == 2:
                    item.setForeground(Qt.GlobalColor.green if "allow" in decision
                                       else Qt.GlobalColor.red)
                if c == 1:
                    item.setData(Qt.ItemDataRole.UserRole, cap)
                self._perm_table.setItem(r, c, item)
        self._perm_table.resizeColumnsToContents()
        self._perm_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)

    def _revoke(self) -> None:
        r = self._perm_table.currentRow()
        if r < 0:
            return
        pid = self._perm_table.item(r, 0).text()
        cap = self._perm_table.item(r, 1).data(Qt.ItemDataRole.UserRole)
        from eli.plugins.permissions import store
        store().revoke(pid, cap)
        self._refresh_permissions()

    def _show_audit(self) -> None:
        from eli.plugins.permissions import store
        entries = store().audit_tail(400)
        dlg = QDialog(self)
        dlg.setWindowTitle("Plugin permission activity")
        dlg.setMinimumSize(640, 420)
        lay = QVBoxLayout(dlg)
        te = QTextEdit()
        te.setReadOnly(True)
        te.setStyleSheet("font-family:monospace;font-size:11px;")
        te.setPlainText("\n".join(
            f"{e.get('at')}  {e.get('plugin'):20s} {e.get('capability'):18s} "
            f"{e.get('decision')}" for e in entries) or "No activity recorded yet.")
        lay.addWidget(te)
        dlg.exec()

    # ── MCP servers ───────────────────────────────────────────────────────────
    def _page_mcp(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "<b>MCP servers run as their own programs alongside ELI.</b><br>"
            "<span style='color:#bf616a'>ELI's offline switch cannot stop them reaching "
            "the internet, and ELI cannot see what they send.</span> "
            "<span style='color:#6c7086'>That is how MCP works, not a fault in ELI. What "
            "ELI does guarantee is that a server here actually starts and answers — it is "
            "verified with a real handshake before being saved.</span>"))
        self._mcp_table = QTableWidget(0, 5)
        self._mcp_table.setHorizontalHeaderLabels(
            ["Server", "Command", "Enabled", "Verified", "Tools"])
        self._mcp_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._mcp_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._mcp_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._mcp_table, 1)

        row = QHBoxLayout()
        for label, slot in (("Enable", lambda: self._mcp_enable(True)),
                            ("Disable", lambda: self._mcp_enable(False)),
                            ("Re-check", self._mcp_doctor),
                            ("Remove", self._mcp_remove)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        r = QPushButton("Refresh")
        r.clicked.connect(self._refresh_mcp)
        row.addWidget(r)
        v.addLayout(row)

        self._mcp_status = QLabel("")
        self._mcp_status.setWordWrap(True)
        self._mcp_status.setStyleSheet(f"color:{_DIM};")
        v.addWidget(self._mcp_status)
        return w

    def _refresh_mcp(self) -> None:
        try:
            from eli.plugins.mcp import config_path, list_servers
            servers = list_servers()
        except Exception as exc:
            log.debug(f"[MARKET] MCP unavailable: {exc}", exc_info=True)
            return
        self._mcp_table.setRowCount(len(servers))
        for r, srv in enumerate(servers):
            cmd = srv.get("url") or " ".join(
                [str(srv.get("command", ""))] + [str(a) for a in (srv.get("args") or [])])
            cells = [srv["id"], cmd, "yes" if srv.get("enabled") else "no",
                     "yes" if srv.get("verified") else "no",
                     str(len(srv.get("tools") or []))]
            for c, text in enumerate(cells):
                self._mcp_table.setItem(r, c, QTableWidgetItem(text))
        self._mcp_status.setText(f"Config: {config_path()}")

    def _selected_mcp(self) -> Optional[str]:
        r = self._mcp_table.currentRow()
        item = self._mcp_table.item(r, 0) if r >= 0 else None
        return item.text() if item else None

    def _mcp_enable(self, enabled: bool) -> None:
        sid = self._selected_mcp()
        if not sid:
            return
        from eli.plugins.mcp import network_caveat, set_enabled
        if enabled and QMessageBox.question(
                self, "Enable MCP server",
                f"Enable '{sid}'?\n\n{network_caveat()}") \
                != QMessageBox.StandardButton.Yes:
            return
        set_enabled(sid, enabled)
        self._refresh_mcp()

    def _mcp_remove(self) -> None:
        sid = self._selected_mcp()
        if not sid:
            return
        from eli.plugins.mcp import remove_server
        remove_server(sid)
        self._refresh_mcp()

    def _mcp_doctor(self) -> None:
        from eli.plugins.mcp import doctor
        self._mcp_status.setText("Checking every configured server…")
        self._run_async(lambda: doctor(), self._show_doctor)

    def _show_doctor(self, report: Dict[str, Any]) -> None:
        lines = [report.get("summary", "")]
        for srv in report.get("servers", []):
            state = (f"<span style='color:{_OK}'>ok, {srv['tools']} tool(s)</span>"
                     if srv["ok"] else
                     f"<span style='color:{_BAD}'>{srv['problem']}</span>")
            lines.append(f"<b>{srv['id']}</b>: {state}")
        self._mcp_status.setText("<br>".join(lines))
        self._mcp_status.setTextFormat(Qt.TextFormat.RichText)
        self._refresh_mcp()

    # ── registries ────────────────────────────────────────────────────────────
    def _page_registries(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Community registries this machine will install from. Adding one is a trust "
            "decision: its listings become installable. ELI ships with none — the built-in "
            "entry is just ELI's own bundled plugins."))

        home_row = QHBoxLayout()
        home_row.addWidget(QLabel("Marketplace website:"))
        self._home_edit = QLineEdit()
        self._home_edit.setPlaceholderText(
            "https://…  (ELI ships no default — the marketplace is the community's)")
        home_row.addWidget(self._home_edit, 1)
        save_home = QPushButton("Save")
        save_home.clicked.connect(self._save_home)
        home_row.addWidget(save_home)
        self._open_home = QPushButton("Open in browser")
        self._open_home.setToolTip("Discovery only — a website can never install "
                                   "anything. It gives you a source URL to add here.")
        self._open_home.clicked.connect(self._open_marketplace)
        home_row.addWidget(self._open_home)
        v.addLayout(home_row)
        self._reg_table = QTableWidget(0, 4)
        self._reg_table.setHorizontalHeaderLabels(["Id", "Label", "URL", "Enabled"])
        self._reg_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._reg_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._reg_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self._reg_table, 1)

        form = QHBoxLayout()
        self._reg_id = QLineEdit()
        self._reg_id.setPlaceholderText("id")
        self._reg_url = QLineEdit()
        self._reg_url.setPlaceholderText("https://…/index.json")
        form.addWidget(self._reg_id)
        form.addWidget(self._reg_url, 1)
        add = QPushButton("Add source")
        add.clicked.connect(self._add_registry)
        form.addWidget(add)
        rm = QPushButton("Remove")
        rm.clicked.connect(self._remove_registry)
        form.addWidget(rm)
        v.addLayout(form)
        return w

    def _save_home(self) -> None:
        from eli.plugins.marketplace import set_marketplace_home
        res = set_marketplace_home(self._home_edit.text())
        if not res["ok"]:
            QMessageBox.warning(self, "Marketplace", "\n".join(res["problems"]))
            return
        if res.get("warnings"):
            QMessageBox.warning(self, "Marketplace", "\n".join(res["warnings"]))
        self._refresh_registries()

    def _open_marketplace(self) -> None:
        from eli.plugins.marketplace import marketplace_home
        url = marketplace_home()
        if not url:
            QMessageBox.information(
                self, "Marketplace",
                "No marketplace website is set.\n\nELI ships without one on purpose — "
                "the marketplace belongs to the community, not to ELI's author. Paste "
                "the address of one you trust above, or add a registry URL directly.")
            return
        import webbrowser
        webbrowser.open(url)

    def _refresh_registries(self) -> None:
        from eli.plugins.marketplace import list_registries, marketplace_home
        self._home_edit.setText(marketplace_home())
        regs = list_registries()
        self._reg_table.setRowCount(len(regs))
        for r, reg in enumerate(regs):
            for c, text in enumerate([reg["id"], reg.get("label", ""), reg.get("url", "—"),
                                      "yes" if reg.get("enabled", True) else "no"]):
                self._reg_table.setItem(r, c, QTableWidgetItem(str(text)))

    def _add_registry(self) -> None:
        from eli.plugins.marketplace import add_registry
        rid = self._reg_id.text().strip()
        url = self._reg_url.text().strip()
        if QMessageBox.question(
                self, "Add source",
                f"Add '{rid}' as a plugin source?\n\n{url}\n\n"
                f"Anything listed there becomes installable on this machine. Only add "
                f"sources you trust.") != QMessageBox.StandardButton.Yes:
            return
        res = add_registry(rid, url)
        if not res["ok"]:
            QMessageBox.warning(self, "Add source", "\n".join(res["problems"]))
            return
        if res.get("warnings"):
            QMessageBox.warning(self, "Add source", "\n".join(res["warnings"]))
        self._reg_id.clear()
        self._reg_url.clear()
        self._refresh_registries()

    def _remove_registry(self) -> None:
        r = self._reg_table.currentRow()
        if r < 0:
            return
        from eli.plugins.marketplace import remove_registry
        res = remove_registry(self._reg_table.item(r, 0).text())
        if not res["ok"]:
            QMessageBox.warning(self, "Sources", "\n".join(res["problems"]))
        self._refresh_registries()


class ScanReportDialog(QDialog):
    """Full malware-scan output for one plugin."""

    def __init__(self, plugin_id: str, scan: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Security scan — {plugin_id}")
        self.setMinimumSize(680, 480)
        v = QVBoxLayout(self)
        colour = {"clean": _OK, "suspicious": _WARN, "malicious": _BAD}.get(
            scan.get("verdict"), _DIM)
        v.addWidget(QLabel(
            f"<div style='font-size:15px;color:{colour}'><b>"
            f"{str(scan.get('verdict', '?')).upper()}</b> — risk score "
            f"{scan.get('score', 0)}/100</div>"))
        summary = QLabel(scan.get("summary", ""))
        summary.setWordWrap(True)
        v.addWidget(summary)

        te = QTextEdit()
        te.setReadOnly(True)
        html = ["<h4>Findings</h4>"]
        if not scan.get("findings"):
            html.append("<p>No findings.</p>")
        for f in scan.get("findings", []):
            c = _RISK.get(f["severity"], _DIM)
            line = f" (line {f['line']})" if f.get("line") else ""
            html.append(f"<p><b style='color:{c}'>[{f['severity']}]</b> "
                        f"{f['title']}{line}<br>"
                        f"<span style='color:{_DIM}'>{f['detail']} — {f['engine']}</span></p>")
        html.append("<h4>Engines</h4><ul>")
        for name, info in (scan.get("engines") or {}).items():
            state = (f"ran, {info['findings']} finding(s)" if info.get("ran")
                     else f"<span style='color:{_WARN}'>did not run — "
                          f"{info.get('error', 'unavailable')}</span>")
            html.append(f"<li>{name}: {state}</li>")
        html.append("</ul>")
        te.setHtml("".join(html))
        v.addWidget(te, 1)

        b = QPushButton("Close")
        b.clicked.connect(self.accept)
        v.addWidget(b)


class InstallReviewDialog(QDialog):
    """The decision point: everything ELI checked, then install or don't."""

    def __init__(self, listing: Dict[str, Any], preview: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.approved = False
        self.allow_pip = False
        self._preview = preview
        self.setWindowTitle(f"Install {listing.get('name', '?')}?")
        self.setMinimumSize(620, 520)
        self._build(listing, preview)

    def _build(self, listing: Dict[str, Any], preview: Dict[str, Any]) -> None:
        v = QVBoxLayout(self)
        scan = preview.get("scan") or {}
        blocked = not preview.get("ok")

        verdict = scan.get("verdict", "unknown")
        colour = {"clean": _OK, "suspicious": _WARN, "malicious": _BAD}.get(verdict, _BAD)
        head = QLabel(f"<div style='font-size:16px'><b>{listing.get('name')}</b> "
                      f"<span style='color:{_DIM}'>{listing.get('version', '')} by "
                      f"{listing.get('author', 'unknown')}</span></div>")
        v.addWidget(head)

        te = QTextEdit()
        te.setReadOnly(True)
        html: List[str] = []

        if blocked:
            html.append(f"<div style='color:{_BAD};font-size:14px'><b>ELI refused this "
                        f"plugin at the '{preview.get('stage')}' stage.</b></div>")
            for p in preview.get("problems", []):
                html.append(f"<p style='color:{_BAD}'>• {p}</p>")
        else:
            html.append(f"<p><b>Malware scan:</b> <span style='color:{colour}'>"
                        f"{verdict.upper()}</span> ({scan.get('score', 0)}/100) — "
                        f"{scan.get('summary', '')}</p>")
            html.append(f"<p><b>Integrity:</b> {preview.get('integrity_summary', '')}</p>")

            perms = preview.get("permissions") or []
            if perms:
                html.append("<p><b>It will be able to ask for:</b></p><ul>")
                for d in perms:
                    html.append(f"<li><span style='color:{_RISK.get(d['risk'], _BAD)}'>"
                                f"{d['title']}</span> — {d['detail']}<br>"
                                f"<span style='color:{_DIM}'>{d['why_risky']}</span></li>")
                html.append("</ul>")
                html.append(f"<p style='color:{_DIM}'>Installing does not grant any of "
                            f"these. It will ask you, one at a time, the first time it "
                            f"needs each one.</p>")
            else:
                html.append("<p>Requests no special permissions.</p>")

            if preview.get("pip"):
                html.append(f"<p style='color:{_WARN}'><b>Wants to install "
                            f"{len(preview['pip'])} package(s) from PyPI:</b> "
                            f"{', '.join(preview['pip'])}. Package installers run their own "
                            f"code outside anything ELI can gate.</p>")

            for w in preview.get("warnings", []):
                html.append(f"<p style='color:{_WARN}'>⚠ {w}</p>")

            if scan.get("findings"):
                html.append("<h4>Scan findings</h4>")
                for f in scan["findings"][:15]:
                    c = _RISK.get(f["severity"], _DIM)
                    line = f" (line {f['line']})" if f.get("line") else ""
                    html.append(f"<p><b style='color:{c}'>[{f['severity']}]</b> "
                                f"{f['title']}{line}<br><span style='color:{_DIM}'>"
                                f"{f['detail']}</span></p>")

        te.setHtml("".join(html))
        v.addWidget(te, 1)

        row = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        cancel.setDefault(True)
        row.addWidget(cancel)
        row.addStretch(1)

        if not blocked:
            if preview.get("pip"):
                pip_btn = QPushButton("Install, including PyPI packages")
                pip_btn.clicked.connect(lambda: self._approve(True))
                row.addWidget(pip_btn)
            ok = QPushButton("Install")
            ok.clicked.connect(lambda: self._approve(False))
            row.addWidget(ok)
        v.addLayout(row)

    def _approve(self, allow_pip: bool) -> None:
        self.approved = True
        self.allow_pip = allow_pip
        self.accept()


__all__ = ["MarketplaceTab", "InstallReviewDialog", "ScanReportDialog"]
