"""ELI's own log noise (\"kg sync complete\") pasted into chat must not route to
EXPLAIN_MEMORY_RUNTIME."""
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


# ── a pasted message from someone else (2.5.16 log: ChatGPT's critique of ELI) ──

CHATGPT_CRITIQUE = (
    "Alright, tell ELI the review panel has its notes. ELI has evidence about its own memory "
    "architecture. Your runtime reported, live: Qwen3.6-35B-A3B Q4_K_M, ~16k effective context, eight "
    "physical SQLite stores, 507 memory entries, FTS5, FAISS and a knowledge graph. Show the receipt. "
    "You have an audit ledger. Use it. I am making it more precise: you need to enforce provenance. "
    "Your own trace for a simple greeting assembled a ~9,809-token prompt and took about 267 seconds."
)


def test_the_users_own_words_are_split_from_what_they_pasted():
    from eli.cognition.correction_patterns import shortcut_text, split_pasted
    own, pasted = split_pasted("here is the other assistant's reply, time to bring your best now Eli ---> " + CHATGPT_CRITIQUE)
    assert own == "here is the other assistant's reply, time to bring your best now Eli"
    assert pasted.startswith("Alright, tell ELI")
    own, pasted = split_pasted("here's what it said:\n" + CHATGPT_CRITIQUE)
    assert own == "here's what it said" and pasted.startswith("Alright")
    assert split_pasted("a -> b is an arrow in code") == ("a -> b is an arrow in code", "")
    # a report answers a short request for it; a long message is the user talking
    assert shortcut_text(CHATGPT_CRITIQUE) == ""
    assert shortcut_text("what is your runtime status?") == "what is your runtime status?"


def test_a_paste_mentioning_elis_runtime_and_memory_is_no_report_request():
    """Four runtime and personal-memory dumps answered a pasted ChatGPT critique in one evening."""
    from eli.cognition.correction_patterns import shortcut_text
    from eli.runtime.control_contracts import route_control_text
    for message in (CHATGPT_CRITIQUE, "Right, go all out on this know-it-all, here's its response --> " + CHATGPT_CRITIQUE):
        said = shortcut_text(message)
        assert not said or route_control_text(said, "CHAT") in (None, "", "CHAT")


def test_a_recap_of_the_last_few_messages_is_read_from_the_conversation():
    """It went to the intent model (90 s) and came back as a memory dump reaching back to August."""
    for text in ("can you check the last, say 7-8 messages, summarise what has been said/happening please",
                 "summarise the last few messages", "what was said in the last couple of messages?"):
        out = route(text)
        assert out["action"] == "CHAT" and out["meta"]["matched_by"] == "conversation.recap", text
    assert route("play the last few songs")["action"] != "CHAT"


def test_a_reply_pointed_at_by_count_is_an_earlier_reply():
    from eli.cognition.correction_patterns import refers_to_earlier_reply
    assert refers_to_earlier_reply("look at your message from 2 messages ago- you answered fine in the first half")
    assert refers_to_earlier_reply("a few replies back you said")
    assert not refers_to_earlier_reply("I have two messages for you")
