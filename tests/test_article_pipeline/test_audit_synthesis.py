"""Regressions for the fixes applied while synthesising the 2026-07-25 audit.

All offline: no network, no LLM, no publishing.
"""
import json
import os
import tempfile

import pytest

from article_pipeline.db import TaskDB, TERMINAL_STATES
from article_pipeline.pipeline import Pipeline
from article_pipeline.writer import _extract_samples
from article_pipeline.review import compute_overall_score
from article_pipeline.review.value_density import assess_value_density


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tdb = TaskDB(db_path=path)
    yield tdb
    tdb.conn.close()
    os.unlink(path)


@pytest.fixture
def pipe(db):
    return Pipeline(db=db)


# ── writing samples must survive the corpus' actual quality grades ──

def test_extract_samples_accepts_ai_draft_grade():
    """Every annotation in the live corpus is graded AI_draft, so the note
    renders "[AI_draft级|...]". The old [AB]-only regex matched nothing, which
    silently kept annotation samples out of the writing prompt entirely."""
    note = (
        "### 写作范本（人类编辑的真实文字，模仿这种写法和语感）\n"
        "1. [AI_draft级|principle] 写作应专注于有用而非好看。\n"
        "2. [B级|technique] 先给结果，再讲过程。\n"
    )
    samples = _extract_samples(note)
    assert len(samples) == 2, f"expected both grades to parse, got {samples}"
    assert samples[0]["quality"] == "AI_draft"
    assert samples[0]["type"] == "principle"
    assert samples[1]["quality"] == "B"


# ── the quality gate must actually block publishing ──

def _review_with_gate(db, task_id, decision):
    db.add_review_entry(task_id, {
        "overall_pass": decision == "pass",
        "publish_gate": {"decision": decision,
                         "blocking_reasons": ["密度不足"] if decision == "fail" else []},
    }, passed=decision == "pass")


def test_publish_blocked_when_gate_failed(pipe, db, monkeypatch):
    tid = db.add_task("gate blocks publish", "tutorial", "wptea", 1)
    db.save_stage_output(tid, "article", "正文" * 200)
    db.update_status(tid, "reviewing")
    _review_with_gate(db, tid, "fail")

    called = []
    monkeypatch.setattr("article_pipeline.pipeline.publish_to_wp",
                        lambda *a, **k: called.append(a) or {"published": True})
    pipe.publish(tid)
    assert not called, "publish_to_wp ran despite a failing quality gate"
    assert db.get_task(tid)["status"] == "reviewing"


def test_publish_force_overrides_failed_gate(pipe, db, monkeypatch):
    tid = db.add_task("force override", "tutorial", "wptea", 1)
    db.save_stage_output(tid, "article", "正文" * 200)
    db.update_status(tid, "reviewing")
    _review_with_gate(db, tid, "fail")

    monkeypatch.setattr("article_pipeline.pipeline.publish_to_wp",
                        lambda *a, **k: {"published": True,
                                         "url": "https://wptea.com/x/"})
    pipe.publish(tid, force=True)
    task = db.get_task(tid)
    assert task["status"] == "done"
    assert task["published_url"] == "https://wptea.com/x/"


def test_publish_proceeds_when_gate_passed(pipe, db, monkeypatch):
    tid = db.add_task("gate passes", "tutorial", "wptea", 1)
    db.save_stage_output(tid, "article", "正文" * 200)
    db.update_status(tid, "reviewing")
    _review_with_gate(db, tid, "pass")

    monkeypatch.setattr("article_pipeline.pipeline.publish_to_wp",
                        lambda *a, **k: {"published": True,
                                         "url": "https://wptea.com/y/"})
    pipe.publish(tid)
    assert db.get_task(tid)["status"] == "done"


def test_publish_without_any_review_is_not_blocked(pipe, db, monkeypatch):
    """No review history means no verdict — don't invent a failing one."""
    tid = db.add_task("never reviewed", "tutorial", "wptea", 1)
    db.save_stage_output(tid, "article", "正文" * 200)
    db.update_status(tid, "reviewing")

    monkeypatch.setattr("article_pipeline.pipeline.publish_to_wp",
                        lambda *a, **k: {"published": True,
                                         "url": "https://wptea.com/z/"})
    pipe.publish(tid)
    assert db.get_task(tid)["status"] == "done"


# ── refuse to write with no evidence ──

def test_research_blocks_when_every_channel_empty(pipe, db, monkeypatch):
    tid = db.add_task("no material at all", "tutorial", "wptea", 1)
    monkeypatch.setattr("article_pipeline.pipeline.gather_research",
                        lambda *a, **k: {})
    monkeypatch.setattr("article_pipeline.pipeline.build_research_note",
                        lambda *a, **k: "（无素材）")

    assert pipe.process_research(tid) is None
    task = db.get_task(tid)
    assert task["status"] == "needs_material"
    assert "needs_material" in TERMINAL_STATES
    meta = json.loads(task["meta_json"] or "{}")
    assert meta["retrieval_health"] == {
        "annotations": 0, "web": 0, "web_articles": 0,
        "topic_paragraphs": 0, "cocobook": 0,
    }


def test_research_proceeds_with_partial_material(pipe, db, monkeypatch):
    tid = db.add_task("some material", "tutorial", "wptea", 1)
    monkeypatch.setattr("article_pipeline.pipeline.gather_research",
                        lambda *a, **k: {"web": [{"title": "t", "snippet": "s"}]})
    monkeypatch.setattr("article_pipeline.pipeline.build_research_note",
                        lambda *a, **k: "素材若干")

    assert pipe.process_research(tid) is not None
    assert db.get_task(tid)["status"] == "synthesizing"


def test_research_preserves_existing_meta(pipe, db, monkeypatch):
    """Sources are merged into meta_json; the blob used to be overwritten
    wholesale, discarding trust_tier and retry counters."""
    tid = db.add_task("keep meta", "tutorial", "wptea", 1)
    db.update_status(tid, "queued", {"trust_tier": "TIER_EXTERNAL",
                                     "writing_retries": 1})
    monkeypatch.setattr("article_pipeline.pipeline.gather_research",
                        lambda *a, **k: {"annotations": [{"claim": "c"}]})
    monkeypatch.setattr("article_pipeline.pipeline.build_research_note",
                        lambda *a, **k: "素材")

    pipe.process_research(tid)
    meta = json.loads(db.get_task(tid)["meta_json"] or "{}")
    assert meta["trust_tier"] == "TIER_EXTERNAL"
    assert meta["writing_retries"] == 1
    assert meta["annotations"] == [{"claim": "c"}]


# ── proven-noise indicators must stay out of the weighted score ──

def test_style_compliance_does_not_move_overall_score():
    base = {
        "ai_check": {"score": 9.0}, "dbs_ai": {"score": 9.0},
        "format": {"pass": True}, "fabrication": {"score": 9.0},
        "cross_reference": None, "semantic_facts": {"pass": True},
        "word_count": {"pass": True}, "humanizer": {"total": 46},
        "jargon": {"pass": True}, "value_density": {"overall_score": 6.0},
    }
    low = compute_overall_score({**base, "style_compliance": {"overall_score": 1.0}})
    high = compute_overall_score({**base, "style_compliance": {"overall_score": 10.0}})
    assert low == high, "style_compliance (0.12 separation) must not be scored"


def test_counter_intuitive_does_not_subtract_from_density():
    """It scored 0.0 on all 48 measured texts; a flat penalty on everyone was
    a large part of why human articles scored below machine ones."""
    article = (
        "## 配置步骤\n\n"
        "先运行 `nginx -t` 校验配置。\n\n"
        "```bash\nsudo systemctl reload nginx\n```\n\n"
        "推荐使用 proxy_cache_path 指定缓存目录，参考 https://nginx.org/en/docs/ 。\n\n"
        "关键在于先测量再优化，命中率低于 50% 时才值得调整。\n\n"
    ) * 3
    result = assess_value_density(article, {}, [])
    dims = result["details"]
    assert dims["counter_intuitive"] == 0.0, "expected the dead detector to be 0"
    # A text with strong verifiable/judgment signal must still be able to clear
    # the 6.0 publish threshold despite counter_intuitive being a flat zero.
    # Under the old 0.15 weighting that zero capped it at 8.5 and dragged
    # mid-scoring articles under the bar for everyone equally.
    assert result["overall_score"] >= 6.0, result["reason"]
    contributing = ["unique_info_ratio", "verifiable_operations",
                    "source_depth", "judgment_density"]
    assert result["overall_score"] <= max(dims[d] for d in contributing) + 0.01
