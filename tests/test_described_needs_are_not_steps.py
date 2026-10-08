"""A list item that describes something is not a step a "yes" can run.

Asked what upgrades it wanted, ELI listed what it needed; the list was read as steps and
"I need the executor to stop returning NOOP when it should be sending PAUSE_MEDIA" was kept as
STOP_MEDIA, waiting for a "yes" to stop the music.
"""
from eli.runtime.pending_proposal import read_reply

WISHES = (
    "Here is what I need:\n"
    "1. **Media State Verification:** My success rate for media control is sitting at 51%. "
    "I need the executor to stop returning `NOOP` when it should be sending a `PAUSE_MEDIA` command "
    "because it thinks Spotify is idle but isn't, or vice versa. A simple handshake protocol where the "
    "OS confirms the state before I report it would save us both the embarrassment of me announcing "
    "\"Now playing: Silence\" while you're listening to Eminem.\n"
)


def test_needs_and_descriptions_are_not_steps():
    assert read_reply(WISHES)["items"] == []


def test_steps_still_are():
    items = read_reply("The plan:\n1. Check the calendar for Friday.\n2. Pause the music.\nShall I go ahead?")["items"]
    assert [i["action"] for i in items] == ["LIST_EVENTS", "MEDIA_CONTROL"]
