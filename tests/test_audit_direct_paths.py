"""Actions that never go through CognitiveEngine.process() still get an audit row.

The GUI's voice fast path sends OPEN_APP, CLOSE_APP, READ_FILE, LIST_DIR,
SCREENSHOT, SET_TIMER, NEWS_FETCH and media/volume commands straight to the
executor for latency; the Files tab's Convert button calls CONVERT_DOCUMENT.
Neither reached the engine, so neither was ever recorded. The Convert button
also called self.execute_action, which EliMainWindow has never had, so it
failed with an AttributeError every time since it was added.

GUI module is Qt-coupled; checked at the source level like
test_audit_tab_gui.py.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from eli.kernel import request_context as rc
from eli.kernel.engine import CognitiveEngine
from eli.runtime import orchestrator_audit_ledger as L

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py"
ENGINE = ROOT / "eli" / "kernel" / "engine.py"


def _block(src: str, start: str, end: str) -> str:
    i = src.index(start)
    return src[i:src.index(end, i + len(start))]


def test_record_direct_action_writes_a_signed_row(tmp_path):
    db = tmp_path / "orch.sqlite3"
    with patch.dict("os.environ", {"ELI_ORCHESTRATOR_AUDIT_DB": str(db)}):
        rid = L.record_direct_action(action="open_app", ok=False, outcome="app not found",
                                     source="voice_direct", session_id="s", user_id="u",
                                     elapsed_ms=12.34)
        assert L.flush(timeout=10.0)
    row = L.recent_turns(limit=1, db_path=db)[0]
    assert row["request_id"] == rid
    assert (row["action"], row["source"], row["ok"], row["outcome"]) == (
        "OPEN_APP", "voice_direct", False, "app not found")
    assert (row["session_id"], row["user_id"], row["elapsed_ms"]) == ("s", "u", 12.3)
    assert L.verify_chain(db_path=db)["ok"] is True


def test_voice_fast_path_writes_an_audit_row():
    block = _block(GUI.read_text(encoding="utf-8"),
                   "def _on_stt_transcript(self", "\n    def ")
    i = block.index("_eli_voice_executor.execute_action(")
    after = block[i:]
    assert "record_direct_action(" in after
    assert 'source="voice_direct"' in after
    # The fragment guard isn't an action.
    assert '_action != "NOOP"' in after[:after.index("record_direct_action(")]


def test_convert_button_calls_a_real_executor_and_is_audited():
    src = GUI.read_text(encoding="utf-8")
    block = _block(src, "def _convert_selected_file(self", "\n    def ")
    assert "self.execute_action(" not in block
    assert "executor_enhanced import execute" in block
    assert "record_direct_action(" in block
    assert 'source="gui_button"' in block
    # The method the old code called lives on ExecutorBridge, not the window.
    i = src.index("class EliMainWindow(")
    j = src.find("\nclass ", i + 1)
    assert "    def execute_action(" not in src[i:j if j != -1 else len(src)]


def test_a_middleware_answer_records_which_middleware(tmp_path, monkeypatch):
    """Middleware fast paths return a bare string with no action; the row
    names the middleware that answered instead of UNKNOWN."""
    monkeypatch.setenv("ELI_ORCHESTRATOR_AUDIT_DB", str(tmp_path / "orch.sqlite3"))
    eng = CognitiveEngine.__new__(CognitiveEngine)
    eng._fallback_session_id, eng._fallback_user_id = "s", "u"

    def impl(self, *a, **k):
        rc.note_turn_fact("route", "mw_reasoning_status")
        return "Current reasoning mode: quick"

    with patch.object(CognitiveEngine, "_process_impl", impl):
        eng.process("what reasoning mode are you in")
    assert L.flush(timeout=10.0)
    assert L.recent_turns(limit=1, db_path=tmp_path / "orch.sqlite3")[0]["action"] == "MW_REASONING_STATUS"


def test_pipeline_hit_markers_feed_the_route_fact():
    src = ENGINE.read_text(encoding="utf-8")
    block = _block(src, "def _eli_pipe(event: str", "\n\n")
    assert 'event.endswith("_hit")' in block
    assert 'note_turn_fact("route"' in block
    # Recorded even when ELI_PIPELINE_TRACE is off.
    assert block.index("note_turn_fact") < block.index("if not _eli_pipeline_trace")


def test_stream_meta_uses_the_turns_request_id():
    """_stream_chat stamped its meta with self._pipeline_req_id, shared by
    concurrent turns on the singleton; it reads the turn's own id now."""
    src = ENGINE.read_text(encoding="utf-8")
    assert '_eli_pipeline_req = str(getattr(self, "_pipeline_req_id", "") or "n/a")' not in src
    assert "_request_context.request_id_var.get()\n                                or getattr(self, \"_pipeline_req_id\"" in src
