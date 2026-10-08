"""A settings check that runs out of time says how far it got, and a pass is kept even if late.

Every launch since mid-September logged only "probe timed out after 106s (unproven)": nothing said
whether the model had loaded, or whether the test prompt was what ran long.
"""
import subprocess

import pytest

from eli.core import load_probe as lp


@pytest.fixture
def probe(monkeypatch, tmp_path):
    monkeypatch.setattr(lp, "_cache_path", lambda: tmp_path / "cache.json")
    monkeypatch.setattr(lp, "_gpu_identity", lambda: "test-gpu|8192")
    monkeypatch.setattr(lp, "_free_vram_mb", lambda: 6000)
    monkeypatch.delenv("ELI_LOAD_PROBE", raising=False)

    def run_with(stdout):
        def _run(*a, **k):
            raise subprocess.TimeoutExpired(cmd="probe", timeout=k.get("timeout"), output=stdout)
        monkeypatch.setattr(lp.subprocess, "run", _run)
        return lp.probe_verdict(str(tmp_path / "m.gguf"), 16000, 28, 192, use_cache=False, timeout_s=5)
    return run_with


def test_loaded_but_the_prompt_did_not_finish(probe):
    verdict, why = probe(b"LOADED 31.4\n")
    assert verdict == lp.UNPROVEN_TIMEOUT
    assert "loaded in 31.4s" in why and "7200-token test prompt had not finished" in why


def test_did_not_finish_loading(probe):
    verdict, why = probe(b"")
    assert verdict == lp.UNPROVEN_TIMEOUT and "had not finished loading" in why


def test_a_pass_printed_before_the_cut_is_a_pass(probe):
    verdict, _ = probe("LOADED 20.0\nPROBE_OK 41.2\n")
    assert verdict == lp.PROVEN_OK


def test_the_child_reports_each_stage_and_skips_teardown():
    assert 'print("LOADED' in lp._CHILD and 'print("PROBE_OK' in lp._CHILD
    assert "os._exit(0)" in lp._CHILD
