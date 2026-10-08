""""You did not open spotify" re-runs the open, when that is what ELI just did.

Live: "open spotify" -> "Opened app: Spotify" (it had died at once), then "You did not open spotify
again!!!" went to chat and ELI wrote that it had reviewed the logs, and a pretend ```bash open
spotify``` block. Nothing was opened.
"""
import time

from eli.cognition.self_claims import complains_about_eli
from eli.runtime.action_commitment import redo_applies

NOW = time.time()
OPENED = {"action": "OPEN_APP", "args": {"name": "spotify"}, "input": "open spotify", "ts": NOW - 20}
PLAYED = {"action": "PLAY_MEDIA", "args": {"target": "spotify", "query": "trouble by eminem"},
          "input": "play trouble by eminem", "ts": NOW - 20}


def test_saying_it_did_not_happen_redoes_it():
    for text in ("You did not open spotify again!!!", "spotify didn't open", "nothing happened",
                 "it didn't work", "you never opened it", "spotify still hasn't opened"):
        assert redo_applies(text, OPENED, now=NOW), text
    for text in ("it didn't play", "you didn't play it", "the song didn't play", "nothing is playing",
                 "spotify didn't play the song"):
        assert redo_applies(text, PLAYED, now=NOW), text


def test_only_when_it_is_about_what_eli_just_did():
    assert not redo_applies("you did not open firefox", OPENED, now=NOW)
    assert not redo_applies("you did not play the song", OPENED, now=NOW)
    assert not redo_applies("the printer didn't work", OPENED, now=NOW)
    assert not redo_applies("spotify didn't open", dict(OPENED, ts=NOW - 3600), now=NOW)


def test_the_user_talking_about_themselves_is_not_a_redo():
    for text in ("I did not open it", "we didn't open it yet", "You didn't, i am asking you why you feel"):
        assert not redo_applies(text, OPENED, now=NOW), text


def test_saying_it_did_not_happen_is_a_complaint_about_eli():
    assert complains_about_eli("You did not open spotify again!!!")
    assert complains_about_eli("you haven't played anything")
    assert not complains_about_eli("you never know, it might rain")
