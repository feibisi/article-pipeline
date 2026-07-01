import sqlite3
import os
import tempfile
import pytest
from article_pipeline.db import TaskDB


@pytest.fixture
def db():
    """Create a TaskDB with a temp database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tdb = TaskDB(db_path=path)
    yield tdb
    tdb.conn.close()
    os.unlink(path)


def test_init_creates_tables(db):
    """DB init creates tasks and review_log tables."""
    c = db.conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in c.fetchall()]
    assert "tasks" in tables
    assert "review_log" in tables


def test_add_task(db):
    """add_task inserts a row and returns its id."""
    tid = db.add_task("test keyword", "wp-tech", "wptea", 1)
    assert tid == 1

    task = db.get_task(tid)
    assert task["keyword"] == "test keyword"
    assert task["category"] == "wp-tech"
    assert task["platform"] == "wptea"
    assert task["priority"] == 1
    assert task["status"] == "queued"


def test_add_task_defaults(db):
    """add_task uses defaults for platform and priority."""
    tid = db.add_task("defaults", "book-knowledge")
    task = db.get_task(tid)
    assert task["platform"] == "wptea"
    assert task["priority"] == 2


def test_list_tasks(db):
    """list_tasks returns tasks ordered by priority, created."""
    db.add_task("low", "wp-tech", "wptea", 3)
    db.add_task("high", "wp-tech", "wptea", 1)
    db.add_task("mid", "book-knowledge", "wptea", 2)

    all_tasks = db.list_tasks()
    assert len(all_tasks) == 3
    assert all_tasks[0]["keyword"] == "high"
    assert all_tasks[1]["keyword"] == "mid"
    assert all_tasks[2]["keyword"] == "low"


def test_list_tasks_filter_by_status(db):
    """list_tasks filters by status."""
    db.add_task("a", "wp-tech", "wptea", 1)
    tid = db.add_task("b", "wp-tech", "wptea", 1)
    db.update_status(tid, "researching")

    queued = db.list_tasks(status="queued")
    assert len(queued) == 1
    assert queued[0]["keyword"] == "a"

    researching = db.list_tasks(status="researching")
    assert len(researching) == 1
    assert researching[0]["keyword"] == "b"


def test_list_tasks_filter_by_category(db):
    """list_tasks filters by category."""
    db.add_task("tech", "wp-tech", "wptea", 1)
    db.add_task("book", "book-knowledge", "wptea", 1)

    tech = db.list_tasks(category="wp-tech")
    assert len(tech) == 1
    assert tech[0]["keyword"] == "tech"


def test_update_status(db):
    """update_status changes status and stores metadata."""
    tid = db.add_task("test", "wp-tech", "wptea", 1)
    db.update_status(tid, "researching", {"note": "started"})

    task = db.get_task(tid)
    assert task["status"] == "researching"


def test_update_status_sets_timestamps(db):
    """update_status sets confirmed or published timestamps."""
    tid = db.add_task("test", "wp-tech", "wptea", 1)
    db.update_status(tid, "done")
    task = db.get_task(tid)
    assert task["published_at"] is not None


def test_get_next_batch(db):
    """get_next_batch returns queued tasks up to limit."""
    for i in range(5):
        db.add_task(f"task-{i}", "wp-tech", "wptea", 1)
    batch = db.get_next_batch(limit=3)
    assert len(batch) == 3

    # Verify they are now researching
    for t in batch:
        assert db.get_task(t["id"])["status"] == "researching"


def test_review_log(db):
    """add_review_entry writes to review_log table."""
    tid = db.add_task("test", "wp-tech", "wptea", 1)
    db.add_review_entry(tid, {"ai_score": 3, "facts_ok": True, "issues": []})

    c = db.conn.cursor()
    c.execute("SELECT * FROM review_log WHERE task_id=?", (tid,))
    row = c.fetchone()
    assert row is not None


def test_get_task_not_found(db):
    """get_task returns None for missing id."""
    assert db.get_task(999) is None


def test_save_stage_output(db):
    """save_stage_output saves content to the correct field."""
    tid = db.add_task("test", "wp-tech", "wptea", 1)
    db.save_stage_output(tid, "research_note", "some research")
    db.save_stage_output(tid, "title", "My Title")

    task = db.get_task(tid)
    assert task["research_note"] == "some research"
    assert task["title"] == "My Title"


def test_save_stage_output_invalid_field(db):
    """save_stage_output raises ValueError for invalid field names."""
    tid = db.add_task("test", "wp-tech", "wptea", 1)
    try:
        db.save_stage_output(tid, "nonexistent_field", "value")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
