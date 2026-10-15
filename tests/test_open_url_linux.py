"""Linux browser open URL tests."""
import os

from eli.utils import platform_compat as pc


def _fake_paths(name):
    return {
        "google-chrome": ["/usr/bin/google-chrome"],
        "chromium": ["/usr/bin/chromium"],
        "firefox": ["/usr/bin/firefox"],
    }.get(name, [])


def test_linux_open_url_uses_the_default_browser_first(monkeypatch):
    """Chrome came before the user's default browser (xdg-open) whenever it was installed."""
    monkeypatch.setattr(pc, "LINUX", True)
    monkeypatch.setattr(pc, "ANDROID", False)
    monkeypatch.delenv("ELI_BROWSER", raising=False)
    calls = []
    monkeypatch.setattr(pc, "_executable_paths", _fake_paths)
    monkeypatch.setattr(pc.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("xdg-open", "gio") else None)
    monkeypatch.setattr(pc, "_linux_try_browser", lambda argv: calls.append(argv) or True)
    assert pc._linux_open_url("https://www.youtube.com/watch?v=test") is True
    assert calls == [["xdg-open", "https://www.youtube.com/watch?v=test"]]


def test_linux_open_url_skips_hung_firefox_when_there_is_no_default_handler(monkeypatch):
    monkeypatch.setattr(pc, "LINUX", True)
    monkeypatch.setattr(pc, "ANDROID", False)
    monkeypatch.delenv("ELI_BROWSER", raising=False)
    calls = []

    def _fake_try(argv):
        calls.append(argv)
        base = os.path.basename(argv[0])
        if base == "firefox":
            return False
        return base in {"chromium", "google-chrome"}

    monkeypatch.setattr(pc, "_executable_paths", _fake_paths)
    monkeypatch.setattr(pc.shutil, "which", lambda name: None)
    monkeypatch.setattr(pc, "_linux_try_browser", _fake_try)
    assert pc._linux_open_url("https://www.youtube.com/watch?v=test") is True
    assert os.path.basename(calls[0][0]) == "google-chrome"
    assert all(os.path.basename(c[0]) != "firefox" for c in calls)
