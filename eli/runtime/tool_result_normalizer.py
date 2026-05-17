from __future__ import annotations

from typing import Any, Dict

from eli.runtime.tool_result_models import ToolResultRecord


def _trim(text: str, n: int = 240) -> str:
    s = " ".join(str(text or "").split()).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _dict_preview(data: Dict[str, Any], limit: int = 12) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for i, (k, v) in enumerate((data or {}).items()):
        if i >= limit:
            break
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[str(k)] = v
        else:
            out[str(k)] = repr(v)[:200]
    return out


def normalize_tool_result(
    action: str,
    args: Dict[str, Any] | None,
    result: Any,
    *,
    source: str = "executor",
) -> ToolResultRecord:
    action = str(action or "")
    args = dict(args or {})

    if isinstance(result, BaseException):
        return ToolResultRecord(
            action=action,
            ok=False,
            status="error",
            summary=_trim(f"{type(result).__name__}: {result}"),
            args=args,
            payload={"error_type": type(result).__name__, "error": str(result)},
            source=source,
            result_type="exception",
        )

    if isinstance(result, dict):
        ok = bool(result.get("ok", True))
        if "error" in result and result.get("error"):
            ok = False
        status = str(result.get("status") or ("ok" if ok else "error"))
        summary = (
            result.get("summary")
            or result.get("message")
            or result.get("error")
            or repr(_dict_preview(result))
        )
        return ToolResultRecord(
            action=action,
            ok=ok,
            status=status,
            summary=_trim(summary),
            args=args,
            payload=_dict_preview(result),
            source=source,
            result_type="dict",
        )

    if isinstance(result, str):
        low = result.strip().lower()
        ok = not (low.startswith("error") or low.startswith("❌") or "traceback" in low)
        return ToolResultRecord(
            action=action,
            ok=ok,
            status="ok" if ok else "error",
            summary=_trim(result),
            args=args,
            payload={"text": result[:4000]},
            source=source,
            result_type="str",
        )

    if isinstance(result, (list, tuple)):
        return ToolResultRecord(
            action=action,
            ok=True,
            status="ok",
            summary=_trim(f"{type(result).__name__} len={len(result)}"),
            args=args,
            payload={"items_count": len(result), "preview": [repr(x)[:120] for x in list(result)[:8]]},
            source=source,
            result_type=type(result).__name__,
        )

    return ToolResultRecord(
        action=action,
        ok=True,
        status="ok",
        summary=_trim(repr(result)),
        args=args,
        payload={"repr": repr(result)[:4000]},
        source=source,
        result_type=type(result).__name__,
    )
