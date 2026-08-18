"""The operator's load settings are used as entered, or proven not to work.

Live at 2.2.7, on a card with 6268MB free:

    [GUI][LOAD] smart-fit ... : ctx=10384 gpu_layers=28
    [GUI][LOAD] smart-fit reduced GPU layers 99->28 to fit 6268MB free VRAM
    [GUI][LOAD] attempt 1/13: requested (ctx=10384 gpu_layers=99 batch=128)
    [GUI][LOAD] selected=requested (ctx=10384 gpu_layers=99 batch=128)
    ✅ Model loaded successfully
    ...
    [GGUF][TIMING] prompt_tokens=5189
    ggml-cuda.cu:98: CUDA error  ->  Aborted (core dumped)

Two wrong answers were tried before this one.

The first was the loader's original reasoning: queue the operator's numbers
first, and if the hardware cannot honour them the driver will refuse, costing
one failed attempt before the fallbacks take over. llama.cpp/CUDA allocate
LAZILY, so no refusal comes. The load reports success, wins the ladder, and the
process is killed later by abort() inside the CUDA backend — with no failed
attempt to fall back FROM, so none of the twelve remaining rungs can run. It
survived earlier releases only because their first turn was a short greeting
whose KV cache stayed small.

The second was to clamp the layer count to what a VRAM calculation predicted.
That removes the crash by overruling the operator, which is the opposite of
honouring the setting, and it makes ELI's arithmetic the authority on hardware
it is only estimating.

The answer is to MEASURE. eli/core/load_probe.py loads the exact requested
parameters in a SEPARATE PROCESS and drives a real decode through them. A parent
can survive a child's abort(); it cannot survive its own. A clean probe means
the settings are used verbatim — now a fact about this machine rather than an
assumption. A failed probe is the "cannot be honoured" signal the ladder was
always meant to receive.

Nothing is capped, substituted or hardcoded. The probe's own sizes derive from
the caller's context, the verdict is cached per (model, parameters, GPU), and a
probe that cannot RUN returns pass — an unavailable check must never become a
reason to override the operator.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from eli.core import load_probe

LOADER = (pathlib.Path(__file__).resolve().parents[1]
          / "eli" / "gui" / "eli_pro_audio_gui_v2_0.py")


def _code(src: str) -> str:
    return "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def loader_src():
    src = LOADER.read_text(encoding="utf-8")
    i = src.index("def _add_attempt(")
    j = src.index("Hardware profile recommendation", i)
    return src[i:j]


# ── the settings go in untouched ───────────────────────────────────────────
def test_the_request_is_queued_verbatim(loader_src):
    """No clamp, no substitution: the operator's own three numbers."""
    code = _code(loader_src)
    m = re.search(r'_add_attempt\("requested",\s*([^)]*)\)', code)
    assert m, "requested attempt not found"
    args = m.group(1)
    assert "_base_ctx" in args and "_base_layers" in args and "_base_batch" in args
    for calculated in ("_sf_ctx", "_sf_layers", "_sf_batch", "_req_layers", "_sf_fit_layers"):
        assert calculated not in args, \
            f"the request is being replaced with {calculated}"


def test_nothing_reduces_the_requested_layers(loader_src):
    code = _code(loader_src)
    assert "min(" not in code.split("_add_attempt(\"requested\"")[0].split("_base_layers = ")[-1][:400]
    assert "_req_layers" not in code, "a clamp variable is back"


def test_the_request_is_still_the_first_attempt(loader_src):
    code = _code(loader_src)
    assert "front=True" in code
    assert "_attempts.insert(0, _entry)" in code


def test_the_request_is_marked_for_verification(loader_src):
    """Conditionally: only when it exceeds what the fit measured. An
    unconditional verify=True is what made 2.2.8 probe every GPU start."""
    code = _code(loader_src)
    assert "verify=_needs_proof" in code


def test_only_the_request_is_verified(loader_src):
    """ELI's own calculated rungs are the fallback; verifying them would just
    spend probes on the thing being fallen back to."""
    code = _code(loader_src)
    assert code.count("verify=_needs_proof") == 1, "exactly one attempt is verified"
    assert "verify: bool = False" in code, "every other attempt defaults to unverified"


# ── the loader acts on the verdict ─────────────────────────────────────────
def test_the_loader_probes_before_loading():
    src = LOADER.read_text(encoding="utf-8")
    i = src.index('if _cand.get("verify"):')
    j = src.index("llama_kwargs: Dict[str, Any] = dict(", i)
    window = src[i:j]
    assert "probe_config" in window
    assert "continue" in window, "a failed verdict must fall through to the next rung"


def test_a_probe_that_cannot_run_does_not_override_the_operator():
    src = LOADER.read_text(encoding="utf-8")
    i = src.index('if _cand.get("verify"):')
    window = src[i:i + 1600]
    assert "_ok, _why = True" in window, \
        "an unavailable probe must leave the operator's settings standing"


def test_the_failure_message_says_nothing_was_altered():
    src = LOADER.read_text(encoding="utf-8")
    i = src.index('if _cand.get("verify"):')
    window = src[i:i + 1800].lower()
    assert "not being altered" in window


# ── the probe's own contract ───────────────────────────────────────────────
def test_a_cpu_only_config_is_not_probed():
    """No GPU allocation to prove, and a probe would cost a full cold load."""
    ok, why = load_probe.probe_config("/nonexistent.gguf", 4096, 0, 128,
                                      use_cache=False)
    assert ok is True
    assert "cpu-only" in why


def test_the_probe_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ELI_LOAD_PROBE", "0")
    ok, why = load_probe.probe_config("/nonexistent.gguf", 4096, 99, 128,
                                      use_cache=False)
    assert ok is True
    assert "disabled" in why


def test_a_timeout_is_unproven_not_failed(monkeypatch):
    """Slow hardware must not have its settings overridden for being slow."""
    import subprocess

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="probe", timeout=1)

    monkeypatch.setattr(load_probe.subprocess, "run", _boom)
    ok, why = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert ok is True
    assert "unproven" in why


def test_an_unavailable_probe_is_unproven_not_failed(monkeypatch):
    def _boom(*a, **k):
        raise OSError("no subprocess here")

    monkeypatch.setattr(load_probe.subprocess, "run", _boom)
    ok, why = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert ok is True
    assert "unavailable" in why


def test_a_missing_llama_cpp_in_the_child_is_unproven(monkeypatch):
    """rc=3 is "the check could not run", not "your settings are bad"."""
    class _R:
        returncode = 3
        stdout = ""
        stderr = "IMPORT_FAIL:No module named 'llama_cpp'"

    monkeypatch.setattr(load_probe.subprocess, "run", lambda *a, **k: _R())
    ok, _ = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert ok is True


def test_a_real_failure_is_reported_as_failure(monkeypatch, tmp_path):
    class _R:
        returncode = 4
        stdout = ""
        stderr = "LOAD_FAIL:Failed to load model from file: /x.gguf"

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe.subprocess, "run", lambda *a, **k: _R())
    ok, why = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert ok is False
    assert "Failed to load model" in why


def test_an_abort_signal_is_reported_as_failure(monkeypatch, tmp_path):
    """SIGABRT from the CUDA backend is the exact case this exists for; a
    negative return code is how the parent sees it."""
    class _R:
        returncode = -6
        stdout = ""
        stderr = ""

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe.subprocess, "run", lambda *a, **k: _R())
    ok, _ = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert ok is False


def test_the_destructor_noise_is_not_reported_as_the_reason(monkeypatch, tmp_path):
    """llama_cpp's LlamaModel.__del__ raises after a failed constructor, so the
    LAST stderr line is its noise rather than the real message."""
    class _R:
        returncode = 4
        stdout = ""
        stderr = (
            "LOAD_FAIL:Failed to load model from file: /x.gguf\n"
            "Exception ignored in: <function LlamaModel.__del__>\n"
            "AttributeError: 'LlamaModel' object has no attribute 'sampler'"
        )

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe.subprocess, "run", lambda *a, **k: _R())
    _, why = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert "Failed to load model" in why
    assert "sampler" not in why


# ── probe sizing is derived, never hardcoded ───────────────────────────────
def test_probe_sizes_derive_from_the_callers_context(monkeypatch, tmp_path):
    seen = {}

    class _R:
        returncode = 0
        stdout = "PROBE_OK"
        stderr = ""

    def _capture(cmd, **k):
        seen.update(json.loads(cmd[-1]))
        return _R()

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe.subprocess, "run", _capture)
    load_probe.probe_config("/x.gguf", 20000, 99, 128, use_cache=False)
    big = seen["probe_tokens"]
    seen.clear()
    load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    small = seen["probe_tokens"]
    assert big > small, "probe size must scale with the operator's context"


def test_the_probe_decodes_rather_than_only_loading():
    """The 2.2.7 abort happened with the model already resident and the context
    already created — loading alone proves nothing."""
    src = pathlib.Path(load_probe.__file__).read_text(encoding="utf-8")
    child = src[src.index("_CHILD = r'''"):src.index("def probe_config(")]
    assert "max_tokens" in child and "llm(" in child


# ── caching ────────────────────────────────────────────────────────────────
def test_a_verdict_is_cached_and_reused(monkeypatch, tmp_path):
    calls = []

    class _R:
        returncode = 0
        stdout = "PROBE_OK"
        stderr = ""

    import sys

    def _run(cmd, **k):
        # _gpu_identity() also shells out (nvidia-smi); count only real probes.
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == sys.executable:
            calls.append(1)
        return _R()

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe, "_gpu_identity", lambda: "TestCard|8192")
    monkeypatch.setattr(load_probe.subprocess, "run", _run)
    load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert len(calls) == 1
    ok, why = load_probe.probe_config("/x.gguf", 4096, 99, 128)
    assert ok is True and "cached" in why
    assert len(calls) == 1, "a cached verdict must not re-run the probe"


def test_the_cache_key_includes_the_gpu(monkeypatch, tmp_path):
    """A verdict proven on one card says nothing about another."""
    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe, "_gpu_identity", lambda: "CardA|8192")
    a = load_probe._key("/x.gguf", 4096, 99, 128)
    monkeypatch.setattr(load_probe, "_gpu_identity", lambda: "CardB|24576")
    b = load_probe._key("/x.gguf", 4096, 99, 128)
    assert a != b


def test_the_cache_key_distinguishes_parameters(monkeypatch, tmp_path):
    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    base = load_probe._key("/x.gguf", 4096, 99, 128)
    assert load_probe._key("/x.gguf", 8192, 99, 128) != base
    assert load_probe._key("/x.gguf", 4096, 28, 128) != base
    assert load_probe._key("/x.gguf", 4096, 99, 256) != base


def test_a_stale_verdict_is_re_proven(monkeypatch, tmp_path):
    """Drivers, other GPU tenants and resident models all move."""
    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    load_probe._record("/x.gguf", 4096, 99, 128, True, "ok")
    assert load_probe.cached_verdict("/x.gguf", 4096, 99, 128) is True
    monkeypatch.setenv("ELI_LOAD_PROBE_TTL", "0")
    assert load_probe.cached_verdict("/x.gguf", 4096, 99, 128) is None


def test_an_unproven_result_is_not_cached(monkeypatch, tmp_path):
    """A timeout must not become a permanent pass."""
    import subprocess

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="probe", timeout=1)

    monkeypatch.setattr(load_probe.subprocess, "run", _boom)
    load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert load_probe.cached_verdict("/x.gguf", 4096, 99, 128) is None


# ── the fallback ladder survives ───────────────────────────────────────────
def test_the_calculated_fallbacks_are_still_there(loader_src):
    src = LOADER.read_text(encoding="utf-8")
    assert '_add_attempt("smart-fit"' in src
    for rung in ('"live-tuner-gpu"', '"lower-batch-half"', '"cpu-fallback"'):
        assert rung in src, f"lost the {rung} fallback"

# ── the proof is only spent where there is doubt ───────────────────────────
def test_a_request_inside_the_measured_fit_is_not_probed(loader_src):
    """Shipped without this, 2.2.8 probed every GPU start — including the ones
    certain to pass — and a live launch sat on "attempt 1/13" for 3m29s."""
    code = _code(loader_src)
    assert "_needs_proof" in code
    assert "int(_base_layers) > int(_sf_fit_layers)" in code
    assert "verify=_needs_proof" in code


def test_the_probe_is_announced_before_it_blocks():
    """The silent gap is what made it look hung."""
    src = LOADER.read_text(encoding="utf-8")
    i = src.index('if _cand.get("verify"):')
    j = src.index("probe_config", i)
    window = src[i:j]
    assert "verifying your settings" in window, \
        "the probe still blocks startup with nothing on screen"


def test_the_timeout_is_a_wait_an_operator_would_tolerate():
    from eli.core import load_probe as lp

    assert lp._DEFAULT_TIMEOUT_S <= 90, \
        "a startup probe must not block for minutes"


def test_an_external_termination_is_not_a_verdict(monkeypatch, tmp_path):
    """SIGTERM says nothing about the configuration; caching it as a failure
    would condemn settings that were never actually tested."""
    class _R:
        returncode = -15
        stdout = ""
        stderr = ""

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe, "_gpu_identity", lambda: "TestCard|8192")
    monkeypatch.setattr(load_probe.subprocess, "run", lambda *a, **k: _R())
    ok, why = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert ok is True
    assert "unproven" in why
    assert load_probe.cached_verdict("/x.gguf", 4096, 99, 128) is None


def test_an_abort_is_still_a_verdict(monkeypatch, tmp_path):
    """SIGABRT is the CUDA backend crash this exists to catch."""
    class _R:
        returncode = -6
        stdout = ""
        stderr = ""

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe, "_gpu_identity", lambda: "TestCard|8192")
    monkeypatch.setattr(load_probe.subprocess, "run", lambda *a, **k: _R())
    ok, _ = load_probe.probe_config("/x.gguf", 4096, 99, 128, use_cache=False)
    assert ok is False


def test_the_probe_prompt_stays_realistic(monkeypatch, tmp_path):
    """A cheaper probe (a few batches) was tried and reverted: the operator's
    own logs show ~2147-token prompts passing on a configuration that aborted
    at 5189, so a short probe would have passed every startup before the crash."""
    import json as _json

    seen = {}

    class _R:
        returncode = 0
        stdout = "PROBE_OK"
        stderr = ""

    def _capture(cmd, **k):
        seen.update(_json.loads(cmd[-1]))
        return _R()

    monkeypatch.setattr(load_probe, "_cache_path", lambda: tmp_path / "p.json")
    monkeypatch.setattr(load_probe, "_gpu_identity", lambda: "TestCard|8192")
    monkeypatch.setattr(load_probe.subprocess, "run", _capture)
    load_probe.probe_config("/x.gguf", 10384, 99, 128, use_cache=False)
    assert seen["probe_tokens"] >= 4000, \
        "the probe prompt is too small to reach the allocation that crashes"
