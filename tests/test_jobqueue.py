"""The durable job queue: submit, run with a worker, capture output, survive a crash."""
import sys

import pytest

from eli.planning import jobqueue as jq
from eli.planning import jobqueue_cli as cli


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(jq, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jq, "DB_PATH", tmp_path / "jobs" / "jobs.sqlite")


def test_a_queued_job_runs_and_its_output_is_kept():
    jid = jq.submit([sys.executable, "-c", "print('hello from a job')"])
    assert jq.get_job(jid)["status"] == "queued"
    jq.run_worker(once=True)
    job = jq.get_job(jid)
    assert job["status"] == "done" and job["meta"]["returncode"] == 0
    assert "hello from a job" in open(job["stdout_path"]).read()


def test_a_failing_job_is_marked_failed_with_its_stderr():
    jid = jq.submit([sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"])
    jq.run_worker(once=True)
    job = jq.get_job(jid)
    assert job["status"] == "failed" and job["meta"]["returncode"] == 3
    assert "boom" in open(job["stderr_path"]).read()


def test_a_job_over_its_timeout_fails():
    jid = jq.submit([sys.executable, "-c", "import time; time.sleep(30)"], timeout_s=1)
    jq.run_worker(once=True)
    assert jq.get_job(jid)["status"] == "failed"


def test_jobs_run_in_submission_order():
    ids = [jq.submit([sys.executable, "-c", f"print({n})"]) for n in range(3)]
    jq.run_worker(once=True)
    assert [jq.get_job(i)["status"] for i in ids] == ["done"] * 3


def test_a_job_left_running_by_a_dead_worker_is_recovered_as_failed():
    jid = jq.submit([sys.executable, "-c", "pass"])
    conn = jq._db()
    conn.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
    conn.commit(); conn.close()
    assert jq.recover_interrupted() == 1
    job = jq.get_job(jid)
    assert job["status"] == "failed" and "worker stopped" in job["meta"]["error"]


def test_the_cli_submits_runs_and_reports(capsys):
    assert cli.main(["submit", "--cmd", f"{sys.executable} -c \"print(7)\""]) == 0
    jid = int(capsys.readouterr().out.strip())
    assert cli.main(["worker", "--once"]) == 0
    assert cli.main(["get", "--id", str(jid)]) == 0
    assert '"status": "done"' in capsys.readouterr().out
    assert cli.main(["get", "--id", "999"]) == 1
