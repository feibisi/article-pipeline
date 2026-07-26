"""Coverage for the Pipeline cascade stages that had none.

Before this file, 11 of Pipeline's 20 methods were never exercised by a test —
including every gate that is supposed to stop a bad article from advancing.
That is how a pipeline shipped with `TaskDB.save_meta` missing for three weeks:
nothing ever ran the compile stage.

All offline. Every LLM/network boundary is injected.
"""
import json
import os
import tempfile

import pytest

from article_pipeline.db import TaskDB
from article_pipeline.pipeline import Pipeline
from article_pipeline.framework import resolve_genre


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


def _task_with_research(db, keyword="Nginx 缓存命中率优化", category="tutorial"):
    tid = db.add_task(keyword, category, "wptea", 1)
    db.save_stage_output(tid, "research_note", "素材：命中率从 30% 升到 90%。")
    meta = json.loads(db.get_task(tid)["meta_json"] or "{}")
    meta["annotations"] = [{"claim": "先测量再优化", "book": "某书"}]
    db.update_status(tid, "synthesizing", meta)
    return tid


def _synthesis(db, tid, **over):
    payload = {
        "core_judgment": "默认的缓存配置会让命中率接近零",
        "evidence_for": [{"source": "实测", "claim": "命中率 90%", "strength": 0.9}],
        "evidence_against": [],
        "conflicts": [],
        "unique_claims": ["本站实测命中率数据"],
        "differentiation": "包含本站实测数据，公开搜索结果里没有这一条",
        "confidence": 0.8,
        "freeform_note": "",
    }
    payload.update(over)
    db.save_stage_output(tid, "synthesis", json.dumps(payload, ensure_ascii=False))
    return payload


# ── __init__ ──

def test_pipeline_accepts_an_injected_db(db):
    p = Pipeline(db=db)
    assert p.db is db


# ── process_synthesis: the confidence / no-judgment gate ──

def test_synthesis_without_a_core_judgment_is_skipped(pipe, db, monkeypatch):
    """A cascade whose root produced no judgment has nothing to write about.
    It must stop, not proceed with an empty judgment object."""
    class _Empty:
        core_judgment = ""
        evidence_for = []
        evidence_against = []
        conflicts = []
        unique_claims = []
        differentiation = ""
        confidence = 0.0
        freeform_note = ""

    tid = _task_with_research(db)
    monkeypatch.setattr("article_pipeline.pipeline.run_synthesis",
                        lambda *a, **k: _Empty())
    assert pipe.process_synthesis(tid) is None
    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert "synthesis_no_judgment" in (task["skip_reason"] or "")


def test_synthesis_persists_all_contract_fields(pipe, db, monkeypatch):
    class _Full:
        core_judgment = "默认配置让命中率接近零"
        evidence_for = [{"source": "实测", "claim": "90%"}]
        evidence_against = [{"source": "文档", "claim": "反例"}]
        conflicts = ["两处说法不一致"]
        unique_claims = ["本站实测"]
        differentiation = "有本站实测数据，别处没有这一条"
        confidence = 0.7
        freeform_note = "补充说明"

    tid = _task_with_research(db)
    monkeypatch.setattr("article_pipeline.pipeline.run_synthesis",
                        lambda *a, **k: _Full())
    assert pipe.process_synthesis(tid) is not None

    stored = json.loads(db.get_task(tid)["synthesis"])
    for field in ("core_judgment", "evidence_for", "evidence_against",
                  "conflicts", "unique_claims", "differentiation",
                  "confidence", "freeform_note"):
        assert field in stored, f"{field} dropped on the way to the DB"
    assert stored["evidence_against"], "counter-evidence must survive"
    assert stored["conflicts"], "conflicts must survive"


def test_synthesis_receives_the_keyword(pipe, db, monkeypatch):
    """run_synthesis always accepted a keyword but the pipeline never passed
    one, so the root of the cascade summarised material without knowing what
    the article was about."""
    seen = {}

    class _S:
        core_judgment = "有判断"
        evidence_for = []
        evidence_against = []
        conflicts = []
        unique_claims = []
        differentiation = ""
        confidence = 0.5
        freeform_note = ""

    def fake(sources, keyword="", **k):
        seen["keyword"] = keyword
        return _S()

    tid = _task_with_research(db, keyword="Nginx 缓存命中率优化")
    monkeypatch.setattr("article_pipeline.pipeline.run_synthesis", fake)
    pipe.process_synthesis(tid)
    assert seen.get("keyword") == "Nginx 缓存命中率优化"


# ── genre mapping: the hyphen/underscore hazard ──

@pytest.mark.parametrize("category,genre_dir", [
    ("case-study", "case-study"),
    ("tool-review", "tool-review"),
    ("tutorial", "tutorial"),
    ("opinion", "opinion"),
])
def test_mapped_category_always_resolves_to_a_real_genre_dir(pipe, category, genre_dir):
    """_map_category_to_genre emits underscore forms (case_study) while the
    genres/ directories use hyphens (case-study). Unresolved, that raised
    ValueError and took the whole prosody stage down while framework silently
    degraded to generic_structure. resolve_genre() is the guard; assert the
    two halves actually agree."""
    mapped = pipe._map_category_to_genre(category)
    assert resolve_genre(mapped) == genre_dir


def test_unknown_category_falls_back_instead_of_raising(pipe):
    mapped = pipe._map_category_to_genre("完全没听过的品类")
    assert resolve_genre(mapped)  # must not raise


# ── process_framework / process_prosody ──

def test_framework_stage_stores_output_and_advances(pipe, db):
    tid = _task_with_research(db)
    _synthesis(db, tid)
    db.update_status(tid, "framework")

    assert pipe.process_framework(tid) is not None
    task = db.get_task(tid)
    assert task["framework"], "framework output not persisted"
    assert task["status"] != "framework", "stage did not advance"


def test_prosody_stage_stores_output_and_advances(pipe, db):
    tid = _task_with_research(db)
    _synthesis(db, tid)
    db.update_status(tid, "framework")
    pipe.process_framework(tid)
    db.update_status(tid, "prosody")

    assert pipe.process_prosody(tid) is not None
    task = db.get_task(tid)
    assert task["prosody"], "prosody output not persisted"


def test_prosody_survives_a_hyphenated_category(pipe, db):
    """Regression: category=case-study used to crash the prosody stage."""
    tid = _task_with_research(db, category="case-study")
    _synthesis(db, tid)
    db.update_status(tid, "framework")
    pipe.process_framework(tid)
    db.update_status(tid, "prosody")
    assert pipe.process_prosody(tid) is not None


# ── process_outline ──

def _outline_payload():
    return {
        "title": "Nginx 缓存命中率：先测量，再调参",
        "claim": {"statement": "默认配置让命中率接近零",
                  "why_matters": "站长以为开了缓存就有效"},
        "hook": "开了缓存，TTFB 没变",
        "audience": "自建站的中文站长",
        "differentiation": "包含本站实测命中率数据，公开搜索结果没有这一条",
        "sections": [{"h2": "先测出真实命中率"}, {"h2": "为什么默认配置无效"}],
    }


def test_outline_stage_persists_and_advances(pipe, db, monkeypatch):
    tid = _task_with_research(db)
    _synthesis(db, tid)
    db.update_status(tid, "framework")
    pipe.process_framework(tid)
    db.update_status(tid, "prosody")
    pipe.process_prosody(tid)
    db.update_status(tid, "outlining")

    monkeypatch.setattr("article_pipeline.outline.generate_outline_from_layers",
                        lambda *a, **k: {"outline": _outline_payload()})
    assert pipe.process_outline(tid) is not None
    assert db.get_task(tid)["outline"], "outline not persisted"


def test_outline_failure_is_recorded_not_swallowed(pipe, db, monkeypatch):
    tid = _task_with_research(db)
    _synthesis(db, tid)
    db.update_status(tid, "outlining")
    monkeypatch.setattr("article_pipeline.outline.generate_outline_from_layers",
                        lambda *a, **k: {"error": "all_providers_failed"})

    pipe.process_outline(tid)
    task = db.get_task(tid)
    # Either queued for retry or skipped with a reason — never silently stuck
    # in `outlining` with no explanation.
    assert task["status"] != "outlining"
    meta = json.loads(task["meta_json"] or "{}")
    assert task["skip_reason"] or meta.get("outline_retries") is not None


# ── approve_outline: the human gate ──

def test_approve_outline_requires_the_outline_review_state(pipe, db, capsys):
    tid = _task_with_research(db)
    db.update_status(tid, "reviewing")
    pipe.approve_outline(tid)
    assert db.get_task(tid)["status"] == "reviewing", "gate bypassed"
    assert "outline review" in capsys.readouterr().out


def test_approve_outline_on_missing_task_is_graceful(pipe, capsys):
    pipe.approve_outline(999999)
    assert "not found" in capsys.readouterr().out.lower()


def test_approve_outline_advances_a_held_task(pipe, db):
    tid = _task_with_research(db)
    db.save_stage_output(tid, "outline", json.dumps(_outline_payload(),
                                                    ensure_ascii=False))
    db.update_status(tid, "outline_review")
    pipe.approve_outline(tid)
    assert db.get_task(tid)["status"] != "outline_review"


# ── process_writing ──

def test_writing_failure_retries_then_gives_up(pipe, db, monkeypatch):
    tid = _task_with_research(db)
    _synthesis(db, tid)
    db.save_stage_output(tid, "outline", json.dumps(_outline_payload(),
                                                    ensure_ascii=False))
    monkeypatch.setattr("article_pipeline.pipeline.write_article",
                        lambda *a, **k: {"error": "client_error",
                                         "message": "HTTP 401"})
    for _ in range(4):
        db.update_status(tid, "writing")
        pipe.process_writing(tid)

    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert "writing_failed" in (task["skip_reason"] or "")


def test_writing_success_stores_article_and_moves_to_reviewing(pipe, db, monkeypatch):
    tid = _task_with_research(db)
    _synthesis(db, tid)
    db.save_stage_output(tid, "outline", json.dumps(_outline_payload(),
                                                    ensure_ascii=False))
    db.update_status(tid, "writing")
    body = "## 先测出真实命中率\n\n正文段落。\n\n" * 5
    monkeypatch.setattr("article_pipeline.pipeline.write_article",
                        lambda *a, **k: {"article": body, "model": "test-model",
                                         "tokens": {"input_tokens": 10,
                                                    "output_tokens": 20}})
    assert pipe.process_writing(tid) is not None
    task = db.get_task(tid)
    assert task["article"]
    assert task["status"] == "reviewing"


def test_writing_records_token_cost(pipe, db, monkeypatch):
    tid = _task_with_research(db)
    _synthesis(db, tid)
    db.save_stage_output(tid, "outline", json.dumps(_outline_payload(),
                                                    ensure_ascii=False))
    db.update_status(tid, "writing")
    monkeypatch.setattr("article_pipeline.pipeline.write_article",
                        lambda *a, **k: {"article": "## H\n\n正文。\n\n" * 5,
                                         "model": "m",
                                         "tokens": {"input_tokens": 111,
                                                    "output_tokens": 222}})
    pipe.process_writing(tid)
    meta = json.loads(db.get_task(tid)["meta_json"] or "{}")
    entries = meta.get("cost_log", [])
    assert entries and entries[-1]["input_tokens"] == 111


# ── _record_stage_failure ──

def test_record_stage_failure_leaves_a_durable_trail(pipe, db):
    tid = _task_with_research(db)
    pipe._record_stage_failure(tid, "synthesis", RuntimeError("boom"))

    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert "boom" in (task["skip_reason"] or "")
    meta = json.loads(task["meta_json"] or "{}")
    assert meta.get("error_log") or meta.get("last_error"), (
        "a failure with no record is how "
        "'昨晚挂在哪' became unanswerable")


def test_record_stage_failure_accepts_a_plain_string(pipe, db):
    tid = _task_with_research(db)
    pipe._record_stage_failure(tid, "outline", "all_providers_failed")
    assert db.get_task(tid)["status"] == "skipped"


# ── _gate_verdict ──

def test_gate_verdict_is_none_without_review_history(pipe, db):
    tid = _task_with_research(db)
    assert pipe._gate_verdict(tid) is None


def test_gate_verdict_returns_the_latest_entry(pipe, db):
    tid = _task_with_research(db)
    db.add_review_entry(tid, {"publish_gate": {"decision": "fail"}}, passed=False)
    db.add_review_entry(tid, {"publish_gate": {"decision": "pass"}}, passed=True)
    assert pipe._gate_verdict(tid)["decision"] == "pass"


def test_gate_verdict_skips_entries_without_a_gate(pipe, db):
    tid = _task_with_research(db)
    db.add_review_entry(tid, {"publish_gate": {"decision": "fail"}}, passed=False)
    db.add_review_entry(tid, {"overall_score": 7.0}, passed=True)
    assert pipe._gate_verdict(tid)["decision"] == "fail"


# ── unpublish ──

def test_unpublish_returns_a_done_task_to_reviewing(pipe, db):
    tid = _task_with_research(db)
    db.save_stage_output(tid, "article", "正文" * 100)
    db.update_status(tid, "done", {"published_url": "https://wptea.com/x/"})
    pipe.unpublish(tid)
    assert db.get_task(tid)["status"] == "reviewing"


def test_unpublish_on_missing_task_is_graceful(pipe, capsys):
    pipe.unpublish(999999)
    assert "not found" in capsys.readouterr().out.lower()


# ── NULL stage columns must not crash the cascade ──

@pytest.mark.parametrize("stage,status", [
    ("process_outline", "outlining"),
    ("process_writing", "writing"),
    ("process_compile", "compiling"),
])
def test_stage_tolerates_null_prior_stage_columns(pipe, db, monkeypatch, stage, status):
    """`task.get("framework", "{}")` only defaults when the *key* is absent.
    The column always exists and is NULL until its stage runs, so json.loads
    received None and raised TypeError — which run()'s bare except turned into
    a silent `skipped` with no usable reason. A task that reaches a stage
    without its prerequisites must fail with a recorded reason instead.
    """
    tid = db.add_task(f"null column {stage}", "tutorial", "wptea", 1)
    db.save_stage_output(tid, "research_note", "素材")
    db.update_status(tid, status)

    monkeypatch.setattr("article_pipeline.outline.generate_outline_from_layers",
                        lambda *a, **k: {"error": "all_providers_failed"})
    monkeypatch.setattr("article_pipeline.pipeline.write_article",
                        lambda *a, **k: {"error": "no_material"})

    # A missing prerequisite must surface as either a clean return or a named
    # ContractViolation — never as TypeError/AttributeError, which the bare
    # except in run() would flatten into an unexplained `skipped`.
    from article_pipeline.contracts import ContractViolation
    try:
        getattr(pipe, stage)(tid)
    except ContractViolation:
        pass  # named, actionable, and recorded by _drive()
    except (TypeError, AttributeError) as e:
        pytest.fail(f"{stage} crashed on NULL prior stage: {type(e).__name__}: {e}")
    assert db.get_task(tid) is not None
