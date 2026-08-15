"""Outline generation — 基于 FrameworkOutput 的方法论驱动生成.

Phase 2 改造: 从 synthesis 的核心判断 + framework 的方法论结构生成 outline，
而非使用固定模板。
"""
from article_pipeline.config import load_config
import json
import requests
import yaml
import os
from typing import Optional

import logging
logger = logging.getLogger(__name__)


# 基于 FrameworkOutput 的 outline prompt
METHODOLOGY_DRIVEN_PROMPT = """你是一位资深内容编辑。任务：基于提供的核心判断和方法论结构，生成文章提纲。

## 核心判断（来自 Synthesis 层）
{core_judgment}

## 证据概览
### 支持判断的证据
{evidence_for}

### 反对或质疑的证据
{evidence_against}

### 素材间的矛盾
{conflicts}

### 独特主张（搜索结果找不到的）
{unique_claims}

## 方法论结构（来自 Framework 层）
方法名: {method_name}
方法论描述: {method_description}

### 结构要求
{structure_requirements}

## 审美约束（来自 Style 层）
{style_instructions}

## 语感参考（来自 Prosody 层）
{prosody_hint}

---

## 你的任务

基于以上信息生成 outline，要求：

1. **核心论点**：从 core_judgment 提炼，一句话说清你的判断

2. **段落结构**：严格遵循 methodology 结构要求
   - 每个段落的 heading 参考 structure 的 h2_title
   - 每个段落的 points 参考 structure 的 purpose 和展开方式
   - 每个 point 只能基于上面列出的证据（[E*] / [A*]）或核心判断。**不要在 point 里写上面没有的数字、百分比、版本号、价格、日期、产品名、人名。**
   - 某个段落没有证据支撑时，把它的 point 写成"需补充素材：<缺什么>"，不要用编造的细节填满

3. **差异化说明**（必填）：
   基于 unique_claims 和 conflicts，说明"这篇文章比搜索第一页的结果多给读者什么"。
   必须包含具体信息（书名/数据/场景/反效果/无人提及），少于20字或缺乏具体信息会被拒绝。

4. **标题候选**（3个）:
   - 标题A: 偏搜索友好（含关键词）
   - 标题B: 偏点击吸引力
   - 标题C: 偏专业/技术感
   标题必须暗含判断，不许用"全面指南""深度解析""入门教程"等后缀。

5. **素材引用清单**（material_map）: 每条给出 section_index、evidence_id（上面的 [E*]/[A*] 编号）、source（证据里的来源原文）、usage。
   只能引用上面真实出现过的编号和来源，不要新造来源名。没有可引用素材的段落不要出现在清单里。

6. **SEO 元数据**:
   - 目标关键词（首要 + 2-3个次要）
   - meta description 草稿（120-160字）

请输出 JSON 格式（只输出 JSON，不要其他内容）:
{{
  "core_argument": "...",
  "titles": [
      {{"style": "seo", "text": "..."}},
      {{"style": "clickbait", "text": "..."}},
      {{"style": "professional", "text": "..."}}
  ],
  "sections": [
      {{"heading": "...", "points": ["...", "..."], "purpose": "..."}}
  ],
  "material_map": [{{"section_index": 0, "evidence_id": "E1", "source": "...", "usage": "..."}}],
  "seo": {{
    "primary_keyword": "...",
    "secondary_keywords": ["...", "..."],
    "meta_description": "..."
  }},
  "differentiation": "必填。一句话描述'这篇文章比搜索第一页的结果多给读者什么'。必须包含具体信息（书名/数据/场景/反效果/无人提及），少于20字或缺乏具体信息会被拒绝。"
}}

## 品类特殊说明
{genre_specific_notes}
"""


def _format_framework_structure(structure: list[dict]) -> str:
    """将 framework structure 格式化为 LLM 可读的文本."""
    parts = []
    for i, sec in enumerate(structure):
        role = sec.get("role", "")
        purpose = sec.get("purpose", "")
        h2 = sec.get("h2_title", "")
        word_budget = sec.get("word_budget", "")
        pattern = sec.get("pattern", "")

        parts.append(f"### 段落 {i+1}: {role}")
        if h2:
            parts.append(f"H2 标题建议: {h2}")
        parts.append(f"目的: {purpose}")
        if pattern:
            parts.append(f"展开方式: {pattern}")
        if word_budget:
            parts.append(f"字数预算: {word_budget}")
        parts.append("")

    return "\n".join(parts)


def _format_evidence(evidence: list[dict], prefix: str = "E") -> str:
    """格式化证据列表，每条带稳定编号供 material_map 引用."""
    if not evidence:
        return "（无）"

    parts = []
    for i, e in enumerate(evidence[:5], 1):
        if not isinstance(e, dict):
            parts.append(f"- [{prefix}{i}] {e}")
            continue
        source = e.get("source", "未知来源")
        claim = e.get("claim", e.get("text", ""))
        strength = e.get("strength", "")
        parts.append(f"- [{prefix}{i}] {claim}（来源: {source}）")
        if strength:
            parts.append(f"  强度: {strength}")

    return "\n".join(parts)


def _get_genre_specific_notes(category: str) -> str:
    """获取品类特定的补充说明."""
    notes_map = {
        "tutorial": """
教程类特殊要求:
- 开头必须用具体场景或问题引入，不要用"X 是..."的定义开头
- 每个步骤后面必须有"不这样做会怎样"的说明
- 必须包含验证步骤
        """,
        "comparison": """
对比类特殊要求:
- 必须给出明确的推荐条件（"如果...则选..."）
- 对比维度要具体可测量，避免主观感受
- 避免"各有优劣"，必须给出倾向性建议
        """,
        "opinion": """
观点类特殊要求:
- 必须有明确立场，不许和稀泥
- 必须指出对立观点的具体错误
- 钩子要具体（数据/场景），不能是抽象陈述
        """,
        "beginner": """
新手类特殊要求:
- 开头必须用具体场景，不要概念定义
- 每次引入新组件都要说明"这是用来做什么的"
- 不要假设读者理解了上下文
        """,
        "troubleshooting": """
排查类特殊要求:
- 必须从问题场景开头
- 按诊断路径组织，不是按技术模块
- 每个解决方案要有验证方法
        """,
        "brand-marketing": """
品牌营销类特殊要求:
- 不是卖产品，是建认知
- 要指出行业盲点，建立"这帮人懂行"的印象
- 读者应该带走一个记忆点
        """,
        "soft-article": """
软文类特殊要求:
- 前三秒不能察觉是广告
- 技术路径要客观完整，不跳过竞争对手
- 产品只在结论占一小段
        """,
        "product-launch": """
产品发布类特殊要求:
- 钩子：之前做不到什么，今天开始不同了
- 用"之前 vs 之后"对比，不是功能列表
- 给具体获取路径
        """,
        "case-study": """
案例研究类特殊要求:
- 结果先行：优化前 X，现在 Y
- 要讲踩坑过程（试了什么，为什么失败）
- 提炼可复用的方法论
        """,
        "thought-leadership": """
思想领导力类特殊要求:
- 必须有立场，不许"取决于情况"
- 支撑判断至少两个独立来源
- 要指出大家都忽略的信号
        """,
        "editorial": """
社论类特殊要求:
- 对事件表态，立场要鲜明
- 指出对立观点的具体错误
- 可以得罪人，但要说清楚
        """,
        "announcement": """
公告类特殊要求:
- 什么变了（一行说清）
- 影响谁（列具体人群）
- 要做什么（具体行动路径）
- 什么时候生效
        """,
        "news": """
新闻类特殊要求:
- 事件概述（5W1H）
- 背景和影响
- 相关链接
        """,
    }
    return notes_map.get(category, "")


def _try_ollama(prompt: str, ollama_url: str, model: str) -> dict:
    """Try generating via Ollama，returns result dict or raises on error."""
    resp = requests.post(
        f"{ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 4096}
        },
        timeout=120
    )
    resp.raise_for_status()
    data = resp.json()
    response_text = data.get("response", "")
    json_start = response_text.find("{")
    json_end = response_text.rfind("}") + 1
    if json_start >= 0 and json_end > json_start:
        return json.loads(response_text[json_start:json_end])
    else:
        return {"error": "no_json_found", "raw": response_text[:500]}


def _try_api(prompt: str) -> dict:
    """Generate outline via API，tries primary (GLM/z.ai) then falls back to DeepSeek."""
    config = load_config()
    ds = config.get("deepseek", {})

    # 不回退到 ANTHROPIC_AUTH_TOKEN(Claude Code 运行时凭据),见 llm.get_api_key。
    api_key = (os.environ.get("AP_DS_API_KEY") or
               os.environ.get("DEEPSEEK_API_KEY") or
               os.environ.get("ANTHROPIC_API_KEY"))
    if not api_key:
        return {"error": "no_api_key"}

    # Try primary first, then fallback
    endpoints = [
        (ds.get("base_url", "https://api.z.ai/api/anthropic"),
         ds.get("model", "glm-5.1")),
        (ds.get("fallback_url", "https://api.deepseek.com/anthropic"),
         ds.get("fallback_model", "deepseek-v4-pro")),
    ]

    # Outline is a structured-extraction call, not creative writing: keep it cold.
    # Without this the request omits temperature and inherits the provider
    # default (~1.0), which is why outlines drift away from the evidence.
    temperature = ds.get("outline_temperature", 0.2)

    last_error = None
    for base_url, model in endpoints:
        if not base_url or not model:
            continue
        try:
            resp = requests.post(
                f"{base_url}/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "max_tokens": 4096,
                    "temperature": temperature,
                    "system": "你是一位资深内容编辑。请输出 JSON 格式的提纲。只输出 JSON，不要其他内容。",
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=120
            )
            resp.raise_for_status()
            data = resp.json()

            text_parts = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            response_text = "\n".join(text_parts)

            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response_text[json_start:json_end])
            else:
                last_error = {"error": "no_json_found", "raw": response_text[:500]}
                continue

        except (requests.RequestException, json.JSONDecodeError) as e:
            last_error = {"error": str(e)}
            continue

    return last_error or {"error": "all_endpoints_failed"}


def _validate_differentiation(outline: dict) -> None:
    """检查 differentiation 是否足够具体，不够则警告或抛出错误。"""
    differentiation = outline.get("differentiation", "")

    # 检查是否为空
    if not differentiation or not differentiation.strip():
        raise ValueError("differentiation 字段为空或缺失")

    differentiation = differentiation.strip()

    # 检查长度（少于 20 字拒绝）
    if len(differentiation) < 20:
        raise ValueError(f"differentiation 不够具体（少于20字）: {differentiation}")

    # 检查是否包含具体信息元素
    specificity_keywords = ["实测", "数据", "本书", "交叉", "对比", "场景",
                            "反效果", "无人", "官方", "书名", "案例", "实验",
                            "源码", "内部", "独家", "第一手", "原创"]
    if not any(kw in differentiation for kw in specificity_keywords):
        logger.warning(f"differentiation 缺乏具体信息元素: {differentiation}")

    # 检查是否是空洞词汇
    empty_phrases = ["详细介绍", "深入分析", "全面解析", "全面介绍",
                     "详细说明", "深度解读"]
    for phrase in empty_phrases:
        if phrase in differentiation.lower():
            raise ValueError(f"differentiation 包含空洞词汇: {differentiation}")


def _checked(outline: dict) -> dict:
    """Run the differentiation gate but report failure as an error dict.

    Raising here escaped past pipeline's per-stage retry logic and got caught by
    the run loop's blanket ``except Exception``, which marks the task *skipped*.
    A rejected differentiation is a retryable generation failure, not a dead task.
    """
    try:
        _validate_differentiation(outline)
    except ValueError as e:
        return {"error": "differentiation_rejected", "message": str(e)}
    return outline


def generate_outline_from_layers(
    keyword: str,
    category: str,
    platform: str,
    synthesis_output: dict,
    framework_output: dict,
    style_output: Optional[dict] = None,
    prosody_output: Optional[dict] = None,
) -> dict:
    """基于层级输出生成 outline（Phase 2 改造版）.

    Args:
        keyword: 关键词
        category: 品类
        platform: 平台
        synthesis_output: Synthesis 层输出（或兼容格式的 dict）
        framework_output: Framework 层输出（或兼容格式的 dict）
        style_output: Style 层输出（可选）
        prosody_output: Prosody 层输出（可选）

    Returns:
        outline dict（与旧格式兼容）
    """
    # 提取 synthesis 内容
    core_judgment = synthesis_output.get("core_judgment", "")
    evidence_for = _format_evidence(synthesis_output.get("evidence_for", []))
    evidence_against = _format_evidence(synthesis_output.get("evidence_against", []))
    conflicts_list = synthesis_output.get("conflicts", [])
    conflicts = "\n".join([
        f"- {c.get('source_a', '')} vs {c.get('source_b', '')}: {c.get('resolution', '')}"
        for c in conflicts_list
    ]) if conflicts_list else "（无矛盾）"
    unique_claims = "\n".join([
        f"- {uc}" for uc in synthesis_output.get("unique_claims", [])
    ]) if synthesis_output.get("unique_claims") else "（无独特主张）"

    # 提取 framework 内容
    method_name = framework_output.get("method", "generic")
    method_desc = framework_output.get("freeform_note", "")
    structure = framework_output.get("structure", [])
    structure_requirements = _format_framework_structure(structure)

    # 提取 style 内容
    style_instructions = ""
    if style_output:
        constraints = style_output.get("constraints", {})
        require = constraints.get("require", [])
        avoid = constraints.get("avoid", [])
        if require or avoid:
            style_instructions = "### 必须做到\n" + "\n".join([f"- {r}" for r in require])
            if avoid:
                style_instructions += "\n### 避免出现\n" + "\n".join([f"- {a}" for a in avoid])
    else:
        style_instructions = "（无特定约束）"

    # 提取 prosody 内容
    prosody_hint = ""
    if prosody_output:
        prosody_hint = prosody_output.get("rhythm_hint", "")
    else:
        prosody_hint = "（无特定语感要求）"

    # 品类特殊说明
    genre_specific = _get_genre_specific_notes(category)

    # 组装 prompt
    prompt = METHODOLOGY_DRIVEN_PROMPT.format(
        core_judgment=core_judgment or "（未提供核心判断）",
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        conflicts=conflicts,
        unique_claims=unique_claims,
        method_name=method_name,
        method_description=method_desc,
        structure_requirements=structure_requirements,
        style_instructions=style_instructions,
        prosody_hint=prosody_hint,
        genre_specific_notes=genre_specific,
    )

    # 尝试生成
    result = _try_api(prompt)
    if "error" not in result:
        return _checked(result)

    # Fallback: Ollama
    config = load_config()
    ollama = config.get("ollama", {})
    ollama_url = ollama.get("base_url", "http://localhost:11434")
    model = ollama.get("outline_model", "gemma3:12b")

    try:
        result = _try_ollama(prompt, ollama_url, model)
        if "error" not in result:
            return _checked(result)
        return result
    except (requests.ConnectionError, requests.Timeout, requests.RequestException, json.JSONDecodeError):
        pass

    return {"error": "all_providers_failed",
            "message": "Both Ollama and API failed to generate outline"}


def generate_outline(keyword: str, category: str, platform: str,
                     research_note: str) -> dict:
    """兼容旧接口的 outline 生成（回退到模板方式）.

    注意：新代码应使用 generate_outline_from_layers()。
    本函数仅为保持向后兼容而保留。
    """
    config = load_config()

    cat_lower = category.lower().strip() if category else ""
    tier_external_categories = {
        "product-launch", "announcement", "brand-marketing",
        "case-study", "tool-review", "resource-roundup",
        "soft-article", "marketing",
    }
    outline_char_limit = 4000 if cat_lower in tier_external_categories else 2000

    # 使用简化版模板（保留旧版逻辑）
    TEMPLATE_PROMPT = """你是一位资深内容编辑。任务：为以下关键词生成文章提纲。

## 关键词: {keyword}
## 分类: {category}
## 平台: {platform}

## 研究素材:
{research_note}

请输出 JSON 格式的 outline，包含：
- core_argument: 核心论点
- titles: 3 个标题候选
- sections: 段落结构
- material_map: 素材引用
- seo: SEO 元数据
- differentiation: 差异化说明（必填，20字以上，含具体信息）

{{
  "core_argument": "...",
  "titles": [{{"style": "seo", "text": "..."}}, ...],
  "sections": [{{"heading": "...", "points": ["..."]}}, ...],
  "material_map": [{{"section_index": 0, "source": "...", "usage": "..."}}],
  "seo": {{}}
  "differentiation": "..."
}}
"""

    prompt = TEMPLATE_PROMPT.format(
        keyword=keyword,
        category=category,
        platform=platform,
        research_note=research_note[:outline_char_limit]
    )

    result = _try_api(prompt)
    if "error" not in result:
        return _checked(result)

    ollama = config.get("ollama", {})
    ollama_url = ollama.get("base_url", "http://localhost:11434")
    model = ollama.get("outline_model", "gemma3:12b")

    try:
        result = _try_ollama(prompt, ollama_url, model)
        if "error" not in result:
            return _checked(result)
        return result
    except (requests.ConnectionError, requests.Timeout, requests.RequestException, json.JSONDecodeError):
        pass

    return {"error": "all_providers_failed",
            "message": "Both Ollama and API failed to generate outline"}


def format_outline_for_review(outline: dict) -> str:
    """Format the outline dict as readable markdown for human review."""
    if "error" in outline:
        return f"**提纲生成失败**: {outline.get('error', 'unknown')}\n\n{outline.get('message', outline.get('raw', ''))}"

    lines = ["## 提纲\n"]

    lines.append("### 标题候选")
    for i, t in enumerate(outline.get("titles", [])):
        lines.append(f"{i+1}. [{t.get('style', '')}] {t.get('text', '')}")

    lines.append(f"\n### 核心论点\n{outline.get('core_argument', 'N/A')}")

    # 差异化价值
    differentiation = outline.get('differentiation', '')
    if differentiation:
        lines.append(f"\n### 差异化价值\n{differentiation}")
    else:
        lines.append("\n### 差异化价值\n*（缺失）*")

    lines.append("\n### 段落结构")
    for i, sec in enumerate(outline.get("sections", [])):
        lines.append(f"\n**{i+1}. {sec.get('heading', '')}**")
        if sec.get('purpose'):
            lines.append(f"目的: {sec['purpose']}")
        for pt in sec.get("points", []):
            lines.append(f"  - {pt}")

    lines.append("\n### 素材引用")
    for item in outline.get("material_map", []):
        lines.append(f"- 段落 {item.get('section_index', '?')}: {item.get('source', '')} — {item.get('usage', '')}")

    lines.append("\n### SEO 元数据")
    seo = outline.get("seo", {})
    lines.append(f"- 首要关键词: {seo.get('primary_keyword', 'N/A')}")
    lines.append(f"- 次要关键词: {', '.join(seo.get('secondary_keywords', []))}")
    lines.append(f"- Meta: {seo.get('meta_description', 'N/A')}")

    return "\n".join(lines)


def test_differentiation_validation():
    """测试 differentiation 门控逻辑。"""
    # 合法案例（应该通过）
    valid_cases = [
        "基于 cocobook 3 本书的交叉对比，搜索结果都只引用了官方文档",
        "包含 elementary 实测的性能数据，搜索结果都是理论描述",
        "指出了官方推荐做法在特定场景下的反效果，无人提及",
        "通过源码分析发现了内部实现的 Bug，公开文档未记载",
    ]

    # 非法案例（应该抛出 ValueError）
    invalid_cases = [
        "",  # 空字符串
        "   ",  # 只有空白
        "本文提供了详细的介绍",  # 太泛
        "深入分析",  # 太短
        "a" * 19,  # 少于 20 字
    ]

    for case in valid_cases:
        try:
            _validate_differentiation({"differentiation": case})
            print(f"PASS: {case[:50]}...")
        except ValueError as e:
            print(f"FAIL (should pass): {case[:50]}... -> {e}")
            raise

    for case in invalid_cases:
        try:
            _validate_differentiation({"differentiation": case})
            print(f"FAIL (should raise): {case[:50]}...")
            raise AssertionError(f"Case should raise ValueError: {case}")
        except ValueError:
            print(f"PASS (raised): {case[:50]}...")

    print("\nAll differentiation validation tests passed!")


if __name__ == "__main__":
    test_differentiation_validation()
