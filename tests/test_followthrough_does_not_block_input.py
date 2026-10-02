"""Live session report (2026-10-02): "ELI finished response but why is it still
generating, which is stopping me from asking a follow-up query?" — _stream_with_
followthrough (engine.py) silently re-runs the whole pipeline after the visible
reply is done (to make good on anything ELI said it would do), and the GUI's
Send button stayed locked for that whole hidden re-run since it only unlocks
when the generator is fully exhausted.

Fixed with a sentinel the engine yields right after the visible reply, which the
GUI uses to unlock input early while the worker thread keeps consuming any
trailing followthrough text in the background — plus a prior-thread cancel+join
in send_message() so a second worker can't write to the chat at the same time
as a still-finishing followthrough tail from the first.

Qt-coupled GUI module, not directly executable in CI — verified at the
source-text level (established pattern, see test_moe_gpu_layer_print_matches_
what_loads.py).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "eli/gui/eli_pro_audio_gui_v2_0.py"
ENGINE = ROOT / "eli/kernel/engine.py"


def test_engine_exports_the_sentinel_and_yields_it_before_followthrough():
    src = ENGINE.read_text(encoding="utf-8")
    assert "MAIN_REPLY_DONE_SENTINEL" in src
    i = src.index("def _stream_with_followthrough")
    j = src.index("detect_action_commitment", i)
    block = src[i:j]
    assert "yield MAIN_REPLY_DONE_SENTINEL" in block


def test_gui_unlocks_input_on_the_sentinel_without_appending_it_as_text():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("def generate_worker")
    j = src.index("def clear_chat", i) if "def clear_chat" in src[i:] else i + 20000
    block = src[i:j]
    assert "_MAIN_REPLY_DONE" in block
    assert "self.is_generating = False" in block
    k = block.index("token == _MAIN_REPLY_DONE")
    nearby = block[k:k + 600]
    assert "continue" in nearby  # must not fall through to full_tokens.append


def test_send_message_cancels_and_joins_a_still_running_prior_worker():
    src = GUI.read_text(encoding="utf-8")
    i = src.index("def send_message")
    j = src.index("self.is_generating = True", i)
    block = src[i:j]
    assert "_generate_thread" in block
    assert "is_alive()" in block
    assert "_request_generation_cancel" in block
    assert ".join(timeout=" in block


def test_stop_generation_and_send_message_share_the_same_cancel_helper():
    src = GUI.read_text(encoding="utf-8")
    assert src.count("_request_generation_cancel()") >= 2


def test_worker_thread_reference_is_stored_not_fire_and_forget():
    src = GUI.read_text(encoding="utf-8")
    assert "self._generate_thread = threading.Thread(target=generate_worker" in src
