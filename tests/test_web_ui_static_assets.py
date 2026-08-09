"""Locks on the web UI living in real files rather than a Python string.

The UI was a single 233KB triple-quoted literal inside api/server.py: unlintable,
undiffable in review, and untouchable by an editor or a designer. It now lives in
api/static/ as index.html + app.css + app.js.

The extraction had one trap worth remembering: the literal contained 140 `\\'`
sequences, which Python turns into `\'` at runtime. Copying the *source text* into
a file would have shipped the doubled backslashes and broken the JavaScript, so the
split was done on the evaluated string. The round-trip was verified byte-identical.

The failure mode these guard against is silent and total — a missing or unmounted
asset serves an unstyled, non-functional page, and only in a packaged build.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "api" / "static"
SERVER = REPO_ROOT / "api" / "server.py"


@pytest.mark.parametrize("name,floor", [
    ("index.html", 2_000),
    ("app.css", 20_000),
    ("app.js", 100_000),
])
def test_asset_exists_and_is_not_truncated(name, floor):
    f = STATIC / name
    assert f.is_file(), f"missing UI asset: {f}"
    assert f.stat().st_size > floor, f"{name} looks truncated ({f.stat().st_size} bytes)"


def test_index_references_both_assets():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '/static/app.css' in html
    assert '/static/app.js' in html


def test_theme_script_stayed_inline():
    """The no-FOUC theme init must run before paint; moving it into app.js would
    flash the dark theme at users who chose light."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    head = html[: html.index("</head>")]
    assert "eli_theme" in head and "<script>" in head


def test_javascript_escapes_survived_extraction():
    """The `\\'` trap: doubled backslashes here would mean the file was built from
    the source literal instead of its evaluated value."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "\\\\'" not in js, "JS carries doubled backslashes — extracted from source text, not runtime value"
    assert "\\'" in js, "expected escaped quotes inside the JS string literals"


# ── the page must still be assembled and served ─────────────────────────────
def test_server_no_longer_embeds_the_ui():
    src = SERVER.read_text(encoding="utf-8")
    assert "_WEB_UI = \"\"\"" not in src, "the 233KB literal is back in server.py"
    assert "def _web_ui(" in src


def test_static_is_mounted():
    src = SERVER.read_text(encoding="utf-8")
    assert 'app.mount("/static"' in src


def _load_loader(static_dir: Path):
    """Exec the real `_web_ui` source against a chosen static dir.

    conftest force-mocks pydantic for the whole suite, so `import api.server`
    raises and the loader cannot be reached the ordinary way. Lifting the actual
    function out of the file still exercises the shipped code — importing a
    mocked module would only have proved the mock works.
    """
    lines = SERVER.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, l in enumerate(lines) if l.startswith("_UI_CACHE"))
    body = next(i for i, l in enumerate(lines) if l.startswith("def _web_ui("))
    # Run to the end of the function: the first line after it that starts a new
    # top-level statement. Slicing on `return _UI_CACHE["html"]` instead cut the
    # function off at the fallback branch and never defined the real logic.
    end = next(i for i in range(body + 1, len(lines))
               if lines[i].strip() and not lines[i][0].isspace())
    ns: dict = {"_STATIC_DIR": static_dir, "Path": Path}
    exec(compile("".join(lines[start:end]), "loader", "exec"), ns)
    return ns["_web_ui"]


def test_loader_returns_the_index():
    html = _load_loader(STATIC)()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "/static/app.js" in html


def test_loader_picks_up_edits(tmp_path):
    """Cached on mtime — a stale cache would make UI edits appear to do nothing."""
    import os

    fake = tmp_path / "static"
    fake.mkdir()
    index = fake / "index.html"
    index.write_text("<!doctype html>first", encoding="utf-8")
    web_ui = _load_loader(fake)

    assert "first" in web_ui()

    index.write_text("<!doctype html>second", encoding="utf-8")
    os.utime(index, (index.stat().st_atime, index.stat().st_mtime + 10))

    assert "second" in web_ui()


def test_missing_assets_degrade_instead_of_crashing(tmp_path):
    out = _load_loader(tmp_path / "nope")()
    assert "missing" in out.lower()


# ── and they have to actually ship ──────────────────────────────────────────
def test_assets_are_git_tracked():
    """ELI.spec builds its data manifest from `git ls-files` alone. An untracked
    asset is silently absent from every AppImage/exe, serving an unstyled page in
    the packaged build while working perfectly from source."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "api/static"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:  # pragma: no cover - not a git checkout
        pytest.skip("not a git checkout")
    tracked = {line.strip() for line in out.splitlines() if line.strip()}
    for name in ("index.html", "app.css", "app.js"):
        assert f"api/static/{name}" in tracked, (
            f"api/static/{name} is untracked — it will not be packaged"
        )
