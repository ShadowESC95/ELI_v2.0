"""Regression for a live 2.4.54 bug report: pasting ELI's OWN console output
back at it could hijack routing.

`eli.gui.panels.startup` prints `persona_updater: kg sync complete -- N
entities, M relations` on every single turn -- it is not incidental, it is
the normal steady-state log line. The memory-internals route contract
(`_eli_phase38_final_memory_question_contract`) matched the bare word "kg"
anywhere in the input, so a user who pasted a GUI load-ladder log to ask "why
did my GPU settings get overridden?" had their whole question re-routed to
EXPLAIN_MEMORY_RUNTIME at confidence 0.995, registered as a "final" (i.e.
override-priority) pipeline stage -- which preempted the long-question guard
before it got a chance to run at all. The reply that came back answered a
question about SQLite memory internals, not the GPU/ctx question that was
actually asked.

Fix: drop the bare "kg" / "rag" tokens from the mechanism-name alternation
(both too short to be unambiguous); keep the full, unambiguous phrases.
"""
from __future__ import annotations

from eli.execution.router_enhanced import route

# The actual pasted GUI log from the bug report (trimmed to the load-ladder
# lines that matter, including the "kg sync complete" line that caused it).
PASTED_GUI_LOG = (
    "[GUI][LOAD] attempt 1/13: requested (ctx=12384 gpu_layers=10 batch=128)\n"
    "[GUI][LOAD] verifying your settings on this machine "
    "(ctx=12384 gpu_layers=10 batch=128) — up to 180s this once, then remembered…\n"
    "persona_updater: overlay updated (8 sections)\n"
    "persona_updater: kg sync complete — 1 entities, 0 relations\n"
    "[LOAD_PROBE] timed out after 180s — treating as unproven\n"
    "[GUI][LOAD] could not verify your settings in time "
    "(probe timed out after 180s (unproven)) — they exceed the measured fit "
    "(ctx 12384>4096), and loading them unproven is what aborts mid-generation. "
    "Falling through to the measured fallbacks; raise ELI_LOAD_PROBE_TIMEOUT to "
    "allow the check more time, or set ELI_LOAD_PROBE=0 to load them as entered "
    "without proof.\n"
    "[GUI][LOAD] attempt 2/13: smart-fit (ctx=4096 gpu_layers=11 batch=128)\n"
    "[GUI][LOAD] selected=smart-fit (ctx=4096 gpu_layers=11 batch=128)"
)


def test_pasted_gui_log_no_longer_hijacks_the_memory_route():
    out = route(PASTED_GUI_LOG)
    assert out["action"] != "EXPLAIN_MEMORY_RUNTIME", (
        f"a pasted GUI load log's incidental 'kg sync complete' line must not "
        f"route the whole question to memory internals, got {out['action']} "
        f"(matched_by={out.get('meta', {}).get('matched_by')})"
    )


def test_bare_kg_alone_does_not_match_memory_internals():
    # Isolates the exact token that caused the false positive, independent of
    # the rest of the pasted log.
    out = route("persona_updater: kg sync complete — 1 entities, 0 relations")
    assert out.get("meta", {}).get("matched_by") != "eli.final_memory_internals_route_contract"


def test_bare_rag_alone_does_not_match_memory_internals():
    out = route("I bought a nice rag for cleaning the GPU fans")
    assert out.get("meta", {}).get("matched_by") != "eli.final_memory_internals_route_contract"


# The fix must not blunt genuine mechanism questions -- these still name the
# retrieval/storage stack unambiguously and should still route as before.
def test_knowledge_graph_full_phrase_still_matches():
    out = route("Explain how your knowledge graph works internally")
    assert out["action"] == "EXPLAIN_MEMORY_RUNTIME", out


def test_faiss_still_matches():
    out = route("Walk me through how FAISS fits into your memory pipeline")
    assert out["action"] == "EXPLAIN_MEMORY_RUNTIME", out


def test_hyde_still_matches():
    out = route("Explain how HyDE works in your retrieval pipeline start to finish")
    assert out["action"] == "EXPLAIN_MEMORY_RUNTIME", out
