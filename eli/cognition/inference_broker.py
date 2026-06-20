from __future__ import annotations
import threading
import time as _time
from typing import Optional, Dict, Any


from eli.utils.log import get_logger
log = get_logger(__name__)

_broker: Optional["InferenceBroker"] = None
_broker_lock = threading.Lock()

# Timestamp of the last FOREGROUND (user-facing) inference. Background daemon work (proactive
# insight synthesis, autonomy tick, self-improvement) checks foreground_recently_active() and
# yields, so it never wedges itself between the calls of a foreground request — a multi-section
# document or a reasoning-mode loop — which on a slow/CPU-offloaded model stretched turns to 40+
# minutes of interleaved background generations.
_last_foreground_ts = 0.0
_last_foreground_duration = 0.0   # seconds the most recent foreground turn took to generate
_MAX_ADAPTIVE_DEFER = 900.0       # cap so a pathological 20-min turn can't defer chores forever


def _is_think_only(response: str) -> bool:
    """True if a non-empty response is ENTIRELY a reasoning block that strips to
    empty (a thinking model that ran out of budget mid-<think>). Such a response
    is non-empty here but useless to the caller, so it should trigger the
    no-think retry just like a truly empty one. Best-effort; never raises."""
    if not response:
        return False
    try:
        from eli.cognition.gguf_inference import _strip_think_text
        return not _strip_think_text(response).strip()
    except Exception:
        return False


def foreground_recently_active(window: float = 30.0) -> bool:
    """True if a user-facing inference ran (or was running) recently.

    The effective window scales UP with the last foreground turn's DURATION: on a slow /
    CPU-offloaded model where one turn takes minutes, background chores then defer for about
    as long as a turn takes (bounded by _MAX_ADAPTIVE_DEFER), so they don't fire in the brief
    gap right after a turn and collide with the user's next message. On fast hardware the
    duration is tiny, so the base `window` dominates and behaviour is unchanged."""
    try:
        eff = min(max(float(window), float(_last_foreground_duration)), _MAX_ADAPTIVE_DEFER)
        return (_time.monotonic() - _last_foreground_ts) < eff
    except Exception:
        return False


def get_inference_broker() -> Optional["InferenceBroker"]:
    global _broker
    if _broker is not None:
        return _broker
    with _broker_lock:
        if _broker is None:
            try:
                _broker = InferenceBroker()
            except Exception as e:
                log.debug(f"[BROKER] Failed to create InferenceBroker: {e}")
                return None
    return _broker


class InferenceBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gguf: Any = None
        self._load_error: Optional[str] = None
        self._init_gguf()

    def _init_gguf(self) -> None:
        try:
            from eli.cognition import gguf_inference as gi
            self._gguf = gi
        except Exception as e:
            self._load_error = str(e)
            log.debug(f"[BROKER] gguf_inference unavailable: {e}")

    @property
    def gguf_ready(self) -> bool:
        if self._gguf is None:
            return False
        try:
            if hasattr(self._gguf, "is_loaded"):
                return bool(self._gguf.is_loaded)
            if hasattr(self._gguf, "model"):
                return self._gguf.model is not None
            return True
        except Exception:
            return False

    def infer(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        *,
        retry: bool = True,
        background: bool = False,
    ) -> str:
        if not self.gguf_ready:
            raise RuntimeError("GGUF model not ready")
        # During shutdown, don't START a new generation — return empty immediately so a
        # background self-improvement/codegen loop stops paying prompt-eval cost on each
        # remaining item and teardown isn't held up. In-flight calls abort via the
        # gguf stopping-criteria; this just prevents new ones from queueing.
        try:
            if self._gguf.is_shutting_down():
                return ""
        except Exception:
            pass
        global _last_foreground_ts, _last_foreground_duration
        # A call is background if the caller said so OR it runs on a thread already marked
        # background (the proactive daemon marks its loop thread, so all its work qualifies).
        gi = self._gguf
        try:
            background = bool(background) or bool(gi.is_background_inference())
        except Exception:
            pass
        # A foreground turn is live or just ran: don't let background work grab the shared model
        # lock and stall the user (prompt-eval can't be token-preempted once it starts). Skip this
        # cycle — the daemon re-runs the chore on a later idle tick. Best-effort; model/hardware
        # agnostic; ELI's depth is unchanged — only the TIMING of background work moves off the
        # user's turn. Override window via ELI_BG_DEFER_WINDOW (0 disables deferral).
        if background:
            try:
                import os as _os_d
                _win = float(_os_d.environ.get("ELI_BG_DEFER_WINDOW", "30"))
            except Exception:
                _win = 30.0
            if _win > 0 and foreground_recently_active(_win):
                return ""
        # Background generations are hard-capped so they can't hold the shared model lock for
        # minutes on a slow model, and they carry a cooperative abort (set per-thread below) so a
        # foreground turn preempts them. Cap is tunable via ELI_BG_MAX_TOKENS (default 256).
        if background:
            try:
                import os as _os
                _cap = int(_os.environ.get("ELI_BG_MAX_TOKENS", "256"))
            except Exception:
                _cap = 256
            if _cap > 0:
                max_tokens = min(int(max_tokens), _cap)
        # Foreground calls stamp the activity clock (before AND after, so the whole — possibly
        # multi-minute — generation counts as "active"); background calls never do.
        _fg_start = 0.0
        if not background:
            _last_foreground_ts = _time.monotonic()
            _fg_start = _last_foreground_ts
        # Arm the per-thread background flag so gguf_inference installs the abort hook even when
        # the caller (e.g. insight_synthesis) is on a thread not otherwise marked background.
        _armed = False
        try:
            if background and not gi.is_background_inference():
                gi.set_background_inference(True)
                _armed = True
        except Exception:
            pass
        try:
            with self._lock:
                response = self._call(prompt, system, max_tokens, temperature, top_p)
            if (not response or _is_think_only(response)) and retry:
                # A reasoning model can spend its whole budget inside <think> and return either
                # nothing OR a never-closed think block that strips to empty downstream — both
                # leave the caller with no usable answer. Force the think block closed on the
                # retry so the budget goes to the answer. Model-agnostic: a no-op for non-thinking
                # models, and the prompt/context are unchanged — only the hidden think is suppressed.
                try:
                    _nt_ctx = gi.force_no_think()
                except Exception:
                    from contextlib import nullcontext as _nullctx
                    _nt_ctx = _nullctx()
                with _nt_ctx, self._lock:
                    response = self._call(prompt, system, max_tokens, temperature, top_p)
        finally:
            if _armed:
                try:
                    gi.set_background_inference(False)
                except Exception:
                    pass
            if not background:
                _now = _time.monotonic()
                if _fg_start:
                    # Remember how long this turn took, so the deferral window adapts to it.
                    _last_foreground_duration = max(0.0, _now - _fg_start)
                _last_foreground_ts = _now
        if not response:
            raise RuntimeError("GGUF returned empty response after retry")
        return response

    def _call(self, prompt, system, max_tokens, temperature, top_p) -> str:
        gi = self._gguf
        gen_fn = getattr(gi, "generate", None)
        if callable(gen_fn):
            chunks = []
            for chunk in gen_fn(prompt, system=system, max_tokens=max_tokens,
                                temperature=temperature, stream=False):
                if isinstance(chunk, dict):
                    chunks.append(chunk.get("response") or chunk.get("token") or "")
                else:
                    chunks.append(str(chunk) or "")
            return "".join(chunks).strip()
        cc_fn = getattr(gi, "chat_completion", None)
        if callable(cc_fn):
            return (cc_fn(prompt, system=system, max_tokens=max_tokens,
                          temperature=temperature) or "").strip()
        raise RuntimeError("gguf_inference has neither generate() nor chat_completion()")

# backwards-compat aliases — various modules import these names
get_broker            = get_inference_broker
get_inference_broker  = get_inference_broker   # idempotent re-export
