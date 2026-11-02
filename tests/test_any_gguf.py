"""Any GGUF a person downloads: nothing here depends on what family or file name it has."""
from __future__ import annotations

import struct
import threading
import types

import pytest

from eli.cognition import chat_template as ct, model_output_tokens as mot
from eli.core import gguf_sizes as gs


def _string(s):
    b = s.encode()
    return struct.pack("<Q", len(b)) + b


def _gguf(path, meta, tensors=()):
    out = b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", len(tensors)) + struct.pack("<Q", len(meta))
    for k, v in meta.items():
        out += _string(k)
        out += struct.pack("<I", 4) + struct.pack("<I", v) if isinstance(v, int) else struct.pack("<I", 8) + _string(v)
    offset = 0
    for name, size in tensors:
        out += _string(name) + struct.pack("<I", 1) + struct.pack("<Q", size) + struct.pack("<I", 0) + struct.pack("<Q", offset)
        offset += size
    out += b"\0" * (-len(out) % 32) + b"\0" * offset
    path.write_bytes(out)
    return path


@pytest.mark.parametrize("source, folded, parts", [
    # ignores a system turn without a word, as several public models do
    ("{% for m in messages %}{% if m['role'] == 'user' %}<u>{{ m['content'] }}</u>{% endif %}{% endfor %}<a>", True, False),
    # refuses one
    ("{% for m in messages %}{% if m['role'] == 'system' %}{{ raise_exception('no system') }}{% endif %}"
     "<u>{{ m['content'] }}</u>{% endfor %}<a>", True, False),
    # keeps one
    ("{% for m in messages %}<{{ m['role'] }}>{{ m['content'] }}{% endfor %}<a>", False, False),
    # reads content as parts
    ("{% for m in messages %}<{{ m['role'] }}>{{ m['content'][0].get('text') }}{% endfor %}<a>", False, True),
    # tests for tools
    ("{% if tools is none %}{% else %}{% for t in tools %}{{ t }}{% endfor %}{% endif %}"
     "{% for m in messages %}<{{ m['role'] }}>{{ m['content'] }}{% endfor %}<a>", False, False),
])
def test_whatever_form_a_template_takes_both_voices_reach_the_model(source, folded, parts):
    tpl = ct._discover(source, "", "")
    assert (tpl.folds_system, tpl.content_parts) == (folded, parts)
    prompt = ct.render_prompt(tpl, "SYSTEM WORDS", "USER WORDS", think=None)
    assert "SYSTEM WORDS" in prompt and "USER WORDS" in prompt


@pytest.mark.parametrize("source", ["vicuna", "ChatGLM4", "{% if false %}{{ messages }}{% endif %}"])
def test_a_name_in_the_template_field_is_no_template(source):
    assert ct._discover(source, "", "") is None


def test_the_models_own_control_tokens_never_reach_the_reply():
    class Model:
        def token_get_attr(self, token):
            return (1 << 3) if token in (1, 2) else 0

        def token_get_text(self, token):
            return {1: b"<|new_family_end|>", 2: b"<s>", 3: b"hello"}.get(token, b"")

    class Llm:
        _model = Model()

        def n_vocab(self):
            return 4

    mot.learn_control_tokens(Llm())
    try:
        assert mot.strip_special_tokens("hello<|new_family_end|>") == "hello"
    finally:
        mot._LOADED_MODEL_TOKENS = ()


def test_a_split_model_is_one_model_of_all_its_parts(tmp_path):
    first = _gguf(tmp_path / "m-00001-of-00002.gguf", {"general.architecture": "newarch", "newarch.block_count": 2},
                  [("blk.0.attn.weight", 64), ("token_embd.weight", 32)])
    later = _gguf(tmp_path / "m-00002-of-00002.gguf", {}, [("blk.1.ffn_up_exps.weight", 640), ("output.weight", 32)])
    assert gs.model_parts(later) == [first, later] and gs.first_part(later) == first
    assert gs.is_later_part(later) and not gs.is_later_part(first)
    assert gs.model_bytes(first) == first.stat().st_size + later.stat().st_size
    w = gs.weights(first)
    assert w.experts_total and w.blocks == 2


def test_a_missing_part_is_named(tmp_path):
    first = _gguf(tmp_path / "m-00001-of-00002.gguf", {"general.architecture": "x"})
    assert gs.missing_parts(first) == ["m-00002-of-00002.gguf"]
    assert gs.missing_parts(tmp_path / "plain.gguf") == ["plain.gguf"]


def test_the_chooser_lists_a_split_model_once_at_its_whole_size(tmp_path):
    from eli.core.hardware_profile import discover_models
    meta = {"general.architecture": "newarch", "tokenizer.ggml.model": "gpt2"}
    first = _gguf(tmp_path / "m-00001-of-00002.gguf", meta)
    later = _gguf(tmp_path / "m-00002-of-00002.gguf", {})
    found = discover_models(models_dir=tmp_path)
    assert [f["name"] for f in found] == [first.name]
    assert found[0]["size_bytes"] == first.stat().st_size + later.stat().st_size


def test_a_big_endian_file_is_not_read_as_garbage(tmp_path):
    path = tmp_path / "be.gguf"
    path.write_bytes(b"GGUF" + struct.pack(">I", 3) + b"\0" * 64)
    assert gs._read_header(str(path)) is None


def test_only_a_language_model_is_a_chat_model(tmp_path):
    from eli.cognition.model_load_diagnostics import not_a_chat_model
    image = _gguf(tmp_path / "picture.gguf", {"general.architecture": "flux"})
    assert "no tokenizer" in not_a_chat_model(image)
    chat = _gguf(tmp_path / "anything.gguf", {"general.architecture": "brandnew", "tokenizer.ggml.model": "gpt2"})
    assert not_a_chat_model(chat) == ""


def test_a_projector_is_told_by_its_metadata_and_paired_whatever_it_is_called(tmp_path, monkeypatch):
    from eli.perception import vision
    proj = _gguf(tmp_path / "vision-weights.gguf", {"general.architecture": "clip", "clip.has_vision_encoder": 1})
    base = _gguf(tmp_path / "some-model.gguf", {"general.architecture": "newvl", "tokenizer.ggml.model": "gpt2"})
    assert vision._is_projector(proj) and not vision._is_projector(base)
    assert [(b, p) for b, p, _ in vision._discover_vl_pairs(tmp_path)] == [(base, proj)]


def test_vision_uses_the_handler_that_reads_the_models_own_template():
    from eli.perception import vision
    pytest.importorskip("llama_cpp.llama_chat_format")
    assert vision._resolve_handler_class("/x/brand-new-model.gguf")[1] == "MTMDChatHandler"
    assert vision._resolve_handler_class("/x/m.gguf", "Llava15ChatHandler")[1] == "Llava15ChatHandler"


def test_a_split_model_with_a_part_missing_says_which(tmp_path):
    from eli.cognition.model_load_diagnostics import explain_load_failure
    first = _gguf(tmp_path / "m-00001-of-00002.gguf", {"general.architecture": "x"})
    assert "m-00002-of-00002.gguf" in explain_load_failure(RuntimeError("failed"), [], first)


def test_a_model_that_picks_badly_does_not_choose_actions(tmp_path, monkeypatch):
    from eli.cognition import action_trust as at
    monkeypatch.setattr(at, "_record_path", lambda: tmp_path / "trust.json")
    monkeypatch.setattr(at, "_model_key", lambda: "some-model|1")
    bad = at.measure(lambda text: {"action": "GET_WEATHER"})
    assert bad["trusted"] is False


def test_a_model_that_picks_well_does(tmp_path, monkeypatch):
    from eli.cognition import action_trust as at
    monkeypatch.setattr(at, "_record_path", lambda: tmp_path / "trust.json")
    monkeypatch.setattr(at, "_model_key", lambda: "some-model|1")
    answers = dict((t, a[0]) for t, a in at._COMMANDS)
    assert at.measure(lambda text: {"action": answers.get(text, "CHAT")})["trusted"] is True
    assert at._records()["some-model|1"]["trusted"] is True


def test_one_wrong_action_on_plain_talk_is_enough(tmp_path, monkeypatch):
    from eli.cognition import action_trust as at
    monkeypatch.setattr(at, "_record_path", lambda: tmp_path / "trust.json")
    monkeypatch.setattr(at, "_model_key", lambda: "some-model|1")
    answers = dict((t, a[0]) for t, a in at._COMMANDS)
    answers[at._TALK[0]] = "CLOSE_APP"
    assert at.measure(lambda text: {"action": answers.get(text, "CHAT")})["trusted"] is False


def test_nothing_is_asked_of_a_model_that_has_been_asked(tmp_path, monkeypatch):
    from eli.cognition import action_trust as at, gguf_inference
    monkeypatch.setattr(at, "_record_path", lambda: tmp_path / "trust.json")
    monkeypatch.setattr(at, "_model_key", lambda: "some-model|1")
    monkeypatch.setattr(gguf_inference, "is_loaded", lambda: True)
    monkeypatch.delenv("ELI_MODEL_CHOOSES_ACTIONS", raising=False)
    (tmp_path / "trust.json").write_text('{"some-model|1": {"trusted": false}}')
    assert at.may_choose_actions() is False
    (tmp_path / "trust.json").write_text('{"some-model|1": {"trusted": true}}')
    assert at.may_choose_actions() is True
    monkeypatch.setenv("ELI_MODEL_CHOOSES_ACTIONS", "0")
    assert at.may_choose_actions() is False


def test_a_model_that_could_not_answer_is_not_marked_down(tmp_path, monkeypatch):
    """A failed call reads as CHAT. Counted, a good model would be kept as one that cannot choose."""
    from eli.cognition import action_trust as at, gguf_inference, llm_intent
    monkeypatch.setattr(at, "_record_path", lambda: tmp_path / "trust.json")
    monkeypatch.setattr(at, "_model_key", lambda: "some-model|1")
    monkeypatch.setattr(gguf_inference, "is_loaded", lambda: True)
    monkeypatch.setattr(gguf_inference, "is_shutting_down", lambda: False)
    monkeypatch.setattr(gguf_inference, "chat_completion", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")))
    monkeypatch.setattr(llm_intent, "_action_grammar", lambda *a: None, raising=False)
    with pytest.raises(at._NotAnswered):
        at.measure()
    assert not (tmp_path / "trust.json").exists()


def test_a_model_changed_during_the_questions_is_not_given_the_verdict(tmp_path, monkeypatch):
    from eli.cognition import action_trust as at, gguf_inference, llm_intent
    monkeypatch.setattr(at, "_record_path", lambda: tmp_path / "trust.json")
    keys = iter(["first|1"] + ["second|1"] * 50)
    monkeypatch.setattr(at, "_model_key", lambda: next(keys))
    monkeypatch.setattr(gguf_inference, "is_loaded", lambda: True)
    monkeypatch.setattr(gguf_inference, "is_shutting_down", lambda: False)
    monkeypatch.setattr(llm_intent, "parse_with_llm", lambda text: {"action": "CHAT", "meta": {}})
    with pytest.raises(at._NotAnswered):
        at.measure()
    assert not (tmp_path / "trust.json").exists()


class _Closes:
    closed = 0

    def __init__(self):
        self._ctx = types.SimpleNamespace(ctx=object())

    def close(self):
        self.closed += 1
        self._ctx.ctx = None


def test_a_load_that_finishes_behind_an_unload_closes_what_it_made(monkeypatch):
    from eli.cognition import gguf_inference as g
    made = _Closes()

    def load_while_it_is_unloaded(_request=None):
        g.unload_model()
        return made

    monkeypatch.setattr(g, "_llm", None)
    monkeypatch.setattr(g, "_load_model_now", load_while_it_is_unloaded)
    with pytest.raises(RuntimeError, match="unloaded while it was loading"):
        g.load_model()
    assert made.closed == 1 and g._llm is None


def test_a_load_with_no_unload_hands_over_the_model(monkeypatch):
    from eli.cognition import gguf_inference as g
    made = _Closes()
    monkeypatch.setattr(g, "_llm", None)
    monkeypatch.setattr(g, "_load_model_now", lambda _request=None: made)
    assert g.load_model() is made and g._llm is made and made.closed == 0
    monkeypatch.setattr(g, "_llm", None)


def test_an_unload_does_not_wait_for_a_load(monkeypatch):
    from eli.cognition import gguf_inference as g
    started, finish = threading.Event(), threading.Event()
    made = _Closes()

    def slow(_request=None):
        started.set()
        finish.wait(30)
        return made

    monkeypatch.setattr(g, "_llm", None)
    monkeypatch.setattr(g, "_load_model_now", slow)
    errors = []

    def loading():
        try:
            g.load_model()
        except RuntimeError as err:
            errors.append(str(err))

    worker = threading.Thread(target=loading)
    worker.start()
    assert started.wait(30)
    done = threading.Event()
    threading.Thread(target=lambda: (g.unload_model(), done.set())).start()
    assert done.wait(10), "the unload waited for the load"
    finish.set()
    worker.join(30)
    assert errors and made.closed == 1


def test_no_load_starts_during_shutdown(monkeypatch):
    from eli.cognition import gguf_inference as g
    monkeypatch.setattr(g, "_llm", None)
    monkeypatch.setattr(g, "_load_model_now", lambda _request=None: pytest.fail("loaded during shutdown"))
    g.signal_shutdown()
    try:
        with pytest.raises(RuntimeError, match="shutting down"):
            g.load_model()
    finally:
        g.clear_shutdown()


def test_a_call_on_a_model_closed_since_is_refused_before_any_native_call():
    from eli.cognition import gguf_inference as g

    class _Model(_Closes):
        def __call__(self, *a, **k):
            pytest.fail("called native code on a closed model")

    model = _Model()
    model.close()
    with pytest.raises(RuntimeError, match="unloaded before this call"):
        g._safe_invoke_llm(model, "hello", temperature=0.1, max_tokens=8, top_p=1, top_k=1, repeat_penalty=1,
                           stop=[], stream=False, grammar=None)


def test_a_reply_that_reads_its_instructions_back_is_not_served():
    from eli.cognition import self_claims as sc
    from eli.kernel import request_context as rc
    token = rc.turn_facts_var.set({"user_input": "hello"})
    try:
        out = "".join(sc.gate_stream(["The field is soft. You always know the weekday and the date, never claim otherwise."],
                                     instructions="RULES: you always know the weekday and the date, never claim otherwise. Be kind."))
    finally:
        rc.turn_facts_var.reset(token)
    assert "weekday" not in out and "The field is soft" in out


def test_a_template_that_refuses_to_think_less_still_answers():
    source = ("{% if enable_thinking is defined and not enable_thinking %}{{ raise_exception('no') }}{% endif %}"
              "{% for m in messages %}<{{ m['role'] }}>{{ m['content'] }}{% endfor %}<a>")
    tpl = ct._discover(source, "", "")
    assert "USER WORDS" in ct.render_prompt(tpl, "SYSTEM WORDS", "USER WORDS", think=False)


@pytest.mark.parametrize("text", [
    "I am here to help you. " * 80,
    " ".join(["date month year week start state data current online status sunday"] * 40),
    "\n".join(f"{i}. Item number {i} says the same thing again." for i in range(60)),
])
def test_a_reply_that_is_going_nowhere_is_told_from_a_long_one(text):
    from eli.cognition.gguf_inference import reads_as_runaway
    assert reads_as_runaway(text)


@pytest.mark.parametrize("text", [
    "\n".join(f"{i},{'fox owl seal hare wolf crab newt'.split()[i % 7]},{'oak elm ash fir yew'.split()[i % 5]},"
              f"{20 + i % 37},{(i * 37) % 100}.{i % 10}" for i in range(120)),
    "\n".join(f"    def test_add_{i}(self):\n        self.assertEqual(add({i}, {i * 7}), {i * 8})" for i in range(40)),
    "\n".join(f"def f{i}(x):\n    return x * {i} + {i * i}" for i in range(60)),
    "\n".join(f"| {i} | row {i} | {i * 3} |" for i in range(90)),
    "The ocean holds most of the water on Earth, and its currents move heat around. Winds push the surface. " * 2,
    "short",
])
def test_long_lists_code_and_prose_are_not_cut_off(text):
    from eli.cognition.gguf_inference import reads_as_runaway
    assert not reads_as_runaway(text[:3000])


def test_the_stop_reads_only_every_so_often_and_ends_a_runaway():
    from eli.cognition import gguf_inference as g

    class Llm:
        reads = 0

        def detokenize(self, ids):
            Llm.reads += 1
            return ("again and again " * 200).encode()

    stop = g._runaway_stop(Llm())
    results = [stop(list(range(600)), None) for _ in range(g._RUNAWAY_TOKENS)]
    assert results[-1] is True and not any(results[:-1]) and Llm.reads == 1
