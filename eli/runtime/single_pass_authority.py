from __future__ import annotations

import threading
from typing import Optional

from eli.runtime.response_packets import FinalAnswerRequest

_tls = threading.local()


def begin_single_pass_cycle() -> None:
    _tls.single_pass_active = True


def end_single_pass_cycle() -> None:
    for k in ("single_pass_active", "final_answer_request"):
        try:
            delattr(_tls, k)
        except Exception:
            pass


def single_pass_active() -> bool:
    return bool(getattr(_tls, "single_pass_active", False))


def set_final_answer_request(req: FinalAnswerRequest) -> FinalAnswerRequest:
    _tls.final_answer_request = req
    return req


def get_final_answer_request() -> Optional[FinalAnswerRequest]:
    return getattr(_tls, "final_answer_request", None)
