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
