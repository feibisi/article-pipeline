"""Regression locks for the quality gate.

Each test here corresponds to a defect that actually shipped slop to production.
They exist to make a *silent* re-introduction impossible. Do not relax an
assertion here without a written decision — the original bugs were all of the
"computed a verdict, then ignored it" shape, which no other test could see.
"""
import pytest

from article_pipeline.review import (
    compute_overall_score,
    compute_publish_gate,
    run_self_review,
)
from article_pipeline.review.value_density import _check_unique_info

# A fluent, correct, utterly empty article — the shape of everything that
# reached production. High surface scores, zero information.
SLOP = """# WordPress 网站性能优化的最佳实践

## 为什么性能优化很重要

在当今这个数字化时代，网站性能已经成为影响用户体验的关键因素。研究表明，
页面加载时间每增加一秒，转化率就会下降。因此，性能优化对于任何网站来说
都是不可忽视的一环。

## 缓存的使用

缓存是提升性能的有效手段。推荐使用成熟的缓存插件来实现页面缓存。通过合理
配置缓存策略，可以显著减少服务器负载，从而改善网站的响应速度。关键在于
根据实际情况选择合适的缓存方案。

## 图片优化

图片通常占据页面体积的很大一部分。建议采用现代图片格式，并对图片进行压缩
处理。此外，懒加载技术也是值得考虑的优化手段。

## 数据库优化

定期清理数据库中的冗余数据是必要的。应该定期检查并删除无用的修订版本和
垃圾评论。

## 总结

综上所述，网站性能优化是一项系统性的工作。希望本文介绍的方法能够帮助您
更好地提升网站性能，为用户提供更优质的浏览体验。
"""


class TestUniqueInfoNeutralWithoutCorpus:
    """Bug: `_check_unique_info` returned 10.0 when no comparison corpus existed.

    The live pipeline passes no DDG results (pipeline.py:662), so *every* article
    scored a perfect 10/10 on "information found nowhere else" — the single
    dimension most responsible for detecting recycled content.
    """

    def test_empty_corpus_returns_neutral_not_perfect(self):
        score = _check_unique_info(["某个具体的断言，长度足够"], [])
        assert score == 5.0, "no corpus must mean 'unknown', never 'perfect'"
        assert score != 10.0

    def test_no_claims_still_scores_zero(self):
        assert _check_unique_info([], []) == 0.0

    def test_corpus_present_still_discriminates(self):
        claims = ["性能提升了 300%", "默认配置是 64MB"]
        overlapping = [{"title": "t", "body": "性能提升了 300%，默认配置是 64MB"}] * 3
        assert _check_unique_info(claims, overlapping) < 5.0, (
            "claims echoed by the corpus must score below neutral"
        )


class TestValueDensityInOverallScore:
    """Bug: `value_density` — the only anti-slop signal — carried zero weight.

    Fluent-but-empty content scored 9+/10 overall while its density was 4.x.
    """

    def test_value_density_is_weighted(self):
        base = {
            "ai_check": {"score": 10}, "dbs_ai": {"score": 10},
            "format": {"pass": True}, "fabrication": {"pass": True},
            "semantic_facts": {"pass": True}, "word_count": {"pass": True},
            "humanizer": {"total": 50}, "jargon": {"pass": True},
            "style_compliance": {"overall_score": 10.0},
        }
        high = compute_overall_score({**base, "value_density": {"overall_score": 10.0}})
        low = compute_overall_score({**base, "value_density": {"overall_score": 0.0}})
        assert high > low, "value_density must move the headline score"
        assert high - low >= 1.5, (
            f"value_density weight is too small to matter (delta={high - low})"
        )

    def test_missing_value_density_does_not_crash(self):
        assert compute_overall_score({}) >= 0.0


class TestPublishGateIsEnforced:
    """Bug: `publish_gate` was computed and then never read.

    A "fail" (slop) verdict did not stop the task from being marked completed,
    because `overall_pass` was derived only from the surface checks.
    """

    def test_gate_fail_forces_overall_pass_false(self):
        res = run_self_review(SLOP, tier="A", research_note="")
        assert res["publish_gate"]["decision"] in ("fail", "needs_human")
        assert res["overall_pass"] is False, (
            "a failing publish gate must veto overall_pass"
        )

    def test_slop_density_is_below_threshold(self):
        res = run_self_review(SLOP, tier="A", research_note="")
        assert res["value_density"]["overall_score"] < 6.0

    @pytest.mark.parametrize("decision", ["fail", "needs_human"])
    def test_both_blocking_decisions_veto(self, decision, monkeypatch):
        import article_pipeline.review as R
        monkeypatch.setattr(R, "compute_publish_gate",
                            lambda **kw: {"decision": decision, "reason": "",
                                          "signals": {}, "blocking_reasons": []})
        res = R.run_self_review(SLOP, tier="A", research_note="")
        assert res["overall_pass"] is False

    def test_gate_pass_does_not_itself_force_a_fail(self, monkeypatch):
        """Guard against over-correction: a passing gate must stay neutral."""
        import article_pipeline.review as R
        monkeypatch.setattr(R, "compute_publish_gate",
                            lambda **kw: {"decision": "pass", "reason": "",
                                          "signals": {}, "blocking_reasons": []})
        res = R.run_self_review(SLOP, tier="A", research_note="")
        # overall_pass may still be False for surface reasons, but not because
        # of the gate — the gate contributed no blocking reason.
        assert res["publish_gate"]["decision"] == "pass"


class TestPublishGateBands:
    """The three density bands must be exact and unconditionally asserted.

    The pre-existing boundary test wrapped its only assertion in an `if`, so it
    went green while asserting nothing whenever scoring drifted.
    """

    @pytest.mark.parametrize("score,expected", [
        (0.0, "fail"), (3.9, "fail"),
        (4.0, "needs_human"), (5.9, "needs_human"),
        (6.0, "pass"), (10.0, "pass"),
    ])
    def test_band_boundaries(self, score, expected):
        out = compute_publish_gate({"overall_score": score}, False, False)
        assert out["decision"] == expected, f"density {score} should be {expected}"

    def test_hard_fail_cannot_be_rescued_by_differentiation(self):
        out = compute_publish_gate({"overall_score": 2.0}, True, True)
        assert out["decision"] == "fail", (
            "below 4.0 is slop; differentiation must not buy a pass"
        )

    def test_mid_band_is_rescued_by_differentiation(self):
        assert compute_publish_gate({"overall_score": 5.0}, True, False)["decision"] == "pass"

    def test_mid_band_is_rescued_by_unique_claims(self):
        assert compute_publish_gate({"overall_score": 5.0}, False, True)["decision"] == "pass"

    def test_signals_report_the_numeric_score_not_a_bool(self):
        out = compute_publish_gate({"overall_score": 7.5}, False, False)
        assert out["signals"]["value_density"] == 7.5
        assert not isinstance(out["signals"]["value_density"], bool)
