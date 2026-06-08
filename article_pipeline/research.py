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


AI_PATTERNS = [
    r"在当今数字化的?时代",
    r"随着.{1,6}的(?:发展|进步|普及)",
    r"首先.{0,10}其次.{0,10}最后",
    r"首先[,，]?",
    r"总而言之",
    r"综上所述",
    r"不仅如此.{0,10}而且",
]



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


def search_web(query: str, limit: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo."""
    if not query.strip():
        return []

    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=limit):
                results.append({
                    "title": _clean_title(r.get("title", "")),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })
        return results
    except Exception:
        return []



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
    """Extract concrete data points, claims, and stats from MCP results."""
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

    for item in sources.get("web", [])[:3]:
        snippet = item.get("snippet", "")
        num_sentences = re.findall(r"[^。.!！?？\n]*(?:\d+[%％倍亿万千]|\d{4}年)[^。.!！?？\n]*[。.]", snippet)
        for s in num_sentences[:3]:
            if len(s) > 10:
                points.append(f"数据: {s.strip()}")
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
        for item in sources["web"][:5]:
            title = item.get("title", "")
            snippet = item.get("snippet", "")[:200]
            # Strip domain — model should cite article/source name, not raw URL
            sections.append(f"- **{title}**: {snippet}")

    if sources.get("code"):
        sections.append("\n### 代码依据")
        for item in sources["code"][:5]:
            sections.append(f"- `{item.get('file', '')}`")

    if sources.get("vm_consult"):
        sections.append("\n### 跨 VM 确认")
        for item in sources["vm_consult"]:
            sections.append(f"- **{item.get('vm', '')}**: {item.get('response', '')}")

    note = "\n".join(sections)
    if len(note) > 4000:
        cutoff = note[:4000].rfind("\n")
        note = note[:cutoff] + "\n\n[... 已截断，完整素材保留在数据库]"

    return note


def gather_research(keyword: str, category: str) -> dict:
    """Run all research channels, return compiled sources."""
    cocobook_results = search_cocobook(keyword)
    web_results = search_web(keyword)
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
