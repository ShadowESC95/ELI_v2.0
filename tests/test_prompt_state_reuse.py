"""The model's state at the end of a prompt's fixed part is kept and given back.

Measured 2026-10-14 on Qwen3.6-35B-A3B (qwen35moe, a hybrid model whose layers carry a running
state llama.cpp cannot roll back): every call read its whole prompt again, 62 s for 7k tokens,
for each pass of a Normal-mode turn and for every intent-resolver call. With the state saved at
the end of the system part (135 MiB, 0.08 s) and restored for the next prompt that starts the
same way (0.02 s), the second pass took 2 s and gave the same next token as a full read.
"""
from types import SimpleNamespace

import pytest

from eli.cognition import gguf_inference as gi


class _Ctx:
    def __init__(self, llm):
        self.llm, self.ctx = llm, object()

    def kv_cache_clear(self):
        self.llm.memory = []

    def kv_cache_seq_rm(self, seq, p0, p1):
        if self.llm.running_state:          # a hybrid model's state cannot be cut back
            return False
        del self.llm.memory[p0:]
        return True


class _Llm:
    """Tokens are characters; the memory is the list of tokens read."""
    n_batch = 4

    def __init__(self, running_state=True):
        self.running_state = running_state
        self.memory, self.read = [], []
        self.n_tokens = 0
        self._input_ids = [0] * 4096
        self._ctx = _Ctx(self)

    def n_ctx(self):
        return 4096

    def tokenize(self, b, add_bos=True, special=True):
        return ([1] if add_bos else []) + list(b)

    def reset(self):
        self.n_tokens = 0

    def eval(self, tokens):
        self.read.extend(tokens)
        self.memory.extend(tokens)
        self._input_ids[self.n_tokens:self.n_tokens + len(tokens)] = list(tokens)
        self.n_tokens += len(tokens)


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    gi.forget_saved_states()
    monkeypatch.setattr(gi, "_resolve_family_for_loaded", lambda path=None: "chatml")
    monkeypatch.setattr(gi, "get_model_path", lambda: None)
    monkeypatch.setattr(gi, "_saved_states_room", lambda: 10 ** 9)
    monkeypatch.setattr(gi, "_save_seq_state", lambda llm: (list(llm.memory), len(llm.memory)))

    def load(llm, saved, tokens):
        llm.memory = list(saved[0])
        llm.n_tokens = len(tokens)
        llm._input_ids[:len(tokens)] = tokens
        return True
    monkeypatch.setattr(gi, "_load_seq_state", load)
    yield
    gi.forget_saved_states()


SYSTEM = "You are ELI. " + "Evidence line. " * 20


def _ready(llm, system, user, create=True):
    full = gi._format_prompt(system, user)
    return gi._resume_from_saved_state(llm, full, create=create), full


def test_the_fixed_part_is_the_prompt_up_to_where_the_message_starts():
    gi._format_prompt(SYSTEM, "first message")
    fixed = gi._stable_prefix_var.get()
    assert fixed.endswith("<|im_start|>user\n") and SYSTEM.strip() in fixed
    gi._format_prompt("", "no system")
    assert gi._stable_prefix_var.get() == ""


def test_the_second_pass_reads_only_its_own_message():
    llm = _Llm()
    how, full = _ready(llm, SYSTEM, "Think through the request step by step.")
    assert how == "saved"
    fixed_tokens = llm.n_tokens
    llm.eval(llm.tokenize(full.encode())[fixed_tokens:])          # pass 1 goes on past the fixed part
    llm.read.clear()
    how, _ = _ready(llm, SYSTEM, "Using your reasoning, write the answer.")
    assert how == "restored" and llm.read == [], "nothing of the fixed part is read again"
    assert llm.n_tokens == fixed_tokens and llm.memory == list(llm.tokenize(gi._stable_prefix_var.get().encode()))


def test_another_system_prompt_gets_a_state_of_its_own_and_both_are_kept():
    llm = _Llm()
    assert _ready(llm, SYSTEM, "a")[0] == "saved"
    assert _ready(llm, "The intent resolver. " * 10, "b")[0] == "saved"
    assert _ready(llm, SYSTEM, "c")[0] == "restored"
    assert _ready(llm, "The intent resolver. " * 10, "d")[0] == "restored"


def test_the_states_keep_within_their_share_of_free_memory(monkeypatch):
    llm = _Llm()
    _ready(llm, SYSTEM, "a")
    one = len(gi._SAVED_STATES[next(iter(gi._SAVED_STATES))]["tokens"])
    monkeypatch.setattr(gi, "_saved_states_room", lambda: one + 10)
    _ready(llm, SYSTEM.replace("ELI", "ELJ"), "b")
    assert len(gi._SAVED_STATES) == 1, "the oldest gives way"
    monkeypatch.setattr(gi, "_saved_states_room", lambda: 5)
    assert _ready(llm, SYSTEM.replace("ELI", "ELK"), "c")[0] == "", "a state larger than the room is not kept"


def test_the_states_keep_within_two_contexts_worth_of_state():
    llm = _Llm()
    llm.n_ctx = lambda: 200          # a context of 200 tokens: states up to 400 tokens' worth in all
    for word in ("ELA", "ELB", "ELC", "ELD"):
        _ready(llm, SYSTEM.replace("ELI", word), "a")
    assert sum(len(e["state"][0]) for e in gi._SAVED_STATES.values()) <= 400 and len(gi._SAVED_STATES) < 4


def test_background_work_uses_a_saved_state_but_never_adds_one():
    llm = _Llm()
    assert _ready(llm, SYSTEM, "a", create=False)[0] == "" and llm.read == []
    _ready(llm, SYSTEM, "a")
    assert _ready(llm, SYSTEM, "b", create=False)[0] == "restored"


def test_an_attention_cache_holding_the_fixed_part_is_cut_back_not_read_again():
    llm = _Llm(running_state=False)
    _, full = _ready(llm, SYSTEM, "a", create=False)
    llm.eval(llm.tokenize(full.encode()))           # the whole of a previous prompt is in the cache
    llm.read.clear()
    assert _ready(llm, SYSTEM, "b")[0] == "saved" and llm.read == []


def test_a_short_fixed_part_or_no_message_is_left_to_llama_cpp():
    llm = _Llm()
    llm.n_batch = 10 ** 6
    assert _ready(llm, SYSTEM, "a")[0] == ""


def test_it_can_be_switched_off_and_a_failure_leaves_an_ordinary_read(monkeypatch):
    llm = _Llm()
    monkeypatch.setenv("ELI_PROMPT_STATE_REUSE", "0")
    assert _ready(llm, SYSTEM, "a")[0] == ""
    monkeypatch.delenv("ELI_PROMPT_STATE_REUSE")
    monkeypatch.setattr(llm, "eval", lambda tokens: (_ for _ in ()).throw(RuntimeError("decode failed")))
    assert _ready(llm, SYSTEM, "a")[0] == "" and llm.n_tokens == 0 and llm.memory == []


def test_the_states_go_with_the_model(monkeypatch):
    llm = _Llm()
    _ready(llm, SYSTEM, "a")
    monkeypatch.setattr(gi, "_llm", None)
    gi.unload_model()
    assert not gi._SAVED_STATES


def test_the_resolver_keeps_its_action_list_in_the_fixed_part(monkeypatch):
    from eli.cognition import llm_intent
    seen = {}

    def chat(prompt, system=None, **kw):
        seen["prompt"], seen["system"] = prompt, system
        return '{"action": "CHAT", "args": {}, "confidence": 0.9}'
    monkeypatch.setattr(llm_intent, "gguf_inference", SimpleNamespace(chat_completion=chat))
    monkeypatch.setattr(llm_intent, "_GRAMMAR_CACHE", {})
    monkeypatch.setattr(llm_intent, "_action_grammar", lambda catalogue: None)
    llm_intent.parse_with_llm("could you sort my downloads by date")
    assert "ACTIONS (choose exactly one, or CHAT)" in seen["system"] and "EXAMPLES" in seen["system"]
    assert seen["prompt"] == 'USER: "could you sort my downloads by date"\nJSON:'
