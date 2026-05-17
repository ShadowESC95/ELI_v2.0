
from __future__ import annotations

import ast

import pytest


def _src(repo_root):
    return (repo_root / "gui/eli_pro_audio_gui_MKI.py").read_text(encoding="utf-8", errors="ignore")


def test_gui_file_parses(repo_root):
    ast.parse(_src(repo_root), filename="eli_pro_audio_gui_MKI.py")


@pytest.mark.parametrize("needle", [
    "class ELIEntropicGUI",
    "class ELIWorker",
    "class LLMStreamWorker",
    "def main(",
    "from eli.brain.cognition import gguf_inference",
    "from eli.brain.proactive.proactive_daemon import start_daemon",
])
def test_gui_contains_expected_runtime_hooks(repo_root, needle: str):
    assert needle in _src(repo_root)


@pytest.mark.parametrize("forbidden", ["/home/jay", "jay@ghost", 'Path.home() / ".eli_mkvii"'])
def test_gui_contains_no_user_specific_paths(repo_root, forbidden: str):
    assert forbidden not in _src(repo_root)
