"""ELI MKXI — Advanced Settings dialog panel."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from eli.gui.panels._qt import (
    QAbstractItemView, QCheckBox, QDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QTimer, QVBoxLayout, QWidget, Qt, pyqtSignal,
)
from eli.gui.panels.agent_wizard import AgentEditDialog


class AdvancedSettingsDialog(QDialog):
    """
    Comprehensive settings dialog with four tabs:
      1. Agents   — list, edit, enable/disable all bus agents
      2. Models   — list installed GGUF + Ollama models
      3. Plugins  — install, enable/disable, uninstall
      4. Upgrade  — self-improvement cycle + capability manifest
    """
    # Thread-safe signals — worker threads emit these; Qt delivers them on the main thread
    _plugin_log_sig   = pyqtSignal(str)
    _plugin_refresh_sig = pyqtSignal()
    _upgrade_log_sig  = pyqtSignal(str)

    def __init__(self, parent=None, start_tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("\u2699\ufe0f Advanced Settings")
        self.setMinimumSize(780, 560)
        self._agent_overrides: dict = {}
        self._build_ui()
        # Connect thread-safe signals to actual GUI slots
        self._plugin_log_sig.connect(self._do_log_plugin,   Qt.ConnectionType.QueuedConnection)
        self._plugin_refresh_sig.connect(self._populate_plugins_table, Qt.ConnectionType.QueuedConnection)
        self._upgrade_log_sig.connect(self._do_log_upgrade, Qt.ConnectionType.QueuedConnection)
        # Jump to the requested tab
        if 0 <= start_tab < self.inner_tabs.count():
            self.inner_tabs.setCurrentIndex(start_tab)

    # ── UI skeleton ────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        self.inner_tabs = QTabWidget()
        root.addWidget(self.inner_tabs)

        self.inner_tabs.addTab(self._build_agents_tab(),  "\U0001f916 Agents")
        self.inner_tabs.addTab(self._build_models_tab(),  "\U0001f9e0 Models")
        self.inner_tabs.addTab(self._build_plugins_tab(), "\U0001f50c Plugins")
        self.inner_tabs.addTab(self._build_upgrade_tab(), "\U0001f504 Self-Upgrade")

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn)

    # ── Agents tab ─────────────────────────────────────────────────────────────
    def _build_agents_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel("All registered ELI agents. Edit timeout, description, persona, or disable individual agents.")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.agents_table = QTableWidget()
        self.agents_table.setColumnCount(5)
        self.agents_table.setHorizontalHeaderLabels(
            ["Name", "Description", "Timeout (s)", "Enabled", "Actions"]
        )
        self.agents_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.agents_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.agents_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.agents_table)

        self._populate_agents_table()

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("\U0001f504 Refresh")
        refresh_btn.clicked.connect(self._populate_agents_table)
        btn_row.addWidget(refresh_btn)
        save_btn = QPushButton("\U0001f4be Apply Changes")
        save_btn.clicked.connect(self._apply_agent_changes)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return w

    def _get_agent_list(self) -> list:
        agents = []
        try:
            from eli.cognition.agent_bus import _ALL_AGENTS
            for ag in _ALL_AGENTS:
                overrides = self._agent_overrides.get(ag.name, {})
                agents.append({
                    "name": ag.name,
                    "class": type(ag).__name__,
                    "description": overrides.get("description", getattr(ag, "__doc__", "") or ""),
                    "timeout_s": overrides.get("timeout_s", getattr(ag, "timeout_s", 5.0)),
                    "enabled": overrides.get("enabled", getattr(ag, "_enabled", True)),
                    "persona": overrides.get("persona", ""),
                })
        except Exception as e:
            agents.append({
                "name": f"(unavailable: {e})", "class": "", "description": "",
                "timeout_s": 5.0, "enabled": True, "persona": "",
            })
        return agents

    def _populate_agents_table(self):
        agents = self._get_agent_list()
        self.agents_table.setRowCount(len(agents))
        self._agent_rows = agents

        for row, ag in enumerate(agents):
            self.agents_table.setItem(row, 0, QTableWidgetItem(ag["name"]))
            desc = (ag["description"] or "").strip().replace("\n", " ")[:80]
            self.agents_table.setItem(row, 1, QTableWidgetItem(desc))
            self.agents_table.setItem(row, 2, QTableWidgetItem(str(ag["timeout_s"])))

            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.setContentsMargins(8, 0, 8, 0)
            chk = QCheckBox()
            chk.setChecked(ag.get("enabled", True))
            chk.setProperty("agent_name", ag["name"])
            chk_layout.addWidget(chk)
            self.agents_table.setCellWidget(row, 3, chk_widget)

            edit_btn = QPushButton("\u270f\ufe0f Edit")
            edit_btn.setProperty("agent_name", ag["name"])
            edit_btn.clicked.connect(lambda _, r=row, a=ag: self._edit_agent(r, a))
            self.agents_table.setCellWidget(row, 4, edit_btn)

        self.agents_table.resizeRowsToContents()

    def _edit_agent(self, row: int, agent_info: dict):
        dlg = AgentEditDialog(agent_info, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            result = dlg.get_result()
            self._agent_overrides[agent_info["name"]] = result
            self.agents_table.item(row, 2).setText(str(result["timeout_s"]))
            desc = (result["description"] or "").replace("\n", " ")[:80]
            self.agents_table.item(row, 1).setText(desc)
            chk_w = self.agents_table.cellWidget(row, 3)
            if chk_w:
                chk = chk_w.findChild(QCheckBox)
                if chk:
                    chk.setChecked(result["enabled"])

    def _apply_agent_changes(self):
        try:
            from eli.cognition.agent_bus import _ALL_AGENTS
            applied = []
            for ag in _ALL_AGENTS:
                overrides = self._agent_overrides.get(ag.name, {})
                if overrides:
                    if "timeout_s" in overrides:
                        ag.timeout_s = overrides["timeout_s"]
                    if "enabled" in overrides:
                        ag._enabled = overrides["enabled"]
                    applied.append(ag.name)
            for row in range(self.agents_table.rowCount()):
                chk_w = self.agents_table.cellWidget(row, 3)
                if chk_w:
                    chk = chk_w.findChild(QCheckBox)
                    if chk:
                        name = chk.property("agent_name")
                        for ag in _ALL_AGENTS:
                            if ag.name == name:
                                ag._enabled = chk.isChecked()
            QMessageBox.information(
                self, "Agents",
                f"Applied overrides to: {', '.join(applied) or 'none'}.\nChanges are live until restart."
            )
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not apply changes: {e}")

    # ── Models tab ─────────────────────────────────────────────────────────────
    def _build_models_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel("Installed GGUF models and available Ollama models.")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.models_table = QTableWidget()
        self.models_table.setColumnCount(4)
        self.models_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Path / Tag"])
        self.models_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.models_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.models_table)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("\U0001f504 Refresh Models")
        refresh_btn.clicked.connect(self._populate_models_table)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._populate_models_table()
        return w

    def _populate_models_table(self):
        rows = []
        try:
            from eli.gui.eli_pro_audio_gui_MKI import discover_gguf_models
            models = discover_gguf_models()
            for m in models:
                size_str = f"{m.get('size_gb', 0.0):.2f} GB"
                rows.append((m.get("name", "?"), "GGUF", size_str, m.get("path", "")))
        except Exception:
            pass
        try:
            from eli.gui.eli_pro_audio_gui_MKI import OllamaModelManager
            host = "http://localhost:11434"
            om = OllamaModelManager()
            ollama_names = om.list_models(host)
            for name in ollama_names:
                rows.append((name, "Ollama", "\u2014", host))
        except Exception:
            pass

        self.models_table.setRowCount(len(rows))
        for i, (name, mtype, size, path) in enumerate(rows):
            self.models_table.setItem(i, 0, QTableWidgetItem(name))
            self.models_table.setItem(i, 1, QTableWidgetItem(mtype))
            self.models_table.setItem(i, 2, QTableWidgetItem(size))
            self.models_table.setItem(i, 3, QTableWidgetItem(str(path)))
        self.models_table.resizeRowsToContents()

    # ── Plugins tab ────────────────────────────────────────────────────────────
    def _build_plugins_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel("Manage ELI plugins. Install from registry, enable, disable, or uninstall.")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        self.plugins_table = QTableWidget()
        self.plugins_table.setColumnCount(5)
        self.plugins_table.setHorizontalHeaderLabels(
            ["ID", "Version", "Status", "Description", "Actions"]
        )
        self.plugins_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.plugins_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.plugins_table)

        self.plugin_log = QTextEdit()
        self.plugin_log.setReadOnly(True)
        self.plugin_log.setFixedHeight(90)
        self.plugin_log.setPlaceholderText("Plugin operations log\u2026")
        layout.addWidget(self.plugin_log)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("\U0001f504 Refresh")
        refresh_btn.clicked.connect(self._populate_plugins_table)
        btn_row.addWidget(refresh_btn)
        registry_btn = QPushButton("\U0001f310 Fetch Registry")
        registry_btn.clicked.connect(self._fetch_registry)
        btn_row.addWidget(registry_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._populate_plugins_table()
        return w

    def _get_plugin_manager(self):
        try:
            from eli.plugins.manager import get_manager
            return get_manager()
        except Exception as e:
            self._log_plugin(f"Plugin manager unavailable: {e}")
            return None

    def _log_plugin(self, msg: str):
        self._plugin_log_sig.emit(str(msg))

    def _do_log_plugin(self, msg: str):
        if hasattr(self, "plugin_log"):
            self.plugin_log.append(msg)

    def _populate_plugins_table(self):
        mgr = self._get_plugin_manager()
        if mgr is None:
            self.plugins_table.setRowCount(0)
            return

        installed = {p["id"]: p for p in mgr.list_installed()}
        available = mgr.list_available()

        all_ids = {e["id"] for e in available}
        for pid in installed:
            all_ids.add(pid)

        rows = []
        for entry in available:
            pid = entry["id"]
            inst = installed.get(pid)
            status = "installed+enabled" if (inst and inst.get("enabled")) else \
                     "installed" if inst else "available"
            rows.append({
                "id": pid,
                "version": entry.get("version", "?"),
                "status": status,
                "description": entry.get("description", ""),
                "installed": inst is not None,
                "enabled": inst.get("enabled", False) if inst else False,
            })

        self.plugins_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.plugins_table.setItem(i, 0, QTableWidgetItem(row["id"]))
            self.plugins_table.setItem(i, 1, QTableWidgetItem(row["version"]))
            self.plugins_table.setItem(i, 2, QTableWidgetItem(row["status"]))
            self.plugins_table.setItem(i, 3, QTableWidgetItem(row["description"][:60]))

            btn_w = QWidget()
            btn_l = QHBoxLayout(btn_w)
            btn_l.setContentsMargins(4, 2, 4, 2)
            btn_l.setSpacing(4)

            if not row["installed"]:
                inst_btn = QPushButton("\u2b07 Install")
                inst_btn.clicked.connect(lambda _, pid=row["id"]: self._install_plugin(pid))
                btn_l.addWidget(inst_btn)
            else:
                if row["enabled"]:
                    dis_btn = QPushButton("\u23f8 Disable")
                    dis_btn.clicked.connect(lambda _, pid=row["id"]: self._disable_plugin(pid))
                    btn_l.addWidget(dis_btn)
                else:
                    en_btn = QPushButton("\u25b6 Enable")
                    en_btn.clicked.connect(lambda _, pid=row["id"]: self._enable_plugin(pid))
                    btn_l.addWidget(en_btn)
                rm_btn = QPushButton("\U0001f5d1 Remove")
                rm_btn.clicked.connect(lambda _, pid=row["id"]: self._uninstall_plugin(pid))
                btn_l.addWidget(rm_btn)

            self.plugins_table.setCellWidget(i, 4, btn_w)

        self.plugins_table.resizeRowsToContents()

    def _install_plugin(self, plugin_id: str):
        self._log_plugin(f"Installing {plugin_id}\u2026")
        def worker():
            mgr = self._get_plugin_manager()
            if mgr:
                result = mgr.install(plugin_id, progress_cb=self._log_plugin)
                if result.get("ok", True):
                    self._log_plugin(f"\u2705 {plugin_id} installed.")
                else:
                    self._log_plugin(f"\u274c {plugin_id}: {result.get('error', 'unknown error')}")
            self._plugin_refresh_sig.emit()
        threading.Thread(target=worker, daemon=True).start()

    def _enable_plugin(self, plugin_id: str):
        mgr = self._get_plugin_manager()
        if mgr:
            mgr.enable(plugin_id)
            self._log_plugin(f"\u2705 {plugin_id} enabled.")
            self._populate_plugins_table()

    def _disable_plugin(self, plugin_id: str):
        mgr = self._get_plugin_manager()
        if mgr:
            mgr.disable(plugin_id)
            self._log_plugin(f"\u23f8 {plugin_id} disabled.")
            self._populate_plugins_table()

    def _uninstall_plugin(self, plugin_id: str):
        reply = QMessageBox.question(
            self, "Uninstall Plugin",
            f"Remove plugin '{plugin_id}'? This will delete its files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            mgr = self._get_plugin_manager()
            if mgr:
                mgr.uninstall(plugin_id)
                self._log_plugin(f"\U0001f5d1 {plugin_id} uninstalled.")
                self._populate_plugins_table()

    def _fetch_registry(self):
        self._log_plugin("Fetching plugin registry\u2026")
        def worker():
            mgr = self._get_plugin_manager()
            if mgr:
                try:
                    mgr.refresh_registry()
                    self._log_plugin("\u2705 Registry refreshed.")
                except Exception as e:
                    self._log_plugin(f"\u274c Registry fetch error: {e}")
            self._plugin_refresh_sig.emit()
        threading.Thread(target=worker, daemon=True).start()

    # ── Self-Upgrade tab ───────────────────────────────────────────────────────
    def _build_upgrade_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        lbl = QLabel(
            "Self-upgrade tools: run improvement cycle, update capability manifest, "
            "view improvement proposals, and apply system updates."
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        status_group = QGroupBox("System Status")
        status_layout = QFormLayout(status_group)
        self.upgrade_agent_status = QLabel("Loading\u2026")
        status_layout.addRow("Agent Bus:", self.upgrade_agent_status)
        self.upgrade_plugin_status = QLabel("Loading\u2026")
        status_layout.addRow("Plugins:", self.upgrade_plugin_status)
        self.upgrade_memory_status = QLabel("Loading\u2026")
        status_layout.addRow("Memory:", self.upgrade_memory_status)
        layout.addWidget(status_group)

        actions_group = QGroupBox("Actions")
        actions_layout = QGridLayout(actions_group)

        cycle_btn = QPushButton("\U0001f504 Run Self-Improvement Cycle")
        cycle_btn.setToolTip("Analyze recent failures and generate improvement proposals")
        cycle_btn.clicked.connect(self._run_improvement_cycle)
        actions_layout.addWidget(cycle_btn, 0, 0)

        manifest_btn = QPushButton("\U0001f4cb Update Capability Manifest")
        manifest_btn.setToolTip("Scan executor and plugins and regenerate capability_manifest.json")
        manifest_btn.clicked.connect(self._update_capability_manifest)
        actions_layout.addWidget(manifest_btn, 0, 1)

        persona_btn = QPushButton("\U0001f9ec Refresh Persona")
        persona_btn.setToolTip("Re-derive ELI's persona from memory and self-model")
        persona_btn.clicked.connect(self._refresh_persona)
        actions_layout.addWidget(persona_btn, 1, 0)

        kg_btn = QPushButton("\U0001f5fa Rebuild Knowledge Graph")
        kg_btn.setToolTip("Re-extract entity triples from all stored memories")
        kg_btn.clicked.connect(self._rebuild_kg)
        actions_layout.addWidget(kg_btn, 1, 1)

        faiss_btn = QPushButton("\U0001f522 Rebuild FAISS Index")
        faiss_btn.setToolTip("Re-vectorize all memories in the FAISS index")
        faiss_btn.clicked.connect(self._rebuild_faiss)
        actions_layout.addWidget(faiss_btn, 2, 0)

        layout.addWidget(actions_group)

        self.upgrade_log = QTextEdit()
        self.upgrade_log.setReadOnly(True)
        self.upgrade_log.setPlaceholderText("Upgrade output will appear here\u2026")
        layout.addWidget(self.upgrade_log)

        QTimer.singleShot(200, self._refresh_upgrade_status)
        return w

    def _log_upgrade(self, msg: str):
        self._upgrade_log_sig.emit(str(msg))

    def _do_log_upgrade(self, msg: str):
        if hasattr(self, "upgrade_log"):
            self.upgrade_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _refresh_upgrade_status(self):
        try:
            from eli.cognition.agent_bus import _ALL_AGENTS
            enabled = sum(1 for a in _ALL_AGENTS if getattr(a, "_enabled", True))
            self.upgrade_agent_status.setText(f"{enabled}/{len(_ALL_AGENTS)} agents active")
        except Exception as e:
            self.upgrade_agent_status.setText(f"unavailable ({e})")

        try:
            from eli.plugins.manager import get_manager
            mgr = get_manager()
            inst = mgr.list_installed()
            enabled_plugins = [p for p in inst if p.get("enabled")]
            self.upgrade_plugin_status.setText(f"{len(enabled_plugins)}/{len(inst)} enabled")
        except Exception as e:
            self.upgrade_plugin_status.setText(f"unavailable ({e})")

        try:
            import sqlite3
            from eli.core.paths import user_db_path
            conn = sqlite3.connect(str(user_db_path()))
            mc = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            conn.close()
            self.upgrade_memory_status.setText(f"{mc} memories stored")
        except Exception as e:
            self.upgrade_memory_status.setText(f"unavailable ({e})")

    def _run_improvement_cycle(self):
        self._log_upgrade("Starting self-improvement cycle\u2026")
        def worker():
            try:
                from eli.runtime.self_improvement import SelfImprovementEngine
                eng = SelfImprovementEngine()
                result = eng.analyze_and_improve()
                proposals = result.get("improvements", []) if isinstance(result, dict) else list(result or [])
                if proposals:
                    for p in proposals[:5]:
                        desc = p.get("description", str(p))[:120] if isinstance(p, dict) else str(p)[:120]
                        self._log_upgrade(f"  \U0001f4a1 {desc}")
                    self._log_upgrade(f"\u2705 Cycle complete. {len(proposals)} proposal(s) generated.")
                else:
                    self._log_upgrade("\u2705 Cycle complete. No new proposals.")
            except Exception as e:
                self._log_upgrade(f"\u274c Cycle error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _update_capability_manifest(self):
        self._log_upgrade("Updating capability manifest\u2026")
        def worker():
            try:
                from eli.tools.registry.capability_updater import update_capability_manifest
                update_capability_manifest()
                self._log_upgrade("\u2705 Capability manifest updated.")
            except Exception as e:
                try:
                    import subprocess, sys
                    root = Path(__file__).resolve().parents[3]
                    result = subprocess.run(
                        [sys.executable, str(root / "auto_update.py"), "--dry-run"],
                        capture_output=True, text=True, timeout=30
                    )
                    self._log_upgrade(result.stdout[-500:] if result.stdout else f"\u274c {e}")
                except Exception as e2:
                    self._log_upgrade(f"\u274c {e} / {e2}")
        threading.Thread(target=worker, daemon=True).start()

    def _refresh_persona(self):
        self._log_upgrade("Refreshing persona overlay\u2026")
        def worker():
            try:
                from eli.cognition.persona_updater import update_persona_overlay
                update_persona_overlay()
                self._log_upgrade("\u2705 Persona refreshed.")
            except Exception as e:
                self._log_upgrade(f"\u274c Persona refresh error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_kg(self):
        self._log_upgrade("Rebuilding knowledge graph from memories\u2026")
        def worker():
            try:
                from eli.memory.knowledge_graph import get_knowledge_graph, reset_knowledge_graph
                import sqlite3
                from eli.core.paths import user_db_path
                reset_knowledge_graph()
                kg = get_knowledge_graph()
                conn = sqlite3.connect(str(user_db_path()))
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT COALESCE(text, content, '') AS text, COALESCE(source,'user') AS source "
                    "FROM memories WHERE COALESCE(text,content,'') != ''"
                ).fetchall()
                conn.close()
                ok = 0
                for row in rows:
                    kg.extract_from_memory(row["text"], source=row["source"])
                    ok += 1
                stats = kg.stats()
                self._log_upgrade(
                    f"\u2705 KG rebuilt from {ok} memories \u2192 {stats['entities']} entities, "
                    f"{stats['relations']} relations."
                )
            except Exception as e:
                self._log_upgrade(f"\u274c KG rebuild error: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def _rebuild_faiss(self):
        self._log_upgrade("Rebuilding FAISS vector index (full) \u2014 this may take a minute\u2026")
        def worker():
            try:
                from eli.memory import rebuild_vector_index_from_search_db
                result = rebuild_vector_index_from_search_db()
                if result.get("ok"):
                    self._log_upgrade(
                        "\u2705 FAISS rebuild complete: "
                        f"{result.get('indexed', 0)}/{result.get('source_count', 0)} vectors indexed "
                        f"({result.get('faiss_index_path', 'unknown index')})"
                    )
                else:
                    self._log_upgrade(f"\u274c FAISS rebuild failed: {result.get('error', result)}")
            except Exception as e:
                self._log_upgrade(f"\u274c FAISS rebuild error: {e}")
        threading.Thread(target=worker, daemon=True).start()
