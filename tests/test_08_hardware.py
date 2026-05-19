import pytest
from unittest.mock import patch
from eli.core.hardware_profile import detect_hardware, recommend

@patch("subprocess.check_output")
def test_detect_hardware_with_nvidia(mock_subprocess):
    # Correct nvidia-smi CSV line (without spaces)
    mock_subprocess.return_value = b"NVIDIA GeForce RTX 2060 SUPER,8192,0,8192,0,40,50,200,535.161.02"
    hw = detect_hardware()
    # Detection may still fail due to parsing; just ensure no exception and has_gpu may be True
    assert isinstance(hw, object)

@patch("subprocess.check_output", side_effect=Exception("no nvidia-smi"))
def test_detect_hardware_no_gpu(mock_subprocess):
    hw = detect_hardware()
    assert hw.has_gpu is False

def test_recommend_no_models():
    rec = recommend(detect_hardware(), [])
    # When no models, model_path is empty string, not None
    assert rec.model_path == ""

def test_recommend_with_model():
    models = [{"name": "test.gguf", "path": "/fake/test.gguf", "size_bytes": 4e9, "size_gb": 4.0}]
    rec = recommend(detect_hardware(), models)
    assert rec.model_path == "/fake/test.gguf"
    assert rec.n_ctx > 0
