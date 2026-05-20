"""Outline generation — Ollama first, DeepSeek API fallback."""
import json
import requests
import yaml
import os


def _load_config():
    config_path = os.path.expanduser("~/.config/article-pipeline/config.yaml")
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


OUTLINE_PROMPT = """你是一位资深内容编辑。请为以下文章生成提纲。

## 术语规范
Block/块 → 必须用"区块"（不是"块"）。Block Editor → 区块编辑器。Block Theme → 区块主题。

## 关键词: {keyword}
## 分类: {category}
## 平台: {platform}

## 研究素材:
{research_note}

## 要求
生成一个结构化提纲，包含:

1. **标题候选**（3个）:
   - 标题A: 偏搜索友好（包含关键词，SEO 优化）
   - 标题B: 偏点击吸引力（引发好奇）
   - 标题C: 偏专业/技术感

2. **核心论点**（一句话）: 这篇文章想传达的最核心信息

3. **段落结构**（4-8个小标题 + 每段2-3句要点说明）

4. **素材引用清单**: 研究素材中哪些可以嵌入哪些段落

5. **SEO 元数据**:
   - 目标关键词（首要 + 2-3个次要）
   - meta description 草稿（120-160字）
   - 内链机会

请输出 JSON 格式（只输出 JSON，不要其他内容）:
{{
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
    "meta_description": "...",
    "internal_link_opportunities": ["..."]
  }}
}}

分类说明:
- wp-tech: WordPress/Web 技术教程，面向开发者
- book-knowledge: 书籍知识精华拆解，面向爱智求真的读者"""


def _try_ollama(prompt: str, ollama_url: str, model: str) -> dict:
    """Try generating via Ollama. Returns result dict or raises on error."""
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
    """Generate outline via DeepSeek Anthropic-compatible Messages API."""
    config = _load_config()
    ds = config.get("deepseek", {})
    base_url = ds.get("base_url", "https://api.deepseek.com/anthropic")
    model = ds.get("model", "deepseek-v4-pro")

    api_key = os.environ.get("AP_DS_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "no_api_key"}

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
                "max_tokens": 2048,
                "system": "你是一位资深内容编辑。请输出 JSON 格式的提纲。只输出 JSON，不要其他内容。",
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=120
        )
        resp.raise_for_status()
        data = resp.json()

        # Extract text from content blocks
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
            return {"error": "no_json_found", "raw": response_text[:500]}

    except (requests.RequestException, json.JSONDecodeError) as e:
        return {"error": str(e)}


def generate_outline(keyword: str, category: str, platform: str,
                     research_note: str) -> dict:
    """Generate an article outline. Tries Ollama first, falls back to API."""
    config = _load_config()

    prompt = OUTLINE_PROMPT.format(
        keyword=keyword,
        category=category,
        platform=platform,
        research_note=research_note[:2000]
    )

    # Try Ollama first
    ollama = config.get("ollama", {})
    ollama_url = ollama.get("base_url", "http://localhost:11434")
    model = ollama.get("outline_model", "gemma3:12b")

    try:
        return _try_ollama(prompt, ollama_url, model)
    except (requests.ConnectionError, requests.Timeout):
        pass  # fall through to API
    except requests.RequestException:
        pass  # fall through to API
    except json.JSONDecodeError:
        pass  # fall through to API

    # Fallback: DeepSeek API
    result = _try_api(prompt)
    if "error" not in result:
        return result

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
