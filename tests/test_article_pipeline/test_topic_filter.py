"""Coverage for topic_filter.py — the topic-admission layer.

Two kinds of test here:
  1. Locks on behaviour that was repaired in the 2026-07-25 audit.
  2. Explicit assertions that pin *known contradictions* which were deliberately
     NOT changed (changing them alters task admission and is a product call).
     They are recorded as tests so the next person meets them as documented
     facts rather than rediscovering them.
"""
import pytest

from article_pipeline.topic_filter import (
    BenchmarkTopicFilter,
    TopicFilter,
    filter_topic,
)


def _results(*titles, body="通用正文", field="snippet"):
    return [{"title": t, field: body} for t in titles]


# ── _result_text: the field-name mismatch that blinded three filters ──

def test_result_text_reads_snippet_not_only_body():
    """research.search_web() returns `snippet`; this class used to read only
    `body`, so the search-volume / pain-point / material filters saw titles
    alone and every body signal was silently discarded."""
    text = BenchmarkTopicFilter._result_text(
        {"title": "标题", "snippet": "正文里有报错信息"})
    assert "报错" in text


@pytest.mark.parametrize("field", ["body", "snippet", "description", "text"])
def test_result_text_accepts_every_known_body_field(field):
    text = BenchmarkTopicFilter._result_text({"title": "T", field: "配置失败"})
    assert "配置失败" in text


def test_result_text_tolerates_missing_and_none_fields():
    assert BenchmarkTopicFilter._result_text({}) == "    "
    assert "t" in BenchmarkTopicFilter._result_text({"title": "T", "body": None})


# ── _tokens ──

def test_tokens_extracts_ascii_words_and_cjk_bigrams():
    toks = BenchmarkTopicFilter._tokens("Nginx 缓存配置")
    assert "nginx" in toks
    assert "缓存" in toks and "存配" in toks and "配置" in toks


def test_tokens_ignores_short_ascii():
    assert "of" not in BenchmarkTopicFilter._tokens("a of the")


# ── 筛子 5「值得写吗」: the homogeneity verdict ──

def test_differentiation_ignores_tokens_from_the_keyword_itself():
    """Search titles almost always contain the query. Counting those as
    "everyone writes this" made the filter reject essentially every topic with
    >=5 results — the "DDG 同质判定不可靠" suspicion."""
    f = BenchmarkTopicFilter(_results(
        "Nginx 缓存命中率怎么测",
        "Nginx 缓存与 CDN 的分工",
        "Nginx 缓存踩过的三个坑",
        "Nginx 缓存对 TTFB 的影响",
        "Nginx 缓存在多站点下的隔离",
    ))
    f.keyword, f.category = "Nginx 缓存", ""
    assert f._check_differentiation() is True


def test_differentiation_flags_genuinely_homogeneous_angles():
    """When the *non-keyword* angle words repeat across most titles, the topic
    really is written out."""
    f = BenchmarkTopicFilter(_results(
        "Python 入门教程完整版",
        "Python 入门教程新手必看",
        "Python 入门教程零基础",
        "Python 入门教程详解",
        "Python 入门教程速成",
    ))
    f.keyword, f.category = "Python", ""
    assert f._check_differentiation() is False


def test_differentiation_needs_a_minimum_sample():
    """Four titles is too small a sample to declare a topic exhausted."""
    f = BenchmarkTopicFilter(_results(
        "同样的角度 A", "同样的角度 B", "同样的角度 C", "同样的角度 D"))
    f.keyword, f.category = "某选题", ""
    assert f._check_differentiation() is True


def test_differentiation_passes_with_no_search_results():
    f = BenchmarkTopicFilter([])
    f.keyword, f.category = "任意选题", ""
    assert f._check_differentiation() is True


def test_bare_how_to_is_rejected_but_a_technical_qualifier_rescues_it():
    f = BenchmarkTopicFilter(_results("无关标题"))
    f.keyword, f.category = "如何做好内容", ""
    assert f._check_differentiation() is False

    f.keyword = "如何配置 Nginx 缓存"   # 配置 is a TECH_QUALIFIER
    assert f._check_differentiation() is True


# ── 筛子 1「有人搜吗」 ──

def test_search_volume_requires_at_least_five_results():
    f = BenchmarkTopicFilter(_results(*[f"Nginx 缓存 {i}" for i in range(4)]))
    f.keyword, f.category = "Nginx 缓存", ""
    assert f._check_search_volume() is False


def test_search_volume_fails_with_no_results():
    f = BenchmarkTopicFilter([])
    f.keyword, f.category = "Nginx 缓存", ""
    assert f._check_search_volume() is False


def test_search_volume_passes_on_relevant_bodies_even_if_titles_differ():
    """The relevance signal may live in the body — this is what the body/snippet
    mismatch used to hide."""
    f = BenchmarkTopicFilter([
        {"title": f"结果 {i}", "snippet": "讲的是 Nginx 缓存命中率"}
        for i in range(6)
    ])
    f.keyword, f.category = "Nginx 缓存", ""
    assert f._check_search_volume() is True


# ── 筛子 4「你能写吗」and the 原理 contradiction ──

@pytest.mark.parametrize("kw", ["什么是 WordPress", "WordPress 简介", "缓存基础"])
def test_writability_rejects_too_broad(kw):
    f = BenchmarkTopicFilter([])
    f.keyword, f.category = kw, ""
    assert f._check_writability() is False


@pytest.mark.parametrize("kw", ["WordPress 源码分析", "Nginx 内核剖析"])
def test_writability_rejects_too_deep(kw):
    f = BenchmarkTopicFilter([])
    f.keyword, f.category = kw, ""
    assert f._check_writability() is False


def test_writability_rejects_very_short_keywords():
    f = BenchmarkTopicFilter([])
    f.keyword, f.category = "缓存", ""
    assert f._check_writability() is False


def test_known_contradiction_yuanli_is_both_too_broad_and_too_deep():
    """"原理" sits in TOO_BROAD_KEYWORDS *and* TOO_DEEP_KEYWORDS, so any topic
    containing it can never pass 你能写吗 — while TopicFilter._check_homogeneity
    treats the same word as a *bonus* (-20 homogeneity). The two filters
    disagree about the same word. Left as-is: fixing it changes admission
    policy, which is a product decision, not a bug fix.
    """
    assert "原理" in BenchmarkTopicFilter.TOO_BROAD_KEYWORDS
    assert "原理" in BenchmarkTopicFilter.TOO_DEEP_KEYWORDS
    f = BenchmarkTopicFilter([])
    f.keyword, f.category = "WordPress 缓存原理", ""
    assert f._check_writability() is False


# ── Whole-filter behaviour ──

def test_empty_search_results_can_never_reach_the_pass_bar():
    """Three of five filters short-circuit to False without search results, and
    the bar is 4/5. So a topic filtered with no search data cannot pass — and
    review.filter_topic_by_benchmark() defaults search_results to None.
    """
    result = BenchmarkTopicFilter([]).filter_topic("Nginx 缓存配置优化", "tutorial")
    assert result.passed is False
    assert sum(result.filters.values()) <= 2


def test_strong_topic_with_real_results_passes():
    results = [
        {"title": f"Nginx 缓存命中率{suffix}", "snippet": "报错 怎么 解决 配置 案例 官方文档"}
        for suffix in ("怎么测量", "与压测的关系", "线上翻车记", "分站点隔离", "和 CDN 的分工", "调优笔记")
    ]
    result = BenchmarkTopicFilter(results).filter_topic("Nginx 缓存命中率", "tutorial")
    assert result.passed is True, result.filters
    assert result.score >= 8.0


def test_result_carries_reasons_and_suggestions():
    result = BenchmarkTopicFilter([]).filter_topic("什么是缓存", "tutorial")
    assert result.reasons, "a failing verdict must explain itself"
    assert isinstance(result.suggestions, list)


def test_generate_report_is_renderable_without_search_data():
    report = BenchmarkTopicFilter([]).generate_report("Nginx 缓存配置", "tutorial")
    assert "Nginx 缓存配置" in report


# ── TopicFilter (the one pipeline actually calls) ──

def test_topic_filter_never_returns_reject():
    """pipeline.add_task only refuses a topic when recommendation == "reject",
    but this class emits only accept / low_value — the reject branch in the
    pipeline is unreachable. The docstring advertises "reject"; the code path
    does not exist. Recorded, not fixed: adding a reject path starts blocking
    task admission, which is a product decision.
    """
    verdicts = set()
    for kw in ["WordPress 入门教程", "Docker 快速上手", "随便一个短语",
               "Nginx 避坑指南", "为什么不用 Redis", "数据显示缓存无效"]:
        verdicts.add(TopicFilter().filter_topic(kw)["recommendation"])
    assert "reject" not in verdicts
    assert verdicts <= {"accept", "low_value"}


def test_contrarian_keyword_makes_a_topic_accepted():
    out = TopicFilter().filter_topic("WordPress 缓存的三个误区")
    assert out["recommendation"] == "accept"
    assert out["checks"]["contrarian"]["verdict"] is True


def test_plain_beginner_topic_is_low_value():
    out = TopicFilter().filter_topic("WordPress 入门教程")
    assert out["recommendation"] == "low_value"
    assert out["checks"]["homogeneity"]["score"] > 10


def test_filter_topic_result_shape():
    out = TopicFilter().filter_topic("Nginx 缓存避坑", category="tutorial")
    assert set(out) >= {"recommendation", "reason", "checks", "meta"}
    assert set(out["checks"]) == {"homogeneity", "contrarian", "counter_intuitive"}
    assert out["meta"]["keyword"] == "Nginx 缓存避坑"
    assert out["meta"]["category"] == "tutorial"


def test_mock_search_short_circuits_homogeneity():
    out = TopicFilter(mock_search=True).filter_topic("任意选题")
    assert out["checks"]["homogeneity"] == {"score": 25, "verdict": False}


def test_module_level_filter_topic_delegates():
    out = filter_topic("WordPress 缓存的三个误区")
    assert out["recommendation"] == "accept"
