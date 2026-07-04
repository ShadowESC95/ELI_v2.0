"""Extract relational facts the user mentions in passing.

ELI captured the user's OWN name ("my name is Sam") but nothing about the people and pets
in their life — so "what's my dog's name?" had *nothing stored to recall*, even though the
user had said "Shadow (my dog)" in an earlier chat. This closes that gap: it pulls facts
like "my dog Shadow", "Shadow (my dog)", "my wife is Jane" so they can be stored + recalled.

Deterministic + conservative: names must be Capitalised (proper nouns), questions are
ignored (they're recalls, not statements), and only a known set of relations is matched.
"""
from __future__ import annotations

import re
from typing import Dict, List

# Relations worth remembering. Matched as the word right after "my ".
_RELATIONS = [
    "dog", "cat", "pet", "puppy", "kitten", "bird", "fish", "hamster", "rabbit", "horse",
    "wife", "husband", "partner", "spouse", "girlfriend", "boyfriend", "fiance", "fiancee",
    "son", "daughter", "kid", "child", "baby", "twin",
    "mother", "mom", "mum", "mam", "father", "dad", "brother", "sister", "sibling",
    "grandmother", "grandfather", "grandma", "grandpa", "granny", "aunt", "uncle", "cousin",
    "nephew", "niece",
    "friend", "roommate", "flatmate", "housemate",
    "boss", "manager", "colleague", "coworker", "neighbour", "neighbor", "landlord",
]
_REL_ALT = "|".join(re.escape(r) for r in sorted(_RELATIONS, key=len, reverse=True))
# First letter must be a real capital even though the pattern runs case-insensitively
# (re.I would otherwise let [A-Z] match "is"/"happy"). (?-i:…) turns off i-flag for that char.
_NAME = r"(?P<name>(?-i:[A-Z])[A-Za-z'À-ſ\-]{1,30})"

# "my dog Shadow" · "my dog is Shadow" · "my dog's name is Shadow" · "my dog, Shadow"
_P_MY_REL_NAME = re.compile(
    rf"\bmy\s+(?P<rel>{_REL_ALT})(?:'s)?\s*"
    rf"(?:name\s+is|is\s+called|is\s+named|is|named|called|,|:|-)?\s*{_NAME}\b",
    re.I,
)
# "Shadow (my dog)" · "Shadow, my dog"
_P_NAME_MY_REL = re.compile(
    rf"\b{_NAME}\s*(?:\(\s*|,\s*)my\s+(?P<rel>{_REL_ALT})\b",
    re.I,
)

# Words that look like a name slot but aren't (avoids "my dog is The …" etc.).
_STOP_NAMES = {
    "The", "A", "An", "Is", "Named", "Called", "And", "Who", "That", "He", "She", "It",
    "They", "My", "Name", "Great", "Good", "Best", "Very", "So", "Just", "Really",
}
_REL_CANON = {
    "mom": "mother", "mum": "mother", "mam": "mother", "dad": "father",
    "puppy": "dog", "kitten": "cat", "grandma": "grandmother", "granny": "grandmother",
    "grandpa": "grandfather", "coworker": "colleague", "neighbor": "neighbour",
    "flatmate": "roommate", "housemate": "roommate", "fiancee": "fiance",
}


def _canon_rel(r: str) -> str:
    r = r.lower().strip()
    return _REL_CANON.get(r, r)


def extract_relational_facts(text: str) -> List[Dict[str, str]]:
    """Return [{'relation': 'dog', 'name': 'Shadow'}, …] for facts stated in `text`.

    Only *statements* — a question ("what is my dog's name?") returns nothing, since that's
    a recall, not a new fact. Last mention wins per relation within one message.
    """
    s = str(text or "").strip()
    if not s:
        return []
    # Skip pure questions/recalls unless they also assert ("my dog is X but what breed?").
    if "?" in s and not re.search(r"\bmy\s+\w+\s+(?:is|'s\s+name\s+is)\b", s, re.I):
        return []

    found: Dict[str, str] = {}
    for rx in (_P_MY_REL_NAME, _P_NAME_MY_REL):
        for m in rx.finditer(s):
            name = (m.group("name") or "").strip("'-")
            rel = _canon_rel(m.group("rel"))
            if not name or name in _STOP_NAMES or name.lower() in {r.lower() for r in _RELATIONS}:
                continue
            found[rel] = name  # last mention wins
    return [{"relation": r, "name": n} for r, n in found.items()]
