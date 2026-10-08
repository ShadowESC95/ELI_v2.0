"""Closing the window does not run the engine's shutdown on the window's thread.

The shutdown writes the session summary with a model call (30 s in a real session), and run from
closeEvent it kept the window on screen and unresponsive until it finished: GNOME showed "ELI is
not responding" on every close. main() runs the registered exit handlers once app.exec() returns.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANDIDATES = ("eli/gui/main_window/window.py", "eli/gui/eli_pro_audio_gui_v2_0.py")


def _window_source():
    for rel in CANDIDATES:
        path = ROOT / rel
        if path.is_file() and "def closeEvent" in path.read_text(encoding="utf-8"):
            return path.read_text(encoding="utf-8")
    raise AssertionError("window source not found")


def _function(src, name):
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(name)


def test_close_event_does_not_call_shutdown():
    calls = [n.func.attr for n in ast.walk(_function(_window_source(), "closeEvent"))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "shutdown" not in calls
    assert "hide" in calls


def test_main_runs_the_exit_handlers_after_the_event_loop():
    body = ast.unparse(_function(_window_source(), "main"))
    assert body.index("app.exec()") < body.index("_run_exitfuncs()")


def test_the_conversation_is_saved_as_it_grows_into_one_file(tmp_path):
    """The conversation file was written only on close; the 2026-10-08 crash lost the whole evening.
    It is now rewritten after each reply, one file per conversation."""
    import json
    import logging
    import types
    from datetime import datetime

    src = next(p.read_text(encoding="utf-8") for p in sorted((ROOT / "eli/gui").rglob("*.py"))
               if "def save_conversation" in p.read_text(encoding="utf-8"))
    ns = {"datetime": datetime, "json": json, "CONVERSATIONS_DIR": tmp_path, "now_timestamp": lambda: "now",
          "QMessageBox": None, "log": logging.getLogger("test")}
    exec(compile(ast.Module([_function(src, "save_conversation")], []), "save", "exec"), ns)
    window = types.SimpleNamespace(conversation_history=[{"role": "user", "content": "hi"}],
                                   status_signal=types.SimpleNamespace(emit=lambda *a: None))
    ns["save_conversation"](window, quiet=True)
    window.conversation_history.append({"role": "assistant", "content": "hello"})
    ns["save_conversation"](window, quiet=True)
    files = list(tmp_path.glob("conversation_*.json"))
    assert len(files) == 1 and len(json.loads(files[0].read_text())["messages"]) == 2
    window._autosave_enabled = False
    window.conversation_history.append({"role": "user", "content": "more"})
    ns["save_conversation"](window, quiet=True)
    assert len(json.loads(files[0].read_text())["messages"]) == 2
