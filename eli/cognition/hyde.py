"""
HyDE — Hypothetical Document Embeddings for ELI.
Generates a hypothetical answer to a query, then uses that answer's
embedding to search the vector store. Improves recall for vague queries.
"""
from __future__ import annotations
from typing import List, Optional



from eli.utils.log import get_logger
log = get_logger(__name__)

def expand_query_hyde(
    query: str,
    inference_fn,  # callable(prompt) -> str
    n_hypothetical: int = 1,
) -> List[str]:
    """
    Given a query, generate n_hypothetical synthetic answers using the LLM,
    then return those answers as expanded search queries.
    Falls back to [query] if generation fails.
    """
    prompt = (
        f"Write a short, factual answer (2-3 sentences) to this question "
        f"as if you already know the answer from memory:\n\n{query}\n\nAnswer:"
    )
    hypotheticals = [query]  # always include original
    for _ in range(n_hypothetical):
        try:
            hyp = inference_fn(prompt)
            if hyp and len(hyp.strip()) > 10:
                hypotheticals.append(hyp.strip())
        except Exception:
            pass
    return hypotheticals


def hyde_vector_search(
    query: str,
    inference_fn,
    k: int = 5,
) -> List[dict]:
    """
    Full HyDE pipeline: generate hypothetical doc → embed → vector search.
    Returns merged, deduplicated results.
    """
    try:
        from eli.memory.vector_store import get_vector_store
        vs = get_vector_store()
        if vs is None or vs.ntotal == 0:
            return []

        hypotheticals = expand_query_hyde(query, inference_fn, n_hypothetical=1)
        seen_texts = set()
        results = []
        for hyp in hypotheticals:
            hits = vs.search(hyp, limit=k)
            for h in hits:
                txt = h.get("text", "")
                if txt and txt not in seen_texts:
                    seen_texts.add(txt)
                    results.append(h)
        # Sort by score descending
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:k]
    except Exception as e:
        log.debug(f"[HyDE] search failed: {e}")
        return []
