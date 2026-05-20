"""Research module — gather materials from cocobook, web, code, and VM peers."""
import subprocess
import json
import re
import os
import requests
import yaml


AI_PATTERNS = [
    r"在当今数字化的?时代",
    r"随着.{1,6}的(?:发展|进步|普及)",
    r"首先.{0,10}其次.{0,10}最后",
    r"首先[,，]?",
    r"总而言之",
    r"综上所述",
    r"不仅如此.{0,10}而且",
]


def _load_config():
    config_path = os.path.expanduser("~/.config/article-pipeline/config.yaml")
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


# MCP endpoint — cocobook v4 on kk-pc
MCP_BASE = "http://192.168.1.137:8086"


# ---- Search channels ----

def _search_cocobook_mcp(query: str, limit: int = 5) -> list[dict]:
    """Search via cocobook MCP (annotations + books + wikidata + zim)."""
    try:
        resp = requests.get(
            f"{MCP_BASE}/search",
            params={"q": query, "source": "all", "limit": limit},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for source_name, items in data.get("results", {}).items():
            for item in items:
                item["_source"] = source_name
                if "label" in item and "title" not in item:
                    item["title"] = item["label"]
                if "claim" in item:
                    item["snippet"] = item["claim"]
                if "description" in item and "snippet" not in item:
                    item["snippet"] = item["description"]
                results.append(item)
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        results = [r for r in results if _is_relevant(r, query)]
        return results[:limit]
    except (requests.RequestException, json.JSONDecodeError, KeyError):
        return []


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


def _search_annotations_ssh(keyword: str, limit: int = 8) -> list[dict]:
    """Search cocobook annotations DB on kk-pc via SSH for writing samples."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             "kk-pc", f"wsl sqlite3 /mnt/d/cocobook-library/cocobook-annotations.db "
                      f"\"SELECT quality, claim_type, substr(claim,1,300) FROM annotations "
                      f"WHERE quality IN ('A','B') AND claim LIKE '%{keyword}%' LIMIT {limit};\""],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        samples = []
        for line in result.stdout.strip().split('\n'):
            parts = line.split('|', 2)
            if len(parts) >= 3:
                samples.append({
                    "quality": parts[0], "type": parts[1], "claim": parts[2],
                    "_source": "annotations"
                })
        return samples
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def get_writing_samples(keyword: str, limit: int = 5) -> list[dict]:
    """Get high-quality cocobook annotations as writing style reference."""
    samples = []
    # Try keyword variations from broadest to most specific
    terms = [w for w in keyword.replace('的', ' ').replace('与', ' ').split() if len(w) > 1]
    queries = set()
    # Individual significant words
    for t in terms[:3]:
        queries.add(t)
    # Pairs of words
    if len(terms) >= 2:
        queries.add(' '.join(terms[:2]))
    # Try each query until we get enough samples
    for q in sorted(queries, key=len, reverse=True):
        if len(samples) >= limit:
            break
        results = _search_annotations_ssh(q, limit)
        for r in results:
            if len(samples) >= limit:
                break
            samples.append(r)
    return samples[:limit]


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

    # Writing samples first — most important for tone/voice
    writing_samples = sources.get("writing_samples", [])
    if writing_samples:
        sections.append("### 写作范本（人类编辑的真实文字，模仿这种写法和语感）")
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

    sources = {
        "cocobook": cocobook_results,
        "web": web_results,
        "code": code_results,
        "vm_consult": [],
        "writing_samples": get_writing_samples(keyword),
    }

    # Cross-VM consultation disabled — moved to review stage
    # Use: article-pipeline consult <task_id> --vm wenpai
    # Automatic vm-ask removed to prevent NATS spam

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
    config = _load_config()
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
