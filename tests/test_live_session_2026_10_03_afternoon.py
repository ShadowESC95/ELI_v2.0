"""The 2.4.99 session of 2026-10-03, 14:34-14:54, turn by turn. Every input here is
the user's real message; every expectation is what should have happened.

- "Afternoon Eli" was answered with yesterday's Netflix tab and Don Martin track as
  current: recent turns from earlier sessions reached the prompt undated, under
  "[Recent session]" / "live transcript of THIS session ... do not contradict".
- A complaint plus a correction was split in two; the complaint ran alone as a
  quick-mode META_DIAGNOSTIC, which always returned a JSON envelope as its text.
- "Why ... thursday (2 days ago, the 29th of sep)" searched today only: "today is
  saturday" won, and "29th of sep" wasn't parsed. Nothing in the window, so the
  model was handed nothing and invented dates.
- "...why the vector search is drifting ... analyse that" was a browser-routing
  complaint (cinejoy dump) in one router, and a web search in the other.
- The greeting spent 34 s in the LLM intent resolver before the reply started.
- Quick mode filled the 12.5k window (45 recent turns, 36 reranked hits).
"""
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

NOW = time.mktime(time.strptime("2026-10-03 14:44:59", "%Y-%m-%d %H:%M:%S"))
YESTERDAY_1837 = time.mktime(time.strptime("2026-10-02 18:37:59", "%Y-%m-%d %H:%M:%S"))
TODAY_1434 = time.mktime(time.strptime("2026-10-03 14:34:59", "%Y-%m-%d %H:%M:%S"))


# ── history is dated, and never called "this session" ───────────────────────

def _turns():
    return [{"role": "user", "content": "open netflix", "timestamp": YESTERDAY_1837},
            {"role": "assistant", "content": "Opened URL: https://netflix.com", "timestamp": YESTERDAY_1837},
            {"role": "user", "content": "Afternoon Eli, you back to life yet?", "timestamp": TODAY_1434}]


def test_turn_stamp_names_the_day():
    from eli.cognition.evidence_format import turn_stamp
    assert turn_stamp(YESTERDAY_1837, NOW) == "yesterday 18:37"
    assert turn_stamp(TODAY_1434, NOW) == "today 14:34"
    assert turn_stamp(NOW - 3 * 86400, NOW).endswith("3 days ago")
    assert turn_stamp(None, NOW) == ""


@pytest.mark.parametrize("builder", ["build_inline_exchange_block", "build_session_thread_block"])
def test_history_blocks_date_every_line_and_say_it_is_history(builder):
    from eli.runtime import session_continuity as sc
    with patch("eli.cognition.evidence_format.time.time", return_value=NOW):
        block = getattr(sc, builder)(_turns(), user_input="hello")
    assert "[yesterday 18:37] ELI: Opened URL: https://netflix.com" in block
    assert "history" in block and "not the current state" in block
    assert "THIS session" not in block and "[Recent session]" not in block


def test_persona_dialogue_lines_are_dated():
    from eli.cognition.context_synthesiser import ContextSynthesiser
    with patch("eli.cognition.evidence_format.time.time", return_value=NOW):
        text = ContextSynthesiser._build_turns_block(_turns())
    assert "[yesterday 18:37] assistant: Opened URL" in text


# ── no JSON ever reaches the reply ───────────────────────────────────────────

def test_quick_mode_diagnostic_answers_from_its_evidence_not_json():
    from eli.runtime.control_contracts import finalise_control_result
    eng = SimpleNamespace()
    out = finalise_control_result(eng, "what happened to your memory", "META_DIAGNOSTIC",
                                  {"ok": True, "content": "Recent failures: none logged today."},
                                  trace={}, synthesized_text="")
    assert out["content"] == "Recent failures: none logged today."
    assert "{" not in out["content"]


def test_no_evidence_is_said_plainly_and_marked_failed():
    from eli.runtime.control_contracts import NO_USABLE_EVIDENCE_TEXT, finalise_control_result
    out = finalise_control_result(SimpleNamespace(), "x", "META_DIAGNOSTIC", {"ok": True},
                                  trace={}, synthesized_text="")
    assert out["content"] == NO_USABLE_EVIDENCE_TEXT
    assert out["ok"] is False
    assert "surface" not in out["content"]


# ── a complaint is one turn ──────────────────────────────────────────────────

class _ReachedPipeline(BaseException):
    pass


@pytest.mark.parametrize("msg", [
    "What the fuck has happened to your temporal memory, timestamps and general awareness of "
    "what is fucking going on ?? Mos def was yesterday, not an hour ago, and netflix is not open ?!",
])
def test_a_complaint_with_question_marks_stays_one_turn(msg):
    from eli.kernel.engine import CognitiveEngine
    e = CognitiveEngine()
    real, calls = e.process, []

    def counting(user_input, *a, **k):
        calls.append(user_input)
        return real(user_input, *a, **k) if len(calls) == 1 else {"content": "x"}

    e.process = counting
    with patch.object(CognitiveEngine, "_store_user_turn", side_effect=_ReachedPipeline):
        with pytest.raises(_ReachedPipeline):
            e.process(msg, stream=False)
    assert calls == [msg]


def test_only_question_shaped_parts_count():
    from eli.kernel.engine import _MQS_QUESTION_START as q
    assert q.match("what is the capital of peru")
    assert q.match("and how many people live there")
    assert not q.match("Mos def was yesterday, not an hour ago")
    assert not q.match("Well we just need to get head on quantum encryption")


# ── the vector-search question is neither a browser complaint nor a web search ─

LIVE_ANALYSE = ('Apologies i confused my dates above- but you should be the one that corrects me, '
                'yesterday was friday te 2nd of October-- "want a deep dive into *why* the vector '
                'search is drifting (likely the embedding model’s decay on long-term context vs. '
                'short-term urgency),"-> yes i want you to analyse that')


def test_the_analysis_request_reaches_neither_misroute():
    from eli.execution.router_enhanced import route, wants_routing_fault_explain
    assert not wants_routing_fault_explain(LIVE_ANALYSE.lower())
    assert route(LIVE_ANALYSE)["action"] not in ("ROUTING_FAULT_EXPLAIN", "WEB_SEARCH")


def test_real_browser_complaints_and_searches_still_route():
    from eli.execution.router_enhanced import route, wants_routing_fault_explain
    assert wants_routing_fault_explain("why the fuck did you go onto the browser for that response?")
    with patch("eli.core.config.network_allowed", return_value=True):  # the suite runs offline
        assert route("search hubble deep field images")["action"] == "WEB_SEARCH"
        assert route("do a web search on fusion power")["action"] == "WEB_SEARCH"
        assert route("why is web search slow on my laptop")["action"] != "WEB_SEARCH"


# ── the period asked about ───────────────────────────────────────────────────

def test_the_live_question_searches_the_days_it_names():
    from eli.cognition.query_planner import plan_window
    q = ("Why the fuck are your dates all wrong ? If today is saturday 3rd of Otober and i was "
         "listening to MOS def on thursday (2 days ago on the 29thof sep) NOT 9 days ago- why are "
         "you storing memories with incorrect timestamps")
    start, end = plan_window(q, NOW)
    day = lambda t: time.strftime("%m-%d", time.localtime(t))
    assert (day(start), day(end)) == ("09-29", "10-02")  # 29th, "2 days ago" and thursday; not "today", not the negated 9 days


def test_nth_of_month_is_a_date():
    from eli.cognition.query_planner import plan_window
    start, _ = plan_window("what did i say on the 29th of september", NOW)
    assert time.strftime("%m-%d", time.localtime(start)) == "09-29"


def test_an_empty_window_keeps_the_nearest_dated_matches():
    from eli.memory.retrieval import invalidate_turn_cache, retrieve_for_turn
    invalidate_turn_cache()
    hit = {"id": "m1", "text": "Playing Mos Def - Sunshine on spotify", "timestamp": YESTERDAY_1837}

    class _Mem:
        def recall_memory(self, q, limit=10, **k): return [hit]
        def search_conversations(self, q, user_id=None, limit=10): return []
        def get_recent_conversation(self, **k): return []
        def get_session_summaries(self, **k): return []
        def memories_between(self, a, b, limit=24, **k): return []
        def search_archive(self, q, limit=4): return []

    window = (NOW - 4 * 86400, NOW - 2 * 86400)
    tr = retrieve_for_turn(_Mem(), "mos def", window=window, use_cache=False, rerank=False)
    assert [h["id"] for h in tr.semantic_hits] == ["m1"]
    assert tr.semantic_hits[0]["outside_window"] is True
    assert tr.window_stats["in_window"] == 0 and tr.window_stats["outside_window"] == 1


# ── quick replies stay quick ─────────────────────────────────────────────────

def test_quick_mode_keeps_a_lean_prompt_and_deep_modes_get_the_full_counts():
    from eli.core.cognition_tunables import prompt_count, snapshot
    with patch("eli.core.model_tier.tier_scale", return_value=1.5):
        snap = snapshot()
        assert prompt_count("cog.mem_recent_turns", "quick", snap) == 8
        assert prompt_count("cog.rerank_top_k", "quick", snap) == 12
        assert prompt_count("cog.mem_recent_turns", "research", snap) == snap["cog.mem_recent_turns"] > 8


@pytest.mark.parametrize("text,social", [
    ("Afternoon Eli, you back to life yet?", True),
    ("Morning pal, how is the head?", True),
    ("Morning Eli, what's the weather?", False),
    ("you there? set a timer for 5 minutes", False),
])
def test_greetings_skip_the_llm_intent_resolver(text, social):
    from eli.cognition.llm_intent import is_social_checkin
    assert is_social_checkin(text) is social


# ── what the GPU actually holds ──────────────────────────────────────────────

def test_a_full_expert_offload_asks_llamacpp_for_every_layer():
    from eli.core import moe_offload
    with patch.object(moe_offload, "profile", return_value=SimpleNamespace(block_count=40)):
        assert moe_offload.full_offload_layers(40, "m.gguf") == 41  # 40 gave 39 blocks + output
        assert moe_offload.full_offload_layers(30, "m.gguf") == 30
        assert moe_offload.full_offload_layers(99, "m.gguf") == 99


def test_the_whole_layer_fit_line_is_marked_unused_for_moe():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "eli/core/hardware_profile.py").read_text()
    i = src.index("if _moe_plan:\n        if _dense_fit_line is not None:")
    assert "NOT used for this mixture-of-experts" in src[i:i + 600]


# ── "open cinejoy.pk in web" opens the website (live, 2026-10-02 18:41) ─────

@pytest.mark.parametrize("text,action,arg", [
    ("open cinejoy.pk", "OPEN_URL", "https://cinejoy.pk"),
    ("open cinejoy.pk in web", "OPEN_URL", "https://cinejoy.pk"),
    ("open cinejoy.pk in the browser", "OPEN_URL", "https://cinejoy.pk"),
    ("open spiegel.de", "OPEN_URL", "https://spiegel.de"),
    ("open youtube.com", "OPEN_URL", "https://youtube.com"),
])
def test_websites_open_in_the_browser(text, action, arg):
    from eli.execution.router_enhanced import route
    r = route(text)
    assert r["action"] == action, r
    assert r["args"].get("url") == arg


@pytest.mark.parametrize("text", ["open notes.txt", "open main.py", "open report.pdf"])
def test_files_are_not_websites(text):
    from eli.execution.portable_intent_contract import _looks_like_url_target
    assert not _looks_like_url_target(text.split(" ", 1)[1])


def test_a_non_site_in_the_browser_is_a_browser_search():
    from eli.execution.portable_intent_contract import web_open_target
    assert web_open_target("quantum news in the browser") == ("OPEN_BROWSER", {"query": "quantum news"})
    assert web_open_target("firefox") is None


def test_the_mirror_rule_still_follows_the_rule_it_mirrors():
    """NO FALSE SELF-DENIAL opens "The mirror of the rule above": it must come
    straight after NO INVENTED SELF-MECHANISM, in the full block and in any
    selection that carries both. The two rules added here were first inserted
    between them."""
    from eli.kernel import prompt_rules as pr

    def names(block):
        return [line.split(":")[0] for line in block.splitlines() if line.startswith("- ")]

    full = names(pr.all_rules())
    at = full.index("- NO INVENTED SELF-MECHANISM")
    assert full[at + 1] == "- NO FALSE SELF-DENIAL", "another rule sits between the two"
    assert full.index("- EXPLAINING YOUR OWN MISTAKES") > at + 1 and full.index("- DATES") > at + 1
    picked = names(pr.select_rules(user_input="how does your memory actually work? you got that wrong",
                                   memory_context="", profile_text=""))
    if "- NO INVENTED SELF-MECHANISM" in picked and "- NO FALSE SELF-DENIAL" in picked:
        assert picked.index("- NO FALSE SELF-DENIAL") == picked.index("- NO INVENTED SELF-MECHANISM") + 1
