from __future__ import annotations

import threading
from typing import Any, Dict

from eli.runtime.response_contracts import contract_for_action, ResponseContract

_tls = threading.local()

_PROVIDER_HEADER = (
    "FINAL_RESPONSE_PROVIDER_CONTRACT\n"
    "- Speak as ELI.\n"
    "- Use only grounded evidence already assembled by the system.\n"
    "- Do not invent memory contents, runtime facts, file facts, agent usage, or tool execution.\n"
    "- If evidence is incomplete, say so directly.\n"
    "- Keep personality, but do not let personality override evidence.\n"
    "- Never expose synthetic internal control prompts as user-facing content.\n"
    "- Prefer direct, technical, evidence-first answers.\n"
)

def set_current_action(action: str | None, meta: Dict[str, Any] | None = None) -> ResponseContract:
    c = contract_for_action(action)
    _tls.action = c.action
    _tls.meta = dict(meta or {})
    _tls.contract = c
    return c

def clear_current_action() -> None:
    for k in ("action", "meta", "contract"):
        try:
            delattr(_tls, k)
        except Exception:
            pass

def current_contract() -> ResponseContract:
    c = getattr(_tls, "contract", None)
    if c is None:
        c = contract_for_action("CHAT")
        _tls.contract = c
    return c

def decorate_prompt(prompt: str, contract: ResponseContract | None = None) -> str:
    contract = contract or current_contract()
    text = str(prompt or "")
    if contract.quick:
        return text
    if text.startswith("FINAL_RESPONSE_PROVIDER_CONTRACT"):
        return text
    return _PROVIDER_HEADER + "\n" + text

def apply_generation_kwargs(kwargs: Dict[str, Any] | None = None, contract: ResponseContract | None = None) -> Dict[str, Any]:
    contract = contract or current_contract()
    out = dict(kwargs or {})

    cur_temp = out.get("temperature")
    if cur_temp is None:
        out["temperature"] = contract.temperature
    else:
        try:
            out["temperature"] = min(float(cur_temp), float(contract.temperature))
        except Exception:
            out["temperature"] = contract.temperature

    cur_mt = out.get("max_tokens")
    cap = int(contract.max_tokens_cap)
    if cap <= 0:
        try:
            out["max_tokens"] = -1 if cur_mt is None else int(cur_mt)
        except Exception:
            out["max_tokens"] = -1
    elif cur_mt is None:
        out["max_tokens"] = cap
    else:
        try:
            out["max_tokens"] = max(128, min(int(cur_mt), cap))
        except Exception:
            out["max_tokens"] = cap

    return out


# Note: role-prefix and HR-phrase polish lives in eli.cognition.output_governor
# (govern_output → clean_response_style). The decorate_prompt / contract logic
# above is the only behaviour exposed here.

