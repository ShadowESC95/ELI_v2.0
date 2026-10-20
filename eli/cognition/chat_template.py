"""A model's own chat format, rendered from the template stored in its GGUF file.

Every GGUF chat model carries the prompt format it was trained on as a Jinja template
(`tokenizer.chat_template`). Rendering that template is what gives each model its own format,
whatever its family or age; the family formats in gguf_inference._format_chat are kept only for
files that carry no template, or one that will not render. Hand-written formats are what sent
Gemma 4 a Gemma 3 prompt: it answered in its reasoning channel and closed with `</start_of_turn>`.

The template also says how the model marks its reasoning and the end of its turn. Both are found
by rendering it around sentinel text, so they come from the model as well:

    reasoning open / close   Gemma 4 `<|channel>thought` / `<channel|>`, Qwen3 `<think>` / `</think>`
    end of turn              Gemma 4 `<turn|>`, ChatML `<|im_end|>`, Llama 3 `<|eot_id|>`

Thinking is switched through the template's own `enable_thinking` variable where it has one.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from eli.utils.log import get_logger

log = get_logger(__name__)

# Text no template produces by itself: where it lands in a rendering shows what surrounds it.
_SENT_USER = "⁣ELI-USER-7f3a⁣"
_SENT_REASON = "⁣ELI-REASON-7f3a⁣"
_SENT_ANSWER = "⁣ELI-ANSWER-7f3a⁣"

# The ways a message carries its reasoning in the templates in use (Qwen3, DeepSeek, GLM and
# Gemma 4 read reasoning_content or reasoning; gpt-oss reads thinking).
_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")

# Reasoning markers of templates that write the reasoning into the reply instead of rendering a
# field (DeepSeek-R1 and its distills open `<think>` in the prompt itself), and of files with no
# template. A template's own pair comes first wherever both apply.
DEFAULT_REASONING_MARKERS: Tuple[Tuple[str, str], ...] = (
    ("<think>", "</think>"),
    ("<redacted_thinking>", "</redacted_thinking>"),
)


@dataclass(frozen=True)
class Template:
    source: str
    bos: str
    eos: str
    strip_bos: bool                   # llama.cpp adds BOS itself when tokenising this model's prompt
    thinking_switch: bool             # the template reads `enable_thinking`
    folds_system: bool                # the template refuses a system turn: it goes into the user turn
    reasoning: Optional[Tuple[str, str]]
    turn_end: str


_lock = threading.Lock()
_cache: Dict[str, Optional[Template]] = {}
_compiled: Dict[str, Any] = {}
_active: Optional[Template] = None


def _generation_block():
    """`{% generation %}…{% endgeneration %}`: the tag Hugging Face templates use to mark the
    assistant's text for training masks (SmolLM3 has it). In a prompt it renders its body."""
    from jinja2 import nodes
    from jinja2.ext import Extension

    class _Generation(Extension):
        tags = {"generation"}

        def parse(self, parser):
            lineno = next(parser.stream).lineno
            body = parser.parse_statements(("name:endgeneration",), drop_needle=True)
            return nodes.CallBlock(self.call_method("_body", []), [], [], body).set_lineno(lineno)

        def _body(self, caller):
            return caller()

    return _Generation


def _environment():
    from jinja2.ext import loopcontrols
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def _raise(message):
        from jinja2.exceptions import TemplateError
        raise TemplateError(message)

    def _tojson(value, indent=None, separators=None, sort_keys=False, ensure_ascii=False):
        return json.dumps(value, indent=indent, separators=separators, sort_keys=sort_keys,
                          ensure_ascii=ensure_ascii)

    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True,
                                        extensions=[loopcontrols, _generation_block()])
    env.filters["tojson"] = _tojson
    env.globals["raise_exception"] = _raise
    env.globals["strftime_now"] = lambda fmt: datetime.now().strftime(fmt)
    return env


def _compile(source: str):
    key = hashlib.sha1(source.encode("utf-8", "replace")).hexdigest()
    with _lock:
        got = _compiled.get(key)
    if got is None:
        got = _environment().from_string(source)
        with _lock:
            _compiled[key] = got
    return got


def _render(tpl_source: str, messages: List[Dict[str, Any]], *, bos: str, eos: str,
            add_generation_prompt: bool, think: Optional[bool]) -> str:
    variables: Dict[str, Any] = dict(messages=messages, bos_token=bos, eos_token=eos,
                                     add_generation_prompt=add_generation_prompt)
    if think is not None:
        variables["enable_thinking"] = bool(think)
    return _compile(tpl_source).render(**variables)


def _token_text(llm, token_id) -> str:
    try:
        tid = int(token_id)
        if tid < 0:
            return ""
        return llm.detokenize([tid], special=True).decode("utf-8", "replace")
    except Exception:
        return ""


def _adds_bos(llm, metadata: Dict[str, Any]) -> bool:
    """Whether tokenising a prompt for this model puts BOS in front by itself (llama.cpp's own
    answer when it can give one, else the file's add_bos_token)."""
    try:
        from llama_cpp import llama_cpp as lc
        vocab = lc.llama_model_get_vocab(llm.model)
        return bool(lc.llama_vocab_get_add_bos(vocab))
    except Exception:
        log.debug("chat_template: add-BOS flag not readable from llama.cpp", exc_info=True)
    return str(metadata.get("tokenizer.ggml.add_bos_token", "true")).strip().lower() in ("true", "1")


def _messages(system: str, user: str, *, fold: bool) -> List[Dict[str, Any]]:
    if not system:
        return [{"role": "user", "content": user}]
    if fold:
        return [{"role": "user", "content": f"{system}\n\n{user}"}]
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _discover(source: str, bos: str, eos: str) -> Optional[Template]:
    """Render the template around sentinels: whether it renders at all, whether it takes a
    system turn, and the markers around reasoning and at the end of a turn."""
    folds = False
    try:
        _render(source, _messages("S", _SENT_USER, fold=False), bos=bos, eos=eos,
                add_generation_prompt=True, think=None)
    except Exception:
        try:
            _render(source, _messages("S", _SENT_USER, fold=True), bos=bos, eos=eos,
                    add_generation_prompt=True, think=None)
            folds = True
        except Exception:
            log.debug("chat_template: the model's template does not render", exc_info=True)
            return None

    reasoning: Optional[Tuple[str, str]] = None
    turn_end = ""
    try:
        head = _render(source, [{"role": "user", "content": _SENT_USER}], bos=bos, eos=eos,
                       add_generation_prompt=True, think=True)
        answer = {"role": "assistant", "content": _SENT_ANSWER}
        answer.update({k: _SENT_REASON for k in _REASONING_KEYS})
        full = _render(source, [{"role": "user", "content": _SENT_USER}, answer], bos=bos, eos=eos,
                       add_generation_prompt=False, think=True)
        at_answer = full.find(_SENT_ANSWER)
        if at_answer >= 0:
            turn_end = full[at_answer + len(_SENT_ANSWER):].strip()
            if eos and turn_end.endswith(eos) and turn_end != eos:
                turn_end = turn_end[:-len(eos)].strip()
        at_reason = full.find(_SENT_REASON)
        if 0 <= at_reason < at_answer:
            # what the template writes before the reasoning, after the head of the model's turn
            start = len(head) if full.startswith(head) else len(_common_prefix(full, head))
            opener = full[start:at_reason].strip()
            closer = full[at_reason + len(_SENT_REASON):at_answer].strip()
            if opener and closer:
                reasoning = (opener, closer)
    except Exception:
        log.debug("chat_template: markers not found by rendering", exc_info=True)

    return Template(source=source, bos=bos, eos=eos, strip_bos=False,
                    thinking_switch="enable_thinking" in source, folds_system=folds,
                    reasoning=reasoning, turn_end=turn_end)


def _common_prefix(a: str, b: str) -> str:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return a[:n]


def for_model(llm, metadata: Optional[Dict[str, Any]] = None) -> Optional[Template]:
    """The template of the model `llm` (or of `metadata` when there is no model object), or None
    when it carries none that renders. Becomes the active template for output cleaning."""
    global _active
    md = metadata if metadata is not None else (getattr(llm, "metadata", None) or {})
    source = str(md.get("tokenizer.chat_template") or "")
    if not source.strip():
        _active = None
        return None
    bos = eos = ""
    strip_bos = False
    if llm is not None:
        try:
            bos = _token_text(llm, llm.token_bos())
            eos = _token_text(llm, llm.token_eos())
        except Exception:
            log.debug("chat_template: BOS/EOS text not readable", exc_info=True)
        strip_bos = bool(bos) and _adds_bos(llm, md)
    key = hashlib.sha1(f"{source}\x00{bos}\x00{eos}\x00{strip_bos}".encode("utf-8", "replace")).hexdigest()
    with _lock:
        known = key in _cache
        tpl = _cache.get(key)
    if not known:
        tpl = _discover(source, bos, eos)
        if tpl is not None:
            tpl = Template(**{**tpl.__dict__, "strip_bos": strip_bos})
            log.debug("chat_template: the model's own template is in use (reasoning markers %s, "
                      "end of turn %r, thinking switch %s, system turn %s)", tpl.reasoning,
                      tpl.turn_end, tpl.thinking_switch, "folded" if tpl.folds_system else "kept")
        with _lock:
            _cache[key] = tpl
    _active = tpl
    return tpl


def render_prompt(tpl: Template, system: str, user: str, *, think: Optional[bool]) -> Optional[str]:
    """The prompt for one system + user exchange, ending where the model's reply starts; None
    when the template does not render it. `think` switches reasoning through the template's own
    variable; a model whose template forces reasoning open gets it closed when it is not wanted."""
    try:
        text = _render(tpl.source, _messages(str(system or "").strip(), str(user or "").strip(),
                                             fold=tpl.folds_system),
                       bos=tpl.bos, eos=tpl.eos, add_generation_prompt=True,
                       think=think if tpl.thinking_switch else None)
    except Exception:
        log.debug("chat_template: rendering failed", exc_info=True)
        return None
    if tpl.strip_bos and tpl.bos and text.startswith(tpl.bos):
        text = text[len(tpl.bos):]
    if think is False and not tpl.thinking_switch:
        # No switch to turn reasoning off: close the block the model would open, empty.
        for opener, closer in _pairs(tpl):
            if text.rstrip().endswith(opener):
                return text.rstrip() + "\n\n" + closer + "\n\n"
            if opener in tpl.source:
                return text + opener + "\n\n" + closer + "\n\n"
    return text


def active() -> Optional[Template]:
    return _active


def _pairs(tpl: Optional[Template]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = [tpl.reasoning] if tpl is not None and tpl.reasoning else []
    out += [p for p in DEFAULT_REASONING_MARKERS if p not in out]
    return out


def reasoning_markers() -> List[Tuple[str, str]]:
    """(open, close) reasoning markers to strip from replies: the active model's own first."""
    return _pairs(_active)


def stop_markers() -> List[str]:
    """Text that ends the active model's turn, from its template."""
    tpl = _active
    return [tpl.turn_end] if tpl is not None and tpl.turn_end else []


def scaffold_markers() -> List[str]:
    """Every marker of the active template that must never reach the user as text."""
    tpl = _active
    if tpl is None:
        return []
    out = [m for pair in ([tpl.reasoning] if tpl.reasoning else []) for m in pair]
    if tpl.turn_end:
        out.append(tpl.turn_end)
    return out
