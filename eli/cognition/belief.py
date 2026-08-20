"""Belief revision — what ELI holds, how strongly, and what it takes to change it.

The naive version of this is "the user said something different, so overwrite the
fact". That is what `_supersede_single_valued` does for its four hardcoded types,
and it is the mechanism that turns an assistant into a yes-man: it makes ASSERTION
equal to EVIDENCE, so whoever spoke last is right. An assistant built that way
cannot disagree with you, which means its agreement is worth nothing.

What this does instead: a belief carries WEIGHT, drawn from how it came to be
known and how often it has been borne out. A new claim is weighed against it. The
outcome is one of three, and only one of them is agreement:

    HOLD      the standing belief is much better supported. ELI keeps its
              position and says so, with the evidence it is standing on.
    QUESTION  the two are comparable. ELI raises the conflict rather than
              silently picking a side — this is the honest answer when the
              evidence genuinely does not settle it.
    CONCEDE   the new claim outweighs the old. ELI updates, and RECORDS why and
              when, so it can later say what it used to think and what changed
              its mind.

Pushing back is not a personality setting here. It falls out of the weights: ELI
disagrees when the evidence it holds is stronger, and concedes when it is not.
That is the difference between a colleague and a mirror.

Two properties worth stating because both are easy to get backwards:

  * **A bare assertion does not beat corroboration.** Saying a thing once does not
    outweigh five independent observations. It earns a QUESTION, not a CONCEDE.
  * **Conceding is not forgetting.** The superseded belief is kept with the reason
    and timestamp of the revision. "I used to think X, you corrected me in March"
    is a thing a colleague can say and a mirror cannot.

This module decides and explains. It does NOT phrase the reply — the verdict and
its evidence go to the persona layer so ELI says it in its own words. A canned
"I disagree because..." string would be the same yes-man problem wearing a
different hat.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eli.utils.log import get_logger

log = get_logger(__name__)

HOLD = "hold"
QUESTION = "question"
CONCEDE = "concede"

# How much a claim is worth by where it came from. The ordering is the point:
# something the user stated about themselves outright is strong evidence; ELI's
# own inference about the user is the weakest thing in the room and must never
# outrank the user on their own life.
PROVENANCE_WEIGHT: Dict[str, float] = {
    "user_explicit": 1.0,    # "I am a physicist" / "remember that I …"
    "user_passing": 0.65,    # mentioned in passing, not the point of the turn
    "document": 0.6,         # read out of a file the user pointed at
    "observed": 0.5,         # inferred from behaviour ELI actually saw
    "inferred": 0.35,        # ELI's own reasoning from other beliefs
    "unknown": 0.3,
}

# Corroboration saturates: the fifth independent observation adds far less than
# the second. Without this, anything repeated often enough becomes unfalsifiable —
# which is how ELI's own reflection telemetry came to dominate its recall.
CORROBORATION_HALF = 3.0

# Evidence ages. A fact from a year ago that has never come up since is weaker
# than the same fact from last week, but it does not vanish — it floors at 0.5 of
# its original weight, because "I was born in Dublin" does not expire.
EVIDENCE_HALF_LIFE_DAYS = 240.0
EVIDENCE_AGE_FLOOR = 0.5

# How much better the challenger must be before ELI changes its mind, and how
# close the two must be before it treats the matter as genuinely open.
# Reachable by design. With equal provenance and recency the largest ratio
# corroboration alone can produce against a well-established belief is about
# 1.3, so a margin of 1.35 was unreachable — ELI could never change its mind,
# which is the opposite failure to the yes-man and just as useless.
CONCEDE_MARGIN = 1.15
# Tuned against the ladder in the tests rather than picked. At 0.75 a single
# EXPLICIT correction from the user about their own life was scored HOLD, which
# is not a colleague standing its ground — it is someone who will not listen. The
# user is authoritative about themselves, so a direct correction must at least
# open the question; sustained correction then carries it.
QUESTION_BAND = 0.55


@dataclass
class Belief:
    """A thing ELI holds to be true, and the evidence behind it."""
    statement: str
    provenance: str = "unknown"
    corroboration: int = 1
    confidence: float = 0.8
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    superseded_by: Optional[str] = None
    revised_at: Optional[float] = None
    revision_reason: str = ""
    evidence: List[str] = field(default_factory=list)

    def weight(self, now: Optional[float] = None) -> float:
        """How much this belief counts, in 0..~1.

        Three independent factors, deliberately multiplicative rather than added:
        a belief with impeccable provenance but no corroboration and no recency
        should not score highly on provenance alone.
        """
        now = float(now or time.time())
        prov = PROVENANCE_WEIGHT.get(self.provenance, PROVENANCE_WEIGHT["unknown"])

        # Diminishing, but never fully saturating: 1 -> .25, 3 -> .50, 5 -> .63,
        # 9 -> .75. An earlier version doubled this and clamped at 1.0, which hit
        # the ceiling at three observations — so four corroborations and ninety
        # scored identically and sustained correction could never outweigh
        # anything. The ordering has to survive all the way up.
        n = max(0, int(self.corroboration))
        corr = n / (n + CORROBORATION_HALF) if n else 0.0

        age_days = max(0.0, (now - float(self.last_seen or now)) / 86400.0)
        recency = 2.0 ** (-age_days / EVIDENCE_HALF_LIFE_DAYS)
        recency = EVIDENCE_AGE_FLOOR + (1.0 - EVIDENCE_AGE_FLOOR) * recency

        conf = max(0.0, min(1.0, float(self.confidence)))
        return round(prov * (0.4 + 0.6 * corr) * recency * conf, 6)


@dataclass
class Verdict:
    """The decision, and everything needed to explain it in ELI's own words."""
    action: str
    standing: Optional[Belief]
    challenger: Belief
    standing_weight: float
    challenger_weight: float
    ratio: float
    reasons: List[str] = field(default_factory=list)

    @property
    def agrees(self) -> bool:
        return self.action == CONCEDE

    def as_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "standing": self.standing.statement if self.standing else None,
            "challenger": self.challenger.statement,
            "standing_weight": self.standing_weight,
            "challenger_weight": self.challenger_weight,
            "ratio": self.ratio,
            "reasons": list(self.reasons),
        }


def assess_claim(standing: Optional[Belief], challenger: Belief,
                 now: Optional[float] = None) -> Verdict:
    """Weigh a new claim against what ELI already holds.

    Returns the decision AND the reasoning, so the persona layer can voice it.
    Nothing here writes to the database — deciding and committing are separate so
    a caller can surface a QUESTION to the user before anything changes.
    """
    now = float(now or time.time())
    cw = challenger.weight(now)

    if standing is None:
        return Verdict(CONCEDE, None, challenger, 0.0, cw, float("inf"),
                       ["Nothing was held on this; adopting it."])

    sw = standing.weight(now)
    ratio = (cw / sw) if sw > 0 else float("inf")
    reasons: List[str] = []

    if standing.corroboration > challenger.corroboration:
        reasons.append(
            f"Held {standing.corroboration}x against {challenger.corroboration}x "
            f"for the new claim.")
    if (PROVENANCE_WEIGHT.get(challenger.provenance, 0)
            > PROVENANCE_WEIGHT.get(standing.provenance, 0)):
        reasons.append(
            f"The new claim is better sourced ({challenger.provenance} vs "
            f"{standing.provenance}).")
    elif (PROVENANCE_WEIGHT.get(challenger.provenance, 0)
          < PROVENANCE_WEIGHT.get(standing.provenance, 0)):
        reasons.append(
            f"The standing belief is better sourced ({standing.provenance} vs "
            f"{challenger.provenance}).")

    age = (now - float(standing.last_seen or now)) / 86400.0
    if age > 90:
        reasons.append(f"The standing belief has not come up in {age:.0f} days.")

    if ratio >= CONCEDE_MARGIN:
        action = CONCEDE
        reasons.append("The new evidence is clearly stronger; changing position.")
    elif ratio >= QUESTION_BAND:
        action = QUESTION
        reasons.append(
            "The two are close enough that the evidence does not settle it; "
            "worth asking rather than assuming.")
    else:
        action = HOLD
        reasons.append(
            "What is already held is better supported; keeping it unless there "
            "is more than an assertion.")

    return Verdict(action, standing, challenger, sw, cw, round(ratio, 4), reasons)


def corroborate(belief: Belief, provenance: str = "", now: Optional[float] = None) -> Belief:
    """Record that a held belief was borne out again.

    Repetition strengthens, but saturates — see CORROBORATION_HALF. Upgrading the
    provenance is allowed (a thing first inferred and later stated outright is
    better evidenced than it was); downgrading is not, or a passing mention could
    weaken something the user said outright.
    """
    now = float(now or time.time())
    belief.corroboration = max(1, int(belief.corroboration)) + 1
    belief.last_seen = now
    if provenance and (PROVENANCE_WEIGHT.get(provenance, 0)
                       > PROVENANCE_WEIGHT.get(belief.provenance, 0)):
        belief.provenance = provenance
    belief.confidence = min(1.0, float(belief.confidence) + 0.03)
    return belief


def concede(standing: Belief, challenger: Belief, reason: str = "",
            now: Optional[float] = None) -> Belief:
    """Change position, keeping a record of what was believed and why it changed.

    The old belief is NOT deleted. Being able to say "I thought X until you
    corrected me in March" is the difference between a colleague and a mirror,
    and it is also the only way a wrong revision can ever be spotted.
    """
    now = float(now or time.time())
    standing.superseded_by = challenger.statement
    standing.revised_at = now
    standing.revision_reason = reason or "Outweighed by better-supported evidence."
    return standing


__all__ = [
    "Belief", "Verdict", "assess_claim", "corroborate", "concede",
    "HOLD", "QUESTION", "CONCEDE", "PROVENANCE_WEIGHT",
    "CONCEDE_MARGIN", "QUESTION_BAND",
]
