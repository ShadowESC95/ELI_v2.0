"""Checks that need the real Qt, run in a child process (conftest stubs PySide6 for the tests).

    python -m tests._gui_runtime_checks names|methods|window|settings <window module>

Prints one JSON line starting with RESULT; {"skip": reason} when Qt cannot load here.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import json
import logging
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Used only behind a check that they exist: QScintilla is PyQt-only, and _eli_runtime_publish is
# read after an `in locals()` test.
GUARDED = {"QsciScintilla", "QsciLexerPython", "_eli_runtime_publish"}


def _annotation_positions(tree: ast.AST) -> set:
    found = set()

    def mark(node):
        for n in ast.walk(node) if node is not None else ():
            if isinstance(n, ast.Name):
                found.add((n.lineno, n.col_offset))

    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mark(n.returns)
            a = n.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                if arg is not None:
                    mark(arg.annotation)
        elif isinstance(n, ast.AnnAssign):
            mark(n.annotation)
    return found


def _module_name(path: pathlib.Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def unresolved_names() -> list:
    """Names pyflakes cannot resolve (it does not follow `import *`) that the imported module
    does not have either."""
    from pyflakes import checker, messages
    missing = []
    for path in sorted((ROOT / "eli").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        annotations = _annotation_positions(tree)
        flagged = []
        for m in checker.Checker(tree, filename=str(path)).messages:
            if isinstance(m, (messages.UndefinedName, messages.ImportStarUsage)):
                name = m.message_args[0]
                if name not in GUARDED and (m.lineno, m.col) not in annotations:
                    flagged.append((name, m.lineno))
        if not flagged:
            continue
        names = vars(importlib.import_module(_module_name(path)))
        missing += [f"{path.relative_to(ROOT)}:{line}: {name}" for name, line in flagged
                    if name not in names and not hasattr(builtins, name)]
    return missing


def _walk_own(cls_node: ast.ClassDef):
    """The class's own code: a class defined inside one of its methods has its own `self`."""
    stack = list(cls_node.body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.ClassDef):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def missing_methods(window_module: str) -> list:
    """`self.x` the window reads that neither it, its Qt base, nor any of its code assigns."""
    window = importlib.import_module(window_module).EliMainWindow
    used, assigned, guarded = {}, set(), set()
    for cls in window.__mro__:
        if not cls.__module__.startswith("eli."):
            continue
        for n in _walk_own(ast.parse(inspect.getsource(cls).lstrip()).body[0]):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
                if isinstance(n.ctx, ast.Store):
                    assigned.add(n.attr)
                else:
                    used.setdefault(n.attr, f"{cls.__module__}.{cls.__name__}")
            elif (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in ("hasattr", "getattr", "setattr") and len(n.args) >= 2
                  and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str)):
                (assigned if n.func.id == "setattr" else guarded).add(n.args[1].value)
    return sorted(f"{where}: self.{name}" for name, where in used.items()
                  if not hasattr(window, name) and name not in assigned and name not in guarded)


def build_window(window_module: str) -> dict:
    """Build the main window offscreen; report its tabs and every tab that fell back to its
    'unavailable' page (those failures are only logged)."""
    failed = []

    class _Catch(logging.Handler):
        def emit(self, record):
            text = record.getMessage()
            if "failed to load" in text:
                failed.append(text[:400])

    root = logging.getLogger()
    root.addHandler(_Catch())
    root.setLevel(logging.DEBUG)
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    try:
        # Building the settings page reaches the recogniser, which opens the microphone.
        import eli.perception.audio_stt as _stt
        _stt._get_recognizer = lambda *a, **k: None
    except Exception:
        pass
    # No event processing: the first queued event is the model picker, a dialog waiting for a click.
    window = importlib.import_module(window_module).EliMainWindow()
    return {"tabs": [window.tabs.tabText(i) for i in range(window.tabs.count())], "failed": failed}


def settings_saves(window_module: str) -> dict:
    """The Settings tab saved after one other box changed (or after the tuner ran), case by case:
    what the tab showed, what settings.json and the exported variables hold after the save, and
    what loads once the exports are gone. The window is built once; each case starts from its own
    settings file and exports, shown as the window shows them when it opens (_show_saved_settings).
    ELI_TEST_SETTINGS_CASES names the folder the cases keep their models in."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])  # noqa: F841
    try:
        import eli.perception.audio_stt as _stt
        _stt._get_recognizer = lambda *a, **k: None
    except Exception:
        pass
    root = pathlib.Path(os.environ["ELI_TEST_SETTINGS_CASES"])
    bundled = root / "models" / "gguf" / "base"
    bundled.mkdir(parents=True, exist_ok=True)
    (root / "elsewhere").mkdir(exist_ok=True)
    alpha, beta, gamma = bundled / "alpha.gguf", bundled / "beta.gguf", root / "elsewhere" / "gamma.gguf"
    for model in (alpha, beta, gamma):
        model.write_bytes(b"GGUF" + b"\0" * 64)
    mod = importlib.import_module(window_module)
    mod.BUNDLED_MODEL_DIR = root / "models"              # the program's own models folder, here
    from eli.core import hardware_profile as hp, runtime_settings as rs
    settings_file = pathlib.Path(os.environ["ELI_SETTINGS_FILE"])
    load_vars = set(rs.ENV_TO_KEY) | {"ELI_SETTINGS_PUBLISHED"}
    window = mod.EliMainWindow()

    def temperature_up():
        window.temperature_input.setValue(window.temperature_input.value() + 0.1)

    def run_tuner():
        rec = hp.ModelRecommendation(model_path=str(alpha), model_name=alpha.name, n_gpu_layers=-1,
                                     n_ctx=8192, batch_size=256, n_threads=0)
        real = hp.detect_hardware, hp.recommend
        hp.detect_hardware = lambda *a, **k: hp.HardwareProfile()
        hp.recommend = lambda *a, **k: rec
        try:
            window._apply_hardware_recommendation_for_model(str(alpha))
        finally:
            hp.detect_hardware, hp.recommend = real

    def case(saved, exported, change=temperature_up):
        for name in load_vars:
            os.environ.pop(name, None)
        os.environ.update(exported)
        settings_file.write_text(json.dumps({"ollama_host": "http://127.0.0.1:9", **saved}), encoding="utf-8")
        window._show_saved_settings()
        shown = {"layers": window.n_gpu_layers_input.value(), "layers_text": window.n_gpu_layers_input.text(),
                 "bundled": str(window.bundled_model_combo.currentData() or "")}
        change()
        shown_after = {"layers": window.n_gpu_layers_input.value(),
                       "layers_text": window.n_gpu_layers_input.text()}
        window.save_settings(silent=True)
        env = {name: os.environ.get(name) for name in exported}
        written = json.loads(settings_file.read_text(encoding="utf-8"))
        for name in exported:
            os.environ.pop(name, None)
        after = rs.load_settings()
        return {"shown": shown, "shown_after": shown_after, "env": env, "file": written,
                "loaded": {k: after.get(k) for k in ("n_ctx", "batch_size", "model_path", "temperature",
                                                     "n_gpu_layers", "provider")}}

    custom = {"provider": "custom_gguf", "model_path": str(alpha), "custom_model_path": str(alpha)}
    on_bundled = {"provider": "bundled_gguf", "model_path": str(alpha), "bundled_model_path": str(alpha)}
    return {
        "models": {"alpha": str(alpha), "beta": str(beta), "gamma": str(gamma)},
        "exported_context": case({**custom, "n_ctx": 0, "batch_size": 512, "temperature": 0.5},
                                 {"ELI_N_CTX": "16384", "ELI_GGUF_N_BATCH": "1024"}),
        "exported_every_layer": case({**custom, "n_gpu_layers": 0}, {"ELI_N_GPU_LAYERS": "-1"}),
        "bundled_exported": case(on_bundled, {"ELI_GGUF_MODEL_PATH": str(beta)}),
        "bundled_exported_elsewhere": case(on_bundled, {"ELI_GGUF_MODEL_PATH": str(gamma)}),
        "tuner": case({**on_bundled, "n_gpu_layers": 0, "batch_size": 512, "temperature": 0.3},
                      {"ELI_N_CTX": "16384", "ELI_GGUF_N_BATCH": "1024"}, run_tuner),
    }


def main(argv: list) -> None:
    what, window_module = argv[0], (argv[1] if len(argv) > 1 else "")
    try:
        import PySide6.QtWidgets  # noqa: F401
    except Exception as exc:
        result = {"skip": f"Qt does not load here: {exc}"}
    else:
        if what == "names":
            result = {"missing": unresolved_names()}
        elif what == "methods":
            result = {"missing": missing_methods(window_module)}
        elif what == "settings":
            result = settings_saves(window_module)
        else:
            result = build_window(window_module)
    print("RESULT " + json.dumps(result), flush=True)
    os._exit(0)  # the window starts background threads; nothing here needs them to finish


if __name__ == "__main__":
    main(sys.argv[1:])
