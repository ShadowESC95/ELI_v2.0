import json
import pytest
from unittest.mock import patch
from eli.core.runtime_settings import load_settings, save_settings
import eli.core.runtime_settings as rs

def test_save_load_settings(tmp_path):
    def fake_settings_file():
        return tmp_path / "settings.json"
    with patch.object(rs, "_settings_file", fake_settings_file):
        save_settings({"test": 123})
        loaded = load_settings()
        assert loaded.get("test") == 123
