"""GEO (Generative Engine Optimization) quality scoring — Frase 5-dimension model."""
import re

# ────────────────────────────────────────────────────────────────────

import re


def check_geo(article: str, tier: str = "A") -> dict:
    """GEO quality scoring — 5 dimensions, each 0-20, total 0-100.

    Dimensions (Frase/AutoGEO framework):
    1. Extractability — can LLMs extract direct answers?
    2. Fact Density — stats/numbers/data richness
    3. Authority Signal — citations, sources, expert references
    4. Freshness — temporal signals, dates, recent references
    5. Structural Metadata — heading hierarchy, lists, tables, FAQ

    Tier A: strict (15/20 per dim to pass)
    Tier B: moderate (12/20 per dim to pass)
    Tier C: lenient (10/20 per dim to pass)
    """
    if not article or len(article) < 100:
        return {"score": 0, "total": 0, "pass": False, "dimensions": {},
                "suggestions": []}

    threshold = {"A": 15, "B": 12, "C": 10}.get(tier, 15)

    dims = {
        "extractability": _score_extractability(article),
        "fact_density": _score_fact_density(article),
        "authority_signal": _score_authority(article),
        "freshness": _score_freshness(article),
        "structural_metadata": _score_structural(article),
    }

    total = sum(d["score"] for d in dims.values())
    passed = total >= threshold * 5  # sum of all 5 dims must meet threshold*5

    suggestions = _geo_suggestions(dims, threshold)

    return {
        "score": total,
        "total": total,
        "pass": passed,
        "threshold": threshold,
        "dimensions": dims,
        "suggestions": suggestions,
    }


# ── 1. Extractability ──

def _score_extractability(article: str) -> dict:
    """Score how well LLMs can extract direct answers from the article.

    Checks:
    - Answer-first: direct answer in first 60 words (0-8 pts)
    - Definition sentences: "X是指/是/意味着" patterns (0-4 pts)
    - Concise key sentences: <40 chars sentences with key info (0-4 pts)
    - No meandering intro: first paragraph has substance (0-4 pts)
    """
    score = 0
    flags = []

    # Split into paragraphs
    paragraphs = [p.strip() for p in article.split('\n\n') if p.strip()]
    first_para = paragraphs[0] if paragraphs else ""
    first_60_words = ' '.join(first_para.split()[:60])

    # Check 1: Answer-first (does first 60 words contain a direct statement?)
    # Penalize if first 60 words are all fluff (questions, context-setting)
    has_direct_answer = bool(re.search(
        r'(?:是指|就是|意味着|定义为|本质上是|核心是|关键在于|'
        r'=|可以[让使]|提供了|支持|包含|具备)',
        first_60_words
    ))
    if has_direct_answer:
        score += 8
    else:
        flags.append("前60字缺少直接回答")
        # Partial credit if at least starts with the topic
        if re.search(r'^#{0,3}\s*\S', first_para):
            score += 3

    # Check 2: Definition sentences count
    defn_patterns = re.findall(
        r'(?:.{2,20})(?:是指|是指|是[一一种]|定义为|本质上是)',
        article
    )
    defn_count = len(defn_patterns)
    if defn_count >= 3:
        score += 4
    elif defn_count >= 1:
        score += 2
    else:
        flags.append("缺少定义句式")

    # Check 3: Concise info-bearing sentences
    sentences = re.split(r'[。！？\n]', article)
    concise_info = [s for s in sentences if 10 < len(s) < 40 and
                    re.search(r'[\d%％]', s)]
    if len(concise_info) >= 3:
        score += 4
    elif len(concise_info) >= 1:
        score += 2
    else:
        flags.append("缺少精炼数据句")

    # Check 4: First paragraph substance (not just fluff)
    first_para_substantive = len(first_para) > 50 and not re.match(
        r'^(?:随着|在当今|众所周知|不可否认)', first_para
    )
    if first_para_substantive:
        score += 4
    else:
        flags.append("首段内容空洞")

    return {"score": min(score, 20), "max": 20, "flags": flags}


# ── 2. Fact Density ──

def _score_fact_density(article: str) -> dict:
    """Score data richness — stats, numbers, percentages per word.

    Target: 1 data point per 150 words (Frase benchmark).
    """
    score = 0
    flags = []

    # Count total Chinese characters (approximate word count)
    chars = len(re.sub(r'\s', '', article))
    if chars == 0:
        return {"score": 0, "max": 20, "flags": ["空文章"]}

    # Count data points
    percentages = len(re.findall(r'\d+(?:\.\d+)?\s*[%％]', article))
    absolute_nums = len(re.findall(r'(?<![a-zA-Z])\d{2,}(?:\.\d+)?(?![a-zA-Z/])', article))
    versions = len(re.findall(r'\d+\.\d+(?:\.\d+)?', article))
    dates = len(re.findall(r'\d{4}\s*年|\d{1,2}\s*月|\d{4}-\d{2}', article))
    comparisons = len(re.findall(r'(?:增长了?|提升了?|下降了?|增加了?)\s*[\d.%％]+', article))

    data_points = percentages + absolute_nums + versions + dates + comparisons

    # Ratio
    ratio = chars / max(data_points, 1)

    if ratio <= 100:      # Very data-rich
        score += 10
    elif ratio <= 150:    # Target range
        score += 8
    elif ratio <= 250:
        score += 5
    elif ratio <= 400:
        score += 3
        flags.append(f"数据密度低: 每{int(ratio)}字1个数据点(目标≤150)")
    else:
        flags.append(f"数据密度极低: 每{int(ratio)}字1个数据点(目标≤150)")

    # Bonus for variety of data types
    types_used = sum(1 for v in [percentages, absolute_nums, versions, dates, comparisons] if v > 0)
    score += min(types_used * 2.5, 10)  # Up to 10 pts for variety

    return {
        "score": min(round(score), 20),
        "max": 20,
        "data_points": data_points,
        "ratio": round(ratio),
        "breakdown": {
            "percentages": percentages,
            "numbers": absolute_nums,
            "versions": versions,
            "dates": dates,
            "comparisons": comparisons,
        },
        "flags": flags,
    }


# ── 3. Authority Signal ──

def _score_authority(article: str) -> dict:
    """Score authority signals — citations, sources, expert references.

    Checks:
    - Outbound citations/links (0-6 pts)
    - Named sources (0-6 pts)
    - Expert/official references (0-4 pts)
    - Statistics with source attribution (0-4 pts)
    """
    score = 0
    flags = []
    details = {}

    # Citations: markdown links, bare URLs, bracket citations
    md_links = len(re.findall(r'\[([^\]]+)\]\([^)]+\)', article))
    bare_urls = len(re.findall(r'https?://\S+', article))
    bracket_cites = len(re.findall(r'\[[\d,]+\]', article))
    total_citations = md_links + bare_urls + bracket_cites

    details["citations"] = total_citations
    if total_citations >= 5:
        score += 6
    elif total_citations >= 3:
        score += 4
    elif total_citations >= 1:
        score += 2
    else:
        flags.append("无任何引用链接")

    # Named sources: "根据X", "X表示", "X报告", "X调查"
    named_sources = re.findall(
        r'(?:根据|据|引用|参考)[《]?([^》,\n]{2,30})[》]?',
        article
    )
    official_refs = re.findall(
        r'(?:官方|WordPress\.org|GitHub|W3C|MDN|RFC|ISO|MIT|Apache)',
        article
    )

    details["named_sources"] = len(named_sources)
    details["official_refs"] = len(official_refs)

    if len(named_sources) >= 3:
        score += 6
    elif len(named_sources) >= 1:
        score += 3
    else:
        flags.append("无具名来源引用")

    if official_refs:
        score += min(len(official_refs) * 2, 4)
    else:
        flags.append("缺少权威来源(如WordPress.org/GitHub)")

    # Stats with attribution
    attributed_stats = len(re.findall(
        r'(?:根据|据|按照)[^。，]{0,30}(?:报告|调查|统计|数据|研究)',
        article
    ))
    details["attributed_stats"] = attributed_stats
    if attributed_stats >= 2:
        score += 4
    elif attributed_stats >= 1:
        score += 2

    return {"score": min(score, 20), "max": 20, "details": details, "flags": flags}


# ── 4. Freshness ──

def _score_freshness(article: str) -> dict:
    """Score temporal signals — dates, versions, "最新", year references.

    Checks:
    - Current year mentions (0-6 pts)
    - Version/update signals (0-5 pts)
    - Temporal keywords: 最新/全新/最新版/更新/升级 (0-5 pts)
    - Recent date patterns (0-4 pts)
    """
    import datetime
    score = 0
    flags = []
    current_year = str(datetime.datetime.now().year)
    prev_year = str(datetime.datetime.now().year - 1)

    # Current/recent year mentions
    year_mentions = len(re.findall(rf'{current_year}|{prev_year}', article))
    if year_mentions >= 3:
        score += 6
    elif year_mentions >= 1:
        score += 4
    else:
        flags.append(f"未提及{current_year}或{prev_year}年")

    # Version signals
    version_signals = len(re.findall(r'(?:版本|v\d|更新|升级|发布|Release)', article))
    if version_signals >= 3:
        score += 5
    elif version_signals >= 1:
        score += 3
    else:
        flags.append("无版本/更新信号")

    # Temporal keywords
    temporal_kw = len(re.findall(
        r'(?:最新|全新|最新版|最近|近期|刚刚|已发布|现已|近期)',
        article
    ))
    if temporal_kw >= 3:
        score += 5
    elif temporal_kw >= 1:
        score += 3
    else:
        flags.append("缺少时效性关键词")

    # Specific dates
    specific_dates = len(re.findall(
        r'\d{4}\s*年\s*\d{1,2}\s*月|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}',
        article
    ))
    if specific_dates >= 2:
        score += 4
    elif specific_dates >= 1:
        score += 2

    return {"score": min(score, 20), "max": 20, "flags": flags}


# ── 5. Structural Metadata ──

def _score_structural(article: str) -> dict:
    """Score structural quality for LLM parsing.

    Checks:
    - Heading hierarchy (H1→H2→H3) (0-5 pts)
    - Lists (ordered/unordered) (0-4 pts)
    - Tables (0-3 pts)
    - Question-format headers (0-4 pts)
    - Code examples (0-4 pts)
    """
    score = 0
    flags = []
    details = {}

    # Headings
    h1_count = len(re.findall(r'^#\s+', article, re.MULTILINE))
    h2_count = len(re.findall(r'^##\s+', article, re.MULTILINE))
    h3_count = len(re.findall(r'^###\s+', article, re.MULTILINE))

    details["h1"] = h1_count
    details["h2"] = h2_count
    details["h3"] = h3_count

    if h2_count >= 3:
        score += 5
    elif h2_count >= 1:
        score += 3
    else:
        flags.append("缺少H2标题层级")

    # Lists
    ul_items = len(re.findall(r'^\s*[-*+]\s+', article, re.MULTILINE))
    ol_items = len(re.findall(r'^\s*\d+[.)]\s+', article, re.MULTILINE))
    total_list_items = ul_items + ol_items

    details["list_items"] = total_list_items
    if total_list_items >= 6:
        score += 4
    elif total_list_items >= 3:
        score += 2
    else:
        flags.append("缺少列表结构")

    # Tables
    table_rows = len(re.findall(r'^\|.*\|$', article, re.MULTILINE))
    details["table_rows"] = table_rows
    if table_rows >= 3:
        score += 3
    elif table_rows >= 1:
        score += 1

    # Question-format headers (good for featured snippets)
    all_headers = re.findall(r'^#{1,3}\s+(.+)', article, re.MULTILINE)
    question_headers = [h for h in all_headers if re.search(r'[？?如何怎么什么为什么哪几]', h)]
    details["total_headers"] = len(all_headers)
    details["question_headers"] = len(question_headers)

    if len(all_headers) > 0:
        q_ratio = len(question_headers) / len(all_headers)
        if q_ratio >= 0.3:
            score += 4
        elif q_ratio >= 0.1:
            score += 2
        else:
            flags.append("标题缺少问句格式(推荐≥30%)")

    # Code examples
    code_blocks = len(re.findall(r'```\w*', article))
    inline_code = len(re.findall(r'`[^`]+`', article))
    if code_blocks >= 1 or inline_code >= 3:
        score += 4
    elif inline_code >= 1:
        score += 2

    return {"score": min(score, 20), "max": 20, "details": details, "flags": flags}


# ── Suggestions ──

def _geo_suggestions(dims: dict, threshold: int) -> list[dict]:
    """Generate revision suggestions for underperforming GEO dimensions."""
    suggestions = []
    fixes_map = {
        "extractability": {
            "issue": "答案可提取性不足 — AI 引擎难以直接提取回答",
            "fix": "在首段前60字内直接回答核心问题；使用'X是指/是/意味着'定义句式；精炼数据句控制在40字内"
        },
        "fact_density": {
            "issue": "数据密度不够 — 缺少支撑论点的具体数字",
            "fix": "每150字至少包含1个数据点(百分比/版本号/对比数据)；用具体数字替换模糊描述(如'很多'→'73%')"
        },
        "authority_signal": {
            "issue": "权威信号不足 — 缺少引用和来源",
            "fix": "添加≥3个外链引用；引用官方来源(WordPress.org/GitHub)；统计数据标注出处(如'根据2024年Stack Overflow调查')"
        },
        "freshness": {
            "issue": "时效性信号不足 — 内容显得陈旧",
            "fix": "提及当前年份和最近版本号；添加'最新/已发布/现已'等时效词；标注具体发布日期"
        },
        "structural_metadata": {
            "issue": "结构化元数据不足 — 不利于AI引擎解析",
            "fix": "确保≥3个H2标题；≥30%标题用问句格式；添加列表和表格；技术文章包含代码示例"
        },
    }

    for dim_name, dim_data in dims.items():
        if dim_data["score"] < threshold and dim_name in fixes_map:
            fix_info = fixes_map[dim_name]
            priority = "high" if dim_data["score"] < threshold - 5 else "medium"
            suggestions.append({
                "category": f"geo_{dim_name}",
                "priority": priority,
                "issue": fix_info["issue"],
                "fix": fix_info["fix"],
                "detail": f"当前得分 {dim_data['score']}/20 (需≥{threshold})",
            })

    return suggestions
