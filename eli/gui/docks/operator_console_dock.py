"""
Governed operator console for proposals, goals, autonomy policy, event feed, scheduler attention, and ranked operator priority.
"""
from __future__ import annotations

from eli.gui import qt_compat as QtCompat
from eli.runtime.operator_state import operator_snapshot
from eli.execution.operator_actions import set_proposal_state
from eli.planning.operator_goal_actions import create_goal, set_goal_enabled
from eli.execution.operator_policy import load_policy, set_policy_mode
from eli.runtime.operator_feed import safe_operator_feed
from eli.planning.autonomy_scheduler import scheduler_snapshot, scheduler_tick

Qt = QtCompat.Qt


class OperatorConsoleDock(QtCompat.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("ELI Operator Console", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )

        root = QtCompat.QWidget()
        layout = QtCompat.QVBoxLayout(root)

        btn_row = QtCompat.QHBoxLayout()
        self.refresh_btn = QtCompat.QPushButton("Refresh")
        self.scheduler_btn = QtCompat.QPushButton("Scheduler Tick")
        self.goal_tick_btn = QtCompat.QPushButton("Goal Tick")
        self.drain_btn = QtCompat.QPushButton("Drain Proposals")
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.scheduler_btn)
        btn_row.addWidget(self.goal_tick_btn)
        btn_row.addWidget(self.drain_btn)
        layout.addLayout(btn_row)

        self.badges = QtCompat.QLabel("attention=0 | confirm=0 | blocked=0")
        layout.addWidget(self.badges)

        layout.addWidget(QtCompat.QLabel("Policy mode"))
        pol_row = QtCompat.QHBoxLayout()
        self.policy_mode = QtCompat.QComboBox()
        self.policy_mode.addItems([
            "proposal_only",
            "operator_supervised",
            "goal_driven",
            "observe_only",
        ])
        self.policy_reason = QtCompat.QLineEdit()
        self.policy_reason.setPlaceholderText("Policy reason")
        self.policy_apply_btn = QtCompat.QPushButton("Apply Policy")
        pol_row.addWidget(self.policy_mode)
        pol_row.addWidget(self.policy_reason)
        pol_row.addWidget(self.policy_apply_btn)
        layout.addLayout(pol_row)

        self.summary = QtCompat.QTextEdit()
        self.summary.setReadOnly(True)
        layout.addWidget(self.summary)

        layout.addWidget(QtCompat.QLabel("Recent proposals"))
        self.proposals = QtCompat.QListWidget()
        layout.addWidget(self.proposals)

        proposal_row = QtCompat.QHBoxLayout()
        self.note = QtCompat.QLineEdit()
        self.note.setPlaceholderText("Operator note / reason")
        self.approve_btn = QtCompat.QPushButton("Approve")
        self.reject_btn = QtCompat.QPushButton("Reject")
        self.defer_btn = QtCompat.QPushButton("Defer")
        proposal_row.addWidget(self.note)
        proposal_row.addWidget(self.approve_btn)
        proposal_row.addWidget(self.reject_btn)
        proposal_row.addWidget(self.defer_btn)
        layout.addLayout(proposal_row)

        layout.addWidget(QtCompat.QLabel("Goal mission control"))
        goal_create = QtCompat.QHBoxLayout()
        self.goal_title = QtCompat.QLineEdit()
        self.goal_title.setPlaceholderText("Goal title")
        self.goal_objective = QtCompat.QLineEdit()
        self.goal_objective.setPlaceholderText("Goal objective")
        self.goal_create_btn = QtCompat.QPushButton("Create Goal")
        goal_create.addWidget(self.goal_title)
        goal_create.addWidget(self.goal_objective)
        goal_create.addWidget(self.goal_create_btn)
        layout.addLayout(goal_create)

        self.goals = QtCompat.QListWidget()
        layout.addWidget(self.goals)

        goal_toggle = QtCompat.QHBoxLayout()
        self.goal_enable_btn = QtCompat.QPushButton("Enable Goal")
        self.goal_disable_btn = QtCompat.QPushButton("Disable Goal")
        goal_toggle.addWidget(self.goal_enable_btn)
        goal_toggle.addWidget(self.goal_disable_btn)
        layout.addLayout(goal_toggle)

        layout.addWidget(QtCompat.QLabel("Attention queue"))
        self.attention = QtCompat.QTextEdit()
        self.attention.setReadOnly(True)
        layout.addWidget(self.attention)

        layout.addWidget(QtCompat.QLabel("Operator event feed"))
        self.feed = QtCompat.QTextEdit()
        self.feed.setReadOnly(True)
        layout.addWidget(self.feed)

        layout.addWidget(QtCompat.QLabel("Self model / autonomy"))
        self.self_model = QtCompat.QTextEdit()
        self.self_model.setReadOnly(True)
        layout.addWidget(self.self_model)

        self.setWidget(root)

        self.refresh_btn.clicked.connect(self.refresh_all)
        self.scheduler_btn.clicked.connect(self.run_scheduler_tick)
        self.goal_tick_btn.clicked.connect(self.run_goal_tick)
        self.drain_btn.clicked.connect(self.drain_to_memory)
        self.policy_apply_btn.clicked.connect(self.apply_policy_mode)

        self.approve_btn.clicked.connect(lambda: self._set_selected_state("approved"))
        self.reject_btn.clicked.connect(lambda: self._set_selected_state("rejected"))
        self.defer_btn.clicked.connect(lambda: self._set_selected_state("pending_confirmation"))

        self.goal_create_btn.clicked.connect(self.create_goal_from_ui)
        self.goal_enable_btn.clicked.connect(lambda: self._set_goal_enabled(True))
        self.goal_disable_btn.clicked.connect(lambda: self._set_goal_enabled(False))

        self._timer = QtCompat.QTimer(self)
        self._timer.setInterval(10000)
        self._timer.timeout.connect(self.refresh_all)
        self._timer.start()

        self.refresh_all()

    def _selected_proposal_id(self):
        item = self.proposals.currentItem()
        if not item:
            return None
        try:
            return item.data(Qt.ItemDataRole.UserRole)
        except Exception:
            return None

    def _selected_goal_id(self):
        item = self.goals.currentItem()
        if not item:
            return None
        try:
            return item.data(Qt.ItemDataRole.UserRole)
        except Exception:
            return None

    def _set_selected_state(self, state: str):
        pid = self._selected_proposal_id()
        if not pid:
            self.summary.append("No proposal selected.")
            return
        note = self.note.text().strip()
        out = set_proposal_state(pid, state, note=note, actor="operator_console")
        self.summary.append(f"proposal_state: {out}")
        self.refresh_all()

    def _set_goal_enabled(self, enabled: bool):
        gid = self._selected_goal_id()
        if not gid:
            self.summary.append("No goal selected.")
            return
        out = set_goal_enabled(gid, enabled)
        self.summary.append(f"goal_enabled: {out}")
        self.refresh_all()

    def create_goal_from_ui(self):
        title = self.goal_title.text().strip()
        objective = self.goal_objective.text().strip()
        out = create_goal(
            title=title,
            objective=objective or title,
            cadence_sec=3600,
            autonomy_mode="proposal_only",
        )
        self.summary.append(f"goal_create: {out}")
        if out.get("ok"):
            self.goal_title.setText("")
            self.goal_objective.setText("")
        self.refresh_all()

    def apply_policy_mode(self):
        mode = self.policy_mode.currentText().strip()
        reason = self.policy_reason.text().strip()
        out = set_policy_mode(mode, actor="operator_console", reason=reason)
        self.summary.append(f"policy_apply: {out}")
        self.refresh_all()

    def run_scheduler_tick(self):
        try:
            out = scheduler_tick(limit=3, cooldown_sec=60)
        except Exception as exc:
            out = {"ok": False, "error": str(exc)}
        self.summary.append(f"scheduler_tick: {out}")
        self.refresh_all()

    def run_goal_tick(self):
        try:
            from eli.planning.autonomy_controller import safe_goal_tick
            out = safe_goal_tick(limit=3)
        except Exception as exc:
            out = {"ok": False, "error": str(exc)}
        self.summary.append(f"goal_tick: {out}")
        self.refresh_all()

    def drain_to_memory(self):
        try:
            from eli.planning.proposal_memory_bridge import drain_proposals_to_agent_memory
            out = drain_proposals_to_agent_memory(max_items=64, archive=True)
        except Exception as exc:
            out = {"ok": False, "error": str(exc)}
        self.summary.append(f"proposal_drain: {out}")
        self.refresh_all()

    def refresh_all(self):
        snap = operator_snapshot(limit=25)
        policy = load_policy()
        feed = safe_operator_feed(limit=25)
        sched = scheduler_snapshot(limit=25)

        psummary = snap.get("proposal_summary", {})
        gsummary = snap.get("goal_summary", {})
        smodel = snap.get("self_model", {})
        sstate = sched.get("state", {})
        attent_summary = sched.get("attention_summary", {})

        needs_now = int(attent_summary.get("needs_attention_now", 0) or 0)
        blocked = int(attent_summary.get("states", {}).get("blocked", 0) or 0)
        confirm = int(attent_summary.get("states", {}).get("pending_confirmation", 0) or 0)
        total_attention = sum(int(v) for v in (attent_summary.get("states", {}) or {}).values()) if isinstance(attent_summary.get("states", {}), dict) else 0
        self.badges.setText(f"attention={total_attention} | confirm={confirm} | blocked={blocked} | urgent={needs_now}")

        summary_lines = [
            "=== Operator Snapshot ===",
            f"policy={policy}",
            f"scheduler_state={sstate}",
            f"proposal_summary={psummary}",
            f"goal_summary={gsummary}",
            f"attention_summary={attent_summary}",
        ]
        self.summary.setPlainText("\n".join(summary_lines))

        try:
            idx = self.policy_mode.findText(policy.get("mode", "proposal_only"))
            if idx >= 0:
                self.policy_mode.setCurrentIndex(idx)
        except Exception:
            pass

        self.proposals.clear()
        for rec in snap.get("recent_proposals", {}).get("items", []):
            title = str(rec.get("title") or rec.get("summary") or rec.get("proposal_id") or "proposal")
            state = str(rec.get("approval_state") or "pending")
            pid = str(rec.get("proposal_id") or rec.get("id") or "")
            item = QtCompat.QListWidgetItem(f"[{state}] {title}")
            try:
                item.setData(Qt.ItemDataRole.UserRole, pid)
            except Exception:
                pass
            self.proposals.addItem(item)

        self.goals.clear()
        for goal in snap.get("active_goals", {}).get("items", []):
            title = str(goal.get("title") or goal.get("objective") or goal.get("goal_id") or "goal")
            priority = str(goal.get("priority") or "normal")
            state = str(goal.get("status") or "active")
            gid = str(goal.get("goal_id") or "")
            item = QtCompat.QListWidgetItem(f"[{priority}/{state}] {title}")
            try:
                item.setData(Qt.ItemDataRole.UserRole, gid)
            except Exception:
                pass
            self.goals.addItem(item)

        att_lines = []
        for rec in sched.get("attention", {}).get("items", []):
            att_lines.append(
                f"[score={rec.get('rank_score', 0):.1f}][{rec.get('severity')}/{rec.get('state')}] "
                f"{rec.get('title')} :: {rec.get('source')}"
            )
        self.attention.setPlainText("\n".join(att_lines))

        feed_lines = []
        for ev in feed.get("items", []):
            feed_lines.append(
                f"[rank={float(ev.get('rank_score', 0.0)):.1f}][{ev.get('kind')}] "
                f"{ev.get('state')} :: {ev.get('title')} :: {ev.get('source')}"
            )
        self.feed.setPlainText("\n".join(feed_lines))

        self.self_model.setPlainText(
            "=== Self Model ===\n"
            f"{smodel}\n"
        )
