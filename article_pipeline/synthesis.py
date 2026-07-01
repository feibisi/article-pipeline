"""Article Pipeline Layer 1: SYNTHESIS（理解层）

从 research 原始素材中提取核心判断、证据结构、矛盾、独特性。
"""

import json
import re
from typing import Literal
from .contracts import SynthesisOutput
from .llm import call_with_fallback

# 默认使用 GLM-5.1（便宜，适合跑多次）
DEFAULT_MODEL = "glm-5.1"
FALLBACK_MODEL = "deepseek-5.1"

SYNTHESIS_PROMPT = """你是一位深度阅读分析师。任务：从以下素材中提炼核心判断。

# 素材来源
{sources}

# 你的任务
1. **core_judgment**（一句话）: 这组素材共同指向什么理解？如果有矛盾，指出矛盾的实质。
2. **evidence_for**: 支持判断的证据（来源 + claim + 强度 0-1）
3. **evidence_against**: 反对或质疑的证据
4. **conflicts**: 指出素材间的矛盾（来源A vs 来源B，各自主张，如何化解）
5. **unique_claims**: 哪些主张在主流搜索结果中找不到？（需标注）
6. **differentiation**: 比搜索第一页的结果，这组素材多给读者什么？
7. **confidence**: 0-1，你对判断的信心

# 输出格式（JSON，不要有其他内容）
{{
  "core_judgment": "...",
  "evidence_for": [...],
  "evidence_against": [...],
  "conflicts": [...],
  "unique_claims": [...],
  "differentiation": "...",
  "confidence": 0.7
}}
"""

MIN_CONFIDENCE = 0.4  # 低于此值标记为"无差异化空间"


def _format_sources(sources: dict) -> str:
    """将 research 输出格式化为 LLM 可读的文本。"""
    parts = []

    # cocobook 标注
    annotations = sources.get("annotations", [])
    if annotations:
        parts.append("## 书籍标注")
        for ann in annotations[:10]:  # 限制数量避免 token 爆炸
            parts.append(f"- {ann.get('book', '')}: {ann.get('claim', '')}")

    # DDG 搜索结果
    ddg_results = sources.get("ddg_results", [])
    if ddg_results:
        parts.append("## 搜索结果")
        for r in ddg_results[:10]:
            parts.append(f"- {r.get('title', '')}: {r.get('body', '')[:200]}")

    # Web 文章
    articles = sources.get("web_articles", [])
    if articles:
        parts.append("## 完整文章")
        for article in articles[:5]:
            parts.append(f"\n### {article.get('title', '')}\n{article.get('content', '')[:1000]}")

    # Topic 索引段落
    paragraphs = sources.get("topic_paragraphs", [])
    if paragraphs:
        parts.append("## Topic 索引")
        for p in paragraphs[:10]:
            parts.append(f"- {p.get('text', '')[:200]}")

    return "\n".join(parts) if parts else "无素材"


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON。处理常见格式问题。"""
    # 尝试直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json...``` 块
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 尝试提取 {...} 块
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _call_synthesis_llm(sources: dict, keyword: str = "") -> dict:
    """调用 LLM 生成综合分析。

    Args:
        sources: research 模块的输出
        keyword: 关键词（用于 prompt context）

    Returns:
        解析后的 JSON dict，或包含 error 键的 dict
    """
    sources_text = _format_sources(sources)
    user_prompt = SYNTHESIS_PROMPT.format(sources=sources_text)

    # 如果有 keyword，加到 prompt 前面帮助 LLM 聚焦
    if keyword:
        user_prompt = f"主题关键词：{keyword}\n\n" + user_prompt

    system_prompt = """你是深度阅读分析师。从素材中提炼核心判断，输出 JSON。

关键规则：
1. core_judgment 必须是一句话判断，不能模糊
2. evidence_for/against 必须包含来源信息
3. confidence < 0.4 说明素材不足，无法形成有效判断
4. unique_claims 是这组素材独有的，搜索第一页找不到的
5. 输出纯 JSON，不要有任何解释文字"""

    result = call_with_fallback(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=2048,
        temperature=0.3  # 低温度追求稳定
    )

    if "error" in result:
        return result

    # 提取 JSON
    parsed = _extract_json(result["content"])
    if parsed is None:
        return {"error": "json_parse_failed", "raw": result["content"]}

    return parsed


def run_synthesis(
    sources: dict,
    model: str = DEFAULT_MODEL,
    fallback_model: str = FALLBACK_MODEL,
) -> SynthesisOutput:
    """运行 synthesis 层，从素材中提取结构化理解。

    Args:
        sources: research 模块的输出（cocobook + DDG + 抓取内容）
        model: 主模型（当前未使用，使用 llm.py 的默认 fallback 链）
        fallback_model: 备选模型（同上）

    Returns:
        SynthesisOutput: 结构化理解

    Raises:
        ValueError: confidence < 0.4 时抛出（素材不足，无法形成判断）
    """
    result = _call_synthesis_llm(sources)

    # LLM 调用失败 → 降级返回基础结构
    if "error" in result:
        print(f"  [synthesis] LLM call failed: {result.get('message', result.get('error'))}")
        return SynthesisOutput(
            core_judgment="",
            evidence_for=[],
            evidence_against=[],
            conflicts=[],
            unique_claims=[],
            differentiation="",
            confidence=0.0,
        )

    # 质量门控：confidence < MIN_CONFIDENCE → 标记无差异化空间
    confidence = result.get("confidence", 0.0)
    if confidence < MIN_CONFIDENCE:
        print(f"  [synthesis] Low confidence ({confidence:.2f}), no differentiation space")
        return SynthesisOutput(
            core_judgment="",
            evidence_for=[],
            evidence_against=[],
            conflicts=[],
            unique_claims=[],
            differentiation="",
            confidence=confidence,
        )

    # 构建 SynthesisOutput
    return SynthesisOutput(
        core_judgment=result.get("core_judgment", ""),
        evidence_for=result.get("evidence_for", []),
        evidence_against=result.get("evidence_against", []),
        conflicts=result.get("conflicts", []),
        unique_claims=result.get("unique_claims", []),
        differentiation=result.get("differentiation", ""),
        confidence=confidence,
    )


def assess_material_density(sources: dict) -> float:
    """评估素材是否足够支撑有深度的文章。

    返回 0-1，低于 0.4 建议不写。

    检查项：
    - cocobook 标注数量 >= 3 来源
    - 有矛盾观点（说明有深度可挖）
    - web 文章全文抓取 >= 3 篇
    - topic 索引命中 >= 5 段
    """
    scores = []

    # cocobook 标注数量
    annotations = sources.get("annotations", [])
    scores.append(min(len(annotations) / 3, 1.0))

    # 有矛盾观点
    has_conflicts = sources.get("has_conflicts", False)
    scores.append(1.0 if has_conflicts else 0.3)

    # web 文章数量
    articles = sources.get("web_articles", [])
    scores.append(min(len(articles) / 3, 1.0))

    # topic 段落数量
    paragraphs = sources.get("topic_paragraphs", [])
    scores.append(min(len(paragraphs) / 5, 1.0))

    return sum(scores) / len(scores) if scores else 0.0


__all__ = ["run_synthesis", "assess_material_density", "SynthesisOutput", "_call_synthesis_llm"]
