"""Shutdown/cancel must register llama_set_abort_callback for prefill abort, and the callback must
outlive every model it is set on."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_gguf_inference_installs_abort_callback():
    src = (ROOT / "eli/cognition/gguf_inference.py").read_text(encoding="utf-8")
    assert "_install_llama_abort_callback(_llm)" in src


def test_a_new_load_does_not_free_the_callback_of_a_model_still_decoding(small_chat_model):
    """A full test run died with SIGSEGV in llama_decode: a background job was decoding on one model
    when another load replaced the only reference to that model's abort callback. The same happens in
    the app when the model reloads during a background generation. Run apart, so a crash is a failure."""
    pytest.importorskip("llama_cpp")
    if not small_chat_model:
        pytest.skip("no chat GGUF in models/")
    script = (
        "import gc, sys\n"
        "from llama_cpp import Llama\n"
        "from eli.cognition import gguf_inference as G\n"
        "first = Llama(model_path=sys.argv[1], n_ctx=256, n_threads=2, verbose=False)\n"
        "G._install_llama_abort_callback(first)\n"
        "second = Llama(model_path=sys.argv[1], n_ctx=256, n_threads=2, verbose=False)\n"
        "G._install_llama_abort_callback(second)\n"
        "gc.collect()\n"
        "first.eval(first.tokenize(b'a background job still decoding on the first model'))\n"
        "print('decoded')\n")
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", script, small_chat_model], cwd=str(ROOT), env=env,
                         capture_output=True, text=True, timeout=600)
    assert out.returncode == 0 and "decoded" in out.stdout, (out.returncode, out.stderr[-800:])
