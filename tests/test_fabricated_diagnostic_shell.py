"""Block invented journalctl/bash blocks on conversational turns."""
from eli.cognition.output_governor import (
    govern_output,
    strip_fabricated_diagnostic_shell,
)


def test_journalctl_block_is_stripped():
    text = (
        "Yeah, the timestamp reading is broken. Let me check the logs.\n\n"
        "```bash\njournalctl -u eli --since \"1 hour ago\" | grep timestamp\n```"
    )
    cleaned = strip_fabricated_diagnostic_shell(text)
    assert "journalctl" not in cleaned
    assert "```" not in cleaned


def test_govern_output_applies_shell_strip():
    text = (
        "I'll check runtime logs.\n\n"
        "```bash\ngrep -i timestamp ~/.eli/logs/\n```"
    )
    out = govern_output(text, is_grounded=False)
    assert "grep" not in out.lower()
    assert "```" not in out
