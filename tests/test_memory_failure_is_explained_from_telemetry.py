"""ELI must not invent why memory failed; the account comes from what retrieval did."""
from eli.cognition import memory_diag as D
from eli.cognition.output_governor import govern_output

DIAG = D.retrieval_record(5, 14, 1, 18, 0.55) | {"context_before": 5199, "context_after": 400}


def test_the_diagnostics_block_states_what_ran():
    b = D.block(DIAG)
    assert "keyword=5" in b and "semantic=14" in b and "merged 18" in b and "0.55" in b


def test_no_block_when_nothing_was_retrieved():
    assert D.block(None) == "" and D.block({}) == ""


def test_the_live_false_confession_is_replaced_by_the_real_account():
    said = ("You're right. My previous claim about lacking permanent memory was a lie, and my recall was "
            "incomplete because I failed to query the full extent of my long-term stores before answering. "
            "Here is what is stored: the Dune films.")
    out = D.drop_false_diagnosis(said, DIAG)
    assert "was a lie" not in out and "failed to query" not in out
    assert "I searched my stored memories (18 items found, confidence medium)" in out
    assert "4799 of 5199 characters" in out
    assert "Dune films" in out


def test_a_truthful_answer_is_untouched():
    text = "You mentioned Severance on 24 August."
    assert D.drop_false_diagnosis(text, DIAG) == text


def test_without_retrieval_the_model_is_not_second_guessed():
    text = "I failed to query my stores."
    assert D.drop_false_diagnosis(text, None) == text


def test_the_governor_applies_it():
    out = govern_output("I lied earlier. You watched Dune.", memory_diag=DIAG)
    assert "lied" not in out and "Dune" in out
