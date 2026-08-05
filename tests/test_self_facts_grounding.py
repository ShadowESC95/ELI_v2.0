"""Locks for verified self-facts — the anti-confabulation grounding for
questions about ELI's own construction.

Asked "what fo you know of yourself?", ELI answered from CHAT with no factual
grounding and invented its own internals: databases under `/home/jason/...`
(the real user is `jay`; the name was confabulated from the user's first name),
`agent.sqlite` instead of `agent.sqlite3`, and a self-upgrade mechanism
`./upgrade.sh` that has never existed in this project.
"""
import re

import pytest

from eli.runtime import self_facts


# The trigger as wired into the persona handoff (engine.py). Kept in sync here
# so a phrasing regression is caught by a fast unit test, not a live session.
def _is_self_descriptive(text: str) -> bool:
    low = text.lower()
    return bool(
        (re.search(r"\byoursel(?:f|ves)\b", low)
         and re.search(r"\b(know|knew|tell|telling|describe|description|explain|"
                       r"detail|detailed|accurate|accurately|about|of)\b", low))
        or re.search(
            r"\b(what are you|who are you|describe yourself|"
            r"your (?:architecture|internals?|capabilit\w+|components?|design|"
            r"databases?|storage|memory system|codebase|upgrade path)|"
            r"how (?:do|are) you (?:built|structured|made|work)|"
            r"how do you (?:upgrade|update) yourself|what do you run on)\b",
            low)
    )


@pytest.mark.parametrize("question", [
    # The exact message that produced the fabricated paths, typos and all.
    "i' very impreed ! nd what fo you know of yourself? be as detailed and aurate as possibl please",
    "what do you know about yourself",
    "what do you know of yourself",
    "describe yourself",
    "what are you",
    "how do you upgrade yourself",
    "tell me about your architecture",
    "where are your databases",
])
def test_self_descriptive_questions_are_grounded(question):
    assert _is_self_descriptive(question), question


@pytest.mark.parametrize("question", [
    "what's the craic",
    "open downloads",
    "what do you know about me",
    "how are you feeling",
    "taking over the universe, the usual",
])
def test_ordinary_conversation_is_not_hijacked(question):
    assert not _is_self_descriptive(question), question


# ── the facts themselves must be real ───────────────────────────────────────

def test_block_states_the_real_database_paths():
    from eli.core.paths import user_db_path, agent_db_path
    block = self_facts.render_self_facts_block()
    assert str(user_db_path()) in block
    assert str(agent_db_path()) in block
    # The exact fabrications observed live.
    assert "/home/jason" not in block
    assert not re.search(r"agent\.sqlite\b(?!3)", block)


def test_block_names_the_real_upgrade_mechanism_and_denies_the_invented_one():
    block = self_facts.render_self_facts_block()
    assert "upgrade.sh" not in block.replace("There is no upgrade shell script.", "")
    assert "no upgrade shell script" in block


def test_version_is_not_read_from_stale_installed_metadata():
    """A months-old egg-info reported 2.1.29 while pyproject said 2.1.48."""
    import tomllib
    from pathlib import Path
    from eli.core.paths import project_root

    pyproject = tomllib.loads((Path(project_root()) / "pyproject.toml").read_text())
    assert self_facts.get_self_facts().get("version") == pyproject["project"]["version"]


def test_components_come_from_the_real_import_graph():
    facts = self_facts.get_self_facts()
    comps = facts.get("components") or []
    assert comps, "component list should come from codebase_graph, not be omitted"
    assert "router" in comps and "executor" in comps


def test_identity_canon_is_reachable_at_runtime():
    """The reviewed canon shipped in the repo but was training-only."""
    assert self_facts._canon_lines(), "self-model canon should now be readable at runtime"


def test_block_never_invents_when_sources_are_missing(monkeypatch):
    """Every source failing must yield an empty block, not a plausible one."""
    monkeypatch.setattr(self_facts, "_version", lambda: "")
    monkeypatch.setattr(self_facts, "_database_paths", lambda: [])
    monkeypatch.setattr(self_facts, "_capability_count", lambda: "")
    monkeypatch.setattr(self_facts, "_components", lambda: [])
    monkeypatch.setattr(self_facts, "_upgrade_mechanism", lambda: "")
    monkeypatch.setattr(self_facts, "_install_kind_safe", lambda: "", raising=False)

    import eli.kernel.self_upgrade as su
    monkeypatch.setattr(su, "_install_kind", lambda: (_ for _ in ()).throw(RuntimeError("no")))

    assert self_facts.render_self_facts_block() == ""


# ── fabricated-internals repair ─────────────────────────────────────────────

def test_repairs_the_exact_fabrication_seen_live():
    from eli.core.paths import user_db_path, agent_db_path
    bad = ("Persistent memory is stored in `/home/jason/.local/share/ELI_v2/artifacts/db/user.sqlite3` "
           "(user data) and `/home/jason/.local/share/ELI_v2/artifacts/db/agent.sqlite` (system state). "
           "Self-upgrades occur through scripts like `./upgrade.sh`.")
    out, fixes = self_facts.repair_self_description(bad)

    assert "/home/jason" not in out
    assert str(user_db_path()) in out and str(agent_db_path()) in out
    assert "upgrade.sh" not in out
    assert len(fixes) >= 3


def test_ordinary_replies_are_untouched_and_cheap():
    for text in ["I'm here. What's the craic?",
                 "Same old. What's your move?",
                 "I keep memory in SQLite and a vector index."]:
        out, fixes = self_facts.repair_self_description(text)
        assert out == text and fixes == []


def test_real_existing_paths_are_not_rewritten(tmp_path):
    real = tmp_path / "note.txt"
    real.write_text("x")
    text = f"I wrote that to {real}."
    out, fixes = self_facts.repair_self_description(text)
    assert str(real) in out


# ── profile hygiene ─────────────────────────────────────────────────────────

def test_single_valued_identity_supersedes_instead_of_accumulating(tmp_path):
    """The live DB held BOTH names, so the persona brief carried
    "User's name is jason; User's name is darren" into every single turn."""
    import sqlite3
    from eli.runtime.profile_extractor import ensure_profile_tables
    from eli.runtime.user_model import _read_patterns_grouped

    db = tmp_path / "user.sqlite3"
    ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    con.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) VALUES(?,?,?,?)",
                ("identity.name", "User's name is darren.", 1000.0, 1000.0))
    con.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) VALUES(?,?,?,?)",
                ("identity.name", "User's name is jason.", 2000.0, 2000.0))
    con.commit()
    con.close()

    identity = _read_patterns_grouped(db)["identity"]
    assert any("jason" in v.lower() for v in identity), identity
    assert not any("darren" in v.lower() for v in identity), (
        f"superseded name must not survive: {identity}")


def test_multi_valued_facts_still_accumulate(tmp_path):
    """Supersession is scoped to single-valued slots; interests must still stack."""
    import sqlite3
    from eli.runtime.profile_extractor import ensure_profile_tables
    from eli.runtime.user_model import _read_patterns_grouped

    db = tmp_path / "user.sqlite3"
    ensure_profile_tables(db)
    con = sqlite3.connect(str(db))
    for i, val in enumerate(("User is interested in physics.", "User is interested in hydrogen.")):
        con.execute("INSERT INTO user_patterns(pattern_type, pattern_data, timestamp, ts) VALUES(?,?,?,?)",
                    ("interest.topic", val, 1000.0 + i, 1000.0 + i))
    con.commit()
    con.close()

    assert len(_read_patterns_grouped(db)["interests"]) == 2


@pytest.mark.parametrize("value,rejected", [
    ("User prefers no, i said more than software and tech?! i prefer #4 answers by default.", True),
    ("User prefers detailed, thorough responses — willing to engage with depth and complexity.", False),
    ("User prefers executable terminal/Bash commands for repairs.", False),
    ("User's name is jason.", False),
    ("User's work/role: Software / tech", False),
    ("User wants ELI mainly for: Mix of everything.", False),
    ("User actively engages with dry humor and banter — wit and sarcasm are welcome.", False),
])
def test_raw_utterances_are_not_replayed_as_profile_facts(value, rejected):
    from eli.runtime.user_model import _looks_like_raw_utterance
    assert _looks_like_raw_utterance(value) is rejected, value
