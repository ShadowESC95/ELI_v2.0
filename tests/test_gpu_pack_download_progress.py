"""A small component download reports its real size instead of "0 / 0 MB"."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging" / "pyinstaller"))
import eli_gpu_pack  # noqa: E402


class _Resp(io.BytesIO):
    def __init__(self, data, length=True):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))} if length else {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(monkeypatch, tmp_path, data, length=True, capsys=None):
    monkeypatch.setattr(eli_gpu_pack.urllib.request, "urlopen", lambda url, timeout=60: _Resp(data, length))
    eli_gpu_pack._download("http://x/y.whl", tmp_path / "y.whl")
    return capsys.readouterr().out


def test_a_small_download_shows_tenths_of_a_megabyte(monkeypatch, tmp_path, capsys):
    out = _run(monkeypatch, tmp_path, b"x" * 700_000, capsys=capsys)
    assert "0.7 / 0.7 MB" in out and "0 / 0 MB" not in out


def test_a_large_download_shows_whole_megabytes(monkeypatch, tmp_path, capsys):
    out = _run(monkeypatch, tmp_path, b"x" * (12 << 20), capsys=capsys)
    assert "12 / 12 MB" in out


def test_an_unknown_length_shows_what_arrived(monkeypatch, tmp_path, capsys):
    out = _run(monkeypatch, tmp_path, b"x" * 700_000, length=False, capsys=capsys)
    assert "0.7 MB" in out and "/" not in out.replace("[gpu-pack]", "")


def test_the_window_gets_each_step_with_its_real_size(monkeypatch, tmp_path, capsys):
    seen = []
    monkeypatch.setattr(eli_gpu_pack.urllib.request, "urlopen",
                        lambda url, timeout=60: _Resp(b"x" * (12 << 20)))
    eli_gpu_pack._download("http://x/pack.whl?sig=1", tmp_path / "y.whl",
                           lambda text, pct: seen.append((text, pct)))
    assert seen[-1] == ("Downloading pack.whl: 12 / 12 MB", 100)
    monkeypatch.setattr(eli_gpu_pack.urllib.request, "urlopen",
                        lambda url, timeout=60: _Resp(b"x" * 700_000, length=False))
    eli_gpu_pack._download("http://x/cudart.whl", tmp_path / "z.whl",
                           lambda text, pct: seen.append((text, pct)))
    assert seen[-1] == ("Downloading cudart.whl: 0.7 MB", None)


def test_the_pack_follows_the_detected_vendor_not_the_card_name():
    from types import SimpleNamespace as hw
    take = eli_gpu_pack.pack_backend_for
    assert take(hw(has_gpu=True, gpu_vendor="nvidia", gpu_integrated=False)) == "cuda"
    assert take(hw(has_gpu=True, gpu_vendor="amd", gpu_integrated=False)) == "vulkan"
    assert take(hw(has_gpu=True, gpu_vendor="intel", gpu_integrated=True)) == "vulkan"
    assert take(hw(has_gpu=True, gpu_vendor="qualcomm", gpu_integrated=True)) == "vulkan"
    assert take(hw(has_gpu=True, gpu_vendor="unknown", gpu_integrated=False)) == "vulkan"
    assert take(hw(has_gpu=False, gpu_vendor="", gpu_integrated=False)) == ""
