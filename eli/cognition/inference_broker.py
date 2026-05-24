from __future__ import annotations
import threading
from typing import Optional, Dict, Any


from eli.utils.log import get_logger
log = get_logger(__name__)

_broker: Optional["InferenceBroker"] = None
_broker_lock = threading.Lock()


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
    ) -> str:
        if not self.gguf_ready:
            raise RuntimeError("GGUF model not ready")
        with self._lock:
            response = self._call(prompt, system, max_tokens, temperature, top_p)
        if not response and retry:
            with self._lock:
                response = self._call(prompt, system, max_tokens, temperature, top_p)
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
