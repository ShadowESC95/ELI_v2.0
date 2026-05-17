from __future__ import annotations

from typing import Any, Dict, Iterable, List

from eli.runtime.stage_packets import StagePacket, make_stage_packet


def _trim(text: str, n: int = 220) -> str:
    s = " ".join(str(text or "").split()).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _safe_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _count_hits(obj: Any) -> int:
    if obj is None:
        return 0
    if isinstance(obj, (list, tuple, set)):
        return len(obj)
    if isinstance(obj, dict):
        for key in (
            "items",
            "hits",
            "results",
            "merged",
            "ranked",
            "keyword_hits",
            "semantic_hits",
            "vector_hits",
            "rag_hits",
        ):
            v = obj.get(key)
            if isinstance(v, (list, tuple, set)):
                return len(v)
        if "count" in obj:
            try:
                return int(obj.get("count") or 0)
            except Exception:
                return 0
        return 0
    return 1


def _preview_items(items: Iterable[Any], limit: int = 3) -> List[str]:
    out: List[str] = []
    for x in list(items)[:limit]:
        if isinstance(x, dict):
            txt = (
                x.get("text")
                or x.get("content")
                or x.get("summary")
                or x.get("title")
                or x.get("path")
                or repr(x)
            )
        else:
            txt = repr(x)
        out.append(_trim(str(txt), 120))
    return out


def build_parallel_retrieval_packet(result: Any, *, source: str = "parallel_retrieval") -> StagePacket:
    payload: Dict[str, Any]
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {"items": _safe_list(result)}

    keyword = _count_hits(payload.get("keyword_hits"))
    semantic = _count_hits(payload.get("semantic_hits"))
    rag = _count_hits(payload.get("rag_hits"))
    kg = _count_hits(payload.get("kg_hits"))
    total = keyword + semantic + rag + kg
    if total == 0:
        total = _count_hits(payload)

    payload.setdefault("keyword_count", keyword)
    payload.setdefault("semantic_count", semantic)
    payload.setdefault("rag_count", rag)
    payload.setdefault("kg_count", kg)
    payload.setdefault("total_count", total)

    preview_src = []
    for k in ("keyword_hits", "semantic_hits", "rag_hits", "kg_hits", "items", "hits", "results"):
        v = payload.get(k)
        if isinstance(v, (list, tuple)):
            preview_src = list(v)
            break

    payload["preview"] = _preview_items(preview_src, limit=3)

    return make_stage_packet(
        stage="retrieval",
        kind="parallel_retrieval_packet",
        payload=payload,
        summary=_trim(
            f"src={source} keyword={keyword} semantic={semantic} rag={rag} kg={kg} total={total}"
        ),
    )


def build_hybrid_merge_packet(result: Any) -> StagePacket:
    payload: Dict[str, Any]
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {"merged": _safe_list(result)}

    merged_count = _count_hits(payload.get("merged") or payload.get("items") or payload)
    payload.setdefault("merged_count", merged_count)
    preview_src = payload.get("merged") or payload.get("items") or payload.get("results") or []
    payload["preview"] = _preview_items(_safe_list(preview_src), limit=3)

    return make_stage_packet(
        stage="merge",
        kind="hybrid_merge_packet",
        payload=payload,
        summary=f"merged_count={merged_count}",
    )


def build_rerank_packet(result: Any) -> StagePacket:
    payload: Dict[str, Any]
    if isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {"ranked": _safe_list(result)}

    ranked_count = _count_hits(payload.get("ranked") or payload.get("items") or payload)
    payload.setdefault("ranked_count", ranked_count)
    preview_src = payload.get("ranked") or payload.get("items") or payload.get("results") or []
    payload["preview"] = _preview_items(_safe_list(preview_src), limit=3)

    return make_stage_packet(
        stage="rerank",
        kind="rerank_packet",
        payload=payload,
        summary=f"ranked_count={ranked_count}",
    )


def build_context_source_trace_packet(packets: List[StagePacket]) -> StagePacket:
    retrieval_packets = [p for p in packets if getattr(p, "kind", "") in {
        "parallel_retrieval_packet",
        "hybrid_merge_packet",
        "rerank_packet",
    }]
    payload = {
        "packet_count": len(retrieval_packets),
        "kinds": [getattr(p, "kind", "") for p in retrieval_packets],
        "summaries": [getattr(p, "summary", "") for p in retrieval_packets[:8]],
    }
    return make_stage_packet(
        stage="context_trace",
        kind="context_source_trace_packet",
        payload=payload,
        summary=_trim(" | ".join(payload["summaries"]) or f"retrieval_packets={len(retrieval_packets)}", 180),
    )
