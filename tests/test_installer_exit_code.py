"""GUI installer must not treat Qt Accepted (1) as shell failure.

``QDialog.exec()`` returns 1 for Accepted and 0 for Rejected — the exact inverse of
a shell exit code. Returning it directly made a SUCCESSFUL install look like a
failed one to every caller (``eli_setup.sh`` then printed the terminal-fallback
message over a working install).

Asserted by shape, not by an exact source line: this test previously matched the
literal ``return 0 if dlg._install_succeeded else 1`` and broke the moment v2.4.14
correctly widened the condition to also accept a completed core install when the
wizard was closed early. The contract is "the exit code comes from whether the
install succeeded, never from exec()" — that is what is checked here.
"""
import ast
from pathlib import Path

SRC = Path("eli/setup/unified_installer.py")


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found in {SRC}")


def test_the_success_flag_is_actually_set():
    src = SRC.read_text(encoding="utf-8")
    assert "_install_succeeded = True" in src, (
        "nothing ever marks the install successful, so the exit code cannot reflect it"
    )


def test_the_exit_code_is_not_the_qt_dialog_result():
    fn = _function("run_unified_installer")
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        returned = ast.unparse(node.value)
        assert "exec()" not in returned, (
            f"exit code taken from the Qt dialog result: return {returned}"
        )


def test_the_exit_code_derives_from_install_success():
    fn = _function("run_unified_installer")
    # The success signal may be read directly or through a local; either is fine so
    # long as it reaches the return.
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            value = ast.unparse(node.value)
            if "_install_succeeded" in value or "_core_install_complete" in value:
                names.update(ast.unparse(t) for t in node.targets)

    returns = [ast.unparse(n.value) for n in ast.walk(fn)
               if isinstance(n, ast.Return) and n.value is not None]
    assert returns, "run_unified_installer() never returns"

    ok = any(
        "_install_succeeded" in r or any(n in r for n in names)
        for r in returns
    )
    assert ok, (
        "no return path is derived from install success; "
        f"returns were {returns}"
    )
