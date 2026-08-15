"""Locks on grounded control actions being able to answer in depth.

Seen live on v2.1.55: asked "who are you?", ELI replied with a 162-character
runtime blurb. Told "do better, much more in depth", then asked again, it
returned the *identical* 162 characters — in tree_of_thoughts mode, with
grounding 0.98 and five agents reporting.

It was not the model refusing to elaborate. The SELF_REPORT payload carries
identity, real runtime figures, requested-vs-effective settings and a
runtime_health block naming actual concerns — but only its pre-baked one-line
`content` was forwarded to synthesis, so the model had nothing else in front of
it. The log said it plainly: "compact synthesis on 180 chars of evidence".

The flat-text-only design was itself a fix for a real 35K-char prompt overflow
that produced garbage output and CUDA crashes, so the repair adds a curated slice
under a hard cap rather than the whole payload.
"""
import pytest

from eli.kernel.engine import CognitiveEngine

ONE_LINER = (
    "I'm ELI (Enhanced Learning Interface), running Qwen_Qwen3-8B-Q4_K_M.gguf "
    "locally on GPU (99 layers offloaded). Context window: 10384 tokens. "
    "All core systems nominal. You're alex."
)


def _enrich(payload, base=ONE_LINER, **kw):
    """Call the helper without constructing a full engine (which loads a model)."""
    holder = type("H", (), {"_SYNTH_EVIDENCE_SKIP": CognitiveEngine._SYNTH_EVIDENCE_SKIP})()
    return CognitiveEngine._structured_control_evidence(holder, payload, base, **kw)


@pytest.fixture
def self_report_payload():
    """The shape SELF_REPORT actually returns, including the oversized settings dict."""
    return {
        "ok": True,
        "action": "SELF_REPORT",
        "content": ONE_LINER,
        "response": ONE_LINER,
        "report": {
            "paths": {"user_db": "/x/user.sqlite3", "agent_db": "/x/agent.sqlite3"},
            "settings": {f"knob_{i}": "v" * 40 for i in range(120)},
            "runtime": {"model_name": "Qwen_Qwen3-8B-Q4_K_M.gguf"},
        },
        "evidence": {
            "identity": {"name": "ELI", "active_user_name": "alex"},
            "runtime": {"effective_context_size": 10384, "effective_gpu_layers": 99},
            "runtime_health": {
                "recommended_n_ctx": 6144,
                "concerns": ["context 10384 exceeds the hardware-recommended 6144"],
            },
        },
    }


def test_structured_evidence_reaches_synthesis(self_report_payload):
    """The core regression: synthesis saw only the one-liner."""
    out = _enrich(self_report_payload)

    assert len(out) > len(ONE_LINER) * 2


@pytest.mark.parametrize("fact", [
    "runtime_health",          # the concerns block ELI could never mention
    "concerns",
    "effective_gpu_layers",
    "active_user_name",
    "user_db",
])
def test_substantive_facts_are_available(self_report_payload, fact):
    assert fact in _enrich(self_report_payload)


def test_the_one_liner_is_still_included(self_report_payload):
    """Enrichment adds to the summary, it does not replace it."""
    assert ONE_LINER in _enrich(self_report_payload)


# ── the overflow that the flat-only design was protecting against ───────────
def test_the_settings_blob_is_excluded(self_report_payload):
    """~4KB of image/vision/gaze knobs would crowd out the answer and leak config."""
    out = _enrich(self_report_payload)
    assert "knob_0" not in out and "knob_119" not in out


def test_evidence_is_hard_capped():
    """Overflow caused garbage output and CUDA crashes — the cap is the guard.

    `cap` bounds the STRUCTURED portion; the one-line summary is added on top of
    it, so the ceiling is cap + base + the truncation marker.
    """
    huge = {"evidence": {f"k{i}": "z" * 200 for i in range(200)}}
    cap = 4000

    out = _enrich(huge, cap=cap)

    assert len(out) <= cap + len(ONE_LINER) + 64
    assert "truncated" in out


def test_stays_well_under_the_synthesis_cap(self_report_payload):
    """_compact_grounded_synthesis truncates at 8000; enrichment must not reach it."""
    assert len(_enrich(self_report_payload)) < 8000


# ── it must never break the ordinary paths ──────────────────────────────────
@pytest.mark.parametrize("payload", [None, "not a dict", 42, []])
def test_non_dict_payloads_pass_through(payload):
    assert _enrich(payload) == ONE_LINER


def test_payload_without_structure_passes_through():
    assert _enrich({"content": ONE_LINER}) == ONE_LINER


def test_quick_path_content_is_not_mutated(self_report_payload):
    """Quick mode returns `content` verbatim; enrichment must be a separate value."""
    before = self_report_payload["content"]
    _enrich(self_report_payload)
    assert self_report_payload["content"] == before
