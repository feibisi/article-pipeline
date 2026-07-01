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


def test_synthesis_output_structure():
    """测试 synthesis 输出结构（无 API 调用）"""
    print("\n=== 测试 SynthesisOutput 结构 ===\n")

    # 创建一个 mock 输出验证结构
    output = SynthesisOutput(
        core_judgment="这是一句话判断",
        evidence_for=[{"source": "书A", "claim": "观点1", "strength": 0.8}],
        evidence_against=[],
        conflicts=[],
        unique_claims=["独特观点1"],
        differentiation="比搜索结果多给读者独特视角",
        confidence=0.7,
    )

    assert output.core_judgment == "这是一句话判断"
    assert len(output.evidence_for) == 1
    assert output.confidence == 0.7
    assert 0 <= output.confidence <= 1
    print("✅ SynthesisOutput 结构正确")


def test_synthesis_with_mock():
    """测试 synthesis 在无 API key 时的降级行为"""
    print("\n=== 测试 run_synthesis 降级行为（无 API key）===\n")

    # 无 API key 时应该降级返回空结构
    result = run_synthesis({"annotations": []})

    assert isinstance(result, SynthesisOutput), f"返回类型错误: {type(result)}"
    # 无 API key 时所有字段应该为空或 0
    assert result.confidence == 0.0, f"无 API key 时 confidence 应该为 0: {result.confidence}"
    print("✅ 无 API key 时正确降级返回空 SynthesisOutput")


def test_material_density():
    """测试素材密度评估"""
    print("\n=== 测试 assess_material_density ===\n")

    for case in test_cases:
        density = assess_material_density(case["sources"])
        assert 0 <= density <= 1, f"{case['keyword']}: density 超出范围 [{density}]"
        print(f"✅ {case['keyword']}: density = {density:.2f}")
        # 打印密度评估详情
        annotations = case["sources"].get("annotations", [])
        articles = case["sources"].get("web_articles", [])
        has_conflicts = case["sources"].get("has_conflicts", False)
        print(f"   annotations: {len(annotations)}, articles: {len(articles)}, has_conflicts: {has_conflicts}")


def test_quality_gate():
    """测试质量门控逻辑"""
    print("\n=== 测试质量门控 ===\n")

    # MIN_CONFIDENCE 以下的素材应该返回空 SynthesisOutput
    # 这需要真实的 LLM 调用才能测试，这里只测试常量
    assert 0 <= MIN_CONFIDENCE <= 1, f"MIN_CONFIDENCE 应该在 0-1 之间: {MIN_CONFIDENCE}"
    print(f"✅ MIN_CONFIDENCE = {MIN_CONFIDENCE}")


if __name__ == "__main__":
    test_json_extraction()
    test_format_sources()
    test_synthesis_output_structure()
    test_synthesis_with_mock()
    test_material_density()
    test_quality_gate()
    print("\n=== 所有单元测试通过 ===")
    print("\n提示：要测试真实 LLM 调用，请设置 AP_DS_API_KEY 或 DEEPSEEK_API_KEY 环境变量")
