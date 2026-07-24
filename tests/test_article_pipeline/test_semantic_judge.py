"""Tests for the LLM-as-judge semantic review layer.

Fully offline: every LLM interaction goes through an injected ``call_fn``.
"""
import json
import os

import pytest

from article_pipeline.review import semantic_judge as sj
from article_pipeline.review.semantic_judge import (
    BAND_MAX,
    CALIBRATION_ANCHOR,
    JudgeVerdict,
    apply_judge_to_gate,
    build_judge_prompt,
    estimate_cost,
    is_enabled,
    judge_article,
    merge_verdicts,
    parse_judge_response,
)

# ── fixtures ────────────────────────────────────────────────────────

ARTICLE = """## Nginx 缓存命中率优化

我们把 proxy_cache_valid 从 10m 调到 2h 之后，命中率从 41% 涨到 78%，
但代价是内容更新延迟变成了两小时，编辑部为此投诉了三次。

真正的取舍不在参数上，而在于你愿不愿意为一篇文章的时效性付出额外的
purge 逻辑复杂度。我们最后选择了短 TTL 加主动 purge。
"""

MATERIAL = """nginx.org 文档：proxy_cache_valid 指定不同响应码的缓存时间。
内部压测记录：TTL 10m 时命中率 41%，TTL 2h 时命中率 78%。
"""


def _resp(payload: dict, model="glm-test") -> dict:
    return {"content": json.dumps(payload, ensure_ascii=False),
            "model": model, "tokens": {"input_tokens": 100, "output_tokens": 50}}


def _good_payload() -> dict:
    return {
        "claims": [{
            "text": "命中率从 41% 涨到 78%",
            "kind": "statistic", "verdict": "supported",
            "evidence": "内部压测记录：TTL 10m 时命中率 41%，TTL 2h 时命中率 78%。",
            "severity": "minor", "note": "素材可验证",
        }],
        "dimensions": {
            "factuality": {"score": 3, "reason": "数字有素材支撑",
                           "quotes": ["命中率从 41% 涨到 78%"]},
            "originality": {"score": 3, "reason": "给出了自家实测的 TTL/命中率对照",
                            "quotes": ["编辑部为此投诉了三次"]},
            "insight": {"score": 3, "reason": "指出了 TTL 与 purge 复杂度的取舍",
                        "quotes": ["真正的取舍不在参数上"]},
            "brand_fit": {"score": 2, "reason": "结合了自家运维场景",
                          "quotes": ["我们最后选择了短 TTL 加主动 purge"]},
        },
        "unique_contribution": "自家站点 TTL 10m→2h 的命中率与时效性代价对照",
        "kill_reasons": [],
        "reject_case": "样本只有一个站点，外推性有限",
        "calibration_score": 1,
        "weakest_sentences": ["我们最后选择了短 TTL 加主动 purge。"],
    }


# ── prompt construction ─────────────────────────────────────────────

def test_prompt_includes_article_material_and_calibration_anchor():
    system, user = build_judge_prompt(ARTICLE, material=MATERIAL,
                                      brand_context="文派 WPMind", topic="Nginx 缓存")
    assert "proxy_cache_valid 从 10m 调到 2h" in user
    assert "内部压测记录" in user
    assert CALIBRATION_ANCHOR in user, "calibration ballast must be in every prompt"
    assert "文派 WPMind" in user
    assert "Nginx 缓存" in user
    assert "逐字" in system, "verbatim-quote requirement must be in the system prompt"


def test_prompt_without_material_demands_unsupported():
    _, user = build_judge_prompt(ARTICLE, material="")
    assert "无素材" in user


def test_adversarial_pass_changes_system_prompt():
    s1, _ = build_judge_prompt(ARTICLE, adversarial=False)
    s2, _ = build_judge_prompt(ARTICLE, adversarial=True)
    assert s2 != s1
    assert "退稿方" in s2 and "退稿方" not in s1


def test_prompt_truncates_oversized_inputs():
    _, user = build_judge_prompt("啊" * 40000, material="哦" * 40000)
    assert user.count("啊") == sj.MAX_ARTICLE_CHARS
    assert user.count("哦") == sj.MAX_MATERIAL_CHARS


# ── parsing ─────────────────────────────────────────────────────────

def test_parse_good_article_passes():
    v = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    assert v.decision == "pass"
    assert v.dimensions["originality"].score == 3
    assert v.dimensions["originality"].quotes_verified == 1
    # bands 3/3/3/2 with weights .40/.30/.20/.10 → 2.9/4 * 10
    assert v.score == pytest.approx(7.25, abs=0.06)


def test_parse_handles_markdown_fenced_json():
    raw = "这是我的评估：\n```json\n" + json.dumps(_good_payload(), ensure_ascii=False) + "\n```\n"
    assert parse_judge_response(raw, ARTICLE).decision == "pass"


def test_unparseable_response_is_unavailable_not_pass():
    v = parse_judge_response("抱歉，我无法完成这个任务。", ARTICLE)
    assert v.decision == "unavailable"
    assert v.available is False
    assert v.error == "unparseable_judge_response"


def test_empty_response_is_unavailable():
    assert parse_judge_response("", ARTICLE).decision == "unavailable"


def test_scores_are_clamped_to_band_range():
    p = _good_payload()
    p["dimensions"]["factuality"]["score"] = 99
    p["dimensions"]["insight"]["score"] = -5
    p["dimensions"]["brand_fit"]["score"] = "not a number"
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.dimensions["factuality"].score == BAND_MAX
    assert v.dimensions["insight"].score == 0
    assert v.dimensions["brand_fit"].score == 0


# ── anti-rubber-stamp ───────────────────────────────────────────────

def test_fabricated_quote_demotes_the_score():
    """A high score whose quote is not in the article must be cut."""
    p = _good_payload()
    p["dimensions"]["originality"]["score"] = 4
    p["dimensions"]["originality"]["quotes"] = ["这句话根本不在原文里出现过，是编造的引文"]
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.dimensions["originality"].quotes_verified == 0
    assert v.dimensions["originality"].demoted is True
    assert v.dimensions["originality"].score == 1


def test_all_praise_no_quotes_is_rejected():
    """The classic rubber stamp: 4s across the board, zero evidence."""
    p = {
        "dimensions": {d: {"score": 4, "reason": "非常好，内容详实，结构清晰", "quotes": []}
                       for d in ("factuality", "originality", "insight", "brand_fit")},
        "claims": [],
        "unique_contribution": "本文内容非常全面",
        "calibration_score": 1,
    }
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert all(d.demoted for d in v.dimensions.values())
    assert all(d.score == 1 for d in v.dimensions.values())
    assert v.decision == "reject"


def test_supported_claim_without_evidence_is_downgraded():
    p = _good_payload()
    p["claims"][0]["evidence"] = ""
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.claims[0].verdict == "unverifiable"
    assert "evidence missing" in v.claims[0].note


def test_miscalibrated_judge_verdict_is_not_trusted():
    """Judge that praises the known-bad ballast gets routed to a human."""
    p = _good_payload()
    p["calibration_score"] = 4
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.calibration_ok is False
    assert v.decision == "revise"
    assert any("校准失败" in r for r in v.kill_reasons)


def test_short_quote_does_not_count_as_evidence():
    p = _good_payload()
    p["dimensions"]["originality"]["quotes"] = ["我们"]  # substring, but too short
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.dimensions["originality"].quotes_verified == 0
    assert v.dimensions["originality"].demoted is True


def test_whitespace_insensitive_quote_matching():
    p = _good_payload()
    p["dimensions"]["originality"]["quotes"] = ["命中率从 41%\n 涨到   78%"]
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.dimensions["originality"].quotes_verified == 1


# ── hard reject rules ───────────────────────────────────────────────

def test_fatal_fabricated_constant_forces_reject():
    p = _good_payload()
    p["claims"].append({
        "text": "proxy_cache_min_uses 默认值为 7",
        "kind": "constant", "verdict": "unsupported", "evidence": "",
        "severity": "fatal", "note": "素材与官方文档中查不到该默认值，疑似杜撰",
    })
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.decision == "reject"
    assert any("致命事实错误" in r for r in v.kill_reasons)


def test_contradicted_claim_forces_reject():
    p = _good_payload()
    p["claims"].append({
        "text": "ctime 是文件创建时间", "kind": "concept",
        "verdict": "contradicted", "evidence": "ctime 指 inode 变更时间",
        "severity": "major", "note": "讲反了",
    })
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.decision == "reject"
    assert any("矛盾" in r for r in v.kill_reasons)


def test_zero_originality_forces_reject_even_with_perfect_facts():
    """Correct but says nothing new — the exact defect no surface metric sees."""
    p = _good_payload()
    p["dimensions"]["originality"] = {"score": 0, "reason": "全是官方文档复述", "quotes": []}
    p["unique_contribution"] = ""
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.decision == "reject"
    assert any("信息增量为 0" in r for r in v.kill_reasons)


def test_missing_unique_contribution_forces_reject():
    p = _good_payload()
    p["unique_contribution"] = "   "
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.decision == "reject"


def test_low_factuality_band_forces_reject():
    p = _good_payload()
    p["dimensions"]["factuality"]["score"] = 1
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.decision == "reject"
    assert any("事实可靠性" in r for r in v.kill_reasons)


def test_thin_insight_routes_to_revise_not_reject():
    p = _good_payload()
    p["dimensions"]["insight"]["score"] = 1
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert v.decision == "revise"


# ── multi-pass merge ────────────────────────────────────────────────

def test_merge_takes_the_minimum_not_the_mean():
    lenient = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    strict_p = _good_payload()
    strict_p["dimensions"]["originality"]["score"] = 1
    strict = parse_judge_response(json.dumps(strict_p, ensure_ascii=False), ARTICLE)
    merged = merge_verdicts([lenient, strict])
    assert merged.dimensions["originality"].score == 1, "must be min(3,1), not mean(2)"
    assert merged.decision == "revise"


def test_merge_one_reject_wins():
    ok = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    bad_p = _good_payload()
    bad_p["claims"].append({"text": "杜撰的常量", "kind": "constant",
                            "verdict": "unsupported", "evidence": "",
                            "severity": "fatal", "note": ""})
    bad = parse_judge_response(json.dumps(bad_p, ensure_ascii=False), ARTICLE)
    assert merge_verdicts([ok, bad]).decision == "reject"


def test_merge_drops_unique_contribution_unless_all_passes_found_one():
    a = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    p2 = _good_payload()
    p2["unique_contribution"] = ""
    b = parse_judge_response(json.dumps(p2, ensure_ascii=False), ARTICLE)
    assert merge_verdicts([a, b]).decision == "reject"


def test_merge_ignores_unavailable_verdicts():
    ok = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    dead = JudgeVerdict(decision="unavailable", error="api_timeout")
    assert merge_verdicts([ok, dead]).decision == "pass"


def test_merge_of_only_unavailable_stays_unavailable():
    assert merge_verdicts([JudgeVerdict(error="x"), JudgeVerdict(error="y")]).available is False


# ── judge_article transport handling ────────────────────────────────

def test_judge_article_happy_path_with_injected_call():
    calls = []

    def fake(system, user, **kw):
        calls.append((system, user, kw))
        return _resp(_good_payload())

    v = judge_article(ARTICLE, material=MATERIAL, call_fn=fake)
    assert v.decision == "pass"
    assert v.model == "glm-test"
    assert v.tokens["input_tokens"] == 100
    assert len(calls) == 1
    assert calls[0][2]["temperature"] == 0.0, "judging must be deterministic"


def test_judge_article_two_passes_makes_two_calls_second_adversarial():
    seen = []

    def fake(system, user, **kw):
        seen.append(system)
        return _resp(_good_payload())

    judge_article(ARTICLE, material=MATERIAL, passes=2, call_fn=fake)
    assert len(seen) == 2
    assert "退稿方" in seen[1] and "退稿方" not in seen[0]


def test_judge_article_api_error_is_unavailable():
    v = judge_article(ARTICLE, call_fn=lambda s, u, **kw: {"error": "api_timeout",
                                                           "message": "boom"})
    assert v.decision == "unavailable"
    assert v.error == "api_timeout"


def test_judge_article_exception_does_not_propagate():
    def boom(system, user, **kw):
        raise ConnectionError("network down")

    v = judge_article(ARTICLE, call_fn=boom)
    assert v.decision == "unavailable"
    assert "ConnectionError" in v.error


def test_judge_article_empty_article_short_circuits_without_calling():
    def must_not_run(system, user, **kw):  # pragma: no cover
        raise AssertionError("should not call the LLM for empty input")

    v = judge_article("   ", call_fn=must_not_run)
    assert v.decision == "unavailable"
    assert v.error == "empty_article"


# ── gate integration ────────────────────────────────────────────────

def _gate(decision="pass"):
    return {"decision": decision, "reason": "surface", "signals": {},
            "blocking_reasons": [] if decision == "pass" else ["密度不足"]}


def test_judge_reject_turns_a_passing_gate_into_fail():
    p = _good_payload()
    p["dimensions"]["originality"] = {"score": 0, "reason": "通稿", "quotes": []}
    p["unique_contribution"] = ""
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    out = apply_judge_to_gate(_gate("pass"), v)
    assert out["decision"] == "fail"
    assert any(r.startswith("[judge]") for r in out["blocking_reasons"])


def test_judge_revise_downgrades_pass_to_needs_human():
    p = _good_payload()
    p["dimensions"]["insight"]["score"] = 1
    v = parse_judge_response(json.dumps(p, ensure_ascii=False), ARTICLE)
    assert apply_judge_to_gate(_gate("pass"), v)["decision"] == "needs_human"


def test_judge_can_rescue_needs_human_with_verified_evidence():
    v = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    out = apply_judge_to_gate(_gate("needs_human"), v)
    assert out["decision"] == "pass"
    assert "语义评审放行" in out["reason"]


def test_judge_can_never_rescue_a_hard_fail():
    """Density < 4.0 is a hard fail; the judge must not be able to override it."""
    v = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    out = apply_judge_to_gate(_gate("fail"), v)
    assert out["decision"] == "fail"


def test_unavailable_judge_leaves_gate_untouched():
    for decision in ("pass", "needs_human", "fail"):
        before = _gate(decision)
        out = apply_judge_to_gate(before, JudgeVerdict(error="api_timeout"))
        assert out["decision"] == decision
        assert out["blocking_reasons"] == before["blocking_reasons"]


def test_gate_result_carries_serialisable_judge_payload():
    v = parse_judge_response(json.dumps(_good_payload(), ensure_ascii=False), ARTICLE)
    out = apply_judge_to_gate(_gate("pass"), v)
    json.dumps(out, ensure_ascii=False)  # must not raise
    assert out["semantic_judge"]["decision"] == "pass"
    assert out["semantic_judge"]["dimensions"]["originality"]["quotes_verified"] == 1


# ── feature flag ────────────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AP_SEMANTIC_JUDGE", raising=False)
    assert is_enabled() is False
    assert is_enabled(None) is False


def test_env_var_enables(monkeypatch):
    for val in ("1", "true", "yes", "ON"):
        monkeypatch.setenv("AP_SEMANTIC_JUDGE", val)
        assert is_enabled() is True
    monkeypatch.setenv("AP_SEMANTIC_JUDGE", "0")
    assert is_enabled() is False


def test_explicit_argument_overrides_env(monkeypatch):
    monkeypatch.setenv("AP_SEMANTIC_JUDGE", "1")
    assert is_enabled(False) is False
    monkeypatch.delenv("AP_SEMANTIC_JUDGE", raising=False)
    assert is_enabled(True) is True


def test_run_self_review_does_not_call_judge_by_default(monkeypatch):
    monkeypatch.delenv("AP_SEMANTIC_JUDGE", raising=False)
    from article_pipeline.review import run_self_review

    def must_not_run(*a, **kw):  # pragma: no cover
        raise AssertionError("semantic judge must be off by default")

    res = run_self_review(ARTICLE * 3, "A", MATERIAL, judge_call_fn=must_not_run)
    assert "semantic_judge" not in res


def test_run_self_review_with_judge_enabled_records_verdict(monkeypatch):
    monkeypatch.delenv("AP_SEMANTIC_JUDGE", raising=False)
    from article_pipeline.review import run_self_review

    p = _good_payload()
    p["dimensions"]["originality"] = {"score": 0, "reason": "通稿", "quotes": []}
    p["unique_contribution"] = ""

    res = run_self_review(ARTICLE * 3, "A", MATERIAL,
                          enable_semantic_judge=True,
                          judge_call_fn=lambda s, u, **kw: _resp(p))
    assert res["semantic_judge"]["decision"] == "reject"
    assert res["publish_gate"]["decision"] == "fail"
    assert res["overall_pass"] is False


# ── cost estimate ───────────────────────────────────────────────────

def test_estimate_cost_scales_with_passes():
    one = estimate_cost(ARTICLE * 10, MATERIAL * 10, passes=1)
    two = estimate_cost(ARTICLE * 10, MATERIAL * 10, passes=2)
    assert two["input_tokens"] == 2 * one["input_tokens"]
    assert two["usd"] > one["usd"]
    assert one["input_tokens"] > 0


def test_estimate_cost_is_capped_for_huge_inputs():
    huge = estimate_cost("啊" * 500000, "哦" * 500000)
    bound = (sj.MAX_ARTICLE_CHARS + sj.MAX_MATERIAL_CHARS + 6000) / 1.6
    assert huge["input_tokens"] < bound
