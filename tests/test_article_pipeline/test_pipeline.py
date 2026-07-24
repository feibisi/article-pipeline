"""Tests for pipeline orchestrator.

These previously called the real ``gather_research``, which does live DDG /
MCP / SSH I/O. Consequences: ``pytest tests`` hung indefinitely (the suite could
not be run at all in CI or offline), and the assertions were tautological anyway
— ``result is not None`` is guaranteed because ``process_research`` always
returns a dict, and ``research_note is not None`` because it always writes a
string, even an empty-result one.

Research is now injected, so the tests are deterministic and assert the thing
that actually matters: that the orchestrator persists what the stage produced
and advances the status. The live-network variants are kept behind
``-m network``.
"""
import os
import tempfile

import pytest

from article_pipeline.db import TaskDB
from article_pipeline.pipeline import Pipeline


@pytest.fixture
def pipeline():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = TaskDB(db_path=path)
    p = Pipeline(db=db)
    yield p
    db.conn.close()
    os.unlink(path)


@pytest.fixture
def offline_research(monkeypatch):
    """Stub out all network research. Returns the note the stub will produce."""
    import article_pipeline.pipeline as P

    note = "## 素材\n- nginx.org: proxy_cache_valid 用于指定缓存时长\n"

    # gather_research -> dict of sources; build_research_note -> str.
    # pipeline.py:232-233 calls them in that order.
    monkeypatch.setattr(P, "gather_research", lambda *a, **kw: {
        "cocobook": [], "annotations": [],
        "web": [{"title": "nginx docs", "url": "https://nginx.org"}],
        "web_articles": [], "topic_paragraphs": [], "code": [], "vm_consult": [],
    })
    monkeypatch.setattr(P, "build_research_note", lambda *a, **kw: note)
    return note


def test_process_research_persists_note_and_advances_status(pipeline, offline_research):
    tid = pipeline.db.add_task("测试文章", "wp-tech", "wptea", 1)
    result = pipeline.process_research(tid)

    assert result["task_id"] == tid
    assert result["stage"] == "research"
    task = pipeline.db.get_task(tid)
    # The note must be non-empty, not merely non-None.
    assert task["research_note"], "research stage persisted an empty note"
    assert task["status"] == "synthesizing", (
        f"status must advance past research, got {task['status']}"
    )


def test_process_research_on_missing_task_does_not_corrupt_db(pipeline, offline_research):
    """A bogus id must not create a phantom row or crash the orchestrator."""
    before = len(pipeline.db.list_tasks())
    try:
        pipeline.process_research(999999)
    except Exception:
        pass  # raising is acceptable; silently inventing a task is not
    assert len(pipeline.db.list_tasks()) == before


def test_run_respects_limit_and_advances_only_that_many(pipeline, offline_research):
    for i in range(3):
        pipeline.db.add_task(f"task-{i}", "wp-tech", "wptea", 1)

    results = pipeline.run(limit=2)

    assert len(results) <= 2, f"run(limit=2) processed {len(results)} tasks"
    assert len(results) >= 1
    # The tasks that were processed must have actually moved out of 'queued'.
    still_queued = [t for t in pipeline.db.list_tasks(status="queued")]
    assert len(still_queued) == 3 - len(results), (
        "run() reported progress it did not persist"
    )


def test_show_review_queue_lists_the_task(pipeline, capsys):
    tid = pipeline.db.add_task("review-test", "wp-tech", "wptea", 1)
    pipeline.db.update_status(tid, "reviewing")
    pipeline.db.save_stage_output(tid, "article", "## 测试\n这是测试文章内容。" * 20)

    pipeline.show_review_queue()

    # "should not throw" is not a test. Assert the task is actually shown.
    out = capsys.readouterr().out
    assert "review-test" in out or str(tid) in out, (
        f"review queue did not list the pending task: {out[:300]}"
    )


@pytest.mark.network
def test_process_research_against_live_sources(pipeline):
    """Live smoke test. Opt in with `pytest -m network`."""
    tid = pipeline.db.add_task("WordPress 缓存", "wp-tech", "wptea", 1)
    pipeline.process_research(tid)
    assert pipeline.db.get_task(tid)["research_note"]
