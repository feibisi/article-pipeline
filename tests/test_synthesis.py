"""验证 synthesis 输出质量"""

import sys
sys.path.insert(0, '/home/parallels/Projects/article-pipeline')

from article_pipeline.synthesis import (
    run_synthesis,
    assess_material_density,
    _extract_json,
    _format_sources,
    MIN_CONFIDENCE,
)
from article_pipeline.contracts import SynthesisOutput

# 测试用例
test_cases = [
    {
        "keyword": "WordPress Object Cache",
        "sources": {
            "annotations": [
                {"source": "高性能WordPress", "claim": "Redis 是最常用的对象缓存方案"},
                {"source": "WordPress性能优化", "claim": "小站点用对象缓存可能是反优化"}
            ],
            "web_articles": ["文章1", "文章2"],
            "has_conflicts": True
        }
    },
    {
        "keyword": "WordPress区块编辑器",
        "sources": {
            "annotations": [
                {"source": "Gutenberg开发指南", "claim": "区块编辑器是未来方向"}
            ],
            "web_articles": [],
            "has_conflicts": False
        }
    },
    {
        "keyword": "WordPress REST API",
        "sources": {
            "annotations": [
                {"source": "REST API手册", "claim": "REST API支持所有内容类型"},
                {"source": "WP开发实战", "claim": "REST API性能优于admin-ajax"}
            ],
            "web_articles": ["文章1", "文章2", "文章3"],
            "has_conflicts": False
        }
    }
]


def test_json_extraction():
    """测试 JSON 提取函数"""
    print("\n=== 测试 _extract_json ===\n")

    # 纯 JSON
    text1 = '{"key": "value", "number": 42}'
    result1 = _extract_json(text1)
    assert result1 == {"key": "value", "number": 42}, f"纯 JSON 提取失败: {result1}"
    print("✅ 纯 JSON 提取")

    # ```json 块
    text2 = '```json\n{"key": "value", "number": 42}\n```'
    result2 = _extract_json(text2)
    assert result2 == {"key": "value", "number": 42}, f"```json 块提取失败: {result2}"
    print("✅ ```json 块提取")

    # ``` 块（无 json 标记）
    text3 = '```\n{"key": "value"}\n```'
    result3 = _extract_json(text3)
    assert result3 == {"key": "value"}, f"``` 块提取失败: {result3}"
    print("✅ ``` 块提取")

    # 混合文本
    text4 = '这是一些前置文本\n{"key": "value"}\n后置文本'
    result4 = _extract_json(text4)
    assert result4 == {"key": "value"}, f"混合文本提取失败: {result4}"
    print("✅ 混合文本提取")

    # 无效 JSON
    text5 = '这不是 JSON'
    result5 = _extract_json(text5)
    assert result5 is None, f"无效 JSON 应该返回 None: {result5}"
    print("✅ 无效 JSON 返回 None")


def test_format_sources():
    """测试素材格式化"""
    print("\n=== 测试 _format_sources ===\n")

    # 空素材
    result1 = _format_sources({})
    assert result1 == "无素材", f"空素材应该返回'无素材': {result1}"
    print("✅ 空素材处理")

    # 完整素材
    sources = {
        "annotations": [
            {"book": "高性能WordPress", "claim": "Redis 是最常用的对象缓存方案"}
        ],
        "ddg_results": [
            {"title": "WordPress缓存指南", "body": "对象缓存可以提升..."}
        ],
        "web_articles": [
            {"title": "深入理解Redis", "content": "Redis 是..."}
        ],
        "topic_paragraphs": [
            {"text": "对象缓存是 WordPress 性能优化的关键"}
        ]
    }
    result2 = _format_sources(sources)
    assert "书籍标注" in result2, "应该包含书籍标注部分"
    assert "搜索结果" in result2, "应该包含搜索结果部分"
    assert "完整文章" in result2, "应该包含完整文章部分"
    assert "Topic 索引" in result2, "应该包含 Topic 索引部分"
    assert "高性能WordPress" in result2, "应该包含书籍名"
    print("✅ 完整素材格式化")


# REMOVED test_synthesis_output_structure: it constructed a SynthesisOutput and
# asserted back the literals it had just passed in. No production code ran.
#
# REMOVED test_synthesis_with_mock: despite the name it mocked nothing. It called
# the real run_synthesis and asserted confidence == 0.0 — satisfied by *any*
# failure (no API key, network down, malformed JSON), and on a machine with
# AP_DS_API_KEY set it made a live billable call. Replaced below with a version
# that actually injects a fake LLM.
#
# REMOVED test_quality_gate: asserted only `0 <= MIN_CONFIDENCE <= 1`, i.e. that
# a constant is a probability. Its own docstring admitted it tested nothing.


def test_synthesis_degrades_on_llm_failure(monkeypatch):
    """A failed LLM call must degrade to an empty, low-confidence output.

    Injects the failure rather than relying on the ambient absence of an API key,
    so the test is deterministic and never makes a network call.
    """
    import article_pipeline.synthesis as S

    monkeypatch.setattr(S, "call_with_fallback",
                        lambda *a, **kw: {"error": "api_timeout", "message": "x"},
                        raising=False)
    result = S.run_synthesis({"annotations": [{"claim": "某个断言", "source": "书A"}]})

    assert isinstance(result, SynthesisOutput)
    assert result.confidence == 0.0
    assert result.core_judgment == ""
    assert result.unique_claims == []
    assert result.differentiation == ""


def test_material_density_discriminates_rich_from_empty():
    """Density must be *ordered*, not merely inside [0, 1].

    The previous assertion (`0 <= density <= 1`) is guaranteed by the `min(x, 1.0)`
    in synthesis.py and could never fail.
    """
    empty = assess_material_density({"annotations": [], "web_articles": []})
    rich = assess_material_density({
        "annotations": [{"claim": f"断言{i}"} for i in range(10)],
        "web_articles": [{"title": f"文章{i}"} for i in range(8)],
        "has_conflicts": True,
    })
    # NOTE: empty material scores 0.075, not 0 — synthesis.py:238 awards an
    # unconditional 0.3 to the "no conflicts" dimension even with zero sources,
    # so the floor is 0.3/4. Harmless today (still far below MIN_CONFIDENCE) but
    # asserted explicitly so the floor cannot silently drift upward into the
    # passing range.
    assert empty < 0.1, f"no material must score near 0, got {empty}"
    assert empty < MIN_CONFIDENCE, "empty material must never clear the gate"
    assert rich > empty
    assert rich >= MIN_CONFIDENCE, (
        f"a corpus this rich must clear the quality gate ({rich} < {MIN_CONFIDENCE})"
    )
    # Monotonic in annotation count.
    few = assess_material_density({"annotations": [{"claim": "一条"}]})
    many = assess_material_density({"annotations": [{"claim": f"第{i}条"} for i in range(6)]})
    assert many > few
