"""A correction that also asks a real memory/log question must not get the correction-repair
shortcut's evidence-free patch prompt. From a live session: 'that is most definitely not an in
depth answer. So you are not aware of anything that happened over the last week? nothing in your
logs?' was classified CORRECTION and handed to a prompt with only the last few raw turns (no
retrieval) and an instruction to leave memory/runtime out — so it deflected with "I don't have
access to external logs" instead of actually checking. The embedded question must escalate to the
full pipeline, which does real retrieval.
"""
from eli.kernel.engine import _correction_embeds_memory_question


def test_the_live_failing_message_is_caught():
    msg = ("Dude, that is most definitely not an in depth answer. So you are not aware of "
           "anything that happened over the last week? nothing in your logs ?")
    assert _correction_embeds_memory_question(msg)


def test_plain_corrections_without_a_memory_question_are_left_alone():
    for msg in (
        "that's not what I asked",
        "you didn't answer my question properly",
        "no, that's wrong",
        "what the fuck are you talking about",
    ):
        assert not _correction_embeds_memory_question(msg)


def test_other_phrasings_of_a_real_memory_question_are_caught():
    for msg in (
        "check your memory logs and conversation logs over the past week",
        "do you remember what I told you two days ago?",
        "what do you remember about that",
    ):
        assert _correction_embeds_memory_question(msg)
