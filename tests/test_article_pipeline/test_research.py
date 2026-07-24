"""Tests for research module."""
import pytest
from article_pipeline.research import (
    search_cocobook,
    build_research_note,
    strip_ai_patterns,
)


@pytest.mark.network
def test_search_cocobook_returns_list():
    """cocobook search returns a list of results.

    Marked `network`: this does live MCP/SSH I/O and was one of the two tests
    that made `pytest tests` hang indefinitely. It is also nearly powerless —
    `isinstance(results, list)` passes when every backend is down and the
    function returns `[]`, i.e. it goes green precisely when retrieval is
    broken. Kept as an opt-in smoke test with a real assertion.
    """
    results = search_cocobook("设计模式")
    assert isinstance(results, list)
    assert results, "live cocobook search returned nothing for a common term"


def test_search_cocobook_empty_query():
    """Empty query returns empty list."""
    results = search_cocobook("")
    assert results == []


def test_build_research_note_structure():
    """Research note has required sections."""
    sources = {
        "cocobook": [{"title": "测试书", "claim": "一个观点"}],
        "web": [{"title": "测试文章", "url": "https://example.com"}],
        "code": [],
        "vm_consult": [],
    }
    note = build_research_note("测试关键词", sources)
    assert "## 研究笔记" in note
    assert "测试关键词" in note
    assert "测试书" in note
    assert "测试文章" in note


def test_build_research_note_truncation():
    """Research note is truncated when content exceeds 8000 chars."""
    sources = {
        "cocobook": [{"title": f"书{i}", "author": f"作者{i}",
                       "claim": "观点内容" * 120, "type": "principle",
                       "_source": "annotations"} for i in range(100)],
        "annotations": [{"book": f"书{i}", "author": f"作者{i}",
                          "type": "principle", "claim": "观点" * 150,
                          "context": "上下文" * 50} for i in range(30)],
        "web": [{"title": f"文章{i}", "url": f"https://example.com/{i}",
                  "snippet": "内容" * 200} for i in range(40)],
        "code": [],
        "vm_consult": [],
    }
    note = build_research_note("关键词", sources)
    assert len(note) < 9000
    assert "[... 已截断" in note


def test_strip_ai_patterns():
    """strip_ai_patterns removes known AI template phrases."""
    text = "在当今数字化时代，WordPress 是很好的选择。首先，我们来看看。"
    cleaned = strip_ai_patterns(text)
    assert "在当今数字化时代" not in cleaned
    assert "首先" not in cleaned
