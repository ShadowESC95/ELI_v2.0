"""The human review gate had no way to be passed.

`lora_trainer_guard` requires every training row to be approved by a person and
scoped to the target. That was enforced but unreachable: `dataset_builder` writes
candidates tagged `needs_review`, and nothing in the product could retag one. Live
state before the review queue existed: 615 candidate rows, 0 trainable, so
`will_train` was False no matter what the operator did.

These tests pin the loop end to end — candidates in, approvals out, guard satisfied
— and pin the part that must NOT change: triage may reject on its own, never approve.
"""
import json

import pytest

from eli.learning.review_queue import (
    DECISION_APPROVED, DECISION_PENDING, DECISION_REJECTED, ReviewQueue,
    VERDICT_FLAG, VERDICT_OK, VERDICT_REJECT,
)


def _rows():
    return [
        {"instruction": "What did I say about the grant deadline?",
         "response": "You said the filing was due in December, and you sent it on the 3rd.",
         "tags": ["conversation_candidate", "needs_review"], "source": "sqlite:turns"},
        {"instruction": "hi", "response": "Hello.",
         "tags": ["needs_review"], "source": "sqlite:turns"},          # too short both ends
        {"instruction": "Summarise the reactor notes for me please",
         "response": "x", "tags": ["needs_review"], "source": "sqlite:turns"},  # bad response
        {"instruction": "What did I say about the grant deadline?",
         "response": "You said the filing was due in December, and you sent it on the 3rd.",
         "tags": ["needs_review"], "source": "sqlite:turns"},          # duplicate
        {"instruction": "Walk me through the pulse circuit again",
         "response": "The ZVS driver charges the primary, then " + "the flyback dumps it. " * 400,
         "tags": ["needs_review"], "source": "sqlite:turns"},          # very long -> flag
    ]


@pytest.fixture()
def queue(tmp_path):
    return ReviewQueue("t", _rows(), tmp_path / "t.trainable.jsonl")


def test_triage_rejects_the_unusable_and_keeps_the_rest(queue):
    verdicts = [x["verdict"] for x in queue.items]
    assert verdicts[0] == VERDICT_OK
    assert verdicts[1] == VERDICT_REJECT      # instruction under the floor
    assert verdicts[2] == VERDICT_REJECT      # bad response surface
    assert verdicts[3] == VERDICT_REJECT      # duplicate
    assert verdicts[4] == VERDICT_FLAG        # long, needs a human eye


def test_triage_never_approves_on_its_own(queue):
    """The whole point of the gate. Triage may pre-reject; approval is a person's act."""
    assert all(x["decision"] != DECISION_APPROVED for x in queue.items)
    assert queue.items[0]["decision"] == DECISION_PENDING
    assert queue.items[4]["decision"] == DECISION_PENDING  # flagged stays for the human


def test_approve_clean_leaves_flagged_rows_for_the_operator(queue):
    n = queue.approve_clean()
    assert n == 1
    assert queue.items[4]["decision"] == DECISION_PENDING
    assert queue.stats()["pending"] == 1


def test_saved_rows_satisfy_the_guard_contract(tmp_path):
    q = ReviewQueue("my_target", _rows(), tmp_path / "out.jsonl")
    q.approve_clean()
    report = q.save()
    assert report["written"] == 1

    from eli.learning.dataset_filters import row_is_reviewed
    saved = [json.loads(l) for l in (tmp_path / "out.jsonl").read_text().splitlines() if l.strip()]
    for row in saved:
        assert row_is_reviewed(row)                 # the gate the trainer checks
        assert row["target"] == "my_target"          # scoped to this target
        assert "my_target" in row["targets"]
        assert "needs_review" not in row["tags"]


def test_editing_re_triages_and_can_rescue_a_row(tmp_path):
    q = ReviewQueue("t", _rows(), tmp_path / "o.jsonl")
    assert q.items[2]["verdict"] == VERDICT_REJECT
    q.edit(2, response="The notes describe a two-stage Marx bank feeding the primary coil.")
    assert q.items[2]["verdict"] == VERDICT_OK
    assert q.items[2]["edited"] is True
    q.set_decision(2, DECISION_APPROVED)
    assert any("operator_edited" in r["tags"] for r in q.to_trainable_rows())


def test_editing_can_also_break_a_row_that_passed(tmp_path):
    q = ReviewQueue("t", _rows(), tmp_path / "o.jsonl")
    q.edit(0, response="x")
    assert q.items[0]["verdict"] == VERDICT_REJECT
    assert q.items[0]["decision"] == DECISION_REJECTED


def test_save_overwrites_rather_than_duplicating(tmp_path):
    out = tmp_path / "o.jsonl"
    q = ReviewQueue("t", _rows(), out)
    q.approve_clean()
    q.save()
    q.save()
    lines = [l for l in out.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


def test_decisions_survive_a_reload(tmp_path):
    out = tmp_path / "o.jsonl"
    q = ReviewQueue("t", _rows(), out)
    q.approve_clean()
    q.save()
    again = ReviewQueue("t", _rows(), out)
    again._restore_decisions()
    assert again.items[0]["decision"] == DECISION_APPROVED


def test_rejected_rows_never_reach_the_dataset(tmp_path):
    q = ReviewQueue("t", _rows(), tmp_path / "o.jsonl")
    q.set_decisions([0, 1, 2, 3, 4], DECISION_REJECTED)
    assert q.to_trainable_rows() == []
