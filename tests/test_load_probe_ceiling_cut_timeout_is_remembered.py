"""A probe that cannot finish inside its ceiling must not re-pay it every launch.

Live report (2.4.61): a 22GB model, ctx 12380. The probe's own estimate
(30 + 22.3*10 + 12.4*2 = ~277s) exceeds its 180s ceiling, so it could never finish;
it timed out, fell back to the measured fit, and the timeout memo expired after an
hour -- so every fresh session spent three minutes proving nothing, under a
message that said "one-off, then cached".
"""
import time

import pytest

from eli.core import load_probe as lp


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.delenv("ELI_LOAD_PROBE_TIMEOUT", raising=False)
    monkeypatch.setattr(lp, "_cache_path", lambda: tmp_path / "cache.json")
    monkeypatch.setattr(lp, "_gpu_identity", lambda: "test-gpu|8192")
    p = tmp_path / "m.gguf"
    with open(p, "wb") as f:
        f.truncate(int(22.3 * 1024 ** 3))          # sparse: no real disk used
    return str(p)


def test_a_big_model_is_flagged_as_expected_to_be_cut(model):
    assert lp.budget_is_ceiling_cut(model, 12380) is True


def test_a_small_model_is_not(tmp_path, monkeypatch):
    monkeypatch.delenv("ELI_LOAD_PROBE_TIMEOUT", raising=False)
    p = tmp_path / "s.gguf"
    with open(p, "wb") as f:
        f.truncate(3 * 1024 ** 3)
    assert lp.budget_is_ceiling_cut(str(p), 8192) is False


def test_an_explicit_timeout_override_is_never_called_cut(model, monkeypatch):
    monkeypatch.setenv("ELI_LOAD_PROBE_TIMEOUT", "600")
    assert lp.budget_is_ceiling_cut(model, 12380) is False


def test_a_ceiling_cut_timeout_outlives_the_hour(model, monkeypatch):
    lp._record_timeout(model, 12380, 10, 256)
    real = time.time()
    monkeypatch.setattr(lp.time, "time", lambda: real + 3 * 3600)     # 3h later
    assert lp._recently_timed_out(model, 12380, 10, 256) is True


def test_an_ordinary_timeout_still_expires_after_the_hour(tmp_path, monkeypatch):
    monkeypatch.delenv("ELI_LOAD_PROBE_TIMEOUT", raising=False)
    monkeypatch.setattr(lp, "_cache_path", lambda: tmp_path / "cache.json")
    monkeypatch.setattr(lp, "_gpu_identity", lambda: "test-gpu|8192")
    p = tmp_path / "s.gguf"
    with open(p, "wb") as f:
        f.truncate(3 * 1024 ** 3)
    lp._record_timeout(str(p), 8192, 10, 256)
    real = time.time()
    monkeypatch.setattr(lp.time, "time", lambda: real + 3 * 3600)
    assert lp._recently_timed_out(str(p), 8192, 10, 256) is False


def test_a_different_model_file_does_not_inherit_the_memo(model, tmp_path):
    lp._record_timeout(model, 12380, 10, 256)
    other = tmp_path / "m.gguf"
    with open(other, "wb") as f:
        f.truncate(int(23.5 * 1024 ** 3))       # same path, replaced file
    assert lp._recently_timed_out(str(other), 12380, 10, 256) is False
