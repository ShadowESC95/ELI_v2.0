"""#7 — observability lint: freeze the silent `except: pass` count, fail on growth.

A silent `except …: pass` (a handler whose entire body is just `pass`) hides
failures — it's the main reason bugs in ELI tend to surface only via runtime logs,
and it fights the project's own no-fake-actions / honesty principle.

The bulk auto-conversion of these to `log.debug("suppressed exception",
exc_info=True)` was *attempted and reverted*: a meaningful subset live in code that
runs at module-import time before the module's `log` is bound, so a blind rewrite
breaks import (`NameError: name 'log' is not defined`). Converting them safely
requires per-site scope checking, done incrementally.

What this test gives us now: a **ratchet**. The count can't grow — a new silent
swallow fails CI. To clear a real one, make it observable (log it, with `log`
proven in scope) and lower CEILING; never raise it to hide a new swallow.
"""
import ast
import glob
import os

# Current count of silent `except: pass` handlers across eli/. Ratchet DOWN only.
CEILING = 950

_ELI_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "eli"))


def _count_silent_swallows() -> int:
    n = 0
    for f in glob.glob(os.path.join(_ELI_ROOT, "**", "*.py"), recursive=True):
        try:
            tree = ast.parse(open(f, encoding="utf-8").read())
        except Exception:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.ExceptHandler)
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)):
                n += 1
    return n


def test_silent_swallows_do_not_grow():
    n = _count_silent_swallows()
    assert n <= CEILING, (
        f"{n} silent `except: pass` handlers in eli/ — over the {CEILING} ceiling. "
        f"A new silent swallow was added: make it observable "
        f"(`log.debug('suppressed exception', exc_info=True)`, with `log` in scope) "
        f"instead of swallowing the failure. Never raise CEILING to admit a new one; "
        f"lower it as you clear real ones."
    )
