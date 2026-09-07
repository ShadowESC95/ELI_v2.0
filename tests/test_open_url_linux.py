"""Linux browser open URL tests."""
import os

from eli.utils import platform_compat as pc


def test_linux_open_url_skips_hung_firefox(monkeypatch):
    monkeypatch.setattr(pc, "LINUX", True)
    monkeypatch.setattr(pc, "ANDROID", False)
    calls = []

    def _fake_try(argv):
        calls.append(argv)
        base = os.path.basename(argv[0])
        if base == "firefox":
            return False
        return base in {"chromium", "google-chrome"}

    def _fake_paths(name):
        return {
            "google-chrome": ["/usr/bin/google-chrome"],
            "chromium": ["/usr/bin/chromium"],
            "firefox": ["/usr/bin/firefox"],
        }.get(name, [])

    monkeypatch.setattr(pc, "_executable_paths", _fake_paths)
    monkeypatch.setattr(pc, "_linux_try_browser", _fake_try)
    assert pc._linux_open_url("https://www.youtube.com/watch?v=test") is True
    assert os.path.basename(calls[0][0]) == "google-chrome"
    assert all(os.path.basename(c[0]) != "firefox" for c in calls)
