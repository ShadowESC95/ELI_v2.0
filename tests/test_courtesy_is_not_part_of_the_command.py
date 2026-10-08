"""Please / thanks / for me / now after a command are not part of what it names.

"open spotify please" looked for an app called "spotify please", found none and offered to
install it; the same happened to every command's target (apps, songs, timers, sites).
"""
import pytest

from eli.execution.router_enhanced import route


@pytest.mark.parametrize("text,action,key,value", [
    ("open spotify please", "OPEN_APP", "name", "spotify"),
    ("open spotify for me please", "OPEN_APP", "name", "spotify"),
    ("launch firefox pls", "OPEN_APP", "name", "firefox"),
    ("close spotify please", "CLOSE_APP", "name", "spotify"),
    ("open youtube please", "OPEN_URL", "url", "https://youtube.com"),
    ("play trouble by eminem please", "PLAY_MEDIA", "query", "trouble by eminem"),
    # before the command too: "good. play the third world ..." searched for "good. play the third world"
    ("good. play the third world by immortal technique on spotify", "PLAY_MEDIA", "query",
     "the third world by immortal technique"),
    ("ok, open spotify", "OPEN_APP", "name", "spotify"),
])
def test_the_target_is_what_was_named(text, action, key, value):
    r = route(text)
    assert r["action"] == action and r["args"][key] == value


def test_a_title_that_is_a_courtesy_word_is_kept():
    assert route("play thank you")["args"]["query"] == "thank you"


def test_conversation_keeps_its_words():
    r = route("I love it thanks")
    assert r["action"] == "CHAT" and r["args"]["message"] == "I love it thanks"


def test_a_leading_word_stays_when_it_is_the_command_or_an_answer():
    assert route("right click")["args"].get("button") == "right"
    assert route("no, play it on youtube")["args"].get("query") != "it"
