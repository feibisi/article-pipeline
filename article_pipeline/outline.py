"""Outline generation，Ollama first then DeepSeek API fallback."""
from article_pipeline.config import load_config
import json
import requests
import yaml
import os

import logging
logger = logging.getLogger(__name__)



OUTLINE_PROMPT = """你是一位有观点、有立场的资深技术编辑。你的任务不是生成"关于X的介绍"，而是先想清楚你对这个话题的判断是什么，然后围绕这个判断搭建结构。

## 术语规范
Block/块 → 必须用"区块"（不是"块"）。Block Editor → 区块编辑器。Block Theme → 区块主题。

## 关键词: {keyword}
## 分类: {category}
## 平台: {platform}

## 研究素材:
{research_note}

## 第一步：根据文章类型先想清楚你要说什么

分类 "{category}" 对应以下类型：

### 搜索型（tutorial/guide/troubleshooting/comparison/beginner/tool-review/listicle/resource-roundup）
读者有明确问题，搜到你。直接给答案：
- 为什么这件事重要？（给具体后果——不这么做会怎样？做了会怎样？）
- 大多数人在这里的误解是什么？（没有误解，文章就没有存在的必要）
- 你的核心判断是什么？（不许说"取决于情况""各有优劣"。选一个立场。）
- 读这篇文章的人是谁？（具体处境+此刻痛点+想看什么）

### 相遇型
读者没在找你。先把他拉住，再给判断。所有相遇型必须有钩子。

**opinion/trend**: 给一个他没想过的角度。
- **钩子**：指出一个常见的错误认知或盲点。用具体数据或场景。
- 你的核心判断是什么？
- 读这篇文章的人是谁？

**marketing/brand-marketing**: 不是卖产品，是建认知。读者看完不买，但下次听到这个名字会觉得"这帮人懂行"。
- **钩子**：这个行业有一个大家都忽视的盲点。具体指出来。
- 为什么你关注这个盲点？（建立你说话的资格——不是因为你是专家，是因为你看到了具体的问题）
- 读完这篇文章，读者应该带走的一个记忆点是什么？

**soft-article（软文）**: 伪装成搜索型的技术文章或对比文，结论自然指向你的方案。读者不应该在前三秒察觉是广告。
- **钩子**：和搜索型一样——读者有真实问题，你认真回答。直到结论才揭晓你的产品是答案之一。
- 解决问题的技术路径（客观、完整，不跳过竞争对手的方案）
- 你的产品在这条路径的什么位置？（只占结论的一小段，不喧宾夺主）

**product-launch**: 告诉用户一件事改变了。
- **钩子**：之前他做不到什么（或很痛苦才能做到），今天开始不同了。
- 改了什么？（用之前 vs. 之后对比，不是功能列表）
- 怎么获取/开始？（具体路径）
- 下一步是什么？（路线图预告）

**case-study**: 让他觉得"这个我也能做到"。
- **钩子**：结果先行——优化前 X，现在 Y，中间经历了什么。
- 踩坑过程（试了什么，为什么失败，怎么想通的）
- 可复用的方法论（不只讲"这次做了什么"）

**thought-leadership（思想领导力）**: 对行业趋势发表有立场的判断。
- **钩子**：大家都说 X，但数据说的是另一回事。或：有一个信号所有人都忽略了。
- 你的核心判断（必须有立场，不许和稀泥）
- 支撑判断的数据/案例（至少两个独立来源）

**editorial（社论/评论）**: 对最近的事件/新闻表态，立场要鲜明。
- **钩子**：发生了什么事 + 为什么这件事不是表面看起来那么简单。
- 你的立场（哪怕得罪人也要说清楚）
- 为什么对立观点是错的（具体指出）

### 告知型（announcement/news）
读者在关注更新。直接说事：
- 什么变了？（一行说清）
- 影响谁？（列具体人群，不在影响的也说明）
- 要做什么？（给具体行动路径，不说"请联系客服"）
- 什么时候生效？

主张+读者（+钩子如果是相遇型），这些是整篇文章的锚。后面所有的结构、标题、素材引用都服务于它们。

## 第二步，用一句话说清楚读者的收获

写完上面的判断后，用一句话回答：

**读者读完这篇文章后，能用一句什么话转述给朋友？**

这句话必须：
- 具体到可以直接引用（不是"关于 X 的一些建议"）
- 包含一个判断或事实（不是"了解 X 的方方面面"）
- 让没读文章的人也觉得有价值（不是"如何安装 X"）

如果你写不出这句话，说明这个选题/角度不值得写。在 takeaway 字段写"SKIP: 无法提炼出有价值的一句话收获"。

## 第三步，围绕主张搭建结构

1. **主张**（从第一步来，3句话以内）

2. **标题候选**（3个）:
   - 标题A: 偏搜索友好
   - 标题B: 偏点击吸引力
   - 标题C: 偏专业/技术感
   标题必须暗含主张。不许用"全面指南""深度解析""入门教程"等后缀——如果你的主张够强，标题不需要这些词。

3. **段落结构**（4-8个小标题 + 每段2-3句要点说明）
   每段的存在理由是，它在论证主张的哪一部分？如果某段对论证主张没有贡献，删掉。

4. **素材引用清单**: 研究素材中哪些可以嵌入哪些段落

5. **SEO 元数据**:
   - 目标关键词（首要 + 2-3个次要）
   - meta description 草稿（120-160字）

请输出 JSON 格式（只输出 JSON，不要其他内容）:
{{
  "claim": {{
    "why_matters": "...",
    "common_misunderstanding": "...",
    "core_judgment": "..."
  }},
  "hook": "相遇型必填。一句话——具体场景或数字，不是抽象陈述。告知型和搜索型可省略。",
  "audience": "搜索型+相遇型必填。写清楚具体处境和此刻痛点，不要空泛标签。",
  "takeaway": "一句话读者收获。具体、可引用、含判断或事实。无法提炼时写 \\"SKIP: 无法提炼出有价值的一句话收获\\"。",
  "notification": {{
    "what_changed": "告知型必填。一行说清什么变了",
    "who_affected": "列具体人群，不在影响的也说明",
    "what_to_do": "给具体行动路径",
    "effective_date": "生效时间"
  }},
  "titles": [
    {{"style": "seo", "text": "..."}},
    {{"style": "clickbait", "text": "..."}},
    {{"style": "professional", "text": "..."}}
  ],
  "core_argument": "...",
  "sections": [
    {{"heading": "...", "points": ["...", "..."]}}
  ],
  "material_map": [{{"section_index": 0, "source": "...", "usage": "..."}}],
  "seo": {{
    "primary_keyword": "...",
    "secondary_keywords": ["...", "..."],
    "meta_description": "..."
  }},
  "differentiation": "必填。一句话描述'这篇文章比搜索第一页的结果多给读者什么'。必须包含具体信息（书名/数据/场景/反效果/无人提及），不能是泛泛而谈。示例：'基于 cocobook 3 本书的交叉对比，搜索结果都只引用了官方文档'；'包含 elementary 实测的性能数据，搜索结果都是理论描述'。少于20字或缺乏具体信息会被拒绝。"
}}

分类说明:
- wp-tech: WordPress/Web 技术教程，面向开发者
- book-knowledge: 书籍知识精华拆解，面向爱智求真的读者"""


def _try_ollama(prompt: str, ollama_url: str, model: str) -> dict:
    """Try generating via Ollama，returns result dict or raises on error."""
    resp = requests.post(
        f"{ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 2048}
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

    api_key = (os.environ.get("AP_DS_API_KEY") or
               os.environ.get("ANTHROPIC_API_KEY") or
               os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if not api_key:
        return {"error": "no_api_key"}

    # Try primary first, then fallback
    endpoints = [
        (ds.get("base_url", "https://api.z.ai/api/anthropic"),
         ds.get("model", "glm-5.1")),
        (ds.get("fallback_url", "https://api.deepseek.com/anthropic"),
         ds.get("fallback_model", "deepseek-v4-pro")),
    ]

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
        raise ValueError(f"differentiation 字段为空或缺失")

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
                     "详细说明", "深度解读", " comprehensive "]
    for phrase in empty_phrases:
        if phrase in differentiation.lower():
            raise ValueError(f"differentiation 包含空洞词汇: {differentiation}")


def generate_outline(keyword: str, category: str, platform: str,
                     research_note: str) -> dict:
    """Generate an article outline，tries Ollama first then falls back to API."""
    config = load_config()

    # TIER_EXTERNAL categories get more research context for outline generation
    cat_lower = category.lower().strip() if category else ""
    tier_external_categories = {
        "product-launch", "announcement", "brand-marketing",
        "case-study", "tool-review", "resource-roundup",
        "soft-article", "marketing",
    }
    outline_char_limit = 4000 if cat_lower in tier_external_categories else 2000

    prompt = OUTLINE_PROMPT.format(
        keyword=keyword,
        category=category,
        platform=platform,
        research_note=research_note[:outline_char_limit]
    )

    # Try DeepSeek API first (ANTHROPIC_AUTH_TOKEN configures Anthropic-compatible endpoint)
    result = _try_api(prompt)
    if "error" not in result:
        # 验证 differentiation 字段
        _validate_differentiation(result)
        return result

    # Fallback: Ollama
    ollama = config.get("ollama", {})
    ollama_url = ollama.get("base_url", "http://localhost:11434")
    model = ollama.get("outline_model", "gemma3:12b")

    try:
        result = _try_ollama(prompt, ollama_url, model)
        # 验证 differentiation 字段
        if "error" not in result:
            _validate_differentiation(result)
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
    lines.append(f"- 内链机会: {', '.join(seo.get('internal_link_opportunities', []))}")

    return "\n".join(lines)


def test_differentiation_validation():
    """测试 differentiation 门控逻辑。"""
    import pytest

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
