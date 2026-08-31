"""ELI v2.0 — Agent edit dialog panel."""
from __future__ import annotations

from eli.gui.panels._qt import (
    QCheckBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLineEdit, QPushButton, QTextEdit, QVBoxLayout,
)


class AgentEditDialog(QDialog):
    """Edit an individual agent's metadata and persona."""

    def __init__(self, agent_info: dict, parent=None):
        super().__init__(parent)
        self.agent_info = dict(agent_info)
        self.setWindowTitle(f"Edit Agent: {agent_info.get('name', 'Unknown')}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit(self.agent_info.get("name", ""))
        self.name_edit.setReadOnly(True)  # class name is fixed
        form.addRow("Name:", self.name_edit)

        self.desc_edit = QTextEdit()
        self.desc_edit.setPlainText(self.agent_info.get("description", ""))
        self.desc_edit.setFixedHeight(80)
        form.addRow("Description:", self.desc_edit)

        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.5, 60.0)
        self.timeout_spin.setSingleStep(0.5)
        self.timeout_spin.setValue(float(self.agent_info.get("timeout_s", 5.0)))
        form.addRow("Timeout (s):", self.timeout_spin)

        self.persona_edit = QTextEdit()
        self.persona_edit.setPlainText(self.agent_info.get("persona", ""))
        self.persona_edit.setPlaceholderText(
            "Optional persona / system-prompt injection for this agent\u2026"
        )
        self.persona_edit.setFixedHeight(120)
        form.addRow("Persona / Notes:", self.persona_edit)

        self.enabled_chk = QCheckBox("Enabled")
        self.enabled_chk.setChecked(self.agent_info.get("enabled", True))
        form.addRow(self.enabled_chk)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("\U0001f4be Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def get_result(self) -> dict:
        return {
            **self.agent_info,
            "description": self.desc_edit.toPlainText().strip(),
            "timeout_s": self.timeout_spin.value(),
            "persona": self.persona_edit.toPlainText().strip(),
            "enabled": self.enabled_chk.isChecked(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Creating a NEW agent
#
# `AgentEditDialog` above edits an agent that already exists. Creating one used to
# have no interface at all: you wrote a .py file by hand, dropped it in a directory
# inside the installation, and hoped. Nothing asked what the agent was FOR, when it
# should fire, or how you would know it worked — so an agent either seemed fine or
# it didn't, and there was no way to tell which.
#
# This wizard collects an `AgentSpec` (see eli/cognition/agent_spec.py). A spec is
# DATA, not code: it executes nothing, so it needs no trust grant, no hash and no
# sandbox. The four required fields are required because each one's absence produced
# a specific failure — no objective to judge by, a prompt too thin to steer, no
# trigger so it never ran, no criteria so nobody could tell whether it worked.
# ─────────────────────────────────────────────────────────────────────────────

from eli.gui.panels._qt import (  # noqa: E402
    QComboBox, QGroupBox, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QSpinBox, QSplitter, QTabWidget, QWidget, Qt,
)


class AgentCreateDialog(QDialog):
    """Author a new custom agent as a specification."""

    def __init__(self, parent=None, existing: dict | None = None, *, prefill: dict | None = None):
        super().__init__(parent)
        self._existing = existing or prefill or {}
        self._is_edit = bool(existing)
        self.setWindowTitle("Create agent" if not self._is_edit else "Edit agent spec")
        self.setMinimumSize(680, 640)
        self._build_ui()
        if existing:
            self._load(existing, lock_id=True)
        elif prefill:
            self._load(prefill, lock_id=False)

    @staticmethod
    def prefill_from_legacy_wizard(
        name_purpose: str,
        triggers_data: str,
        persona_output: str,
    ) -> dict:
        from eli.cognition.agent_spec import prefill_from_legacy_wizard
        return prefill_from_legacy_wizard(name_purpose, triggers_data, persona_output)

    # ── ui ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "<b>A custom agent runs alongside ELI's main reply.</b><br>"
            "<span style='color:#6c7086'>Author as many agents as you need — each is a "
            "specification (not code), saved under your ELI data directory, validated, and "
            "registered on the agent bus. No built-in limit on count; IDs must be unique.</span>"))

        tabs = QTabWidget()
        tabs.addTab(self._page_identity(), "1 · What it is")
        tabs.addTab(self._page_triggers(), "2 · When it runs")
        tabs.addTab(self._page_measures(), "3 · How you'd know it worked")
        tabs.addTab(self._page_advanced(), "4 · Advanced")
        root.addWidget(tabs, 1)

        self._problems = QLabel("")
        self._problems.setWordWrap(True)
        self._problems.setStyleSheet("color:#bf616a;padding:4px;")
        root.addWidget(self._problems)

        row = QHBoxLayout()
        test = QPushButton("Check")
        test.setToolTip("Validate the specification without saving it.")
        test.clicked.connect(self._check)
        row.addWidget(test)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        save = QPushButton("\U0001f4be Create agent")
        save.setObjectName("save_btn")
        save.clicked.connect(self._save)
        row.addWidget(save)
        root.addLayout(row)
        self._save_btn = save

    def _page_identity(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("grant_writer   (lowercase, underscores)")
        form.addRow("ID:", self.id_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Grant Writer")
        form.addRow("Display name:", self.name_edit)

        self.objective_edit = QTextEdit()
        self.objective_edit.setFixedHeight(70)
        self.objective_edit.setPlaceholderText(
            "One sentence: what is this agent responsible for?\n"
            "e.g. \"Draft and critique funding-application text, keeping every claim "
            "inside what the evidence supports.\"")
        form.addRow("Objective:", self.objective_edit)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setFixedHeight(150)
        self.prompt_edit.setPlaceholderText(
            "The instruction the model actually receives when this agent runs.\n"
            "Be specific about what to do and what never to do.")
        form.addRow("Instruction:", self.prompt_edit)
        return w

    def _page_triggers(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "<b>When should this agent wake up?</b><br>"
            "<span style='color:#6c7086'>At least one is required — without a trigger the "
            "agent is registered and then never runs. Avoid <i>always</i> unless you mean "
            "it: it costs time on every single turn.</span>"))
        self.trigger_list = QListWidget()
        v.addWidget(self.trigger_list, 1)

        row = QHBoxLayout()
        self.trigger_kind = QComboBox()
        self.trigger_kind.addItems(["keyword", "regex", "action", "always"])
        row.addWidget(self.trigger_kind)
        self.trigger_value = QLineEdit()
        self.trigger_value.setPlaceholderText("grant")
        self.trigger_value.returnPressed.connect(self._add_trigger)
        row.addWidget(self.trigger_value, 1)
        add = QPushButton("Add")
        add.clicked.connect(self._add_trigger)
        row.addWidget(add)
        rm = QPushButton("Remove")
        rm.clicked.connect(lambda: self._remove(self.trigger_list))
        row.addWidget(rm)
        v.addLayout(row)
        return w

    def _page_measures(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "<b>How would you know this agent did its job?</b><br>"
            "<span style='color:#6c7086'>Checks ELI can actually run on the answer. This is "
            "the part people skip, and it is why it is required: an agent that fails its own "
            "test contributes nothing, instead of quietly adding noise to your replies.</span>"))
        self.check_list = QListWidget()
        v.addWidget(self.check_list, 1)

        row = QHBoxLayout()
        self.check_kind = QComboBox()
        self.check_kind.addItems(["non_empty", "min_length", "max_length", "contains",
                                  "not_contains", "regex", "is_json"])
        row.addWidget(self.check_kind)
        self.check_value = QLineEdit()
        self.check_value.setPlaceholderText("value (not needed for non_empty / is_json)")
        self.check_value.returnPressed.connect(self._add_check)
        row.addWidget(self.check_value, 1)
        add = QPushButton("Add")
        add.clicked.connect(self._add_check)
        row.addWidget(add)
        rm = QPushButton("Remove")
        rm.clicked.connect(lambda: self._remove(self.check_list))
        row.addWidget(rm)
        v.addLayout(row)

        v.addWidget(QLabel(
            "<span style='color:#6c7086'>Common set: <i>non_empty</i> + <i>min_length 120</i> "
            "(no stub answers) + <i>not_contains \"as an AI\"</i> (no assistant "
            "boilerplate).</span>"))
        return w

    def _page_advanced(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.5, 300.0)
        self.timeout_spin.setSingleStep(0.5)
        self.timeout_spin.setValue(8.0)
        form.addRow("Timeout (s):", self.timeout_spin)

        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(32, 8192)
        self.tokens_spin.setSingleStep(64)
        self.tokens_spin.setValue(512)
        form.addRow("Max tokens:", self.tokens_spin)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.05)
        self.temp_spin.setValue(0.4)
        form.addRow("Temperature:", self.temp_spin)

        self.author_edit = QLineEdit()
        form.addRow("Author:", self.author_edit)

        self.enabled_chk = QCheckBox("Enabled (runs when triggers match)")
        self.enabled_chk.setChecked(False)
        form.addRow(self.enabled_chk)

        self.perm_box = QGroupBox("Capabilities this agent may use")
        pv = QVBoxLayout(self.perm_box)
        pv.addWidget(QLabel(
            "<span style='color:#6c7086'>Each one is asked for at first use, like a phone "
            "permission. Leave unchecked what it does not need.</span>"))
        self._perm_checks = {}
        try:
            from eli.plugins.permissions import ALL_CAPABILITIES, describe
            for cap in ALL_CAPABILITIES:
                d = describe(cap)
                chk = QCheckBox(f"{d['title']}  ({cap})")
                chk.setToolTip(d["why_risky"])
                if cap == "model_access":
                    chk.setChecked(True)
                self._perm_checks[cap] = chk
                pv.addWidget(chk)
        except Exception:
            pv.addWidget(QLabel("Capability list unavailable."))
        form.addRow(self.perm_box)
        return w

    # ── helpers ──────────────────────────────────────────────────────────────
    def _add_trigger(self):
        kind = self.trigger_kind.currentText()
        value = self.trigger_value.text().strip()
        if kind != "always" and not value:
            self._problems.setText("A keyword, regex or action trigger needs a value.")
            return
        item = QListWidgetItem(f"{kind}: {value}" if value else kind)
        item.setData(Qt.ItemDataRole.UserRole, {"kind": kind, "value": value})
        self.trigger_list.addItem(item)
        self.trigger_value.clear()
        self._problems.setText("")

    def _add_check(self):
        kind = self.check_kind.currentText()
        value = self.check_value.text().strip()
        if kind in ("contains", "not_contains", "regex", "min_length", "max_length") \
                and not value:
            self._problems.setText(f"A {kind} check needs a value.")
            return
        item = QListWidgetItem(f"{kind}: {value}" if value else kind)
        item.setData(Qt.ItemDataRole.UserRole, {"kind": kind, "value": value})
        self.check_list.addItem(item)
        self.check_value.clear()
        self._problems.setText("")

    @staticmethod
    def _remove(widget):
        for item in widget.selectedItems():
            widget.takeItem(widget.row(item))

    @staticmethod
    def _items(widget) -> list:
        return [widget.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(widget.count())]

    def _load(self, data: dict, *, lock_id: bool = False):
        self.id_edit.setText(data.get("id", ""))
        self.id_edit.setReadOnly(lock_id)
        self.name_edit.setText(data.get("name", ""))
        self.objective_edit.setPlainText(data.get("objective", ""))
        self.prompt_edit.setPlainText(data.get("system_prompt", ""))
        self.author_edit.setText(data.get("author", ""))
        self.timeout_spin.setValue(float(data.get("timeout_s", 8.0)))
        self.tokens_spin.setValue(int(data.get("max_tokens", 512)))
        self.temp_spin.setValue(float(data.get("temperature", 0.4)))
        self.enabled_chk.setChecked(bool(data.get("enabled", False)))
        if self._is_edit:
            self._save_btn.setText("\U0001f4be Save changes")
        for t in data.get("triggers", []):
            item = QListWidgetItem(f"{t['kind']}: {t.get('value', '')}")
            item.setData(Qt.ItemDataRole.UserRole, t)
            self.trigger_list.addItem(item)
        for c in data.get("success_criteria", []):
            item = QListWidgetItem(f"{c['kind']}: {c.get('value', '')}")
            item.setData(Qt.ItemDataRole.UserRole, c)
            self.check_list.addItem(item)
        for cap, chk in self._perm_checks.items():
            chk.setChecked(cap in (data.get("permissions") or []))

    def build_spec(self):
        from eli.cognition.agent_spec import AgentSpec, SuccessCheck, Trigger
        created = str(self._existing.get("created") or "")
        return AgentSpec(
            id=self.id_edit.text().strip(),
            name=self.name_edit.text().strip(),
            author=self.author_edit.text().strip(),
            objective=self.objective_edit.toPlainText().strip(),
            system_prompt=self.prompt_edit.toPlainText().strip(),
            triggers=[Trigger(**t) for t in self._items(self.trigger_list)],
            success_criteria=[SuccessCheck(**c) for c in self._items(self.check_list)],
            permissions=[c for c, chk in self._perm_checks.items() if chk.isChecked()],
            timeout_s=self.timeout_spin.value(),
            max_tokens=self.tokens_spin.value(),
            temperature=self.temp_spin.value(),
            enabled=self.enabled_chk.isChecked(),
            created=created,
        )

    def _check(self) -> bool:
        from eli.cognition.agent_spec import validate
        result = validate(self.build_spec())
        if result["ok"]:
            note = ("Specification is valid."
                    + ("  Warnings: " + "; ".join(result["warnings"])
                       if result["warnings"] else ""))
            self._problems.setStyleSheet("color:#a3be8c;padding:4px;")
            self._problems.setText(note)
            return True
        self._problems.setStyleSheet("color:#bf616a;padding:4px;")
        self._problems.setText("• " + "<br>• ".join(result["problems"]))
        return False

    def _save(self):
        if not self._check():
            return
        from eli.cognition.agent_spec import save_spec
        result = save_spec(self.build_spec())
        if not result["ok"]:
            self._problems.setText("• " + "<br>• ".join(result["problems"]))
            return
        # Register immediately — the loader used to run only at import, so a new
        # agent did nothing until ELI was restarted and nothing said why.
        registered = ""
        try:
            from eli.cognition.agent_bus import reload_custom_agents
            report = reload_custom_agents()
            mine = [r for r in report if r.get("id") == self.id_edit.text().strip()]
            if mine:
                registered = "\n\n" + mine[0]["reason"]
        except Exception as exc:
            registered = f"\n\nSaved, but live registration failed: {exc}"
        QMessageBox.information(
            self, "Agent saved" if self._is_edit else "Agent created",
            f"Saved to {result['path']}.{registered}\n\n"
            + ("Enable it here or in Settings ▸ Agents."
               if not self.enabled_chk.isChecked()
               else "It is enabled and will run when its triggers match."))
        self.accept()


__all__ = ["AgentEditDialog", "AgentCreateDialog"]
