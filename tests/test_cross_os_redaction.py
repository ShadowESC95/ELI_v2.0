"""Cross-platform home-path redaction (regression, 2026-07-04).

The runtime output redactor was Linux-only — it stripped `/home/<user>` and `~<user>`
but NOT macOS (`/Users/<user>`) or Windows (`C:\\Users\\<user>`) home paths, so on those
OSes a user's home path (and username) could leak into ELI's output. This locks in the
fix: all three path styles are redacted, on any platform, for the current user.
"""
import getpass

from eli.runtime import deterministic_grounding_gate as G


def _redact(s: str) -> str:
    # The two runtime redactors that carry the home-path stripping.
    return G._eli_v12_redact(G._eli_v11_redact_user_identity(s))


def test_linux_home_path_redacted():
    u = getpass.getuser()
    out = _redact(f"I wrote it to /home/{u}/notes/todo.txt")
    assert u not in out, out
    assert "/home/<user>" in out, out


def test_macos_home_path_redacted():
    u = getpass.getuser()
    out = _redact(f"Saved at /Users/{u}/Documents/a.md")
    assert u not in out, out
    assert "/Users/<user>" in out, out


def test_windows_home_path_redacted():
    u = getpass.getuser()
    out = _redact(f"File written: C:\\Users\\{u}\\Desktop\\x.txt")
    assert u not in out, out
    assert "<user>" in out, out


def test_all_three_in_one_string():
    u = getpass.getuser()
    s = f"/home/{u}/a and /Users/{u}/b and D:\\Users\\{u}\\c"
    out = _redact(s)
    assert u not in out, out


def test_unrelated_text_untouched():
    # Redaction must not mangle ordinary text that merely contains a common word.
    s = "The user opened a file in their home directory."
    out = _redact(s)
    assert "home directory" in out
