"""Device selection has to be honest on hardware this was not written on.

The old rule was a flat `free_vram >= 10 GiB` floor, written for a Phi-3 on an 8 GB
card, with the failure mode being a silent fall-through to CPU — where a run takes
days and looks to the operator exactly like a hang. It also named every accelerator
"cuda", so an AMD owner was shown CUDA on a Radeon.

The floor is now the model's own estimated requirement, the vendor is reported as
what it is, and a refusal has to say what would fix it.
"""
from unittest.mock import MagicMock, patch

import pytest

from eli.learning import lora_trainer as lt


def _torch(*, cuda=True, hip=None, name="NVIDIA GeForce RTX 4090",
           free=20 * 1024 ** 3, total=24 * 1024 ** 3):
    t = MagicMock()
    t.cuda.is_available.return_value = cuda
    t.cuda.get_device_name.return_value = name
    t.cuda.mem_get_info.return_value = (free, total)
    t.version.hip = hip
    t.backends.mps.is_available.return_value = False
    t.xpu.is_available.return_value = False
    return t


def test_amd_is_reported_as_amd_not_cuda():
    with patch.dict("sys.modules", {"torch": _torch(hip="6.2", name="AMD Radeon RX 7900 XTX")}):
        acc = lt._accelerator()
    assert acc["vendor"] == "amd"
    assert acc["kind"] == "cuda"          # torch routes ROCm through the cuda API
    assert acc["trainable"] is True
    assert "ROCm" in acc["note"]


def test_nvidia_is_reported_as_nvidia():
    with patch.dict("sys.modules", {"torch": _torch()}):
        acc = lt._accelerator()
    assert acc["vendor"] == "nvidia"
    assert acc["trainable"] is True


def test_apple_and_intel_are_named_and_marked_untrainable():
    t = _torch(cuda=False)
    t.backends.mps.is_available.return_value = True
    with patch.dict("sys.modules", {"torch": t}):
        acc = lt._accelerator()
    assert acc["vendor"] == "apple" and acc["trainable"] is False and acc["note"]

    t2 = _torch(cuda=False)
    t2.backends.mps.is_available.return_value = False
    t2.xpu.is_available.return_value = True
    with patch.dict("sys.modules", {"torch": t2}):
        acc2 = lt._accelerator()
    assert acc2["vendor"] == "intel" and acc2["trainable"] is False


def test_mocked_torch_never_produces_a_mock_vram_number():
    """A Mock leaking into the VRAM comparison used to raise TypeError inside job
    building, which the pipeline swallowed as a failed stage."""
    t = MagicMock()
    t.cuda.is_available.return_value = True
    t.version.hip = None
    with patch.dict("sys.modules", {"torch": t}):
        acc = lt._accelerator()
    assert isinstance(acc["free_gb"], float)
    assert isinstance(acc["total_gb"], float)


def test_small_model_fits_a_small_card(tmp_path):
    """The old flat 10 GiB floor refused a 1B on a 6 GB card that fits easily."""
    tiny = tmp_path / "tiny"
    tiny.mkdir()
    (tiny / "model.safetensors").write_bytes(b"\0" * (1024 ** 3))  # ~1 GB
    with patch.dict("sys.modules", {"torch": _torch(free=6 * 1024 ** 3, total=8 * 1024 ** 3)}):
        d = lt._pick_device("auto", base_model_path=tiny)
    assert d["selected"] == "cuda"


def test_refusal_explains_what_would_fix_it(tmp_path):
    big = tmp_path / "big"
    big.mkdir()
    (big / "model.safetensors").write_bytes(b"\0" * 8192)
    with patch.object(lt, "estimate_vram_gb", return_value=40.0):
        with patch.dict("sys.modules", {"torch": _torch(free=6 * 1024 ** 3, total=8 * 1024 ** 3)}):
            d = lt._pick_device("auto", base_model_path=big)
    assert d["selected"] == "cpu"
    assert "hours to days" in d["reason"]        # not a silent fall-through
    assert "bitsandbytes" in d["reason"]         # and a route out


def test_cpu_only_machine_says_so_plainly():
    with patch.dict("sys.modules", {"torch": _torch(cuda=False)}):
        d = lt._pick_device("auto")
    assert d["selected"] == "cpu"
    assert d["four_bit"] is False
    assert d["reason"]


def test_four_bit_lowers_the_requirement(tmp_path):
    m = tmp_path / "m"
    m.mkdir()
    (m / "model.safetensors").write_bytes(b"\0" * (4 * 1024 ** 3))
    assert lt.estimate_vram_gb(m, four_bit=True) < lt.estimate_vram_gb(m, four_bit=False)


def test_explicit_cpu_request_is_obeyed():
    with patch.dict("sys.modules", {"torch": _torch()}):
        assert lt._pick_device("cpu")["selected"] == "cpu"
