"""A message read as what it tells ELI to do and what it only says.

Two jobs, one vocabulary (`COMMAND_VERBS`, the verbs a command starts with):

  * `split_commands`  one utterance chaining several commands, into its parts;
  * `read_message`    a message of several sentences, into the ones that are instructions
                      and the rest, which is talk. `instruction` is its test of form.

`split_commands` splits one utterance that chains several imperative commands into its parts.

    "close steam and set an alarm for 7am"   → ["close steam", "set an alarm for 7am"]
    "open spotify then play vincent's tale"   → ["open spotify", "play vincent's tale"]

The engine runs each part through its normal pipeline (route → agents → execute) and
combines the results — so a single sentence can trigger several actions.

Guards against false splits (the hard part):
  • must START with an imperative verb (so questions / statements aren't split);
  • EVERY segment must also start with an imperative verb — so "play tom and jerry",
    "open the file and folder manager", "set the volume and brightness" stay whole;
  • no "?" (compound questions are handled by the engine's question splitter);
  • 2–5 segments.

Pure/deterministic — no model, no I/O. The engine additionally verifies ≥2 segments
route to real actions before executing, as a second safety net.
"""
from __future__ import annotations

import re
from typing import List, Optional

# Conjunctions that separate chained commands. "and then" / "and also" before bare
# "and"/"then" so they're consumed as one separator.
_CONJ_RX = re.compile(
    r"\s+(?:and then|and also|;|,\s*then\s+|\bthen\b|\band\b)\s+", re.I)

# "analyse and summarise report.docx" is ONE request (synonyms for "engage with this
# file"), not two — but "analyse" and "summarise" each pass _IMP_START on their own, so
# it split into ["Analyse", "summarise report.docx"], the first with no object at all.
# The router's own SUMMARIZE_FILE pattern already treats these as one compound verb;
# don't steal the match before it gets there.
_FILE_ENGAGE_VERBS = re.compile(r"^\s*(?:summari[sz]e|analyse|analyze|read|look\s+at)\b", re.I)

# Imperative verbs a real command starts with: the splitter's model of what ELI can be told
# to do. It had drifted from the capability manifest, so "do a web search and open the browser"
# and "open firefox then maximise it" didn't split. Only real imperatives are added; most manifest
# verbs are nouns from action names (GPU_STATUS) and would split ordinary phrases. The companion
# test locks both directions.
_SPLIT_VERBS = (
    r"open|launch|start|play|pause|stop|close|quit|kill|set|get|fetch|show"
    r"|check|run|remind|turn|mute|unmute|screenshot|take|send|search|find|read"
    r"|generate|create|write|build|schedule|update|download|enable|disable|email"
    r"|message|post|analyse|analyze|examine|review|make|give me|tell me to"
    # capability-derived imperatives
    r"|do|add|cancel|clear|confirm|convert|decline|design|diagnose|dictate"
    r"|execute|exit|explain|fix|focus|help|hide|import|list|listen"
    r"|maximise|maximize|minimise|minimize|next|previous|prepare|refresh"
    r"|remove|rename|repeat|resolve|restore|resume|say|shuffle|skip|speak"
    r"|summarise|summarize|switch|test|tile|train|transcribe"
    # desktop-control imperatives
    r"|click|press|type|copy|paste|scroll|move|select|record|toggle"
    r"|install|uninstall|connect|disconnect|increase|decrease|lower|raise"
)
_IMP_START = re.compile(r"^\s*(" + _SPLIT_VERBS + r")\b", re.I)
# Verbs a command also starts with that do not divide a sentence in two: "save it and tell me when
# it is done" is one request. With the ones above this is the one list of what a command starts
# with (the intent resolver kept a second, shorter one).
_ALSO_STARTS = "call|delete|describe|forget|give|improve|look|remember|save|store|tell|volume"
_COMMAND_START = re.compile(r"^\s*(" + _SPLIT_VERBS + "|" + _ALSO_STARTS + r")\b", re.I)
COMMAND_VERBS = tuple(sorted({v for v in (_SPLIT_VERBS + "|" + _ALSO_STARTS).split("|") if " " not in v}))


def _trim_trailing_chatter(seg: str) -> str:
    """Drop a conversational sentence fused onto the end of a command segment, e.g.
    'play evil by eminem. haha no, you already told me about that' →
    'play evil by eminem'. Without this the trailing banter became part of the media
    title and was searched verbatim.

    Conservative on purpose: only cut at a '. ' / '! ' / '? ' boundary when the tail is
    ≥3 words and is NOT itself imperative — so short titles with internal punctuation
    ('play mr. brightside') and any genuinely chained command survive untouched."""
    for mt in re.finditer(r"[.!?]\s+", seg):
        head = seg[:mt.start()].strip(" ,.")
        tail = seg[mt.end():].strip()
        if not head or _IMP_START.search(tail):
            continue
        if len(tail.split()) >= 3:
            return head
    return seg


def split_commands(text: str, *, max_parts: int = 5) -> Optional[List[str]]:
    """Return the imperative command segments if `text` chains ≥2 of them, else None."""
    t = (text or "").strip()
    if not t or "?" in t:
        return None
    if not _IMP_START.search(t):
        return None
    parts = [p.strip(" ,.") for p in _CONJ_RX.split(t) if p.strip(" ,.")]
    if not (2 <= len(parts) <= max_parts):
        return None
    if not all(_IMP_START.search(p) for p in parts):
        return None
    if all(_FILE_ENGAGE_VERBS.search(p) for p in parts):
        return None
    return [_trim_trailing_chatter(p) for p in parts]


# ── instructions and talk ────────────────────────────────────────────────────
#
# Rules that fire on a word carried commands out from inside sentences that were not telling ELI
# to do anything: a complaint ("...you did not open spotify or play any song just now, you need
# to stop lying to me...") stopped the film that was playing, and a sentence of ELI's own
# explanation ("Spotify received that stop signal, paused the track, ...") was stored as a step
# and run on "yes". What follows is about the form of a sentence only. No action is named here.

# What may stand in front of an instruction without changing it: a greeting, an address, a
# courtesy, a joining word.
_LEAD = re.compile(
    r"^\s*(?:(?:and|but|so|then|also|now|ok|okay|alright|right|well|hey|hi|hello|yo|eli|please|pls|kindly|"
    r"just|quickly|buddy|bud|mate|man|good|great|nice|cool|thanks|thank you|cheers)\b[\s,.!:;-]*"
    # "see, ..." and "look, ..." call for attention; "see if ..." and "look up ..." are verbs
    r"|(?:see|look|listen)\s*[,.!:;-]+\s*)*",
    re.I)
# The frame of a request. What follows it is the instruction.
_REQUEST = re.compile(
    r"^(?:(?:can|could|would|will|won'?t) (?:you|u)(?: (?:please|kindly|just|now|also|quickly))*"
    r"|i(?:'d| would) (?:like|love)(?: (?:you|for you))? to|i (?:want|need)(?: you)? to|i wanna"
    r"|you (?:can|could|may)(?: (?:now|just|also))?|go ahead and|let'?s|time to"
    r"|why (?:don'?t|not) (?:you|u|we)(?: just)?|how about (?:you|u|we)(?: just)?)\s+", re.I)
# A sentence about something, or asking about it: it starts with who or what it is about, or with
# the verb that asks. An instruction starts with what to do.
_ABOUT = re.compile(
    r"^(?:you|u|i|it|he|she|they|we|that|this|these|those|there|someone|something|nothing|everything|"
    r"you'?re|you'?ve|you'?d|i'?m|i'?ve|i'?d|it'?s|that'?s|there'?s|"
    r"why|what(?:'?s)?|who(?:'?s)?|whose|where(?:'?s)?|when|which|how(?:'?s)?|"
    r"did|didn'?t|haven'?t|has|hasn'?t|hadn'?t|was|wasn'?t|were|weren'?t|is|isn'?t|are|aren'?t|am|does|doesn'?t|"
    # "have you opened it?" asks; "have the summary ready by tomorrow" tells
    r"(?:do|have|had) (?:you|u|i|we|they|it|he|she|that|this))\b(?![.-]\w)", re.I)
# Where a sentence about something turns to telling ELI what to do: "this is great, play it again".
# Speech arrives without punctuation ("that was great can you play some jazz"), so a request's own
# frame marks the turn as well.
_CLAUSE_END = re.compile(
    r"[,;]\s+|\s+[-–—]\s+"
    r"|\s+(?=(?:can|could|would|will) (?:you|u)\b|i(?:'d| would) like you to\b|i (?:want|need) you to\b|please\s+\w)")
_SENTENCE_END = re.compile(r"(?<=[.!?])[\s]+(?=[^\s])|\n+")
# "mr. brightside", "vs. the world", "feat. ill bill": a full stop that does not end a sentence.
_ABBREVIATION = re.compile(r"\b(?:mr|mrs|ms|dr|st|vs|feat|ft|no|vol|pt|jr|sr|inc|ltd|e\.g|i\.e|etc)\.$", re.I)


def sentences(text: str) -> List[str]:
    """The sentences of a message, in order. A title's full stop is not an end."""
    out: List[str] = []
    for piece in _SENTENCE_END.split(str(text or "").strip()):
        piece = piece.strip()
        if not piece:
            continue
        if out and _ABBREVIATION.search(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return [part for sentence in out for part in _at_the_turn(sentence)]


def _at_the_turn(sentence: str) -> List[str]:
    """A sentence about something that goes on to tell ELI what to do, as its two parts."""
    if instruction(sentence):
        return [sentence]
    for brk in _CLAUSE_END.finditer(sentence):
        rest = _LEAD.sub("", sentence[brk.end():], count=1)
        if _REQUEST.match(rest) or _COMMAND_START.match(rest):
            cut = brk.start() + (1 if sentence[brk.start()] in ",;" else 0)
            return [sentence[:cut].strip(), sentence[brk.end():].strip()]
    return [sentence]


def starts_with_command(text: str, *, after_lead: bool = False) -> bool:
    """Whether the text starts with a verb a command starts with (the one list). With
    `after_lead`, a greeting or courtesy in front of it is passed over first."""
    said = str(text or "")
    return bool(_COMMAND_START.match(_LEAD.sub("", said, count=1) if after_lead else said))


# The frames that ask ELI. "i want to ..." and "i need to ..." are in `_REQUEST` because a command
# may follow them ("i want to play some jazz"), but on their own they say what the user wants or
# has to do ("i need to study tonight"), not what ELI should.
_ASKS_ELI = re.compile(
    r"^(?:(?:can|could|would|will|won'?t) (?:you|u)\b|i(?:'d| would) (?:like|love) (?:you|for you) to\b"
    r"|i (?:want|need) you to\b|go ahead and\b|why (?:don'?t|not) (?:you|u)\b|how about (?:you|u)\b)", re.I)


def is_request(sentence: str) -> bool:
    """Whether the sentence asks ELI for something by its frame: "could you ...", "i'd like you to ..."."""
    return bool(_ASKS_ELI.match(_LEAD.sub("", str(sentence or "").strip(), count=1)))


def instruction(sentence: str) -> str:
    """What a sentence tells ELI to do, without what stands in front of it:
    "ok, could you open spotify please" -> "open spotify please". "" when the sentence is not
    telling ELI to do anything: it is about something ("you did not open spotify", "it stopped")
    or asks about it ("did you open spotify?", "why is nothing playing?")."""
    said = str(sentence or "").strip()
    rest = _LEAD.sub("", said, count=1)
    framed = _REQUEST.match(rest)
    if framed:
        rest = _LEAD.sub("", rest[framed.end():], count=1)
    elif _ABOUT.match(rest):
        return ""
    return rest.strip() or said


def read_message(text: str) -> List[dict]:
    """The message sentence by sentence: [{"said": the sentence, "tells": the instruction in it
    or ""}]. Which instructions are commands ELI has is the router's to say; this is only the
    form. A message of one sentence comes back as one entry."""
    return [{"said": s, "tells": instruction(s)} for s in sentences(text)]


__all__ = ["split_commands", "sentences", "instruction", "read_message", "starts_with_command", "is_request",
           "COMMAND_VERBS"]
