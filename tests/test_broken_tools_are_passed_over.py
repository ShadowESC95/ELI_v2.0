"""A Python-script tool that can no longer start is passed over for one that can.

After Ubuntu 26.04 replaced Python 3.12, ~/.local/bin/yt-dlp (first on PATH) and an old
install's .venv/bin/yt-dlp still existed and were executable, but their Python was gone. ELI
took the first one and so did mpv: YouTube playback failed with "mpv could not start playback".
"""
import os
import sys

import pytest

from eli.integrations.media import media_deps as md

pytestmark = pytest.mark.skipif(os.name == "nt", reason="shebang scripts")


def _script(path, first_line, body=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{first_line}\n{body}")
    path.chmod(0o755)
    return str(path)


def test_a_broken_first_copy_on_path_is_skipped(tmp_path, monkeypatch):
    _script(tmp_path / "old" / "yt-dlp", "#!/nonexistent/python3.12")
    good = _script(tmp_path / "new" / "yt-dlp", f"#!{sys.executable}", "print('2026.1.1')")
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path / "old"), str(tmp_path / "new"), "/usr/bin", "/bin"]))
    assert md.resolve_binary("yt-dlp") == good


def test_mpv_is_told_which_yt_dlp_to_use(tmp_path, monkeypatch):
    good = _script(tmp_path / "new" / "yt-dlp", f"#!{sys.executable}", "print('2026.1.1')")
    monkeypatch.setattr(md, "resolve_binary", lambda name: good if name == "yt-dlp" else f"/usr/bin/{name}")
    from eli.integrations.media.youtube_playback import build_mpv_youtube_argv
    argv, _ = build_mpv_youtube_argv("song", ipc_path=str(tmp_path / "s"), headless=True)
    assert f"--script-opts=ytdl_hook-ytdl_path={good}" in argv
