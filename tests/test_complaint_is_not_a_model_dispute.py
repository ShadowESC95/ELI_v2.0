"""A complaint that says "you are not ..." is not the user disputing which model is loaded.

Live: "...but you are not properly searching for fucking songs i asked for!!" matched the
model-identity dispute and got the runtime status dump instead of an answer.
"""
from eli.cognition.correction_patterns import is_model_identity_dispute
from eli.kernel.engine import _said_about_the_user

SESSION = ("Why the fuck did you not open spotify when i asked you to, but you can apparently just play one "
           "fucking song/resume on spotify, but you are not properly searching for fucking songs i asked for!!")


def test_complaints_about_what_eli_did_are_not_model_disputes():
    for text in (SESSION, "you are not listening", "that's not what i said", "you're not even trying"):
        assert not is_model_identity_dispute(text), text


def test_real_model_disputes_still_are():
    for text in ("you're not GLM", "you are not running qwen", "check the model again", "wrong model",
                 "you're not using the model I picked", "no you're not"):
        assert is_model_identity_dispute(text), text


def test_the_session_complaint_is_chat_not_a_status_dump():
    from eli.kernel.engine import _mw_rs_is_runtime_status_question
    assert not _mw_rs_is_runtime_status_question(SESSION)


def test_what_eli_said_about_itself_is_not_about_the_user():
    # "Why do you say that?" after this asked ELI what it meant; it apologised for implying
    # something about the user's caffeine intake.
    assert not _said_about_the_user(
        "Feels like I've had a bit more caffeine than usual. What's on your agenda for the evening?")
    assert _said_about_the_user("You mentioned feeling groggy earlier, and you said you slept badly.")
