"""#7 — observability lint: freeze the silent `except: pass` and log-only catch-all counts, fail on growth.

A silent `except …: pass` (a handler whose entire body is just `pass`) hides
failures — it's the main reason bugs in ELI tend to surface only via runtime logs,
and it fights the project's own no-fake-actions / honesty principle.

The bulk auto-conversion of these to `log.debug("suppressed exception",
exc_info=True)` was *attempted and reverted*: a meaningful subset live in code that
runs at module-import time before the module's `log` is bound, so a blind rewrite
breaks import (`NameError: name 'log' is not defined`). Converting them safely
requires per-site scope checking, done incrementally.

What this test gives us now: a **ratchet**. The count can't grow — a new silent
swallow fails CI (`cross-platform-smoke` runs this file). To clear a real one,
make it observable (log it, with `log` proven in scope) and lower CEILING; never
raise it to hide a new swallow.
"""
import ast
import glob
import os

# Current count of silent `except: pass` handlers across eli/. Ratchet DOWN only.
CEILING = 169
# Catch-all handlers (bare, Exception, BaseException) that only log. Observable in a debug log, but
# the caller still carries on as if the step worked: a failed run read as a clean one this way.
# Ratchet DOWN only: a new one must decide what the failure means for the result.
LOG_ONLY_CEILING = 1685

_ELI_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "eli"))
_LOGGERS = {"log", "logger", "logging", "_log", "LOG", "_logger"}


def _catch_all(handler: ast.ExceptHandler) -> bool:
    kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return handler.type is None or any(isinstance(k, ast.Name) and k.id in ("Exception", "BaseException")
                                       for k in kinds)


def _logs_only(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    f = stmt.value.func if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) else None
    return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in _LOGGERS


def _count_swallows() -> tuple:
    silent = log_only = 0
    for f in glob.glob(os.path.join(_ELI_ROOT, "**", "*.py"), recursive=True):
        try:
            tree = ast.parse(open(f, encoding="utf-8").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                silent += 1
            elif _catch_all(node) and all(_logs_only(s) for s in node.body):
                log_only += 1
    return silent, log_only


def test_silent_swallows_do_not_grow():
    silent, log_only = _count_swallows()
    assert silent <= CEILING, (
        f"{silent} silent `except: pass` handlers in eli/ — over the {CEILING} ceiling. "
        f"A new silent swallow was added: make it observable "
        f"(`log.debug('suppressed exception', exc_info=True)`, with `log` in scope) "
        f"instead of swallowing the failure. Never raise CEILING to admit a new one; "
        f"lower it as you clear real ones."
    )
    assert log_only <= LOG_ONLY_CEILING, (
        f"{log_only} catch-all handlers in eli/ only log — over the {LOG_ONLY_CEILING} ceiling. A new one "
        f"was added: catch what can actually fail, and make the result say it failed. Lower the ceiling "
        f"as you clear them; never raise it."
    )
