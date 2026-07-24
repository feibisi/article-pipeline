"""Orchestration/data-layer audit regressions (2026-07-25).

Covers the编排层 defects found while auditing state machine, recovery,
scheduling, config and CLI. Everything here is offline — no network, no LLM.
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from article_pipeline.db import (
    TaskDB, ACTIVE_STATES, HUMAN_GATE_STATES, TERMINAL_STATES,
    MAX_RECOVERY_ATTEMPTS, normalize_keyword,
)
from article_pipeline.pipeline import Pipeline

REPO = Path(__file__).resolve().parents[2]


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


def _backdate(db: TaskDB, task_id: int, minutes: int):
    """Push a task's status_changed_at into the past."""
    past = (datetime.now(timezone.utc) - timedelta(minutes=minutes)
            ).strftime("%Y-%m-%d %H:%M:%S")
    meta = json.loads(db.get_task(task_id)["meta_json"] or "{}")
    meta["status_changed_at"] = past
    db.conn.execute("UPDATE tasks SET meta_json=? WHERE id=?",
                    (json.dumps(meta), task_id))
    db.conn.commit()


# ───────────────────────── save_meta: the fatal gap ─────────────────────────

def test_save_meta_exists(db):
    """TaskDB.save_meta was called by pipeline/screenshot but never defined.

    Every cascade run died at the compile stage with AttributeError.
    """
    assert hasattr(TaskDB, "save_meta")
    tid = db.add_task("k1", "tutorial", "wptea", 2)
    db.save_meta(tid, {"a": 1})
    db.save_meta(tid, {"b": 2})
    meta = json.loads(db.get_task(tid)["meta_json"])
    assert meta["a"] == 1 and meta["b"] == 2
    # must not clobber the transition timestamp written by update_status
    db.update_status(tid, "researching")
    db.save_meta(tid, {"c": 3})
    meta = json.loads(db.get_task(tid)["meta_json"])
    assert "status_changed_at" in meta and meta["c"] == 3


def test_save_meta_unknown_task(db):
    with pytest.raises(ValueError):
        db.save_meta(99999, {"x": 1})


def test_process_compile_completes_offline(pipe):
    """Regression: compile stage must reach 'outlining', not explode."""
    db = pipe.db
    tid = db.add_task("测试选题-compile", "tutorial", "wptea", 2)
    db.save_stage_output(tid, "synthesis", json.dumps({
        "core_judgment": "缓存不是万灵药", "evidence_for": [],
        "evidence_against": [], "conflicts": [], "unique_claims": [],
        "differentiation": "给出失效场景", "confidence": 0.7,
        "freeform_note": ""}, ensure_ascii=False))
    db.save_stage_output(tid, "framework", json.dumps({
        "method": "steel_man", "structure": [
            {"role": "opening", "h2_title": "开头", "purpose": "p",
             "word_budget": 300}],
        "takeaway": "t", "reader_entry_state": "a", "reader_exit_state": "b",
        "visual_anchors": None, "freeform_note": ""}, ensure_ascii=False))
    db.save_stage_output(tid, "prosody", json.dumps({
        "samples": ["范本"], "sample_type": "flowing",
        "negative_constraints": "", "rhythm_hint": "",
        "freeform_note": ""}, ensure_ascii=False))
    db.update_status(tid, "compiling")

    result = pipe.process_compile(tid)

    assert result is not None
    task = db.get_task(tid)
    assert task["status"] == "outlining"
    assert task["compiled_prompt"]
    assert "compile_metadata" in json.loads(task["meta_json"])


# ───────────────────────── _drive: state machine ─────────────────────────

def test_drive_respects_outline_review_gate(pipe, monkeypatch):
    """TIER_EXTERNAL human gate must stop the run.

    The old nested if-chain in run() was mis-indented, so a task parked at
    outline_review was handed straight to process_writing anyway.
    """
    db = pipe.db
    tid = db.add_task("外部选题", "tutorial", "wptea", 2)
    db.update_status(tid, "outline_review")

    called = []
    monkeypatch.setattr(pipe, "process_writing",
                        lambda t: called.append(t) or {"stage": "writing"})

    pipe._drive(tid)

    assert called == []
    assert db.get_task(tid)["status"] == "outline_review"


def test_drive_records_stage_on_failure(pipe, monkeypatch):
    db = pipe.db
    tid = db.add_task("失败选题", "tutorial", "wptea", 2)
    db.update_status(tid, "prosody")

    def boom(_):
        raise RuntimeError("prosody blew up")
    monkeypatch.setattr(pipe, "process_prosody", boom)

    pipe._drive(tid)

    task = db.get_task(tid)
    assert task["status"] == "skipped"
    # skip_reason must land in the real column, not only in the blob
    assert "prosody" in (task["skip_reason"] or "")
    meta = json.loads(task["meta_json"])
    assert meta["failed_stage"] == "prosody"
    assert meta["last_error"]["stage"] == "prosody"
    assert "prosody blew up" in meta["last_error"]["error"]
    assert meta["error_log"] and "traceback" in meta["error_log"][-1]


def test_drive_does_not_spin_when_stage_forgets_to_advance(pipe, monkeypatch):
    """A stage returning success without changing status used to be possible.

    With the old chain it could not happen; with a status-driven driver it
    would be an infinite loop, so the driver must detect it.
    """
    db = pipe.db
    tid = db.add_task("不前进", "tutorial", "wptea", 2)
    db.update_status(tid, "framework")
    monkeypatch.setattr(pipe, "process_framework",
                        lambda t: {"task_id": t, "stage": "framework"})

    results = pipe._drive(tid)

    assert len(results) == 1
    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert "framework" in (task["skip_reason"] or "")


def test_drive_walks_full_cascade(pipe, monkeypatch):
    """Happy path: queued -> ... -> reviewing, stopping at the human gate."""
    db = pipe.db
    tid = db.add_task("完整级联", "tutorial", "wptea", 2)

    order = []

    def make(stage, next_status):
        def fn(t):
            order.append(stage)
            db.update_status(t, next_status)
            return {"task_id": t, "stage": stage}
        return fn

    monkeypatch.setattr(pipe, "process_research", make("research", "synthesizing"))
    monkeypatch.setattr(pipe, "process_synthesis", make("synthesis", "framework"))
    monkeypatch.setattr(pipe, "process_framework", make("framework", "prosody"))
    monkeypatch.setattr(pipe, "process_prosody", make("prosody", "compiling"))
    monkeypatch.setattr(pipe, "process_compile", make("compile", "outlining"))
    monkeypatch.setattr(pipe, "process_outline", make("outline", "writing"))
    monkeypatch.setattr(pipe, "process_writing", make("writing", "reviewing"))
    monkeypatch.setattr(pipe, "process_review", lambda t: {"overall_pass": True})

    results = pipe.run(limit=1)

    assert order == ["research", "synthesis", "framework", "prosody",
                     "compile", "outline", "writing"]
    assert db.get_task(tid)["status"] == "reviewing"
    assert any(r.get("stage") == "review" for r in results)


def test_drive_review_runs_once(pipe, monkeypatch):
    """Self-review must not loop while status stays 'reviewing'."""
    db = pipe.db
    tid = db.add_task("只审一次", "tutorial", "wptea", 2)
    db.update_status(tid, "reviewing")
    calls = []
    monkeypatch.setattr(pipe, "process_review",
                        lambda t: calls.append(t) or {"overall_pass": False})
    pipe._drive(tid)
    assert len(calls) == 1


def test_drive_unknown_status_is_reported(pipe):
    db = pipe.db
    tid = db.add_task("怪状态", "tutorial", "wptea", 2)
    db.update_status(tid, "teleporting")
    pipe._drive(tid)
    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert "unknown status" in json.loads(task["meta_json"])["last_error"]["error"]


def test_every_active_state_has_an_owner():
    """No automated state may be orphaned — that is how tasks wedge."""
    for state in ACTIVE_STATES:
        assert state in Pipeline.STAGE_METHODS, state
    for state in Pipeline.STAGE_METHODS:
        assert state in ACTIVE_STATES, state
    assert not set(ACTIVE_STATES) & set(TERMINAL_STATES)
    assert not set(ACTIVE_STATES) & set(HUMAN_GATE_STATES)


# ───────────────────────── resume: no dead ends ─────────────────────────

@pytest.mark.parametrize("state", list(ACTIVE_STATES))
def test_resume_handles_every_active_state(pipe, monkeypatch, state):
    """Previously synthesizing/framework/prosody/compiling printed
    "not resumable" and the task could only be freed with raw SQL."""
    db = pipe.db
    tid = db.add_task(f"resume-{state}", "tutorial", "wptea", 2)
    db.update_status(tid, state)

    hit = []
    for st, meth in Pipeline.STAGE_METHODS.items():
        monkeypatch.setattr(pipe, meth,
                            (lambda s: lambda t: (hit.append(s), None)[1])(st))

    pipe.resume(tid)
    assert hit == [state], f"resume({state}) dispatched {hit}"


def test_resume_refuses_terminal_and_gates(pipe, monkeypatch):
    db = pipe.db
    monkeypatch.setattr(pipe, "process_writing",
                        lambda t: pytest.fail("must not run"))
    for state in ("done", "skipped", "outline_review", "reviewing"):
        tid = db.add_task(f"gate-{state}", "tutorial", "wptea", 2,
                          allow_duplicate=True)
        db.update_status(tid, state)
        assert pipe.resume(tid) == []
        assert db.get_task(tid)["status"] == state


# ───────────────────────── stuck detection / recovery ─────────────────────

@pytest.mark.parametrize("state", list(ACTIVE_STATES))
def test_stuck_detection_covers_whole_cascade(db, state):
    """Old active_states listed only 4 of 7 stages: a task frozen in
    synthesizing/framework/prosody/compiling was invisible forever."""
    tid = db.add_task(f"stuck-{state}", "tutorial", "wptea", 2)
    db.update_status(tid, state)
    _backdate(db, tid, 120)
    ids = [t["id"] for t in db.get_stuck_tasks(max_minutes=30)]
    assert tid in ids


def test_stuck_detection_skips_human_gates_by_default(db):
    """Auto-rewinding outline_review destroys work awaiting approval."""
    tid = db.add_task("等人审", "tutorial", "wptea", 2)
    db.update_status(tid, "outline_review")
    _backdate(db, tid, 5000)
    assert tid not in [t["id"] for t in db.get_stuck_tasks(max_minutes=30)]
    assert tid in [t["id"] for t in db.get_stuck_tasks(
        max_minutes=30, include_human_gates=True)]


def test_stuck_detection_fresh_task_not_stuck(db):
    tid = db.add_task("刚开始", "tutorial", "wptea", 2)
    db.update_status(tid, "writing")
    assert db.get_stuck_tasks(max_minutes=30) == []


def test_stuck_detection_handles_unparseable_timestamp(db):
    """A garbage timestamp used to make the task silently invisible."""
    tid = db.add_task("坏时间戳", "tutorial", "wptea", 2)
    db.update_status(tid, "writing")
    db.conn.execute("UPDATE tasks SET meta_json=? WHERE id=?",
                    (json.dumps({"status_changed_at": "not-a-date"}), tid))
    db.conn.commit()
    assert tid in [t["id"] for t in db.get_stuck_tasks(max_minutes=30)]


def test_recover_requeues_so_run_can_pick_it_up(db):
    """The old recover rolled back to 'researching'/'outlining', which
    get_next_batch never selects — "recovered" tasks stayed dead."""
    tid = db.add_task("恢复我", "tutorial", "wptea", 2)
    db.update_status(tid, "compiling")
    _backdate(db, tid, 120)

    report = db.recover_stuck(max_minutes=30)

    assert [r["rolled_back_to"] for r in report] == ["queued"]
    assert db.get_task(tid)["status"] == "queued"
    assert tid in [t["id"] for t in db.peek_next_batch(limit=5)]
    meta = json.loads(db.get_task(tid)["meta_json"])
    assert meta["recovered_from"] == "compiling"
    assert meta["recovery_attempts"] == 1


def test_recover_preserves_stage_outputs(db):
    tid = db.add_task("保留产物", "tutorial", "wptea", 2)
    db.save_stage_output(tid, "research_note", "note")
    db.save_stage_output(tid, "synthesis", "{}")
    db.update_status(tid, "writing")
    _backdate(db, tid, 120)
    db.recover_stuck(max_minutes=30)
    task = db.get_task(tid)
    assert task["research_note"] == "note" and task["synthesis"] == "{}"


def test_recover_gives_up_after_max_attempts(db):
    """Otherwise a permanently broken task burns API budget every cycle."""
    tid = db.add_task("死循环", "tutorial", "wptea", 2)
    for _ in range(MAX_RECOVERY_ATTEMPTS):
        db.update_status(tid, "researching")
        _backdate(db, tid, 120)
        db.recover_stuck(max_minutes=30)
        assert db.get_task(tid)["status"] == "queued"

    db.update_status(tid, "researching")
    _backdate(db, tid, 120)
    report = db.recover_stuck(max_minutes=30)

    assert report[0]["rolled_back_to"] == "skipped"
    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert "recovery_exhausted" in task["skip_reason"]


def test_record_failure_keeps_bounded_history(db):
    tid = db.add_task("错误历史", "tutorial", "wptea", 2)
    for i in range(25):
        db.record_failure(tid, "writing", f"err {i}")
    meta = json.loads(db.get_task(tid)["meta_json"])
    assert len(meta["error_log"]) == 20
    assert meta["last_error"]["error"] == "err 24"


# ───────────────────────── claiming / idempotency ─────────────────────────

def test_peek_does_not_claim_but_get_next_batch_does(db):
    """`--dry-run` used to call get_next_batch(), i.e. the preview claimed
    the tasks it was only supposed to show."""
    tid = db.add_task("预览", "tutorial", "wptea", 2)
    assert [t["id"] for t in db.peek_next_batch(limit=5)] == [tid]
    assert db.get_task(tid)["status"] == "queued"

    db.get_next_batch(limit=5)
    assert db.get_task(tid)["status"] == "researching"
    # already claimed: a second call must not hand it out again
    assert db.get_next_batch(limit=5) == []


def test_batch_filters(db):
    a = db.add_task("A 教程", "tutorial", "wptea", 1)
    b = db.add_task("B 指南", "guide", "wptea", 3)
    assert [t["id"] for t in db.peek_next_batch(limit=5, category="guide")] == [b]
    assert [t["id"] for t in db.peek_next_batch(limit=5, max_priority=1)] == [a]


def test_run_claims_exactly_once(pipe, monkeypatch):
    """scripts/pipeline-run.sh used to claim a batch itself and then call
    pipeline.run(task_id) — task_id landed in `limit`, claiming a second
    batch, and the first batch was never driven."""
    db = pipe.db
    ids = [db.add_task(f"批次-{i}", "tutorial", "wptea", 2) for i in range(3)]
    driven = []
    monkeypatch.setattr(pipe, "_drive", lambda t, **kw: driven.append(t) or [])
    pipe.run(limit=2)
    assert driven == ids[:2]
    assert db.get_task(ids[2])["status"] == "queued"


# ───────────────────────── topic dedup ─────────────────────────

@pytest.mark.parametrize("variant", [
    "systemd timer 基础",
    "  systemd   timer 基础 ",
    "Systemd Timer 基础",
    "systemd timer：基础",
])
def test_dedup_catches_normalized_variants(db, variant):
    """#98/#99 were twins from the same keyword and both burned a full
    write+review cycle."""
    first = db.add_task("systemd timer 基础", "tutorial", "wptea", 2)
    dup = db.find_duplicate(variant)
    assert dup and dup["id"] == first
    assert db.add_task(variant, "tutorial", "wptea", 2) == first
    assert db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1


def test_dedup_ignores_skipped_topics(db):
    first = db.add_task("Docker 容器网络隔离", "tutorial", "wptea", 2)
    db.update_status(first, "skipped", {"skip_reason": "test"})
    assert db.find_duplicate("Docker 容器网络隔离") is None
    assert db.find_duplicate("Docker 容器网络隔离",
                             include_terminal=True)["id"] == first
    second = db.add_task("Docker 容器网络隔离", "tutorial", "wptea", 2)
    assert second != first


def test_pipeline_add_task_rejects_duplicate_without_network(pipe):
    """Dedup must run before the topic filter (which does web searches)."""
    db = pipe.db
    first = db.add_task("Nginx 缓存配置入门", "tutorial", "wptea", 2)

    def explode(*a, **kw):
        raise AssertionError("topic filter must not run for a duplicate")
    import article_pipeline.topic_filter as tf
    original, tf.filter_topic = tf.filter_topic, explode
    try:
        assert pipe.add_task("Nginx  缓存配置入门", category="tutorial") is None
    finally:
        tf.filter_topic = original
    assert db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert db.get_task(first)["status"] == "queued"


def test_known_categories_match_shipped_genres():
    """An unknown category silently degrades to the tutorial genre, so the
    CLI must reject typos instead of accepting them."""
    from article_pipeline.pipeline import known_categories
    cats = known_categories()
    assert "tutorial" in cats and "wp-tech" in cats
    assert len(cats) >= 20
    assert not any(c.startswith("_") for c in cats)


# ───────────────────────── layer contracts ─────────────────────────

def test_contract_rejects_missing_core_judgment():
    """The cascade used to rebuild contracts with .get(field, "") defaults, so
    an empty synthesis column produced a valid object with nothing in it."""
    from article_pipeline.contracts import SynthesisOutput, ContractViolation
    with pytest.raises(ContractViolation) as e:
        SynthesisOutput.from_dict({})
    assert "core_judgment" in str(e.value)
    with pytest.raises(ContractViolation):
        SynthesisOutput.from_dict({"core_judgment": ""})


def test_contract_round_trips_through_db_json(db):
    from article_pipeline.contracts import SynthesisOutput
    payload = {"core_judgment": "判断", "evidence_for": [{"claim": "c"}],
               "evidence_against": [], "conflicts": [], "unique_claims": ["u"],
               "differentiation": "d", "confidence": 0.8, "freeform_note": ""}
    tid = db.add_task("契约", "tutorial", "wptea", 2)
    db.save_stage_output(tid, "synthesis", json.dumps(payload, ensure_ascii=False))
    loaded = SynthesisOutput.from_dict(
        json.loads(db.get_task(tid)["synthesis"]))
    assert loaded.core_judgment == "判断"
    assert loaded.confidence == 0.8
    assert loaded.validate() == []


def test_contract_reports_wrong_types_and_extra_fields():
    from article_pipeline.contracts import FrameworkOutput, ProsodyOutput
    bad = FrameworkOutput.from_dict(
        {"method": "m", "structure": [{}], "takeaway": "t",
         "evidence_ids": "oops"}, strict=False)
    assert bad.method == "m"
    obj = ProsodyOutput.from_dict({"sample_type": "flowing",
                                   "samples": "not-a-list"}, strict=False)
    assert any("should be a list" in p for p in obj.validate())


def test_framework_stage_fails_loudly_on_empty_synthesis(pipe):
    """Regression: garbage in must not silently become an article."""
    db = pipe.db
    tid = db.add_task("空 synthesis", "tutorial", "wptea", 2)
    db.save_stage_output(tid, "synthesis", "{}")
    db.update_status(tid, "framework")
    pipe._drive(tid)
    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert "core_judgment" in json.loads(task["meta_json"])["last_error"]["error"]


def test_normalize_keyword():
    assert normalize_keyword("  WordPress：入门  ") == "wordpress 入门"
    assert normalize_keyword("") == ""
    assert normalize_keyword("A-B_C") == "a b c"


# ───────────────────────── config ─────────────────────────

def test_load_config_warns_on_broken_yaml(tmp_path, monkeypatch, capsys):
    """A malformed config used to be swallowed, silently falling back to
    hardcoded endpoints."""
    import article_pipeline.config as cfg
    bad = tmp_path / "config.yaml"
    bad.write_text("deepseek: [unclosed\n")
    monkeypatch.setattr(cfg, "_CONFIG_PATH", str(bad))
    monkeypatch.setattr(cfg, "_warned", False)
    assert cfg.load_config() == {}
    assert "WARNING" in capsys.readouterr().err


def test_load_config_missing_file_is_quiet(tmp_path, monkeypatch, capsys):
    import article_pipeline.config as cfg
    monkeypatch.setattr(cfg, "_CONFIG_PATH", str(tmp_path / "nope.yaml"))
    assert cfg.load_config() == {}
    assert capsys.readouterr().err == ""


def test_validate_config_flags_dead_keys_and_bad_urls(tmp_path, monkeypatch):
    import article_pipeline.config as cfg
    p = tmp_path / "config.yaml"
    p.write_text(
        "pipeline:\n  db_path: /tmp/x.db\n"
        "mcp:\n  base_url: 192.168.0.1:8087\n"
        "bogus_section:\n  a: 1\n"
    )
    monkeypatch.setattr(cfg, "_CONFIG_PATH", str(p))
    monkeypatch.delenv("AP_DS_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    problems = cfg.validate_config()
    msgs = [m for _, m in problems]

    assert any("pipeline.db_path" in m and "ignored" in m for m in msgs)
    assert any("bogus_section" in m for m in msgs)
    assert any("mcp.base_url" in m and "http" in m for m in msgs)
    assert any("AP_DS_API_KEY" in m for m in msgs)
    # never leak secret values, only names
    assert not any("=" in m and "API_KEY" in m.split("=")[-1] for m in msgs)


def test_validate_config_accepts_a_clean_config(tmp_path, monkeypatch):
    import article_pipeline.config as cfg
    p = tmp_path / "config.yaml"
    p.write_text("mcp:\n  base_url: http://example:8087\n")
    monkeypatch.setattr(cfg, "_CONFIG_PATH", str(p))
    monkeypatch.setenv("AP_DS_API_KEY", "x")
    errors = [m for lvl, m in cfg.validate_config() if lvl == "error"]
    assert errors == []


# ───────────────────────── scheduler ─────────────────────────

def test_scheduler_platforms_must_exist_in_the_queue(db):
    """_DEFAULT_RHYTHMS targets wpcommunity/meta while `add` defaults to
    wptea, so coverage was measured against platforms that never get tasks
    and the shortage alert fired forever."""
    from article_pipeline.scheduler import (
        check_queue_coverage, PublishRhythm, DEFAULT_RHYTHMS)
    for i in range(3):
        db.add_task(f"选题-{i}", "tutorial", "wptea", 2)
    st = check_queue_coverage("wptea", 2, db)
    assert st.shortage == 0
    st = check_queue_coverage("wpcommunity", 2, db)
    assert st.shortage == 2, "platform with no tasks always looks short"
    assert {r.platform for r in DEFAULT_RHYTHMS}, "rhythms must be configured"


def test_scheduler_does_not_count_in_flight_as_supply(db):
    """queued + researching was counted as 'available', overstating supply."""
    from article_pipeline.scheduler import check_queue_coverage
    tid = db.add_task("在途选题", "tutorial", "wptea", 2)
    db.update_status(tid, "researching")
    st = check_queue_coverage("wptea", 1, db)
    assert st.researching_count == 1
    assert st.total_available == 0
    assert st.shortage == 1


def test_schedule_check_reports_without_sending(db, monkeypatch):
    from article_pipeline import scheduler
    monkeypatch.setattr(scheduler, "send_nats_alert",
                        lambda *a, **kw: pytest.fail("must not notify"))
    alerts = scheduler.run_schedule_check(db, auto_notify=False)
    assert all(a.shortage > 0 for a in alerts)


# ───────────────────────── CLI / docs consistency ─────────────────────────

def _cli_commands():
    import argparse
    import article_pipeline.pipeline as plmod
    seen = []
    real_init = argparse.ArgumentParser.add_subparsers

    class Rec:
        def __init__(self, inner):
            self.inner = inner

        def add_parser(self, name, **kw):
            seen.append(name)
            seen.extend(kw.get("aliases", []))
            return self.inner.add_parser(name, **kw)

    def patched(self, *a, **kw):
        return Rec(real_init(self, *a, **kw))

    argparse.ArgumentParser.add_subparsers = patched
    try:
        old = sys.argv
        sys.argv = ["ap"]
        try:
            plmod.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old
    finally:
        argparse.ArgumentParser.add_subparsers = real_init
    return seen


def test_cli_exposes_documented_commands():
    """README documented continue/recover/skip/status, none of which existed
    in the installed entry point (article_pipeline.pipeline:main)."""
    cmds = _cli_commands()
    for expected in ("add", "run", "resume", "continue", "status", "recover",
                     "skip", "publish", "review-queue", "list",
                     "approve-outline", "schedule-check", "doctor"):
        assert expected in cmds, f"missing subcommand: {expected}"


def test_readme_does_not_advertise_missing_commands():
    """README promised `article-pipeline review-server`, which no CLI has."""
    readme = (REPO / "README.md").read_text()
    cli_block = readme.split("## CLI", 1)[1].split("```")[1]
    documented = {ln.split()[1] for ln in cli_block.splitlines()
                  if ln.strip().startswith(("article-pipeline", "ap "))
                  and len(ln.split()) > 1}
    available = set(_cli_commands())
    assert documented <= available, f"documented but absent: {documented - available}"


# ───────────────────── shell scripts: static regressions ─────────────────

def test_pipeline_run_script_does_not_double_claim():
    src = (REPO / "scripts" / "pipeline-run.sh").read_text()
    body = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "get_next_batch" not in body, "run script must let run() claim"
    assert "pipeline.run(task_id)" not in body
    assert "pipeline.run(" in body


def test_pipeline_run_dry_run_is_read_only():
    src = (REPO / "scripts" / "pipeline-run.sh").read_text()
    assert "peek_next_batch" in src


def test_scripts_do_not_interpolate_shell_vars_into_python():
    """keyword='$KEYWORD' breaks on quotes and is a code-injection path."""
    for name in ("pipeline-add.sh", "pipeline-run.sh"):
        src = (REPO / "scripts" / name).read_text()
        assert "'$KEYWORD'" not in src
        assert "$BATCH_SIZE)" not in src


def test_cleanup_script_is_dry_run_by_default(db):
    """Zombie cleanup must never touch data without an explicit --execute."""
    tid = db.add_task("测试选题", "tutorial", "test", 2)
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "pipeline-cleanup.py"),
         "--db", db.db_path],
        capture_output=True, text=True, cwd=str(REPO), timeout=120)
    assert out.returncode == 0, out.stderr
    assert "dry-run" in out.stdout
    assert f"#{tid}" in out.stdout
    assert db.get_task(tid)["status"] == "queued", "dry-run must not mutate"


def test_cleanup_script_refuses_execute_without_yes(db):
    db.add_task("测试选题", "tutorial", "test", 2)
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "pipeline-cleanup.py"),
         "--db", db.db_path, "--execute"],
        capture_output=True, text=True, cwd=str(REPO), timeout=120)
    assert out.returncode == 2
    assert "拒绝执行" in out.stdout


def test_cleanup_never_deletes_rows(db):
    """Even with --execute --yes: status change only."""
    tid = db.add_task("测试选题", "tutorial", "test", 2)
    before = db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "pipeline-cleanup.py"),
         "--db", db.db_path, "--execute", "--yes"],
        capture_output=True, text=True, cwd=str(REPO), timeout=120)
    assert out.returncode == 0, out.stderr
    assert db.conn.execute(
        "SELECT COUNT(*) FROM tasks").fetchone()[0] == before
    task = db.get_task(tid)
    assert task["status"] == "skipped"
    assert task["skip_reason"].startswith("cleanup:")
    assert json.loads(task["meta_json"])["cleaned_from"] == "queued"


def test_cleanup_never_touches_published(db):
    tid = db.add_task("测试选题", "tutorial", "test", 2)
    db.update_status(tid, "done", {"published_url": "http://x/y"})
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "pipeline-cleanup.py"),
         "--db", db.db_path, "--execute", "--yes"],
        capture_output=True, text=True, cwd=str(REPO), timeout=120)
    assert db.get_task(tid)["status"] == "done"


# ───────────────────── systemd unit sanity (not enabled) ─────────────────

def test_systemd_unit_has_no_retry_storm():
    """Type=oneshot + Restart=on-failure + a 4x/day timer retries forever
    every RestartSec. The unit stays disabled either way — see the report."""
    unit = Path.home() / ".config/systemd/user/article-pipeline.service"
    if not unit.exists():
        pytest.skip("unit not installed on this host")
    directives = [ln.strip() for ln in unit.read_text().splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
    assert "Restart=on-failure" not in directives
    # a timer-driven oneshot must not also be wanted by default.target
    assert "WantedBy=default.target" not in directives


# ── publish-gate signal wiring (added during audit synthesis) ──

def test_process_review_feeds_gate_all_three_signals(pipe, db, monkeypatch):
    """process_review must hand the gate its three inputs.

    They all live on the task already — unique_claims/differentiation in the
    synthesis column, ddg_results in the meta_json cache written by
    process_research — but used to be omitted, pinning has_differentiation and
    has_unique_claims to False for every article ever reviewed.
    """
    tid = db.add_task("gate signal wiring", "tutorial", "wptea", 1)
    db.save_stage_output(tid, "article", "# T\n\n" + ("正文段落。" * 60))
    db.save_stage_output(tid, "research_note", "素材:命中率从 30% 升到 90%。")
    db.save_stage_output(tid, "synthesis", json.dumps({
        "unique_claims": ["elementary 实测的命中率数据"],
        "evidence_for": [{"source": "实测", "claim": "命中率 90%"}],
        "differentiation": "包含本站实测数据，公开搜索结果里没有这一条",
    }, ensure_ascii=False))
    meta = json.loads(db.get_task(tid)["meta_json"] or "{}")
    meta["ddg_results"] = [{"title": "别处的文章", "body": "泛泛而谈"}]
    db.update_status(tid, "reviewing", meta)

    seen = {}

    def fake_review(article, **kwargs):
        seen.update(kwargs)
        return {"overall_pass": True, "overall_score": 7.0,
                "publish_gate": {"decision": "pass"}}

    monkeypatch.setattr("article_pipeline.pipeline.run_self_review", fake_review)
    pipe.process_review(tid)

    assert seen.get("differentiation"), "differentiation not forwarded to review"
    assert seen["research_output"]["unique_claims"], "unique_claims not forwarded"
    assert seen.get("ddg_results"), "ddg_results not forwarded"
