"""Research module — gather materials from cocobook, web, code, and VM peers."""
from article_pipeline.config import load_config
import subprocess
import json
import re
import os
import sqlite3
import requests
import yaml
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ResearchOutput:
    """Structured research output with unique claims detection."""
    keyword: str  # Search keyword
    sources: dict  # Raw sources from gather_research()
    research_note: str  # Compiled research note
    unique_claims: list[str] = field(default_factory=list)  # DDG 前 10 结果中找不到的 claim


AI_PATTERNS = [
    r"在当今数字化的?时代",
    r"随着.{1,6}的(?:发展|进步|普及)",
    r"首先.{0,10}其次.{0,10}最后",
    r"首先[,，]?",
    r"总而言之",
    r"综上所述",
    r"不仅如此.{0,10}而且",
]

CONTENT_FARMS = frozenset({
    "csdn.net", "blog.csdn.net",
    "51cto.com", "blog.51cto.com",
    "juejin.cn", "juejin.im",
    "jianshu.com", "www.jianshu.com",
    "baijiahao.baidu.com",
    "toutiao.com",
    "zhihu.com", "www.zhihu.com",
    "segmentfault.com",
    "cnblogs.com", "www.cnblogs.com",
})



# MCP endpoint — cocobook v5 on huawei-pc (SSE transport, JSON-RPC 2.0 over /message)
MCP_BASE = load_config().get("mcp", {}).get("base_url", "http://192.168.1.230:8087")

# All available technical topic indexes (wenpai built, 2026-05-21 ~ 05-24)
ALL_TOPICS = {
    "wordpress-developer-docs": "8.3K chunks — plugins, hooks, REST API, WP-CLI",
    "wordpress-theme-development": "13.6K chunks — FSE, blocks, theme.json",
    "php-manual": "9.2K chunks — PHP language reference",
    "nginx-docs": "7.8K chunks — configuration, performance, reverse proxy",
    "docker-docs": "9.8K chunks — containers, compose, networking, volumes",
}

# Topic routing: pick relevant topics based on keyword signals (avoid scanning all 5 every time)
TOPIC_ROUTES = {
    "wordpress": ["wordpress-developer-docs", "wordpress-theme-development", "php-manual"],
    "wp": ["wordpress-developer-docs", "wordpress-theme-development", "php-manual"],
    "nginx": ["nginx-docs"],
    "docker": ["docker-docs", "nginx-docs"],
    "容器": ["docker-docs"],
    "php": ["php-manual"],
    "插件": ["wordpress-developer-docs", "php-manual"],
    "主题": ["wordpress-theme-development"],
    "服务器": ["nginx-docs", "docker-docs"],
    "部署": ["docker-docs", "nginx-docs"],
    "缓存": ["nginx-docs", "wordpress-developer-docs"],
    "代理": ["nginx-docs"],
    "负载": ["nginx-docs"],
}

def _route_topics(keyword: str) -> list[str]:
    """Select relevant topic indexes based on keyword signals."""
    kw = keyword.lower()
    selected = set()
    for signal, topics in TOPIC_ROUTES.items():
        if signal in kw:
            for t in topics:
                selected.add(t)
    if not selected:
        # Fallback: search all 3 WP topics
        selected = {"wordpress-developer-docs", "wordpress-theme-development", "php-manual"}
    return list(selected)[:4]

# Writing craft topic — universal Chinese prose style reference (wenpai built, 2026-05-23)
WRITING_CRAFT_TOPIC = "chinese-writing"


# ---- MCP client ----

def _mcp_call(tool_name: str, arguments: dict, timeout: int = 30) -> dict | None:
    """Call cocobook MCP via JSON-RPC 2.0 over /message endpoint."""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments}
        }
        resp = requests.post(
            f"{MCP_BASE}/message",
            json=payload,
            timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        if "result" in data and "content" in data["result"]:
            text = data["result"]["content"][0]["text"]
            return json.loads(text) if isinstance(text, str) else text
        return None
    except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError):
        return None


# ---- Search channels ----

# Sources that respond fast (<5s even on cold start)
_MCP_FAST_SOURCES = ["books", "wikidata", "topic"]


# Fast sources that don't crash MCP — AA is slow (180s) and books large
_MCP_SAFE_SOURCES = ["books", "annotations", "topic", "zim"]


def _search_cocobook_mcp(query: str, limit: int = 5) -> list[dict]:
    """Search via cocobook MCP v5. Queries safe sources individually to avoid BUS crash."""
    combined = []
    for src in _MCP_SAFE_SOURCES:
        r = _mcp_call("cocobook_search",
                      {"query": query, "source": src, "limit": limit},
                      timeout=25)
        if not r:
            continue
        # Response format: {"books": [...], "anna": [...], "zim": [...], ...}
        # AA results come under "anna" key (not "aa")
        src_keys = [src, "anna"] if src == "aa" else [src]
        for key in src_keys:
            items = r.get(key, [])
            if not isinstance(items, list):
                continue
            for item in items:
                item["_source"] = key
                if "title" not in item and "label" in item:
                    item["title"] = item["label"]
                combined.append(item)
        if len(combined) >= limit * 2:
            break

    if not combined:
        return []

    # Deduplicate by title
    seen = set()
    deduped = []
    for item in combined:
        key = (item.get("title", "") or item.get("claim", ""))[:80]
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)
    deduped.sort(key=lambda x: x.get("score", 0), reverse=True)
    deduped = [r for r in deduped if _is_relevant(r, query)]
    return deduped[:limit]


def _search_cocobook_topic(topic: str, query: str, limit: int = 5) -> list[dict]:
    """Search a cocobook topic index for original document paragraphs."""
    result = _mcp_call("cocobook_topic_search",
                       {"topic": topic, "query": query, "top_k": limit})
    if not result:
        return []

    results = []
    for item in result.get("results", []):
        item["_source"] = f"topic:{topic}"
        item["snippet"] = item.get("text", "")[:300]
        results.append(item)
    return results[:limit]


def _search_cocobook_ssh(query: str, limit: int = 5) -> list[dict]:
    """Search via SSH Tantivy on kk-pc (fallback when MCP is down)."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             "kk-pc", f"wsl python3 /mnt/c/Users/feibisi-BH-PC/tantivy_search.py '{query}' {limit}"],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode != 0:
            return []
        items = json.loads(result.stdout) if result.stdout.strip() else []
        for item in items:
            item["_source"] = "aa"
        return items
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return []


def search_cocobook(query: str, limit: int = 5) -> list[dict]:
    """Search cocobook — MCP first, SSH Tantivy fallback."""
    if not query.strip():
        return []

    results = _search_cocobook_mcp(query, limit)
    if not results:
        results = _search_cocobook_ssh(query, limit)
    return results


ANNOTATIONS_DB = "/mnt/shared-context/cocobook/cocobook-annotations.db"

# Genre → claim_type mapping for targeted annotation search
GENRE_CLAIM_TYPES = {
    "tutorial": ["technique", "principle"],
    "guide": ["technique", "warning"],
    "troubleshooting": ["warning", "technique"],
    "opinion": ["principle", "warning"],
    "comparison": ["framework", "data"],
    "case-study": ["case", "warning"],
    "trend": ["data", "framework"],
    "listicle": ["technique", "data"],
    "beginner": ["technique", "principle"],
    "tool-review": ["framework", "technique"],
    "resource-roundup": ["technique", "data"],
    "marketing": ["principle", "case"],
    "product-launch": ["framework", "data"],
    "announcement": ["principle"],
    "news": ["data", "principle"],
}


ANNOTATIONS_LANCE = "~/docs/ai-context/cocobook-annotations.lance"
OLLAMA_EMBED_URL = "http://10.211.55.2:11434"


def _get_embedding(text: str) -> list[float] | None:
    """Get bge-m3 embedding from Mac Ollama."""
    try:
        resp = requests.post(
            f"{OLLAMA_EMBED_URL}/api/embeddings",
            json={"model": "bge-m3:latest", "prompt": text[:512]},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()["embedding"]
    except (requests.RequestException, KeyError):
        return None


def _search_annotations(keyword: str, category: str, limit: int = 6) -> list[dict]:
    """Search cocobook annotations via LanceDB vector search. Falls back to SQLite."""
    genre_types = GENRE_CLAIM_TYPES.get(category, ["technique", "principle"])
    # Always include principle/technique as fallback (80% of annotations)
    claim_types = list(set(genre_types) | {"principle", "technique"})

    # Primary: MCP cocobook_recommend (Qwen3 semantic + BM25 hybrid on huawei-pc)
    try:
        r = _mcp_call("cocobook_recommend",
                      {"description": keyword, "role": "elementary", "limit": limit * 2},
                      timeout=20)
        if r and isinstance(r, dict):
            items = r.get("recommendations", [])
            formatted = []
            for item in items:
                ct = item.get("claim_type", item.get("type", "principle"))
                if ct in claim_types:
                    formatted.append({
                        "book": item.get("book_title", item.get("book", "")),
                        "author": item.get("author", ""),
                        "type": ct,
                        "claim": item.get("claim", ""),
                        "context": item.get("context", ""),
                        "_source": "annotations",
                    })
                if len(formatted) >= limit:
                    break
            if formatted:
                return formatted
    except Exception:
        pass

    # Fallback: SQLite keyword search
    db_path = Path(ANNOTATIONS_DB).expanduser()
    if not db_path.exists():
        return []

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        kw = keyword[:30]
        terms = "%" + kw.replace(" ", "%").replace("，", "%").replace("的", "%") + "%"
        placeholders = ", ".join(["?"] * len(claim_types))
        query = f"""SELECT book_title, author, claim_type, quality,
                           substr(claim, 1, 300) as claim_text,
                           substr(context, 1, 200) as context_text
                    FROM annotations
                    WHERE claim_type IN ({placeholders})
                      AND (claim LIKE ? OR book_title LIKE ?)
                    ORDER BY RANDOM()
                    LIMIT ?"""
        rows = conn.execute(query, (*claim_types, terms, terms, limit)).fetchall()
        conn.close()

        results = []
        for r in rows:
            results.append({
                "book": r["book_title"] or "",
                "author": r["author"] or "",
                "type": r["claim_type"],
                "claim": r["claim_text"],
                "context": r["context_text"] or "",
                "_source": "annotations",
            })
        return results
    except sqlite3.Error:
        return []


def extract_unique_claims(cocobook_annotations: list, ddg_results: list[dict]) -> list[str]:
    """从 cocobook 标注中提取 unique claims。

    逻辑：
    1. cocobook_annotations 是从 cocobook MCP 返回的标注列表
    2. ddg_results 是 DDG 搜索返回的前 10 个结果的摘要/标题
    3. 对每个 annotation claim，检查是否在 ddg_results 中出现
    4. 未出现 → 加入 unique_claims

    简单实现：用 claim 关键词匹配 ddg_results，如果无重叠则认为 unique
    """
    if not cocobook_annotations:
        return []

    # 构建 DDG 搜索结果的文本语料库（用于关键词匹配）
    ddg_corpus = ""
    for item in ddg_results[:10]:
        ddg_corpus += item.get("title", "") + " "
        ddg_corpus += item.get("snippet", "") + " "
    ddg_corpus = ddg_corpus.lower()

    unique_claims = []

    for annotation in cocobook_annotations:
        claim = annotation.get("claim", "")
        if not claim:
            continue

        # 提取 claim 中的关键词（中文和英文单词）
        # 简单策略：取 claim 中的关键实词，跳过常见的停用词
        claim_lower = claim.lower()

        # 停用词列表（常见的无意义词）
        stopwords = {
            "的", "了", "是", "在", "和", "与", "或", "但", "而", "就", "都", "也", "还",
            "这", "那", "这个", "那个", "这些", "那些", "什么", "怎么", "如何", "为什么",
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "and", "or", "but", "if", "then", "than", "so", "such", "as", "at", "by", "for",
            "from", "in", "into", "of", "on", "to", "with", "about", "into", "onto"
        }

        # 分词（简单的按空格和常见中文分词符号）
        words = re.findall(r'[一-鿿]+|[a-zA-Z]+', claim_lower)
        keywords = [w for w in words if len(w) > 1 and w not in stopwords]

        if not keywords:
            # 没有有效关键词，保守地认为不 unique
            continue

        # 检查关键词是否在 DDG 结果中出现
        # 如果核心关键词（至少 2 个）都不在 DDG 中，认为 unique
        matched_keywords = sum(1 for kw in keywords if kw in ddg_corpus)

        # 判断标准：匹配的关键词少于 30%，认为是独特观点
        if matched_keywords / len(keywords) < 0.3:
            unique_claims.append(claim.strip())

    return unique_claims[:10]  # 最多返回 10 条 unique claims


def get_writing_samples(keyword: str, limit: int = 5) -> list[dict]:
    """Get high-quality cocobook annotations as writing style reference."""
    return _search_annotations(keyword, "principle", limit)


def _clean_title(title: str) -> str:
    """Strip domain names and noise from web article titles."""
    # Remove " — SiteName" and " | SiteName" suffixes
    title = re.sub(r'\s*[—|｜]\s*[a-zA-Z0-9][-a-zA-Z0-9]*(?:\.[a-zA-Z]{2,})+(?:\s*\S*)?$', '', title)
    # Remove leading domain patterns
    title = re.sub(r'^[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}\s*[—|｜]\s*', '', title)
    return title.strip()


def _is_content_farm(url: str) -> bool:
    """Check if URL belongs to a blocked content farm."""
    try:
        host = urlparse(url).hostname or ""
        return host in CONTENT_FARMS or any(
            host.endswith("." + d) for d in CONTENT_FARMS if "." in d
        )
    except Exception:
        return False


def search_web(query: str, limit: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo. Filters out content farms."""
    if not query.strip():
        return []

    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=limit * 3):
                url = r.get("href", "")
                if _is_content_farm(url):
                    continue
                results.append({
                    "title": _clean_title(r.get("title", "")),
                    "url": url,
                    "snippet": r.get("body", "")
                })
                if len(results) >= limit:
                    break
        return results
    except Exception:
        return []


def _fetch_article_text(url: str, max_chars: int = 3000, timeout: int = 15) -> str:
    """Fetch and extract readable text from a URL. Returns first max_chars of content."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ArticlePipeline/1.0)"},
            timeout=timeout,
        )
        resp.raise_for_status()
        html = resp.text

        # Strip scripts, styles, nav, header, footer
        html = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", html)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Decode HTML entities
        import html as html_mod
        text = html_mod.unescape(text)
        return text[:max_chars]
    except Exception:
        return ""


def _generate_web_queries(keyword: str, category: str) -> list[str]:
    """Generate multiple search queries from different angles for better coverage."""
    queries = [keyword]

    # Domain-specific term tables — WP terms extracted from writer glossary at import time
    _CN_EN: dict[str, str] = {
        # WP terminology (from WP_GLOSSARY)
        "仪表盘": "dashboard", "工具栏": "toolbar admin bar",
        "小工具": "widget", "边栏": "sidebar", "菜单": "menu",
        "站点编辑器": "site editor", "区块编辑器": "block editor Gutenberg",
        "区块": "block", "区块模式": "pattern", "模板": "template",
        "模板部件": "template part", "可复用区块": "reusable block",
        "全站编辑": "full site editing FSE",
        "查询循环": "query loop", "组块": "group block",
        "导航区块": "navigation block", "文章摘要": "post excerpt",
        "特色图片": "featured image", "封面": "cover",
        "自定义文章类型": "custom post type", "分类法": "taxonomy",
        "分类": "category", "标签": "tag",
        "固定链接": "permalink", "缩略名": "slug",
        "插件": "plugin", "主题": "theme", "钩子": "hook",
        "动作": "action", "过滤器": "filter", "短代码": "shortcode",
        "计划任务": "cron", "临时缓存": "transient",
        "多站点": "multisite", "子主题": "child theme", "父主题": "parent theme",
        "自定义器": "customizer", "站点健康": "site health",
        # General tech terms
        "性能": "performance", "优化": "optimization",
        "生产环境": "production", "生产使用": "production ready",
        "开发": "development", "部署": "deployment",
        "安全": "security", "数据库": "database",
        "缓存": "cache caching", "错误": "error fix",
        "教程": "tutorial guide", "入门": "beginner getting started",
        "实战": "practical hands-on", "最佳实践": "best practices",
        "问题": "problems issues", "限制": "limitations",
        "对比": "comparison vs", "选择": "choose select",
        "配置": "configuration setup", "安装": "install setup",
        "升级": "upgrade update", "迁移": "migration migrate",
        # Content/marketing terms
        "营销": "marketing", "品牌": "brand",
        "用户体验": "user experience UX",
        "转化率": "conversion rate",
        "流量": "traffic", "增长": "growth",
        "评测": "review", "推荐": "recommendation",
        "案例": "case study", "数据": "data statistics",
        "趋势": "trend", "分析": "analysis",
    }

    # Build English query by translating Chinese terms found in keyword
    en_parts = []
    for cn, en in sorted(_CN_EN.items(), key=lambda x: -len(x[0])):
        if cn in keyword:
            en_parts.append(en)
    # Keep terms already in English
    for word in keyword.split():
        if re.match(r'^[a-zA-Z]', word) and word.lower() not in " ".join(en_parts).lower():
            en_parts.append(word)
    if en_parts:
        queries.append(" ".join(en_parts[:6]))

    # Category-specific angle query
    category_angles = {
        "opinion": "problems limitations issues",
        "tutorial": "step by step guide how to",
        "comparison": "comparison vs alternative",
        "troubleshooting": "fix error solution",
        "guide": "best practices guide",
        "trend": "2026 statistics data report",
        "news": "announcement update 2026",
        "tool-review": "review pros cons",
        "case-study": "case study real world example",
        "beginner": "beginner getting started tutorial",
    }
    angle = category_angles.get(category)
    if angle:
        queries.append(keyword + " " + angle)

    return queries[:3]



def search_codebase(keyword: str, search_paths: list[str] | None = None) -> list[dict]:
    """Search local codebase for relevant files."""
    if search_paths is None:
        search_paths = [os.path.expanduser("~/play")]

    results = []
    for path in search_paths:
        if not os.path.isdir(path):
            continue
        try:
            proc = subprocess.run(
                ["grep", "-rli", "--include=*.php", "--include=*.js",
                 "--include=*.json", "--include=*.md",
                 keyword, path],
                capture_output=True, text=True, timeout=10
            )
            for line in proc.stdout.strip().split("\n")[:5]:
                if line:
                    results.append({"file": line, "keyword": keyword})
        except subprocess.TimeoutExpired:
            pass
    return results


def consult_vm(question: str, vm: str) -> str | None:
    """Send a question to a peer VM via NATS vm-ask."""
    try:
        result = subprocess.run(
            ["vm-ask", vm, question],
            capture_output=True, text=True, timeout=60
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


# ---- Research note builder ----

# Wikidata entities that are commonly confused with WordPress concepts
IRRELEVANT_WIKIDATA = {
    'gutenberg', 'johannes gutenberg', 'project gutenberg',
    'elementor',  # "Elementor" is also a chemical element brand, etc.
}


def _is_relevant(item: dict, keyword: str) -> bool:
    """Filter out Wikidata noise that matches keywords but is wrong domain."""
    source = item.get('_source', '')
    title = (item.get('title', '') or '').lower()
    desc = (item.get('description', '') or '').lower()

    if source == 'wikidata':
        # Check if this is a known off-topic entity
        for noise in IRRELEVANT_WIKIDATA:
            if noise in title and 'wordpress' not in title and 'wordpress' not in desc:
                return False

    return True


def _extract_data_points(sources: dict) -> list[str]:
    """Extract concrete data points, claims, and stats from all sources."""
    points = []
    for item in sources.get("cocobook", [])[:8]:
        source = item.get("_source", "")
        title = item.get("title", "")
        author = item.get("author", "")
        claim = item.get("claim", item.get("snippet", ""))
        claim_type = item.get("type", "")

        if source == "annotations" and claim:
            type_tag = f"[{claim_type}]" if claim_type else ""
            points.append(f"洞见{type_tag}: {claim} (来源: {title})")
        elif source == "books" and title:
            author_str = f" ({author})" if author else ""
            points.append(f"书籍: 《{title}》{author_str}")
        elif source == "wikidata" and title:
            desc = item.get("description", "")
            points.append(f"维基: {title} — {desc}"[:200])
        elif title:
            points.append(f"参考: {title}")

    # Extract factual sentences from web snippets
    for item in sources.get("web", [])[:8]:
        snippet = item.get("snippet", "")
        title = item.get("title", "")
        # Sentences with numbers/percentages/dates
        num_sentences = re.findall(r"[^。.!！?？\n]*(?:\d+[%％倍亿万千]|\d{4}年)[^。.!！?？\n]*[。.]", snippet)
        for s in num_sentences[:3]:
            if len(s) > 10:
                points.append(f"数据: {s.strip()} (来源: {title})")

    for item in sources.get("code", [])[:3]:
        points.append(f"代码: {item.get('file', '')}")

    return points


def build_research_note(keyword: str, sources: dict) -> str:
    """Compile research sources into a dense, structured research note."""
    sections = [f"## 研究笔记: {keyword}\n"]

    # Topic paragraphs first — original document text, best writing reference
    topic_paragraphs = sources.get("topic_paragraphs", [])
    if topic_paragraphs:
        sections.append("### 原文范本（官方文档原文段落，这是最高质量的写作参考）")
        for i, p in enumerate(topic_paragraphs[:8], 1):
            topic_name = p.get("topic", p.get("_source", ""))
            section = p.get("section", "")
            text = p.get("snippet", p.get("text", ""))[:300]
            label = f"[{section}]" if section else ""
            sections.append(f"{i}. {label} {text}")

    # Writing craft paragraphs — Chinese prose style from classic writing books
    writing_craft = sources.get("writing_craft", [])
    if writing_craft:
        sections.append("\n### 写作范本（来自中文写作经典原文段落，学习这些文字的节奏和表达方式）")
        for i, p in enumerate(writing_craft[:6], 1):
            book = p.get("title", "")
            section_title = p.get("section", "")
            text = p.get("snippet", p.get("text", ""))[:300]
            label = f"[{book}]" if book else ""
            if section_title:
                label = f"[{book} — {section_title}]"
            sections.append(f"{i}. {label} {text}")

    # Writing samples — cocobook annotations as fallback style reference
    writing_samples = sources.get("writing_samples", [])
    if writing_samples:
        if not topic_paragraphs and not writing_craft:
            sections.append("### 写作范本（人类编辑的真实文字，模仿这种写法和语感）")
        else:
            sections.append("### 标注范本（人类编辑的补充观点）")
        for i, s in enumerate(writing_samples[:5], 1):
            quality = s.get("quality", "")
            claim_type = s.get("type", "")
            sections.append(f"{i}. [{quality}级|{claim_type}] {s.get('claim', '')}")

    data_points = _extract_data_points(sources)
    if data_points:
        sections.append("\n### 关键素材")
        for pt in data_points[:15]:
            sections.append(f"- {pt}")

    # Group cocobook results by source type
    coco_items = sources.get("cocobook", [])
    annotations = [i for i in coco_items if i.get("_source") == "annotations"]
    books = [i for i in coco_items if i.get("_source") == "books"]
    wikidata = [i for i in coco_items if i.get("_source") == "wikidata"]

    if annotations:
        sections.append(f"\n### 知识标注 ({len(annotations)}条)")
        for item in annotations[:5]:
            quality = item.get("quality", "")
            applicable = item.get("applicable_to", "")
            sections.append(f"- [{quality}] {item.get('claim', '')[:200]}")
            if applicable:
                sections.append(f"  适用: {applicable}")

    # New annotation source — genre-matched claims from cocobook annotations DB
    new_annotations = sources.get("annotations", [])
    if new_annotations:
        sections.append(f"\n### 相关观点（来自 {len(new_annotations)} 本书的标注）")
        for item in new_annotations[:5]:
            btype = item.get("type", "")
            book = item.get("book", "")[:30]
            author = item.get("author", "")
            claim = item.get("claim", "")[:200]
            context = item.get("context", "")[:100]
            sections.append(f"- [{btype} | {book} — {author}] {claim}")
            if context:
                sections.append(f"  上下文: {context}")

    if books:
        sections.append(f"\n### 书籍 ({len(books)}本)")
        for item in books[:5]:
            sections.append(f"- **{item.get('title', '')}** — {item.get('author', '')}")

    if wikidata:
        sections.append(f"\n### Wikidata ({len(wikidata)}条)")
        for item in wikidata[:3]:
            sections.append(f"- {item.get('title', '')}: {item.get('description', '')}")

    if sources.get("web"):
        sections.append("\n### 网络来源（搜索结果，非权威引用。写作时引用具体内容，不要引用域名）")
        for item in sources["web"][:8]:
            title = item.get("title", "")
            snippet = item.get("snippet", "")[:200]
            sections.append(f"- **{title}**: {snippet}")

    # Deep web content — fetched article text
    web_articles = sources.get("web_articles", [])
    if web_articles:
        sections.append(f"\n### 网络文章全文摘要（{len(web_articles)} 篇，可直接引用具体段落）")
        for item in web_articles[:5]:
            title = item.get("title", "")
            text = item.get("text", "")
            if not text:
                continue
            # Split into paragraphs, keep substantive ones (>40 chars)
            paragraphs = [p.strip() for p in text.split("。") if len(p.strip()) > 40]
            # Take up to 8 key paragraphs
            kept = paragraphs[:8]
            sections.append(f"\n#### {title}")
            for p in kept:
                sections.append(f"- {p}。")

    if sources.get("code"):
        sections.append("\n### 代码依据")
        for item in sources["code"][:5]:
            sections.append(f"- `{item.get('file', '')}`")

    if sources.get("vm_consult"):
        sections.append("\n### 跨 VM 确认")
        for item in sources["vm_consult"]:
            sections.append(f"- **{item.get('vm', '')}**: {item.get('response', '')}")

    note = "\n".join(sections)
    if len(note) > 8000:
        cutoff = note[:8000].rfind("\n")
        note = note[:cutoff] + "\n\n[... 已截断，完整素材保留在数据库]"

    return note


def gather_research(keyword: str, category: str) -> dict:
    """Run all research channels, return compiled sources."""
    cocobook_results = search_cocobook(keyword)

    # Multi-query web search for broader coverage
    queries = _generate_web_queries(keyword, category)
    web_results = []
    seen_urls = set()
    for q in queries:
        for item in search_web(q, limit=5):
            url = item.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                web_results.append(item)

    # Fetch full text from top web results
    web_articles = []
    for item in web_results[:5]:
        url = item.get("url", "")
        text = _fetch_article_text(url)
        if text and len(text) > 200:
            web_articles.append({
                "title": item.get("title", ""),
                "url": url,
                "text": text,
            })
    if web_articles:
        print(f"  [research] Fetched {len(web_articles)} web articles")

    code_results = search_codebase(keyword)

    # Topic search — route to relevant indexes based on keyword
    topic_results = []
    for topic in _route_topics(keyword):
        topic_results.extend(_search_cocobook_topic(topic, keyword, limit=5))

    # If topic search returned sparse results, supplement from cocobook books/aa
    if len(topic_results) < 4:
        supplement = _search_cocobook_mcp(keyword, limit=8 - len(topic_results))
        topic_results.extend(supplement)

    # Writing craft search — genre-specific queries for deeper technique matching
    genre_craft_queries = {
        "tutorial": ["操作说明 步骤 先后 顺序", "举例 示例 实例 演示", "详解 讲解 说明方法"],
        "opinion": ["论证 论据 立论 驳论", "观点 立场 判断 主张", "说理 雄辩 说服"],
        "comparison": ["比较 权衡 取舍 对照", "异同 优劣 利弊", "选择 决断"],
        "troubleshooting": ["问题 原因 对策 解决", "排查 诊断 修复", "错误 故障 排除"],
        "case-study": ["经历 过程 结果 反思", "实战 实录 纪实", "前后 对比 变化"],
    }
    craft_queries = [
        "开头 结尾 结构",
        "论证 举例 对比",
        "表达 描写 节奏",
    ]
    # Prepend genre-specific queries
    for gen, queries in genre_craft_queries.items():
        if gen in category.lower() or category.lower() in gen:
            craft_queries = queries + craft_queries
            break
    craft_queries.insert(0, keyword)
    writing_craft_results = []
    seen_texts = set()
    for cq in craft_queries:
        if len(writing_craft_results) >= 8:
            break
        for item in _search_cocobook_topic(WRITING_CRAFT_TOPIC, cq, limit=3):
            text_key = (item.get("text", "") or "")[:80]
            if text_key and text_key not in seen_texts:
                seen_texts.add(text_key)
                writing_craft_results.append(item)

    # Annotation search — match claim_type to article genre
    annotation_results = _search_annotations(keyword, category, limit=6)

    sources = {
        "cocobook": cocobook_results,
        "web": web_results,
        "web_articles": web_articles,
        "code": code_results,
        "vm_consult": [],
        "writing_samples": get_writing_samples(keyword),
        "topic_paragraphs": topic_results,
        "writing_craft": writing_craft_results,
        "annotations": annotation_results,
    }

    return sources


def strip_ai_patterns(text: str) -> str:
    """Remove known AI-template phrases from text."""
    for pattern in AI_PATTERNS:
        text = re.sub(pattern, "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()


def capture_screenshot(url: str, output_path: str,
                       width: int = 1200, height: int = 800,
                       full_page: bool = False) -> bool:
    """Capture a screenshot using Pinchtab service."""
    config = load_config()
    pinchtab_url = config.get("pinchtab", {}).get("base_url", "http://localhost:9867")

    try:
        params = {
            "url": url,
            "width": width,
            "height": height,
            "fullPage": str(full_page).lower()
        }
        resp = requests.get(f"{pinchtab_url}/screenshot", params=params, timeout=30)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return True
    except requests.RequestException:
        return False


def run_research(keyword: str, category: str = "guide") -> ResearchOutput:
    """Run full research pipeline and return structured output with unique claims.

    Args:
        keyword: Search keyword
        category: Article category (tutorial, guide, opinion, etc.)

    Returns:
        ResearchOutput with sources, note, and unique_claims
    """
    sources = gather_research(keyword, category)
    research_note = build_research_note(keyword, sources)

    # Extract unique_claims from cocobook annotations
    cocobook_annotations = sources.get("annotations", [])
    ddg_results = sources.get("web", [])

    unique_claims = extract_unique_claims(cocobook_annotations, ddg_results)

    return ResearchOutput(
        keyword=keyword,
        sources=sources,
        research_note=research_note,
        unique_claims=unique_claims
    )


if __name__ == "__main__":
    # 测试 unique_claims 提取
    result = run_research("WordPress 缓存插件")
    print(f"Found {len(result.unique_claims)} unique claims:")
    for claim in result.unique_claims:
        print(f"  - {claim}")
