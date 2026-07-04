"""Relational-fact extraction (regression, 2026-07-04).

ELI captured the user's OWN name but nothing about the people/pets they mention, so
"what's my dog's name?" had nothing to recall even after the user had said "Shadow (my
dog)". This locks in the extractor that closes that gap — it must catch the real forms and
NOT fire on questions, adjectives, breeds, or bare mentions.
"""
import pytest

from eli.runtime.relational_facts import extract_relational_facts as f


def _pairs(text):
    return sorted((x["relation"], x["name"]) for x in f(text))


@pytest.mark.parametrize("text, expected", [
    # The exact bug: a casual appositive mention.
    ("haha, i am going to explain darwinsim to Shadow (my dog), next", [("dog", "Shadow")]),
    ("my dog is Shadow", [("dog", "Shadow")]),
    ("my dog Shadow loves treats", [("dog", "Shadow")]),
    ("my dog's name is Shadow", [("dog", "Shadow")]),
    ("Shadow, my dog, is asleep", [("dog", "Shadow")]),
    ("my cat is called Luna", [("cat", "Luna")]),
    ("my wife is Jane and my son is Tom", [("son", "Tom"), ("wife", "Jane")]),
])
def test_extracts_real_relations(text, expected):
    assert _pairs(text) == sorted(expected), text


@pytest.mark.parametrize("text", [
    "what is my dog's name?",       # a question / recall, not a statement
    "my dog is happy today",        # lowercase adjective is not a name
    "my dog is a Labrador",         # a breed after an article is not a name
    "i have a dog",                 # no name given
    "the dog ran across the road",  # no possessive relation
    "",
])
def test_ignores_non_facts(text):
    assert f(text) == [], text


def test_canonicalises_relation_synonyms():
    # mum/mom -> mother, puppy -> dog, etc.
    assert _pairs("my mum is Mary") == [("mother", "Mary")]
    assert _pairs("my puppy is Rex") == [("dog", "Rex")]


def test_last_mention_wins_per_relation():
    assert _pairs("my dog is Rex... actually my dog is Shadow") == [("dog", "Shadow")]
