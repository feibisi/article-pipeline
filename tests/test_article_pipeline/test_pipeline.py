"""Tests for pipeline orchestrator."""
import pytest
import tempfile
import os
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


def test_pipeline_process_research(pipeline):
    """Pipeline processes a task through research stage."""
    tid = pipeline.db.add_task("测试文章", "wp-tech", "wptea", 1)
    result = pipeline.process_research(tid)
    assert result is not None
    task = pipeline.db.get_task(tid)
    assert task["research_note"] is not None
    assert task["status"] == "synthesizing"


def test_pipeline_run_processes_batch(pipeline):
    """Pipeline run processes queued tasks through research."""
    for i in range(3):
        pipeline.db.add_task(f"task-{i}", "wp-tech", "wptea", 1)

    results = pipeline.run(limit=2)
    # research should complete for at least 1 task
    assert len(results) >= 1


def test_show_review_queue(pipeline):
    """show_review_queue lists tasks awaiting human review."""
    tid = pipeline.db.add_task("review-test", "wp-tech", "wptea", 1)
    pipeline.db.update_status(tid, "reviewing")
    content = "## 测试\n这是测试文章内容。" * 20
    pipeline.db.save_stage_output(tid, "article", content)
    # Should not throw
    pipeline.show_review_queue()
