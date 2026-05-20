"""ELI MKXI — Agent edit dialog panel."""
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
