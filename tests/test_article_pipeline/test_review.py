"""Tests for review module."""
import pytest
from article_pipeline.review import (
    check_facts,
    check_ai_patterns,
    check_word_count,
    check_format,
    run_self_review,
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
    assert "ai_check" in result
    assert "word_count" in result
    assert "format" in result
    assert "overall_pass" in result
