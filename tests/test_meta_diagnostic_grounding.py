"""META_DIAGNOSTIC (and other control actions) invented specifics not backed
by their own evidence packet.

Live incident (2026-10-02): asked why a timer+Spotify+web-search batch had
gone wrong, ELI's META_DIAGNOSTIC answer stated a "~51% success rate" for
MEDIA_CONTROL and a named "Liebnitz incident" / race-condition mechanism.
Pressed for timestamps, it admitted on its own: "I did not read
files.orchestrator or any log file to produce that explanation; I invented
the narrative."

Root cause, confirmed by reading the actual code paths:

1. `_meta_diagnostic_report()` (control_contracts.py) never calls
   `action_reliability()` — no per-action reliability percentage is ever
   computed or included in META_DIAGNOSTIC's evidence packet. The "51%" had
   no source.
2. The control-synthesis path META_DIAGNOSTIC actually runs through
   (`_run_chat_reasoning_loop` inside the `_is_control_action` branch of
   `process()`) only ran the fixed phrase/path blocklist
   `output_violates_evidence` — not `validate_against_evidence`, which
   already has a general "unsupported figure" check and was already wired
   into the *other* two control-synthesis paths
   (`_compact_grounded_synthesis`, `_synthesize_control_with_mode_framing`).
   This was the one gate that skipped it.

Fixed by wiring `validate_against_evidence` into that third gate too, and by
adding an explicit anti-fabrication line to the PIPELINE CONTRACT prompt
telling the model to say "no logged evidence for that" instead of inventing
an incident name, mechanism, or percentage.
"""
import pathlib

ENGINE = pathlib.Path(__file__).resolve().parents[1] / "eli" / "kernel" / "engine.py"


def _control_action_block() -> str:
    src = ENGINE.read_text(encoding="utf-8")
    i = src.index("if _is_control_action(action):")
    j = src.index("if not _synth:", i)
    return src[i:j]


def test_pipeline_contract_forbids_inventing_incidents_and_percentages():
    block = _control_action_block()
    assert "logged evidence for it" in block
    assert "reliability percentage" in block


def test_full_loop_control_synthesis_runs_the_figure_validator():
    """The gate that produced the live bad answer must now also run
    validate_against_evidence, not just the phrase/path blocklist."""
    block = _control_action_block()
    i = block.index("_output_violates_evidence(_synth, _ev_text)")
    rest = block[i:]
    assert "from eli.cognition.output_governor import validate_against_evidence" in rest
    assert "_ctrl_verdict.get(\"unsafe\")" in rest
