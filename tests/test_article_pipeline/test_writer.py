"""Tests for writer module."""
import pytest
from article_pipeline.writer import (
    get_trust_tier, _genre_rules, _build_writer_prompt, _extract_samples,
    _fix_terminology, TIER_INTERNAL_CATEGORIES, TIER_EXTERNAL_CATEGORIES,
)


def test_trust_tier_internal():
    assert get_trust_tier("tutorial") == "TIER_INTERNAL"
    assert get_trust_tier("wp-tech") == "TIER_INTERNAL"
    assert get_trust_tier("book-knowledge") == "TIER_INTERNAL"
    assert get_trust_tier("opinion") == "TIER_INTERNAL"


def test_trust_tier_external():
    assert get_trust_tier("product-launch") == "TIER_EXTERNAL"
    assert get_trust_tier("announcement") == "TIER_EXTERNAL"
    assert get_trust_tier("brand-marketing") == "TIER_EXTERNAL"
    assert get_trust_tier("marketing") == "TIER_EXTERNAL"


def test_trust_tier_empty():
    assert get_trust_tier("") == "TIER_INTERNAL"
    assert get_trust_tier(None) == "TIER_INTERNAL"


def test_trust_tier_unknown():
    assert get_trust_tier("unknown-category") == "TIER_INTERNAL"


def test_genre_rules_all_categories():
    for cat in TIER_INTERNAL_CATEGORIES | TIER_EXTERNAL_CATEGORIES:
        rules = _genre_rules(cat)
        assert "写作规则" in rules, f"Missing rules for {cat}"
        assert len(rules) > 100, f"Rules too short for {cat}"


def test_genre_rules_external_has_strict():
    rules = _genre_rules("product-launch", "TIER_EXTERNAL")
    assert "信息来源红线" in rules
    assert "禁止假设场景" in rules


def test_genre_rules_internal_allows_scenarios():
    rules = _genre_rules("tutorial", "TIER_INTERNAL")
    assert "写作姿态" in rules


def test_genre_rules_fallback():
    rules = _genre_rules("nonexistent-genre")
    assert "写作规则" in rules
    assert "指南" in rules or "guide" in rules.lower()


def test_build_writer_prompt_basic():
    outline = {
        "titles": [{"style": "seo", "text": "测试标题"}],
        "core_argument": "核心论点",
        "sections": [{"heading": "第一节", "points": ["要点1"]}],
    }
    prompt = _build_writer_prompt("测试关键词", "tutorial", outline, "研究素材内容")
    assert "测试标题" in prompt
    assert "第一节" in prompt
    assert "研究素材内容" in prompt


def test_build_writer_prompt_external_tier():
    outline = {"titles": [{"style": "seo", "text": "标题"}], "sections": []}
    prompt = _build_writer_prompt("关键词", "product-launch", outline, "素材", tier="TIER_EXTERNAL")
    assert "外部产品文章" in prompt or "EXTERNAL" in prompt


def test_build_writer_prompt_short_research():
    outline = {"titles": [{"style": "seo", "text": "标题"}], "sections": []}
    prompt = _build_writer_prompt("关键词", "tutorial", outline, "短")
    assert "素材较少" in prompt


def test_extract_samples():
    note = "1. [A级|technique] 观点一\n2. [B级|principle] 观点二\n3. 其他内容"
    samples = _extract_samples(note)
    assert len(samples) == 2
    assert samples[0]["quality"] == "A"
    assert samples[0]["type"] == "technique"


def test_fix_terminology():
    assert "区块编辑器" in _fix_terminology("块编辑器很好用")
    assert "区块主题" in _fix_terminology("块主题很强大")
    assert "全站编辑" in _fix_terminology("Full Site Editing 是未来")
    assert "全站编辑" in _fix_terminology("FSE 改变了开发方式")
