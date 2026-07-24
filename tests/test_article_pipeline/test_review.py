"""Tests for review module."""
import pytest
from article_pipeline.review import (
    check_facts,
    check_ai_patterns,
    check_word_count,
    check_format,
    run_self_review,
    compute_publish_gate,
)


def test_check_ai_patterns_detects_template():
    """Should flag known AI template phrases."""
    text = "在当今数字化时代，WordPress 非常流行。首先我们安装插件，其次配置参数，最后测试。总而言之，很简单。"
    result = check_ai_patterns(text)
    assert result["score"] < 6
    assert len(result["flags"]) >= 3


def test_check_ai_patterns_clean_text():
    """Clean human-written text should score high."""
    text = """昨天给 WPFonts 加了子集化功能。中文字体文件太大，拆分后加载快了三倍。
具体做法是用 fonttools 的 pyftsubset，配合 WordPress 的 wp_enqueue_scripts 钩子。
有个坑：IE11 不支持 woff2，还得保留 woff 回退。"""
    result = check_ai_patterns(text)
    assert result["score"] >= 7


def test_check_word_count_too_short():
    """Articles under 1000 chars should flag as too short."""
    result = check_word_count("太短了", tier="A")
    assert result["pass"] is False


def test_check_word_count_ok():
    """Article with 1500+ chars should pass for A tier."""
    text = "测试内容。" * 400
    result = check_word_count(text, tier="A")
    assert result["pass"] is True


def test_check_word_count_b_tier():
    """B tier requires 2000+ chars."""
    text = "测试内容。" * 600
    result = check_word_count(text, tier="B")
    assert result["pass"] is True


def test_check_format_has_headings():
    """Article should have H2 headings."""
    good = "## 简介\n这是一段内容。\n\n## 方法\n又是一段。"
    result = check_format(good)
    assert result["has_h2"] is True

    bad = "没有标题的文章内容。只是一堆文字。"
    result = check_format(bad)
    assert result["has_h2"] is False


def test_run_self_review_integration():
    """Full self-review returns structured results."""
    article = """## WordPress 缓存插件深度对比

网站速度是用户体验的核心。本文对比 5 款主流缓存插件。

### 测试环境

所有测试在相同 VPS 上运行，使用 WordPress 6.7、PHP 8.3、Nginx。

### WP Rocket

WP Rocket 是商业插件中的标杆。售价 $59/年。

### W3 Total Cache

老牌免费插件，配置项非常多。

### 结论

根据场景选择最合适的插件。小型站点用免费方案即可。"""
    result = run_self_review(article, tier="A", research_note="测试研究笔记")
    # Key presence alone is worthless — every check could return garbage and
    # this test would still pass. Assert the values the pipeline acts on.
    assert result["format"]["has_h2"] is True
    assert result["word_count"]["pass"] is False, "this sample is ~300 chars, tier A wants 1500+"
    assert 0.0 <= result["ai_check"]["score"] <= 10.0
    assert 0.0 <= result["overall_score"] <= 10.0
    assert isinstance(result["overall_pass"], bool)
    # A short article that fails word count can never be an auto-pass.
    assert result["overall_pass"] is False
    assert result["value_density"]["recommendation"] in ("pass", "needs_human", "fail")
    assert result["publish_gate"]["decision"] in ("pass", "needs_human", "fail")
    # Suggestions must be produced when the article does not pass.
    assert len(result["suggestions"]) > 0


class TestComputePublishGate:
    """Tests for compute_publish_gate function."""

    def test_fail_low_value_density(self):
        """value_density < 4.0 should fail regardless of other signals."""
        value_density = {
            "overall_score": 3.5,
            "recommendation": "fail",
        }
        result = compute_publish_gate(
            value_density_result=value_density,
            has_differentiation=True,
            has_unique_claims=True,
        )
        assert result["decision"] == "fail"
        assert "内容密度不足" in result["reason"]
        assert len(result["blocking_reasons"]) == 1

    def test_needs_human_mid_density_no_signals(self):
        """value_density 4.0~6.0 with no differentiation/unique_claims → needs_human."""
        value_density = {
            "overall_score": 5.0,
            "recommendation": "needs_human",
        }
        result = compute_publish_gate(
            value_density_result=value_density,
            has_differentiation=False,
            has_unique_claims=False,
        )
        assert result["decision"] == "needs_human"
        assert "需人工判断" in result["reason"]
        # Should have blocking reasons
        assert len(result["blocking_reasons"]) > 0

    def test_pass_by_value_density(self):
        """value_density >= 6.0 alone should pass."""
        value_density = {
            "overall_score": 6.5,
            "recommendation": "pass",
        }
        result = compute_publish_gate(
            value_density_result=value_density,
            has_differentiation=False,
            has_unique_claims=False,
        )
        assert result["decision"] == "pass"
        assert "发布条件满足" in result["reason"]
        assert len(result["blocking_reasons"]) == 0

    def test_pass_by_differentiation(self):
        """differentiation alone can compensate mid-level density."""
        value_density = {
            "overall_score": 5.5,
            "recommendation": "needs_human",
        }
        result = compute_publish_gate(
            value_density_result=value_density,
            has_differentiation=True,
            has_unique_claims=False,
        )
        assert result["decision"] == "pass"
        assert "差异化说明" in result["reason"]

    def test_pass_by_unique_claims(self):
        """unique_claims alone can compensate mid-level density."""
        value_density = {
            "overall_score": 5.5,
            "recommendation": "needs_human",
        }
        result = compute_publish_gate(
            value_density_result=value_density,
            has_differentiation=False,
            has_unique_claims=True,
        )
        assert result["decision"] == "pass"
        assert "独到见解" in result["reason"]

    def test_signals_structure(self):
        """Result should contain all three signals."""
        value_density = {
            "overall_score": 7.0,
            "recommendation": "pass",
        }
        result = compute_publish_gate(
            value_density_result=value_density,
            has_differentiation=True,
            has_unique_claims=True,
        )
        signals = result["signals"]
        assert "value_density" in signals
        assert "differentiation" in signals
        assert "unique_claims" in signals
        assert signals["value_density"] == 7.0
        assert signals["differentiation"] is True
        assert signals["unique_claims"] is True


class TestPublishGateIntegration:
    """Tests for publish_gate integration in run_self_review."""

    def test_publish_gate_present_in_results(self):
        """run_self_review should include publish_gate field."""
        article = """## 测试标题

这是一篇测试文章。包含足够的内容来通过基本检查。

## 第二部分

更多内容。""" + "测试内容。" * 100

        result = run_self_review(article, tier="A")
        gate = result["publish_gate"]
        # `decision in (all three possible values)` is tautological. Assert the
        # actual verdict for this input: filler repeated 100x has no density.
        assert gate["decision"] == "fail", f"filler must fail, got {gate}"
        assert result["value_density"]["overall_score"] < 4.0
        assert gate["reason"], "a blocking decision must carry a reason"
        assert gate["blocking_reasons"], "a blocking decision must list reasons"
        assert gate["signals"]["differentiation"] is False
        assert gate["signals"]["unique_claims"] is False
        # And the verdict must be enforced, not merely recorded.
        assert result["overall_pass"] is False

    def test_publish_gate_with_differentiation(self):
        """differentiation parameter should affect publish_gate."""
        article = "## 测试\n" + "内容。" * 200
        research_output = {
            "sources": {},
            "research_note": "测试研究笔记",
            "unique_claims": [],
        }

        # Without differentiation
        result = run_self_review(
            article,
            tier="A",
            research_output=research_output,
            differentiation="",
        )
        assert result["publish_gate"]["signals"]["differentiation"] is False

        # With differentiation
        result = run_self_review(
            article,
            tier="A",
            research_output=research_output,
            differentiation="本文基于实测数据，对比了3种方案的性能，搜索结果均未提及",
        )
        assert result["publish_gate"]["signals"]["differentiation"] is True

    def test_publish_gate_with_unique_claims(self):
        """unique_claims in research_output should affect publish_gate."""
        article = "## 测试\n" + "内容。" * 200
        research_output_with_claims = {
            "sources": {},
            "research_note": "测试研究笔记",
            "unique_claims": ["这是第一个独到见解", "这是第二个独到见解"],
        }

        result = run_self_review(
            article,
            tier="A",
            research_output=research_output_with_claims,
        )
        assert result["publish_gate"]["signals"]["unique_claims"] is True

        # Negative control: without the claims the same article must flip to
        # False. Without this, a hardcoded `True` would pass the test above.
        result_none = run_self_review(
            article, tier="A",
            research_output={**research_output_with_claims, "unique_claims": []},
        )
        assert result_none["publish_gate"]["signals"]["unique_claims"] is False

    def test_publish_gate_boundary_value_density(self):
        """A near-empty article must be blocked as slop.

        The original version of this test wrapped its only assertion in
        `if score < 4.0:` — so if scoring ever drifted upward the test asserted
        nothing and stayed green. Assert unconditionally.
        """
        slop_article = """
## 测试

这是一篇文章。
"""
        result = run_self_review(slop_article, tier="A")
        assert result["value_density"]["overall_score"] < 4.0
        assert result["publish_gate"]["decision"] == "fail"
        assert result["overall_pass"] is False
