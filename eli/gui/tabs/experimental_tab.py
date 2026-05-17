from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

from eli.gui.qt_compat import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from eli.runtime.experimental_inventory import build_experimental_inventory


def _label(text: str, style: str = "") -> QLabel:
    widget = QLabel(str(text or ""))
    widget.setWordWrap(True)
    if style:
        widget.setStyleSheet(style)
    return widget


class ExperimentalTab(QWidget):
    """Safe GUI surface for repo-root experimental prototypes.

    The tab inventories prototypes and opens folders/READMEs on demand. It does
    not run scripts, install dependencies, or mutate experimental assets.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.inventory: Dict[str, Any] = {}
        self.project_container = QWidget()
        self.project_layout = QVBoxLayout(self.project_container)
        self.status = QLabel("Scanning experimental workspace")

        root = QVBoxLayout(self)
        header = _label(
            "Experimental Workbench",
            "font-size: 20px; font-weight: 800; color: #203024; padding: 4px 0;",
        )
        subtitle = _label(
            "Prototype and embodiment kits are listed here safely. Opening a folder is allowed; running scripts stays explicit.",
            "color: #4e5f52; padding-bottom: 8px;",
        )
        root.addWidget(header)
        root.addWidget(subtitle)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        open_root_btn = QPushButton("Open Experimental Folder")
        open_root_btn.clicked.connect(lambda: self._open_path(self.inventory.get("root")))
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(open_root_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.status)
        root.addLayout(toolbar)

        self.summary = _label("", "font-size: 13px; color: #26362b; padding: 8px;")
        self.summary.setStyleSheet(
            "QLabel { background: #eef2e5; border: 1px solid #c8d6bd; border-radius: 10px; padding: 10px; }"
        )
        root.addWidget(self.summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.project_container)
        root.addWidget(scroll, 1)
        self.refresh()

    def _open_path(self, path_value: Any) -> None:
        path = Path(str(path_value or "")).expanduser()
        if not path.exists():
            self.status.setText("Path unavailable")
            return
        try:
            subprocess.Popen(["xdg-open", str(path)])
            self.status.setText(f"Opened {path.name}")
        except Exception as exc:
            self.status.setText(f"Open failed: {type(exc).__name__}: {exc}")

    def _clear_projects(self) -> None:
        while self.project_layout.count():
            item = self.project_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

    def _project_card(self, project: Dict[str, Any]) -> QFrame:
        card = QFrame()
        lifecycle = str(project.get("lifecycle") or "unknown")
        tone = "#f7f1dc" if lifecycle == "active_candidate" else "#f0ede8"
        border = "#cfa94e" if lifecycle == "active_candidate" else "#b7b0a8"
        card.setStyleSheet(
            f"QFrame {{ background: {tone}; border: 1px solid {border}; border-radius: 14px; padding: 10px; }}"
        )
        layout = QVBoxLayout(card)
        title = project.get("title") or project.get("name")
        layout.addWidget(_label(str(title), "font-size: 16px; font-weight: 800; color: #2d2a1f;"))
        layout.addWidget(
            _label(
                f"{project.get('name')} | {lifecycle} | files={project.get('file_count')} | "
                f"scripts={project.get('script_count')} | assets={project.get('asset_count')} | configs={project.get('config_count')}",
                "color: #514b38;",
            )
        )

        scripts = project.get("scripts") or []
        assets = project.get("assets") or []
        if scripts:
            layout.addWidget(_label("Scripts: " + ", ".join(map(str, scripts[:8])), "color: #353225;"))
        if assets:
            layout.addWidget(_label("Assets: " + ", ".join(map(str, assets[:6])), "color: #353225;"))

        buttons = QHBoxLayout()
        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(lambda _checked=False, p=project.get("path"): self._open_path(p))
        buttons.addWidget(open_btn)
        if project.get("readme_exists"):
            readme_btn = QPushButton("Open README")
            readme_btn.clicked.connect(lambda _checked=False, p=project.get("readme_path"): self._open_path(p))
            buttons.addWidget(readme_btn)
        buttons.addStretch()
        layout.addLayout(buttons)
        return card

    def refresh(self) -> None:
        self.inventory = build_experimental_inventory()
        counts = self.inventory.get("counts") or {}
        if not self.inventory.get("exists"):
            self.status.setText("experimental/ not found")
            self.summary.setText("No experimental workspace was found at the repo root.")
            self._clear_projects()
            return

        self.status.setText("Experimental inventory loaded")
        self.summary.setText(
            "Root: {root}\n"
            "Projects: {projects} total, {active} active candidates, {backups} backups\n"
            "Files: {files}; scripts: {scripts}; assets: {assets}; configs: {configs}; archives: {archives}".format(
                root=self.inventory.get("root"),
                projects=counts.get("projects"),
                active=counts.get("active_projects"),
                backups=counts.get("backup_projects"),
                files=counts.get("files"),
                scripts=counts.get("scripts"),
                assets=counts.get("assets"),
                configs=counts.get("configs"),
                archives=counts.get("archives"),
            )
        )

        self._clear_projects()
        for project in self.inventory.get("projects") or []:
            self.project_layout.addWidget(self._project_card(project))
        archives = self.inventory.get("archives") or []
        if archives:
            names = ", ".join(str(a.get("name")) for a in archives[:8])
            self.project_layout.addWidget(
                _label(f"Archives present: {names}", "color: #5d4c26; padding: 8px;")
            )
        self.project_layout.addStretch()

