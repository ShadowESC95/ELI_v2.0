import ast
from pathlib import Path


def _extract_supported_actions():
    src = Path("eli/execution/executor_enhanced.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "SUPPORTED_ACTIONS":
                    assert isinstance(node.value, ast.List)
                    return {
                        elt.value.upper()
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }

    raise AssertionError("SUPPORTED_ACTIONS assignment not found")


def test_user_facing_routable_admin_actions_are_supported():
    supported = _extract_supported_actions()

    expected = {
        "EXPLAIN_LAST_RESPONSE",
        "REFRESH_USER_INFO",
        "SELF_REPORT",
        "SELF_UPDATE",
        "USER_IDENTITY_SUMMARY",
    }

    missing = expected - supported
    assert not missing, f"Missing from SUPPORTED_ACTIONS: {sorted(missing)}"
