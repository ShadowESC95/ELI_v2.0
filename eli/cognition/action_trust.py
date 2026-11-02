"""Whether the loaded model can be left to choose an action.

Every model is made to pick one of the actions for any message the rules did not recognise. A large
one picks well. On smaller and other models "tell me about the sea" came back as the weather, an image
to analyse and a PDF, and "fire up the calculator" as closing an app. No list of families says which
is which, and a new one comes out every week, so each model is asked: a short quiz the first time it
loads, kept per model file. One that fails still has every rule and all of chat; it just does not
choose actions, and what a person types is talked about rather than carried out on its guess.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

# Talk, whatever words it holds. Not one of them asks for an action.
_TALK = ("tell me one interesting thing about rivers",
         "what do you think makes a good story?",
         "i had a long day at work",
         "how do bridges stay up?",
         "my sister moved to a new town last week")
# Each asks for one thing, in plain words, and only these answers are that thing.
_COMMANDS = (("open the calculator", ("OPEN_APP",)),
             ("set a timer for five minutes", ("SET_TIMER", "SET_ALARM", "START_TIMER")),
             ("stop the music", ("STOP_MEDIA", "PAUSE_MEDIA")),
             ("turn the volume up", ("VOLUME", "VOLUME_UP", "SET_VOLUME")),
             ("what's the weather like", ("GET_WEATHER",)),
             ("search the web for river maps", ("WEB_SEARCH", "SEARCH_WEB")))
# All the talk stays talk, and most commands are read: one wrong action is one the person did not ask for.
_COMMANDS_NEEDED = len(_COMMANDS) - 1

_lock = threading.Lock()
_measuring: set = set()


def _record_path() -> Path:
    from eli.core.paths import data_dir
    return Path(data_dir()) / "runtime" / "action_trust.json"


def _records() -> Dict[str, Any]:
    try:
        return json.loads(_record_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.warning("action trust record unreadable: the model will be asked again", exc_info=True)
        return {}


def _model_key() -> Optional[str]:
    from eli.cognition import gguf_inference
    from eli.core.gguf_sizes import _model_key as key
    path = gguf_inference.get_model_path()
    return key(path) if path else None


class _NotAnswered(RuntimeError):
    """The model went or the call failed: says nothing about how it chooses, so nothing is kept."""


def _asking_the_loaded_model(key: Optional[str]):
    from eli.cognition import gguf_inference
    from eli.cognition.llm_intent import parse_with_llm

    def choose(text: str) -> Dict[str, Any]:
        answer = parse_with_llm(text)
        if (answer.get("meta", {}).get("matched_by") == "llm_intent.failed" or not gguf_inference.is_loaded()
                or gguf_inference.is_shutting_down() or _model_key() != key):
            raise _NotAnswered(text)
        return answer

    return choose


def measure(choose=None) -> Dict[str, Any]:
    """Ask the loaded model. `choose(text)` is what it answers with: the resolver, which is what the
    answer will be used by. Kept against the model file."""
    key = _model_key()
    if choose is None:
        choose = _asking_the_loaded_model(key)
    picked = {text: str((choose(text) or {}).get("action") or "CHAT").upper() for text in _TALK}
    talk_right = sum(picked[text] == "CHAT" for text in _TALK)
    commands_right = 0
    for text, answers in _COMMANDS:
        picked[text] = str((choose(text) or {}).get("action") or "CHAT").upper()
        commands_right += picked[text] in answers
    verdict = {"trusted": talk_right == len(_TALK) and commands_right >= _COMMANDS_NEEDED,
               "talk": f"{talk_right}/{len(_TALK)}", "commands": f"{commands_right}/{len(_COMMANDS)}",
               "at": time.time(), "picked": picked}
    if key:
        with _lock:
            kept = _records()
            kept[key] = verdict
            _record_path().parent.mkdir(parents=True, exist_ok=True)
            _record_path().write_text(json.dumps(kept, indent=1), encoding="utf-8")
    log.info("action trust: %s: talk %s, commands %s: %s", key, verdict["talk"], verdict["commands"],
             "chooses actions" if verdict["trusted"] else "rules and chat only")
    return verdict


def _measure_in_the_background(key: str) -> None:
    from eli.cognition.gguf_inference import set_background_inference, set_job_inference
    set_background_inference(True)      # a person's turn goes first
    set_job_inference(True)
    try:
        measure()
    except _NotAnswered as gone:
        log.info("action trust: no answer to %r, asking again on a later turn", str(gone))
    except Exception:
        log.warning("action trust: the model could not be asked; it does not choose actions until the next start",
                    exc_info=True)
        return      # left in _measuring, so a model that fails this is not asked again on every turn
    with _lock:
        _measuring.discard(key)


def may_choose_actions() -> bool:
    """Whether the loaded model has shown it can choose. Until it has, the rules and chat carry the
    turn. ELI_MODEL_CHOOSES_ACTIONS=1 or 0 decides it by hand."""
    forced = os.environ.get("ELI_MODEL_CHOOSES_ACTIONS", "").strip()
    if forced:
        return forced not in ("0", "false", "off", "no")
    from eli.cognition.gguf_inference import is_loaded
    if not is_loaded():
        return True     # nothing to ask, and nothing that could choose
    key = _model_key()
    verdict = _records().get(key) if key else None
    if verdict is not None:
        return bool(verdict.get("trusted"))
    with _lock:
        start = bool(key) and key not in _measuring
        if start:
            _measuring.add(key)
    if start:
        threading.Thread(target=_measure_in_the_background, args=(key,), name="action-trust", daemon=True).start()
    return False
