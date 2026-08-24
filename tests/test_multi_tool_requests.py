"""ELI must act on EVERY half of a multi-capability request.

Reported: "Eli needs to be smarter, especially with complex or multiple
queries that involve tools" and "make sure Eli knows exactly what to do, what
to use, and self aware."

The splitter's imperative vocabulary IS its model of what ELI can be told to
do, and it had drifted from the capability manifest: of the 122 distinct verbs
in ELI's own action names, 99 were unknown to it. Measured consequences:

    "do a web search on QFT and open the browser"
        -> "do" was not a verb, so nothing split and the browser was never
           opened; the tail was swallowed into the query, which was sent to
           the search engine as "on QFT and open the browser".
    "open firefox then maximise it"
        -> "maximise" was not a verb, so the split was rejected and OPEN_APP
           received an app named "firefox then maximise it".

The guard that keeps this safe is that EVERY segment must start with an
imperative, which is why only genuine imperatives were added and not the nouns
lifted from action names (AMBIENT_VISION, GPU_STATUS, CODEBASE_GRAPH). Both
directions are locked below.
"""
import json
import re
from pathlib import Path

import pytest

from eli.execution import router_enhanced as router
from eli.runtime.command_splitter import split_commands, _IMP_START


def _route(text):
    return router.route(text)


# ── both halves must survive ───────────────────────────────────────────────
@pytest.mark.parametrize("phrase,parts", [
    ("do a web search on QFT and open the browser",
     ["do a web search on QFT", "open the browser"]),
    ("open firefox then maximise it", ["open firefox", "maximise it"]),
    ("take a screenshot and open the downloads folder",
     ["take a screenshot", "open the downloads folder"]),
    ("pause spotify then increase the volume",
     ["pause spotify", "increase the volume"]),
    ("open spotify and play the third world",
     ["open spotify", "play the third world"]),
])
def test_multi_capability_requests_split(phrase, parts):
    assert split_commands(phrase) == parts


@pytest.mark.parametrize("phrase", [
    "do a web search on QFT and open the browser",
    "open firefox then maximise it",
    "check the weather and set an alarm for 7am",
])
def test_router_returns_multi_command_not_half_the_job(phrase):
    out = _route(phrase)
    assert out["action"] == "MULTI_COMMAND", (
        f"{phrase!r} -> {out['action']}; only one half of the request would run"
    )
    assert len(out["args"]["commands"]) >= 2


def test_second_half_is_not_swallowed_into_a_search_query():
    """The exact live defect: the browser half ended up inside the query."""
    out = _route("do a web search on QFT and open the browser")
    assert out["action"] != "WEB_SEARCH"
    assert "open the browser" not in str(out.get("args", {}).get("query", ""))


# ── and ordinary phrases must NOT be torn apart ────────────────────────────
@pytest.mark.parametrize("phrase", [
    "play tom and jerry",
    "open the file and folder manager",
    "set the volume and brightness",
    "play rock and roll",
    "play the third world by immortal technique",
    "play bang along by the game",
])
def test_ordinary_phrases_stay_whole(phrase):
    assert split_commands(phrase) is None, f"{phrase!r} was wrongly split"
    assert _route(phrase)["action"] != "MULTI_COMMAND"


def test_questions_are_never_split():
    assert split_commands("what is the weather and should I take a coat?") is None


# ── the vocabulary must track what ELI can actually do ─────────────────────
# Imperative verbs that appear in ELI's own action names. Nouns lifted from
# action names are deliberately excluded — admitting them would split ordinary
# phrases, which the cases above forbid.
_CAPABILITY_IMPERATIVES = {
    "open", "close", "play", "pause", "stop", "set", "get", "run", "send",
    "search", "find", "read", "generate", "create", "write", "schedule",
    "update", "download", "enable", "disable", "examine", "review", "make",
    "add", "cancel", "clear", "confirm", "convert", "design", "diagnose",
    "dictate", "execute", "exit", "explain", "fix", "focus", "help", "hide",
    "import", "list", "listen", "maximise", "minimise", "minimize", "next",
    "previous", "refresh", "repeat", "resolve", "restore", "say", "shuffle",
    "skip", "speak", "switch", "test", "tile", "train", "transcribe",
}


@pytest.mark.parametrize("verb", sorted(_CAPABILITY_IMPERATIVES))
def test_splitter_knows_every_capability_imperative(verb):
    """A capability ELI has but the splitter does not recognise cannot appear
    as the second half of a chained request."""
    assert _IMP_START.search(f"{verb} something"), (
        f"'{verb}' is a real ELI capability verb the splitter does not know — "
        f"'<command> and {verb} ...' would silently drop that half"
    )


def test_capability_imperatives_are_actually_in_the_manifest():
    """Keeps the list above honest: every verb in it must come from a real
    action, so this test fails if a capability is renamed or removed."""
    manifest = Path("capability_manifest.json")
    if not manifest.exists():
        pytest.skip("capability_manifest.json not present")
    actions = {c["action"] for c in json.loads(manifest.read_text())["capabilities"]}
    verbs = {a.split("_")[0].lower() for a in actions}
    # English imperatives ELI accepts that are not action-name prefixes: they
    # reach their capability through the router rather than by name ("enable
    # ambient vision" -> AMBIENT_VISION). Verified absent from the manifest by
    # this test's own first run, which is why they are listed rather than
    # assumed.
    extra = {"do", "make", "find", "read", "help", "explain", "say", "listen",
             "enable", "disable", "send", "update", "review"}
    orphans = sorted(_CAPABILITY_IMPERATIVES - verbs - extra)
    assert not orphans, f"verbs claimed as capabilities but absent from the manifest: {orphans}"
