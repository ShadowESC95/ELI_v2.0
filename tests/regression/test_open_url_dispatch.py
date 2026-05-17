import ast
import importlib
from pathlib import Path


def test_open_url_is_executor_dispatch_backed():
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    actions = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue

        test = node.test

        if isinstance(test, ast.Compare):
            for comp in test.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    actions.add(comp.value.upper())

            for op, comp in zip(test.ops, test.comparators):
                if isinstance(op, ast.In) and isinstance(comp, (ast.Tuple, ast.List, ast.Set)):
                    for elt in comp.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            actions.add(elt.value.upper())

    assert "OPEN_URL" in actions


def test_open_url_helper_accepts_bare_domain(monkeypatch):
    ex = importlib.import_module("eli.execution.executor_enhanced")

    opened = {}

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(
        "webbrowser.open",
        lambda url, new=2: opened.setdefault("url", url) or True,
    )

    res = ex._eli_open_url_action("github.com")

    assert res["ok"] is True
    assert res["url"] == "https://github.com"
    assert opened["url"] == "https://github.com"


def test_open_url_helper_blocks_unsafe_schemes():
    ex = importlib.import_module("eli.execution.executor_enhanced")

    assert ex._eli_open_url_action("javascript:alert(1)")["ok"] is False
    assert ex._eli_open_url_action("file:///etc/passwd")["ok"] is False
    assert ex._eli_open_url_action("data:text/html,test")["ok"] is False
