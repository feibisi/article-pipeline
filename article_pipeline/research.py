"""Research module — gather materials from cocobook, web, code, and VM peers."""
from article_pipeline.config import load_config
import logging
import shlex
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

logger = logging.getLogger(__name__)


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
    # Cloud-vendor "developer communities" — same reposted-tutorial economics as
    # CSDN, and a frequent source of stale/wrong config snippets.
    "cloud.tencent.com", "developer.aliyun.com", "aliyun.com",
    "huaweicloud.com", "bbs.huaweicloud.com",
    "oschina.net", "my.oschina.net", "gitee.com",
    # Known CSDN/StackOverflow scraper mirrors
    "programmersought.com", "codeleading.com", "javashuo.com",
    "cxymm.net", "codenong.com", "yisu.com", "php.cn", "www.php.cn",
    # Portal content mills
    "sohu.com", "163.com", "sina.com.cn", "zhuanlan.zhihu.com",
})

# At most this many results from the same host, so one site cannot supply the
# whole evidence base for an article.
MAX_RESULTS_PER_HOST = 2



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
    """Select relevant topic indexes based on keyword signals.

    Returns [] when no signal matches. The old behaviour defaulted to the three
    WordPress indexes for *any* unmatched keyword, so an article about e.g.
    systemd got WordPress documentation paragraphs injected under the heading
    "官方文档原文段落，这是最高质量的写作参考" — topic-blind injection by
    construction. Retrieving nothing is strictly better than retrieving
    confidently mislabelled material.
    """
    kw = keyword.lower()
    selected = set()
    for signal, topics in TOPIC_ROUTES.items():
        if signal in kw:
            for t in topics:
                selected.add(t)
    if not selected:
        logger.info("no topic index matches keyword %r — skipping topic search", keyword)
        return []
    return sorted(selected)[:4]

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
    # min_score=1: book records carry only title+author, so a metadata-only hit
    # is the best evidence available for them. This still drops results with zero
    # lexical overlap, which is what the backend returns when it has nothing.
    deduped = _filter_relevant_annotations(deduped, query, min_score=1)
    return deduped[:limit]


def _search_cocobook_topic(topic: str, query: str, limit: int = 5,
                           relevance_gate: bool = True) -> list[dict]:
    """Search a cocobook topic index for original document paragraphs.

    relevance_gate=False is for the writing-craft channel, where paragraphs are
    harvested as *prose style* samples and need not be topically related to the
    article keyword.
    """
    result = _mcp_call("cocobook_topic_search",
                       {"topic": topic, "query": query, "top_k": limit})
    if not result:
        return []

    results = []
    for item in result.get("results", []):
        item["_source"] = f"topic:{topic}"
        item["topic"] = topic
        item["snippet"] = item.get("text", "")[:300]
        # Provenance: which index, which section — so a fact can be traced back
        section = item.get("section", "")
        item["_origin"] = f"{topic}" + (f" / {section}" if section else "")
        results.append(item)
    # Same relevance gate as annotations: the topic backend is a BM25/vector
    # hybrid and happily returns the least-bad paragraph for an off-topic query.
    if relevance_gate:
        results = _filter_relevant_annotations(results, query)
    return results[:limit]


def _search_cocobook_ssh(query: str, limit: int = 5) -> list[dict]:
    """Search via SSH Tantivy on kk-pc (fallback when MCP is down).

    Hardened after 2026-07 breakage: kk-pc's WSL can no longer attach the index
    disk, so it prints a UTF-16 Windows error to stdout. With text=True and
    strict decoding that raised UnicodeDecodeError *inside* subprocess.run —
    outside the except clause — which propagated up through search_cocobook()
    and killed the whole research stage. Now: quoted argument, lenient decode,
    catch-all, and error payloads are never passed off as research material.
    """
    try:
        remote_cmd = (
            "wsl python3 /mnt/c/Users/feibisi-BH-PC/tantivy_search.py "
            f"{shlex.quote(query)} {int(limit)}"
        )
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
             "kk-pc", remote_cmd],
            capture_output=True, text=True, errors="replace", timeout=20
        )
        if result.returncode != 0:
            logger.warning("cocobook SSH fallback failed (rc=%s): %.120s",
                           result.returncode, (result.stderr or result.stdout or "").strip())
            return []
        items = json.loads(result.stdout) if result.stdout.strip() else []
        if not isinstance(items, list):
            return []
        cleaned = []
        for item in items:
            if not isinstance(item, dict) or item.get("error"):
                # The remote script reports failures as [{"error": ...}]; without
                # this guard the error text entered the research note as a source.
                logger.warning("cocobook SSH fallback returned an error payload: %.120s",
                               str(item)[:120] if isinstance(item, dict) else item)
                continue
            item["_source"] = "aa"
            item["_origin"] = "cocobook tantivy (kk-pc)"
            cleaned.append(item)
        return cleaned
    except Exception as exc:  # decode errors, timeouts, missing ssh, bad JSON
        logger.warning("cocobook SSH fallback unavailable: %s: %s",
                       type(exc).__name__, exc)
        return []


def search_cocobook(query: str, limit: int = 5) -> list[dict]:
    """Search cocobook — MCP first, SSH Tantivy fallback."""
    if not query.strip():
        return []

    results = _search_cocobook_mcp(query, limit)
    if not results:
        logger.info("cocobook MCP returned nothing for %r — trying SSH tantivy", query)
        results = _search_cocobook_ssh(query, limit)
    if not results:
        logger.warning("cocobook returned no material for %r (all backends down or "
                       "no relevant hits) — the article will have no book knowledge", query)
    return results


ANNOTATIONS_DB = "/mnt/shared-context/cocobook/cocobook-annotations.db"

# The published DB above has been a 0-byte placeholder since 2026-05-21, so the
# SQLite fallback silently returned nothing (connect() succeeds on an empty
# file; the SELECT then raises "no such table" straight into `except
# sqlite3.Error: return []`). The staging DB is the only populated copy today,
# so it is used as an explicit, logged fallback rather than pretending the
# annotation channel exists.
ANNOTATIONS_DB_FALLBACKS = [
    "/mnt/shared-context/cocobook/cocobook-annotations-stage.db",
]


def _annotation_db_paths() -> list[Path]:
    """Candidate annotation DBs, primary first, only those that look usable."""
    paths = []
    for raw in [ANNOTATIONS_DB, *ANNOTATIONS_DB_FALLBACKS]:
        p = Path(raw).expanduser()
        try:
            if p.exists() and p.stat().st_size > 0:
                paths.append(p)
            elif p.exists():
                logger.warning("annotation DB %s is empty (0 bytes) — skipping", p)
        except OSError:
            continue
    return paths

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


# Chinese function characters. A bigram made *entirely* of these carries no
# topical information: the keyword "systemd 定时器为什么不触发" yielded the
# bigrams 为什/什么/么不, which match essentially every Chinese sentence — that
# is how a systemd article matched 复盘五问法 and 量子思维 annotations even with
# a relevance gate in place.
_CJK_STOP_CHARS = set(
    "的了是在和与或但而就都也还很更最又再只已经过着being"
    "这那什么怎样如何为何以及可能会要有没不个我你他她它们"
    "时候上下前后中吗呢啊吧呀哦嗯对于关于因所以但是而且"
    "地得把被让使从到向往其之则即且或者一二三四五六七八九十"
)


def _keyword_tokens(keyword: str) -> set[str]:
    """Build match tokens from a keyword: ASCII words (>=3 chars) + CJK bigrams.

    Bigrams composed only of function characters are dropped — see
    _CJK_STOP_CHARS.
    """
    tokens = set(re.findall(r'[a-z0-9]{3,}', keyword.lower()))
    cjk = re.sub(r'[^一-鿿]', '', keyword)
    for i in range(len(cjk) - 1):
        bigram = cjk[i:i + 2]
        if all(c in _CJK_STOP_CHARS for c in bigram):
            continue
        tokens.add(bigram)
    return tokens


# Minimum lexical relevance a piece of material must reach to be injected.
# A hit inside the claim/context body counts 2, a hit in book/author metadata
# counts 1, so the default of 2 means: one real body hit, or two independent
# metadata hits. Raise it to tighten the gate.
RELEVANCE_MIN_SCORE = 2


def _relevance_score(item: dict, tokens: set[str]) -> int:
    """Score lexical overlap between an item and the keyword tokens.

    Body fields (claim / context / text / snippet) are weighted above metadata
    (book / author / title), because a keyword bigram that only appears in a
    book title is exactly how 《Timing for Animation》 ends up cited in a
    systemd article.
    """
    if not tokens:
        return 0
    body = " ".join(str(item.get(k, "") or "")
                    for k in ("claim", "context", "text", "snippet", "description")).lower()
    meta = " ".join(str(item.get(k, "") or "")
                    for k in ("book", "book_title", "author", "title", "section")).lower()
    score = 0
    for t in tokens:
        if t in body:
            score += 2
        elif t in meta:
            score += 1
    return score


def _filter_relevant_annotations(items: list[dict], keyword: str,
                                 min_score: int = RELEVANCE_MIN_SCORE) -> list[dict]:
    """Keep only material with real lexical overlap with the keyword.

    A conservative guard against topic-blind injection — e.g. CPU-architecture
    claims landing in a systemd article, which is how the pipeline produced
    confident nonsense like "毫秒级调度". Results are returned best-first so
    downstream truncation keeps the most relevant material; ties preserve input
    order, so the function is deterministic.

    This is still only a lexical gate. Real semantic relevance needs a judge
    (LLM or embedding) and is out of scope here.
    """
    tokens = _keyword_tokens(keyword)
    if not tokens:
        return items
    # A latin technical token ("systemd", "nginx") is the strongest signal a
    # keyword can carry. When one is present, a lone CJK bigram collision is not
    # enough — "触发情绪" must not qualify as material about "systemd 定时器不触发".
    latin = {t for t in tokens if re.fullmatch(r'[a-z0-9]+', t)}
    scored = []
    for i, it in enumerate(items):
        score = _relevance_score(it, tokens)
        if latin and score < min_score + 2 and not _relevance_score(it, latin):
            logger.debug("dropped material with no technical-term hit: %.60s",
                         it.get("claim") or it.get("title") or "")
            continue
        if score >= min_score:
            it["_relevance"] = score
            scored.append((-score, i, it))
        else:
            logger.debug("dropped off-topic material (score=%d): %.60s",
                         score, it.get("claim") or it.get("title") or "")
    scored.sort(key=lambda x: (x[0], x[1]))
    return [it for _, _, it in scored]


def _search_annotations(keyword: str, category: str, limit: int = 6) -> list[dict]:
    """Search cocobook annotations: MCP hybrid recommender, then local SQLite.

    (There is no LanceDB code path despite the old docstring — ANNOTATIONS_LANCE
    and _get_embedding are unused leftovers.)
    """
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
                        "quality": item.get("quality", ""),
                        "claim": item.get("claim", ""),
                        "context": item.get("context", ""),
                        "_source": "annotations",
                        "_origin": "cocobook MCP recommend",
                    })
                if len(formatted) >= limit:
                    break
            if formatted:
                # Guard against topic-blind semantic matches (the MCP recommender
                # conflates surface-similar topics, e.g. "timer" → animation
                # timing). Fall through to the SQLite path if nothing is relevant.
                relevant = _filter_relevant_annotations(formatted, keyword)
                if relevant:
                    return relevant
    except Exception:
        pass

    # Fallback: SQLite keyword search
    for db_path in _annotation_db_paths():
        results = _search_annotations_sqlite(db_path, keyword, claim_types, limit)
        if results:
            if str(db_path) != ANNOTATIONS_DB:
                logger.warning("annotations came from fallback DB %s — the published "
                               "DB %s is unusable", db_path, ANNOTATIONS_DB)
            return results
    logger.warning("no annotations found for %r (claim_types=%s) — article will carry "
                   "no book-sourced claims", keyword, claim_types)
    return []


# Quality grades, best first. Used as a deterministic tie-breaker in place of
# the old ORDER BY RANDOM(). Every row in the current corpus is "AI_draft"
# (1504/1504, verified_by='ai-draft'), i.e. an unverified LLM paraphrase of a
# book — ranked below any human-graded annotation.
_QUALITY_RANK = {"A": 0, "B": 1, "C": 2, "D": 3, "AI_draft": 5}

# How a quality grade is described in the note, so the writer and the reviewer
# both know how much weight a claim can carry.
_QUALITY_LABELS = {
    "AI_draft": "AI草稿标注(未经人工核验，不可作为权威依据)",
}


def _search_annotations_sqlite(db_path: Path, keyword: str,
                               claim_types: list[str], limit: int) -> list[dict]:
    """Token-based, deterministic, relevance-ranked annotation lookup.

    Replaces two anti-patterns:
      * ``ORDER BY RANDOM()`` — different material on every run, so an article
        could never be reproduced or diffed, and relevance played no part in
        which claims were injected.
      * ``keyword.replace("的", "%")`` — turning the commonest Chinese particle
        (and every space) into a SQL wildcard made ``LIKE`` match nearly the
        whole table, which is how CPU-architecture claims reached a systemd
        article.
    """
    tokens = sorted(_keyword_tokens(keyword))
    if not tokens:
        return []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        type_ph = ", ".join(["?"] * len(claim_types))
        # One LIKE per token instead of one wildcard-riddled LIKE for the whole
        # keyword. Candidate pool is deliberately wider than `limit` so ranking,
        # not SQL order, decides what survives.
        like_ph = " OR ".join(["claim LIKE ?" for _ in tokens]
                              + ["context LIKE ?" for _ in tokens]
                              + ["book_title LIKE ?" for _ in tokens])
        like_args = [f"%{t}%" for t in tokens] * 3
        query = f"""SELECT id, book_title, author, claim_type, quality,
                           substr(claim, 1, 300) as claim_text,
                           substr(context, 1, 200) as context_text
                    FROM annotations
                    WHERE claim_type IN ({type_ph})
                      AND ({like_ph})
                    ORDER BY id
                    LIMIT ?"""
        rows = conn.execute(query, (*claim_types, *like_args, max(limit * 10, 50))).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        logger.warning("annotation DB %s unusable: %s", db_path, exc)
        return []

    results = []
    for r in rows:
        results.append({
            "book": r["book_title"] or "",
            "author": r["author"] or "",
            "type": r["claim_type"],
            "quality": r["quality"] or "",
            "claim": r["claim_text"],
            "context": r["context_text"] or "",
            "_source": "annotations",
            # Provenance: exact row this claim came from, so a reviewer can go
            # back to the annotation (and from there to the book).
            "_origin": f"{db_path.name}#{r['id']}",
        })

    ranked = _filter_relevant_annotations(results, keyword)
    # Stable secondary sort: relevance first, then annotation quality grade.
    ranked.sort(key=lambda it: (-it.get("_relevance", 0),
                                _QUALITY_RANK.get(it.get("quality", ""), 9)))
    return ranked[:limit]


def extract_unique_claims(cocobook_annotations: list, ddg_results: list[dict],
                          keyword: str = "") -> list[str]:
    """从 cocobook 标注中提取 unique claims。

    逻辑：
    1. cocobook_annotations 是从 cocobook MCP 返回的标注列表
    2. ddg_results 是 DDG 搜索返回的前 10 个结果的摘要/标题
    3. 对每个 annotation claim，检查是否在 ddg_results 中出现
    4. 未出现 **且与选题相关** → 加入 unique_claims

    关于第 4 步的 relevance 前置条件：本函数的判据是"与搜索结果重叠低"，
    而与选题无关的 claim 恰好重叠最低 —— 于是越跑题的素材越容易被标成"独到
    见解"。review.evaluate_publish_gate() 又允许非空 unique_claims 单独把文章
    推过价值门槛，等于奖励跑题。因此先过一道相关性闸，再判独特性。
    """
    if not cocobook_annotations:
        return []

    if keyword:
        cocobook_annotations = _filter_relevant_annotations(
            list(cocobook_annotations), keyword)
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
        host_counts: dict[str, int] = {}
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=limit * 3):
                url = r.get("href", "")
                if _is_content_farm(url):
                    logger.debug("dropped content farm result: %s", url)
                    continue
                host = (urlparse(url).hostname or "").lower()
                if host_counts.get(host, 0) >= MAX_RESULTS_PER_HOST:
                    continue
                host_counts[host] = host_counts.get(host, 0) + 1
                results.append({
                    "title": _clean_title(r.get("title", "")),
                    "url": url,
                    "snippet": r.get("body", ""),
                    # Provenance: a web search hit is the weakest class of
                    # evidence and must be labelled as such downstream.
                    "_source": "web",
                    "_origin": f"DuckDuckGo «{query}» — {host}",
                })
                if len(results) >= limit:
                    break
        if not results:
            logger.warning("web search returned nothing usable for %r", query)
        return results
    except Exception as exc:
        logger.warning("web search failed for %r: %s: %s", query, type(exc).__name__, exc)
        return []


def _resolve_encoding(resp) -> str | None:
    """Pick a sane encoding for a fetched page.

    requests falls back to ISO-8859-1 when a text/html response carries no
    charset parameter, which turns GB18030/UTF-8 Chinese pages into mojibake —
    and that mojibake was going straight into the research note as "可直接引用
    具体段落". Prefer the declared charset, else chardet's guess.
    """
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "charset=" in ctype:
        return resp.encoding
    guess = getattr(resp, "apparent_encoding", None)
    return guess or resp.encoding


def _fetch_article_text(url: str, max_chars: int = 3000, timeout: int = 15) -> str:
    """Fetch and extract readable text from a URL. Returns first max_chars of content."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ArticlePipeline/1.0)"},
            timeout=timeout,
        )
        resp.raise_for_status()
        resp.encoding = _resolve_encoding(resp)
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
            # Annotation records key the book as "book"; only MCP book records use
            # "title". Reading "title" alone produced "(来源: )" — a data point
            # with no attributable source, i.e. an invitation to fabricate.
            src_label = _provenance(item) or "未标注来源"
            points.append(f"洞见{type_tag}: {claim} (来源: {src_label})")
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
        # Trailing 。/. used to be mandatory, so numbers in DDG snippets — which
        # are cut mid-sentence with "…" far more often than not — never became
        # data points at all. The terminator is now optional.
        num_sentences = re.findall(
            r"[^。.!！?？\n]*(?:\d+\s*[%％倍亿万千]|\d{4}\s*年)[^。.!！?？\n]*", snippet)
        url = item.get("url", "")
        for s in num_sentences[:3]:
            if len(s) > 10:
                # Keep the URL next to the number: this is a web search snippet,
                # not an authority, and the reviewer must be able to check it.
                cite = f"{title} {url}".strip() if url else (title or "未知来源")
                points.append(f"数据: {s.strip()} (来源: 网络搜索 — {cite})")

    for item in sources.get("code", [])[:3]:
        points.append(f"代码: {item.get('file', '')}")

    return points


NOTE_CHAR_BUDGET = 8000


def _provenance(item: dict) -> str:
    """Human-readable citation for one piece of material.

    Everything the pipeline knows about where a fact came from, in one string:
    book/title, author, quality grade, and the backend row/topic it came from.
    NOTE: the annotation schema has no page or chapter column, so page-level
    citation is impossible today — see the audit notes.
    """
    book = (item.get("book") or item.get("book_title") or item.get("title") or "").strip()
    author = (item.get("author") or "").strip()
    parts = []
    if book:
        parts.append(f"《{book[:40]}》" if not book.startswith("《") else book[:44])
    if author:
        parts.append(author[:24])
    quality = (item.get("quality") or "").strip()
    if quality:
        parts.append(_QUALITY_LABELS.get(quality, f"{quality}级标注"))
    origin = (item.get("_origin") or "").strip()
    if origin:
        parts.append(origin[:60])
    url = (item.get("url") or "").strip()
    if url:
        parts.append(url[:120])
    return " / ".join(parts)


def _assemble_note(blocks: list[tuple[int, list[str]]],
                   budget: int = NOTE_CHAR_BUDGET,
                   order_by_priority: bool = True) -> str:
    """Join blocks under a char budget, dropping the least valuable lines first.

    Two problems with the old builder, both about position:

    1. It concatenated everything and hard-cut the tail at 8000 chars. Style
       samples (原文范本 / 写作范本) are emitted first and easily fill 4000+
       chars, so the cut deleted precisely the factual tail — fetched web article
       text, code evidence, cross-VM confirmations.
    2. outline.py:487,521 only feeds the *first* 2000 chars (4000 for external
       tiers) of the note to the outline prompt. With style first, the article
       skeleton was planned without ever seeing a fact.

    So blocks carry a priority (lower = more valuable): output is ordered by
    priority, and trimming eats the tail of the lowest-priority blocks first.
    """
    blocks = [(prio, list(lines)) for prio, lines in blocks if lines]
    if order_by_priority:
        blocks.sort(key=lambda b: b[0])  # stable: ties keep insertion order

    def size() -> int:
        return sum(len(line) + 1 for _, lines in blocks for line in lines)

    dropped = 0
    # Trim from the least important blocks; a block is never reduced below its
    # header, and once only the header is left the whole block goes.
    while size() > budget:
        candidates = [i for i, (_, lines) in enumerate(blocks) if len(lines) > 1]
        if not candidates:
            break
        worst = max(candidates, key=lambda i: (blocks[i][0], i))
        blocks[worst][1].pop()
        dropped += 1
    while size() > budget:
        candidates = [i for i, (_, lines) in enumerate(blocks) if lines]
        if not candidates:
            break
        worst = max(candidates, key=lambda i: (blocks[i][0], i))
        blocks[worst][1].clear()
        dropped += 1

    note = "\n".join(line for _, lines in blocks for line in lines)
    if dropped:
        note += "\n\n[... 已截断，完整素材保留在数据库]"
    return note


def build_research_note(keyword: str, sources: dict) -> str:
    """Compile research sources into a dense, structured research note.

    Blocks are (priority, lines); lower priority number survives truncation
    longer. Facts and their provenance outrank style samples.
    """
    blocks: list[tuple[int, list[str]]] = [(0, [f"## 研究笔记: {keyword}\n"])]

    # Topic paragraphs — original document text, best writing reference
    topic_paragraphs = sources.get("topic_paragraphs", [])
    if topic_paragraphs:
        lines = ["### 原文范本（官方文档原文段落，这是最高质量的写作参考）"]
        for i, p in enumerate(topic_paragraphs[:8], 1):
            text = p.get("snippet", p.get("text", ""))[:300]
            # Label with the index + section it came from, not just the section:
            # supplements used to be mixed in here with no way to tell them apart.
            label = p.get("_origin") or p.get("topic") or p.get("section") or ""
            sections_label = f"[{label}]" if label else ""
            lines.append(f"{i}. {sections_label} {text}")
        blocks.append((3, lines))

    # Writing craft paragraphs — Chinese prose style from classic writing books
    writing_craft = sources.get("writing_craft", [])
    if writing_craft:
        lines = ["\n### 写作范本（来自中文写作经典原文段落，学习这些文字的节奏和表达方式）"]
        for i, p in enumerate(writing_craft[:6], 1):
            book = p.get("title", "")
            section_title = p.get("section", "")
            text = p.get("snippet", p.get("text", ""))[:300]
            label = f"[{book}]" if book else ""
            if section_title:
                label = f"[{book} — {section_title}]"
            lines.append(f"{i}. {label} {text}")
        blocks.append((4, lines))

    # Writing samples — cocobook annotations as fallback style reference
    writing_samples = sources.get("writing_samples", [])
    if writing_samples:
        if not topic_paragraphs and not writing_craft:
            lines = ["### 写作范本（人类编辑的真实文字，模仿这种写法和语感）"]
        else:
            lines = ["### 标注范本（人类编辑的补充观点）"]
        for i, s in enumerate(writing_samples[:5], 1):
            quality = s.get("quality", "")
            claim_type = s.get("type", "")
            # Format is parsed by writer._extract_samples — do not change.
            lines.append(f"{i}. [{quality}级|{claim_type}] {s.get('claim', '')}")
        blocks.append((4, lines))

    data_points = _extract_data_points(sources)
    if data_points:
        lines = ["\n### 关键素材"]
        for pt in data_points[:15]:
            lines.append(f"- {pt}")
        blocks.append((1, lines))

    # Group cocobook results by source type
    coco_items = sources.get("cocobook", [])
    annotations = [i for i in coco_items if i.get("_source") == "annotations"]
    books = [i for i in coco_items if i.get("_source") == "books"]
    wikidata = [i for i in coco_items if i.get("_source") == "wikidata"]

    if annotations:
        lines = [f"\n### 知识标注 ({len(annotations)}条)"]
        for item in annotations[:5]:
            applicable = item.get("applicable_to", "")
            cite = _provenance(item) or "未标注来源"
            lines.append(f"- {item.get('claim', '')[:200]}")
            lines.append(f"  出处: {cite}")
            if applicable:
                lines.append(f"  适用: {applicable}")
        blocks.append((2, lines))

    # New annotation source — genre-matched claims from cocobook annotations DB
    new_annotations = sources.get("annotations", [])
    if new_annotations:
        lines = [f"\n### 相关观点（来自 {len(new_annotations)} 本书的标注）"]
        for item in new_annotations[:5]:
            btype = item.get("type", "")
            claim = item.get("claim", "")[:200]
            context = item.get("context", "")[:100]
            lines.append(f"- [{btype}] {claim}")
            lines.append(f"  出处: {_provenance(item) or '未标注来源'}")
            if context:
                lines.append(f"  上下文: {context}")
        blocks.append((1, lines))

    if books:
        lines = [f"\n### 书籍 ({len(books)}本)"]
        for item in books[:5]:
            lines.append(f"- **{item.get('title', '')}** — {item.get('author', '')}")
        blocks.append((3, lines))

    if wikidata:
        lines = [f"\n### Wikidata ({len(wikidata)}条)"]
        for item in wikidata[:3]:
            lines.append(f"- {item.get('title', '')}: {item.get('description', '')}")
        blocks.append((3, lines))

    if sources.get("web"):
        lines = ["\n### 网络来源（搜索结果，非权威引用。写作时引用具体内容，不要引用域名）"]
        for item in sources["web"][:8]:
            title = item.get("title", "")
            snippet = item.get("snippet", "")[:200]
            url = item.get("url", "")
            lines.append(f"- **{title}**: {snippet}")
            if url:
                # The URL has to be in the note: review.check_fabrication treats
                # any URL in the article that is absent from the note as
                # fabricated, and a reviewer needs the link to verify a number.
                lines.append(f"  出处: {url}")
        blocks.append((2, lines))

    # Deep web content — fetched article text
    web_articles = sources.get("web_articles", [])
    if web_articles:
        lines = [f"\n### 网络文章全文摘要（{len(web_articles)} 篇，可直接引用具体段落）"]
        for item in web_articles[:5]:
            title = item.get("title", "")
            text = item.get("text", "")
            if not text:
                continue
            # Split into paragraphs, keep substantive ones (>40 chars)
            paragraphs = [p.strip() for p in text.split("。") if len(p.strip()) > 40]
            kept = paragraphs[:8]
            url = item.get("url", "")
            lines.append(f"\n#### {title}")
            if url:
                lines.append(f"出处: {url}")
            for p in kept:
                lines.append(f"- {p}。")
        blocks.append((2, lines))

    if sources.get("code"):
        lines = ["\n### 代码依据"]
        for item in sources["code"][:5]:
            lines.append(f"- `{item.get('file', '')}`")
        blocks.append((1, lines))

    if sources.get("vm_consult"):
        lines = ["\n### 跨 VM 确认"]
        for item in sources["vm_consult"]:
            lines.append(f"- **{item.get('vm', '')}**: {item.get('response', '')}")
        blocks.append((1, lines))

    return _assemble_note(blocks)


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

    # If topic search returned sparse results, supplement from cocobook books/aa.
    # These are books/zim/wikidata hits, NOT official documentation paragraphs —
    # they used to be appended to topic_results and then rendered under
    # "原文范本（官方文档原文段落）", i.e. relabelled as something they are not.
    # They now join the cocobook bucket, which is rendered honestly.
    if len(topic_results) < 4:
        supplement = _search_cocobook_mcp(keyword, limit=8 - len(topic_results))
        if supplement:
            cocobook_results = cocobook_results + [
                s for s in supplement if s not in cocobook_results
            ]

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
        # relevance_gate=False: craft paragraphs are prose-style samples, they are
        # not expected to be topically related to the article keyword.
        for item in _search_cocobook_topic(WRITING_CRAFT_TOPIC, cq, limit=3,
                                           relevance_gate=False):
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

    unique_claims = extract_unique_claims(cocobook_annotations, ddg_results,
                                          keyword=keyword)

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
