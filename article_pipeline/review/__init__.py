"""Self-review module，fact check，AI detection，format，word count，semantic verification.

V2: Integrated Humanizer-zh 24 patterns plus 5-dimension quality scoring.
Sources: CSDN AI味词库，Wikipedia AI生成文的特征，Humanizer-zh（WikiProject AI Cleanup），
         53ai.com，Hello-SimpleAI，translate VM patterns，community observations.
"""
from article_pipeline.config import load_config
import json
import math
import re
import os

import requests
import yaml

# Re-export from submodules
from article_pipeline.style import get_preset, STYLE_TO_HUMANIZER
from article_pipeline.review.ai_detection import (
    CORE_PATTERNS, STRUCTURAL_PATTERNS,
    HEAVY_TAGS, FILLER_TAGS, LIGHT_TAGS,
    check_ai_patterns,
    check_humanizer_quality,
)
from article_pipeline.review.geo import check_geo
from article_pipeline.review.value_density import assess_value_density
from article_pipeline.review.dbs_ai_check import (
    DbsAIChecker,
    check_ai_fingerprint,
    generate_ai_report,
)
from article_pipeline.topic_filter import (
    BenchmarkTopicFilter,
    BenchmarkFilterResult,
    TopicFilter,
)
from article_pipeline.review.dbs_resonate import (
    ResonanceChecker,
    ResonanceReport,
    check_resonance,
    generate_resonance_report,
)
from article_pipeline.review.style_compliance import (
    StyleComplianceChecker,
    ComplianceReport,
    check_style_compliance,
    generate_compliance_report,
)

# Existing checks（word count，format，facts，fabrication，semantic）

def check_word_count(text: str, tier: str = "A") -> dict:
    chars = len(re.sub(r"[\s\n\r\d\W]", "", text))
    min_chars = {"A": 1000, "B": 2000, "C": 3000}.get(tier, 1000)
    passed = chars >= min_chars
    result = {"pass": passed, "chars": chars, "min_required": min_chars}
    if not passed:
        result["reason"] = "too_short"
    return result


def check_format(text: str) -> dict:
    has_h2 = bool(re.search(r"^##\s", text, re.MULTILINE))
    has_intro = len(text.split("\n\n")[0]) > 30 if text else False
    paragraphs = [p for p in text.split("\n\n") if len(p.strip()) > 30]
    para_count = len(paragraphs)
    return {"has_h2": has_h2, "has_intro": has_intro, "para_count": para_count,
            "pass": has_h2 and para_count >= 4}


def check_facts(article: str, research_note: str) -> dict:
    claim_patterns = re.findall(
        r"(?:根据|据|数据显示|研究表明|统计|报告)([^。.!！?\n]{10,80})", article)
    issues = []
    for claim in claim_patterns:
        if claim[:10] not in research_note:
            issues.append({"claim": claim, "issue": "source_not_in_research"})
    return {"claims_found": len(claim_patterns), "unverified": len(issues),
            "issues": issues, "pass": True}  # advisory only — fabrication check is the hard gate


def check_fabrication(article: str, research_note: str) -> dict:
    flags = []
    urls_in_article = set(re.findall(r'https?://[^\s\)\]"]+', article))
    # Exclude RFC 2606 reserved example domains and placeholder URLs in code
    urls_in_article = {u for u in urls_in_article
                       if not re.search(r'example\.(com|org|net|edu)', u)
                       and not re.search(r'your-site\.com|yoursite\.com|my-?site\.com|mywebsite\.com|localhost|127\.0\.0\.1', u)
                       and not re.search(r'placeholder|dummy|test\.local|wp-json/myplugin', u)
                       and not re.search(r'^https?://[a-zA-Z0-9_-]+[;,]?\s*$', u)
                       and not re.search(r'backend|upstream|server_name|proxy_pass', u)}
    urls_in_research = set(re.findall(r'https?://[^\s\)\]"]+', research_note))
    extra_urls = urls_in_article - urls_in_research
    if extra_urls:
        flags.append({"type": "fabricated_urls", "count": len(extra_urls),
                       "examples": list(extra_urls)[:3]})
    bare_domain_refs = re.findall(
        r'(?:根据|据|按照|来自|参考)([a-zA-Z0-9][-a-zA-Z0-9]*\.(?:com|cn|io|org|net|cc|co|dev|ai|app|site))',
        article)
    for domain in bare_domain_refs:
        if domain not in research_note:
            flags.append({"type": "bare_domain_citation", "domain": domain})
    fake_stat_patterns = re.findall(
        r'(?:达[到至]|超过?|约|近|高达?|低至|仅|占)(\s*\d+(?:\.\d+)?\s*[%％倍亿万千百])(?!.*ref)',
        article)
    for stat in fake_stat_patterns[:10]:
        st = stat.strip()
        # Normalize spaces for comparison (regex captures "10 万" but we check "10万")
        st_norm = re.sub(r'\s+', '', st)
        if st not in research_note and st_norm not in research_note:
            # Skip layout/design percentages
            layout_terms = r'(?:占|宽度|高度|比例|留白|边距|内边距|列|栏|图片|内容区|封面|栅格|网格)'
            if re.search(layout_terms + r'\s*' + re.escape(st), article) or \
               re.search(re.escape(st) + r'\s*(?:的)?\s*' + layout_terms, article):
                continue
            # Skip well-known benchmark stats (Google page speed, CDN savings, etc.)
            known_stats = {
                '32%', '53%', '70%', '70%~80%', '10%', '20%',
                '1秒', '3秒', '10万', '10 万', '100ms', '200ms',
                '1亿', '1 亿', '10亿', '10 亿',
            }
            if st in known_stats or st_norm in known_stats:
                continue
            # Rough comparison multipliers (e.g. "快6倍") are not fabricated stats
            if re.search(r'^\d+\s*倍$', st_norm):
                continue
            flags.append({"type": "unverifiable_stat", "stat": st})
    named_sources = re.findall(
        r'(?:据|根据|按照)((?:[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*|[一-鿿]{2,8})(?:公司|团队|实验室|研究院|中心|部门|平台|网站|博客|报告|数据|统计|研究|调查|分析))',
        article)
    for src in named_sources:
        if src[:4] not in research_note and src not in research_note:
            flags.append({"type": "unverifiable_source", "source": src})
    person_claims = re.findall(
        r'([一-鿿]{2,4})(?:认为|指出|表示|强调|补充说|分析称)', article)
    for name in person_claims:
        # Skip non-person words caught by the broad pattern
        if name in ('手册', '反复', '文档', '指南', '报告', '说明', '规范',
                     '标准', '协议', '接口', '方法', '教程', '我们', '他们',
                     '这里', '上面', '下面', '前面', '后面', '当前',
                     '句话', '句话值得', '所有人', '每个人', '很多人',
                     '没有', '没有', '一个', '几个', '一些', '少数'):
            continue
        if name not in research_note:
            flags.append({"type": "unverifiable_person", "name": name})
    score = max(0, 10 - len(flags) * 2)
    return {"fabrication_flags": len(flags), "details": flags[:10],
            "pass": len(flags) <= 2, "score": score}


# Terminology violations

WP_TERM_VIOLATIONS = [
    # Only catch standalone "块编辑器/块主题" — not "区块编辑器/区块主题"
    (r'(?<!区)块编辑器', '应为"区块编辑器"'),
    (r'(?<!区)块主题', '应为"区块主题"'),
    (r'以块为(?:单位|核心|基础|单元|内容)', '应为"以区块为..."'),
    # Catch standalone 块 used as WP concept, but NOT in generic phrases like "一块/两块/是块"
    (r'(?<![区模板块冰积石砖地方法一俩两三几])块(?=(?:编辑器|主题|模式|样式|为))', '应为"区块"'),
]


def check_content_fact_reference(article: str, research_note: str) -> dict:
    """Cross-reference facts in article against research note.

    For TIER_EXTERNAL articles, every number, URL, date, price, and novel
    product name in the article should be traceable to the research note.
    """
    rn_norm = research_note.lower().replace(' ', '').replace('\n', '')
    flags = []

    # 1. Numbers with units (%, 倍, 亿, 万, 千, 元, $, ¥, etc.)
    number_unit = re.findall(
        r'(\d+(?:\.\d+)?\s*(?:[%％倍亿万千米秒个项条款次届版年月日]|[A-Za-z]{2,}))',
        article
    )
    for num in number_unit:
        n = num.replace(' ', '')
        if n not in rn_norm:
            # Skip common non-factual numbers (years, version numbers, etc.)
            if re.match(r'^\d{4}年', n) or re.match(r'^\d+\.\d+\.\d+', n):
                continue
            flags.append({"type": "unreferenced_number", "value": num})

    # 2. URLs
    urls_in_article = set(re.findall(r'https?://[^\s\)\]"\',]+', article))
    urls_in_article = {u for u in urls_in_article
                       if not re.search(r'example\.(com|org|net)', u)
                       and not re.search(r'localhost|127\.0\.0\.1|placeholder', u)}
    urls_in_research = set(re.findall(r'https?://[^\s\)\]"\',]+', research_note))
    for url in urls_in_article - urls_in_research:
        flags.append({"type": "url_not_in_source", "value": url})

    # 3. Dates (but skip "2026年" alone — that's current year context)
    dates = re.findall(
        r'(\d{4}\s*年\s*\d{1,2}\s*月|\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        article
    )
    for d in dates:
        d_norm = d.replace(' ', '')
        if d_norm not in rn_norm and len(d_norm) > 7:  # skip bare years
            flags.append({"type": "unreferenced_date", "value": d})

    # 4. Price patterns
    prices = re.findall(
        r'([$¥€£]\s*\d+(?:\.\d{2})?|\d+(?:\.\d{2})?\s*(?:元|美元)(?:/月|/年|/站点)?)',
        article
    )
    for p in prices:
        p_norm = p.replace(' ', '')
        if p_norm not in rn_norm:
            flags.append({"type": "unreferenced_price", "value": p})

    score = max(0, 10 - len(flags) * 1.5)
    return {
        "flags": len(flags),
        "details": flags[:15],
        "pass": len(flags) <= 3,
        "score": round(score, 1),
    }


def check_terminology(article: str) -> dict:
    """Check for WordPress terminology violations. Context-aware — skips explanatory parentheticals."""
    flags = []
    for pattern, fix in WP_TERM_VIOLATIONS:
        matches = re.findall(pattern, article)
        for m in matches[:5]:
            mt = str(m)
            # Skip if it's inside an explanatory parenthetical like "（Block Theme）"
            if re.search(r'[（(]' + re.escape(mt) + r'[）)]', article) or \
               re.search(r'简称\s*' + re.escape(mt), article):
                continue
            flags.append({"type": "term_violation", "match": mt[:60], "fix": fix})

    # English terms: only flag if used standalone (not in parenthetical explanation)
    # Action/Filter are proper WordPress API names — conventionally kept in English
    eng_terms = {
        r'\bBlock\b': '区块', r'\bFSE\b': '全站编辑',
        r'\bFull Site Editing\b': '全站编辑', r'\bHook\b': '钩子',
        r'\bPattern\b': '区块模式', r'\bShortcode\b': '短代码',
    }
    # If article has high density of WP dev terms, it's a technical article —
    # allow Hook/Action/Filter as they're the subject matter
    wp_api_terms = len(re.findall(
        r'\b(?:Hook|Action|Filter|Hooks|Actions|Filters'
        r'|Block|Blocks|Pattern|Patterns|Shortcode'
        r'|theme\.json|REST API|WP-CLI)\b', article))
    is_technical_article = wp_api_terms >= 3
    for pattern, zh in eng_terms.items():
        matches = re.findall(pattern, article)
        for m in matches[:3]:
            # Skip explanatory usage: "全站编辑（Full Site Editing，简称 FSE）"
            context_start = max(0, article.find(m) - 30)
            context = article[context_start:article.find(m) + len(m) + 30]
            if re.search(r'[（(].*' + re.escape(m) + r'.*[）)]', context) or \
               re.search(r'简称\s*' + re.escape(m), context):
                continue
            # In technical dev articles, Hook/Action/Filter are the topic, not errors
            if is_technical_article and m in ('Hook', 'Action', 'Filter',
                                               'Hooks', 'Actions', 'Filters',
                                               'Block', 'Blocks', 'Pattern',
                                               'Patterns', 'Shortcode'):
                continue
            flags.append({"type": "english_term", "match": m,
                          "fix": f'应使用中文"{zh}"'})

    return {
        "violations": len(flags),
        "details": flags[:12],
        "pass": len(flags) <= 2
    }


# Jargon and insider slang that alienates general readers.
# These are tech-circle loanwords，management buzzwords，and domain shorthand
# that ordinary WordPress developers would find opaque.
JARGON_BLACKLIST = [
    (r'银弹', '应为"万能方案"或直接描述具体方法'),
    (r'抓手', '应为"切入点/突破口/着手点"'),
    (r'对齐[^齐]', '应为"达成一致/同步"'),
    (r'颗粒度', '应为"细节/细化程度"'),
    (r'闭环', '应为"完整流程/端到端"'),
    (r'赋能', '应为"帮助/提升/增强"'),
    (r'底层逻辑', '应为"基本原理/核心机制"'),
    (r'打法', '应为"策略/方法"'),
    (r'组合拳', '应为"组合方案/综合手段"'),
    (r'护城河', '应为"竞争优势/壁垒"'),
    (r'落地', '应为"实施/执行/部署"'),
    (r'拉通', '应为"协调/打通"'),
    (r'倒逼', '应为"迫使/推动"'),
    (r'收割', '应为"获取/吸引"（指用户/流量时）'),
    (r'心智', '应为"认知/印象"（指用户认知时）'),
    (r'触达', '应为"接触到/传达给"'),
    (r'私域', '应为"自有渠道"'),
    (r'引爆', '应为"引发关注/推动传播"'),
    (r'出圈', '应为"突破原有受众/获得广泛关注"'),
    (r'天花板', '应为"上限/极限"（指能力上限时）'),
    (r'赛道', '应为"领域/方向"'),
    (r'降维打击', '应为"跨层次/碾压式竞争"'),
    (r'范式', '应为"模式/方式/框架"（非学术语境时）'),
    (r'解耦', '应为"分离/拆分/解除依赖"（非软件架构语境时）'),
    (r'幂等', '应为"可重复执行/结果一致"（非API/数据库语境时）'),
    (r'鲁棒性', '应为"稳定性/健壮性/容错能力"'),
    (r'正交', '应为"相互独立/不重叠"（非数学语境时）'),
    (r'原子性', '应为"不可分割/全有或全无"（非数据库/并发语境时）'),
    (r'开箱即用', '应为"安装即用/无需配置"'),
]


COCOBOOK_API = load_config().get("mcp", {}).get("base_url", "http://192.168.1.230:8087")


def check_jargon(article: str) -> dict:
    """Catch tech-circle jargon, management buzzwords, and insider slang."""
    # Detect if article is deeply technical — allow standard CS terms
    tech_signals = len(re.findall(
        r'\b(?:API|REST|HTTP|JSON|SQL|PHP|CLI|SDK|CRUD|OOP|MVC|ORM'
        r'|数据库|微服务|容器|分布式|异步|并发|事务|序列化|端点|回调'
        r'|缓存|代理|负载均衡|命名空间)\b', article))
    is_deeply_technical = tech_signals >= 3
    technical_jargon = {'解耦', '幂等', '原子性', '正交'}

    flags = []
    for pattern, fix in JARGON_BLACKLIST:
        for m in re.finditer(pattern, article):
            # Skip if inside code block
            line_start = article.rfind('\n', 0, m.start()) + 1
            if article[line_start:line_start+4] in ('```', '    '):
                continue
            mt = m.group()
            # Allow standard CS terms in deeply technical articles
            if is_deeply_technical and any(t in mt for t in technical_jargon):
                continue
            # Business genres: allow standard launch/marketing vocabulary
            business_signals = len(re.findall(
                r'(?:发布|上线|推出|新版本|产品|用户|客户|下载|安装|定价|免费|付费|优惠|'
                r'活动|购买|升级|迁移|注册|登录)', article))
            is_business_genre = business_signals >= 5
            business_ok = {'落地', '打法', '出圈', '引爆', '收割'}
            if is_business_genre and mt in business_ok:
                continue
            flags.append({
                "type": "jargon",
                "match": mt[:40],
                "fix": fix
            })

    return {
        "violations": len(flags),
        "details": flags[:15],
        "pass": len(flags) <= 2
    }


def check_dbs_ai(article: str) -> dict:
    """dbs-ai-check: 22 AI 特征检测

    Returns:
        {
            "score": 0-10,
            "hits": int,
            "strong": int,
            "medium": int,
            "weak": int,
            "details": list[dict],
            "pass": bool
        }
    """
    checker = DbsAIChecker(article)
    hits = checker.check_all()

    strong = sum(1 for h in hits if h.severity == "strong")
    medium = sum(1 for h in hits if h.severity == "medium")
    weak = sum(1 for h in hits if h.severity == "weak")

    # 评分：强信号 -2 分，中信号 -1 分，弱信号 -0.5 分
    score = 10 - (strong * 2) - (medium * 1) - (weak * 0.5)
    score = max(0, min(10, score))

    details = []
    for hit in hits[:10]:  # 最多返回 10 处
        details.append({
            "feature_id": hit.feature_id,
            "feature_name": hit.feature_name,
            "severity": hit.severity,
            "text": hit.text[:80],
            "reason": hit.reason[:100],
        })

    return {
        "score": round(score, 1),
        "hits": len(hits),
        "strong": strong,
        "medium": medium,
        "weak": weak,
        "details": details,
        "pass": score >= 6.0
    }


def _extract_claims(article: str) -> list[str]:
    sentences = re.split(r'[。.！!？?\n]', article)
    claims = []
    tech_indicators = (
        r'(?:性能|架构|配置|优化|部署|安全|插件|主题|API|数据库|缓存'
        r'|服务器|容器|Docker|WordPress|Nginx|PHP|MySQL|Redis'
        r'|版本|更新|升级|兼容|支持|功能|模块|组件|接口)'
    )
    for s in sentences:
        s = s.strip()
        if len(s) < 20 or len(s) > 150:
            continue
        if s.startswith('#') or s.startswith('**') or s.startswith('-'):
            continue
        if re.match(r'^[选咱你我]的', s) or '像选' in s[:10]:
            continue
        if re.search(tech_indicators, s):
            claims.append(s)
    return claims[:8]


def check_semantic_facts(article: str, threshold: float = 0.9) -> dict:
    claims = _extract_claims(article)
    if not claims:
        return {"verified": 0, "unverified": 0, "details": [], "pass": True}
    verified, unverified, api_errors = [], [], 0
    for claim in claims:
        try:
            resp = requests.get(
                f"{COCOBOOK_API}/recommend",
                params={"q": claim, "limit": 3},
                timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("recommendations", [])
            if results and results[0].get("score", 99) < threshold:
                verified.append({"claim": claim[:80], "evidence": results[0].get("claim", "")[:80],
                                 "score": results[0].get("score", 0)})
            else:
                unverified.append({"claim": claim[:80]})
        except (requests.RequestException, json.JSONDecodeError):
            api_errors += 1

    api_down = (api_errors > 0 and len(verified) == 0)
    return {"verified": len(verified), "unverified": len(unverified),
            "details": unverified[:8], "verified_details": verified[:5],
            "pass": api_down or len(unverified) <= 3,
            "total_claims": len(claims)}


# Scoring and suggestions

def compute_overall_score(results: dict) -> float:
    """Weighted overall quality score from review results."""
    weights = {"ai_check": 0.10, "dbs_ai": 0.15, "format": 0.05, "fabrication": 0.15,
               "cross_reference": 0.10, "semantic_facts": 0.08,
               "word_count": 0.05, "humanizer": 0.14, "jargon": 0.10, "style_compliance": 0.08}
    # GEO is advisory — not in weighted score
    cross_ref = results.get("cross_reference")
    scores = {
        "ai_check": results.get("ai_check", {}).get("score", 0),
        "dbs_ai": results.get("dbs_ai", {}).get("score", 5),
        "format": 7.0 if results.get("format", {}).get("pass") else 3.0,
        "fabrication": results.get("fabrication", {}).get("score", 0),
        "cross_reference": cross_ref.get("score", 10) if cross_ref else 10,
        "semantic_facts": 8.0 if results.get("semantic_facts", {}).get("pass") else 4.0,
        "word_count": 7.0 if results.get("word_count", {}).get("pass") else 3.0,
        "humanizer": (results.get("humanizer", {}).get("total", 25) / 50) * 10,
        "jargon": 10.0 if results.get("jargon", {}).get("pass") else 4.0,
        "style_compliance": results.get("style_compliance", {}).get("overall_score", 5),
    }
    return round(sum(scores[k] * weights[k] for k in weights), 1)


def generate_revision_suggestions(results: dict) -> list[dict]:
    """Generate structured revision suggestions from review results."""
    suggestions = []

    ai = results.get("ai_check", {})
    ai_flags = ai.get("flags", [])
    not_x_but_y_flags = [f for f in ai_flags if f.get("pattern") in
                          ("translation_not_x_but_y", "translation_not_x_is_y")]
    other_flags = [f for f in ai_flags if f.get("pattern") not in
                    ("translation_not_x_but_y", "translation_not_x_is_y")]

    if not_x_but_y_flags:
        count = not_x_but_y_flags[0].get("count", 1)
        suggestions.append({
            "category": "ai_tone", "priority": "high",
            "issue": f"'不是...而是' 出现 {count} 次，AI 高频模板句式",
            "fix": ("替换方案(推荐顺序): "
                    "1) '并非X，Y才是关键/核心/要点' "
                    "2) '与其说X，不如说Y' "
                    "3) 'X的反面才是重点：Y' "
                    "4) 'X只是表面，真正起作用的是Y' "
                    "5) '别被X误导，Y才决定结果' "
                    "6) '光看X不够，Y才是决定因素' "
                    "7) 直接去掉对比结构，把Y说清楚就行")
        })

    # Humanizer-zh specific patterns with targeted fixes
    hz_heavy = [f for f in ai_flags if f.get("pattern", "").startswith("hz_") and f.get("pattern") in HEAVY_TAGS]
    if hz_heavy:
        fixes = []
        for f in hz_heavy[:4]:
            tag = f.get("pattern", "")
            match = f.get("match", "")
            if "exaggerated" in tag:
                fixes.append(f"'{match}' → 删除夸大词，直接陈述事实")
            elif "promo" in tag:
                fixes.append(f"'{match}' → 去宣传腔，用平实语言描述")
            elif "bright_future" in tag or "positive_conclusion" in tag:
                fixes.append(f"'{match}' → 用具体事实代替空洞展望")
            elif "cliche_challenges" in tag:
                fixes.append(f"'{match}' → 要么具体说挑战是什么，要么删掉这段")
            elif "chatbot" in tag:
                fixes.append(f"'{match}' → 删除，这是聊天机器人残留")
            else:
                fixes.append(f"'{match}' → 重写该句")
        if fixes:
            suggestions.append({
                "category": "ai_tone", "priority": "high",
                "issue": f"Humanizer-zh 检出 {len(hz_heavy)} 处 AI 痕迹",
                "fix": "; ".join(fixes)
            })

    if other_flags and not ai.get("pass", True):
        flagged = [f"'{f.get('match', '')}'" if f.get("match") else f.get("pattern", "")
                   for f in other_flags[:5]]
        suggestions.append({
            "category": "ai_tone", "priority": "medium",
            "issue": f"AI pattern score {ai.get('score', '?')}/10, {len(other_flags)} issues",
            "fix": f"重写标记短语: {', '.join(flagged)}"
        })

    # Humanizer 5-dimension low scores
    hz = results.get("humanizer", {})
    if hz and not hz.get("pass", True):
        dims = hz.get("dimensions", {})
        weak = [(k, v["score"]) for k, v in dims.items() if v["score"] < 6]
        if weak:
            weak_desc = ", ".join(f"{k}({v}/10)" for k, v in weak)
            suggestions.append({
                "category": "quality", "priority": "medium",
                "issue": f"Humanizer 质量评分 {hz.get('total', '?')}/50, 弱项: {weak_desc}",
                "fix": "针对性改进弱项维度：直接性→删填充；节奏→变化句长；信任度→具体来源；真实性→去宣传腔；精炼度→删冗余"
            })

    fab = results.get("fabrication", {})
    if not fab.get("pass", True):
        details = fab.get("details", [])
        issues_desc = []
        for d in details[:3]:
            dtype = d.get("type", "")
            if dtype == "fabricated_urls":
                issues_desc.append(f"伪造URL: {d.get('examples', [])}")
            elif dtype == "bare_domain_citation":
                issues_desc.append(f"裸域名引用: {d.get('domain', '')}")
            elif dtype == "unverifiable_stat":
                issues_desc.append(f"未验证数据: {d.get('stat', '')}")
            elif dtype == "unverifiable_source":
                issues_desc.append(f"未验证来源: {d.get('source', '')}")
            elif dtype == "unverifiable_person":
                issues_desc.append(f"未验证人名: {d.get('name', '')}")
        suggestions.append({
            "category": "fabrication", "priority": "high",
            "issue": f"发现 {fab.get('fabrication_flags', 0)} 处编造嫌疑",
            "fix": f"删除或验证: {'; '.join(issues_desc)}"
        })

    sem = results.get("semantic_facts", {})
    if sem and not sem.get("pass", True):
        unverified = [u.get("claim", "") for u in sem.get("details", [])[:3]]
        suggestions.append({
            "category": "fact_verification", "priority": "medium",
            "issue": f"{sem.get('unverified', 0)}/{sem.get('total_claims', 0)} 条声明未验证",
            "fix": f"补充来源或删除: {'; '.join(unverified)}"
        })

    fmt = results.get("format", {})
    if not fmt.get("pass", True):
        missing = []
        if not fmt.get("has_h2"):
            missing.append("H2 标题")
        if fmt.get("para_count", 0) < 4:
            missing.append(f"仅 {fmt.get('para_count', 0)} 段(需>=4)")
        suggestions.append({
            "category": "format", "priority": "low",
            "issue": "结构问题",
            "fix": f"添加: {', '.join(missing)}"
        })

    wc = results.get("word_count", {})
    if not wc.get("pass", True):
        if wc.get("reason") == "too_short":
            suggestions.append({
                "category": "length", "priority": "medium",
                "issue": f"太短: {wc.get('chars', 0)} 字",
                "fix": f"扩充到至少 {wc.get('min_required', 1000)} 字"
            })

    # dbs-ai-check suggestions
    dbs = results.get("dbs_ai", {})
    # 如果 dbs_ai 不通过，或者有 hits 且分数 < 8.0，则生成建议
    if dbs and (not dbs.get("pass", True) or (dbs.get("hits", 0) > 0 and dbs.get("score", 10) < 8.0)):
        strong = dbs.get("strong", 0)
        medium = dbs.get("medium", 0)
        weak = dbs.get("weak", 0)
        details = dbs.get("details", [])

        # 按特征分组建议
        feature_fixes = {
            "堵住所有反驳": "只留真的被人问过的反驳，删除想象出来的",
            "匀速排比": "把最想说的那一句加长，打破均匀节奏",
            "让步模板反复用": "第二遍之后换说法或直接跳过",
            "命名仪式": "只留真正精准的名字，删掉仪式感",
            "不是X是Y高密度": "只留一次翻转，其他直接说Y",
            "开头三件套": "从真正想让读者知道的事开始说",
            "连接词过度使用": "删掉一半，读者自己能感觉到话锋变了",
            "翻译腔": "用嘴上会说的词来写",
            "虚假讲故事": "换一个真实的经历，或补充具体细节",
            "结尾祝福": "删掉最后一段，文章已经结束了",
            "过拟合深刻": "实操问题不需要升维到哲学层面",
        }

        fix_list = []
        for d in details[:5]:
            name = d.get("feature_name", "")
            fix = feature_fixes.get(name, d.get("reason", "重写该句")[:50])
            fix_list.append(f"{name}: {fix}")

        suggestions.append({
            "category": "ai_fingerprint",
            "priority": "high" if strong > 0 else "medium",
            "issue": f"dbs-ai-check 检出 {dbs.get('hits', 0)} 处 AI 指纹（🔴{strong}强 ⚠️{medium}中 💡{weak}弱），评分 {dbs.get('score', 0)}/10",
            "fix": "; ".join(fix_list)
        })

    # Jargon/insider slang suggestions
    jargon = results.get("jargon", {})
    if jargon and not jargon.get("pass", True):
        for d in jargon.get("details", []):
            suggestions.append({
                "category": "jargon", "priority": "medium",
                "issue": f"圈内黑话: '{d.get('match', '')}' — 普通读者看不懂",
                "fix": d.get("fix", "换为通俗表达")
            })

    # GEO suggestions
    geo = results.get("geo", {})
    if geo and not geo.get("pass", True):
        geo_sugs = geo.get("suggestions", [])
        suggestions.extend(geo_sugs)

    return suggestions


def compute_publish_gate(
    value_density_result: dict,
    has_differentiation: bool,
    has_unique_claims: bool,
) -> dict:
    """聚合三个信号，输出发布决策。

    Args:
        value_density_result: assess_value_density() 返回的结果
        has_differentiation: differentiation 是否非空且具体（大于等于20字）
        has_unique_claims: unique_claims 是否非空（大于等于1条）

    Returns:
        {
            "decision": "pass" | "needs_human" | "fail",
            "reason": str,
            "signals": {
                "value_density": float,
                "differentiation": bool,
                "unique_claims": bool,
            },
            "blocking_reasons": list[str],
        }
    """
    overall_score = value_density_result.get("overall_score", 0)
    blocking_reasons = []

    # 硬拦截：value_density < 4.0（slop）
    if overall_score < 4.0:
        signals = {
            "value_density": overall_score,
            "differentiation": has_differentiation,
            "unique_claims": has_unique_claims,
        }
        return {
            "decision": "fail",
            "reason": f"内容密度不足（{overall_score}/10 < 4.0），疑似 slop，不可发布",
            "signals": signals,
            "blocking_reasons": [f"内容密度 {overall_score}/10 低于 4.0 门槛"],
        }

    # 发布必要条件检查
    # 至少满足一条：value_density >= 6.0 或 differentiation 或 unique_claims
    has_value_gate = overall_score >= 6.0
    publish_conditions = {
        "value_density": overall_score,  # 存储实际分数，而不是布尔值
        "differentiation": has_differentiation,
        "unique_claims": has_unique_claims,
    }

    satisfied = sum(publish_conditions.values())

    # fail: value_density 4.0~6.0 但无任何发布必要条件
    if overall_score < 6.0 and not has_differentiation and not has_unique_claims:
        signals = {
            "value_density": overall_score,
            "differentiation": has_differentiation,
            "unique_claims": has_unique_claims,
        }
        return {
            "decision": "needs_human",
            "reason": (
                f"内容密度 {overall_score}/10 处于边界区，"
                f"且无差异化说明和独到见解，需人工判断是否值得发布"
            ),
            "signals": signals,
            "blocking_reasons": [
                "内容密度低于 6.0 且无其他发布必要条件",
                "缺乏差异化说明（differentiation 为空或不足20字）" if not has_differentiation else None,
                "缺乏独到见解（unique_claims 为空）" if not has_unique_claims else None,
            ],
        }

    # pass: 至少满足一条发布必要条件
    satisfied_reasons = []
    if has_value_gate:
        satisfied_reasons.append(f"内容密度 {overall_score}/10 达标")
    if has_differentiation:
        satisfied_reasons.append("差异化说明具体（>=20字）")
    if has_unique_claims:
        satisfied_reasons.append("包含独到见解（>=1条unique claim）")

    # 重新构建 signals 确保返回实际分数
    signals = {
        "value_density": overall_score,
        "differentiation": has_differentiation,
        "unique_claims": has_unique_claims,
    }

    return {
        "decision": "pass",
        "reason": f"发布条件满足：{'；'.join(satisfied_reasons)}",
        "signals": signals,
        "blocking_reasons": [],
    }


def run_self_review(article: str, tier: str = "A",
                    research_note: str = "",
                    trust_tier: str = "TIER_INTERNAL",
                    category: str = "",
                    ddg_results: list[dict] | None = None,
                    research_output: dict | None = None,
                    differentiation: str = "") -> dict:
    """Run all self-review checks and return consolidated results."""
    ai_check = check_ai_patterns(article)
    dbs_ai = check_dbs_ai(article)  # dbs-ai-check: 22 AI 特征检测
    word_check = check_word_count(article, tier)
    format_check = check_format(article)
    fact_check = check_facts(article, research_note or "")
    fab_check = check_fabrication(article, research_note or "")
    sem_check = check_semantic_facts(article)
    humanizer = check_humanizer_quality(article)
    term_check = check_terminology(article)
    jargon_check = check_jargon(article)
    geo_check = check_geo(article, tier)
    # Style compliance check (风格遵循度)
    style_compliance_result = check_style_compliance(article)
    style_compliance = {
        "overall_score": style_compliance_result.overall_score,
        "dimensions": [
            {
                "name": d.name,
                "score": d.score,
                "status": d.status,
                "details": d.details,
                "evidence": d.evidence,
            }
            for d in style_compliance_result.dimensions
        ],
        "suggestions": style_compliance_result.suggestions,
    }
    # Value density check (slop detection)
    value_density = assess_value_density(article, research_output or {}, ddg_results or [])
    # Cross-reference fact check (TIER_EXTERNAL only)
    cross_ref = None
    if trust_tier == "TIER_EXTERNAL" and research_note:
        cross_ref = check_content_fact_reference(article, research_note)

    all_pass = all([
        ai_check.get("pass", False),
        dbs_ai.get("pass", True),  # dbs_ai 是软指标，不强制阻止发布
        word_check.get("pass", False),
        format_check.get("pass", False),
        fact_check.get("pass", True),
        fab_check.get("pass", True),
        True,  # semantic check is informational only — MCP can be unreliable
        humanizer.get("pass", True),
        term_check.get("pass", True),
        jargon_check.get("pass", True),
        cross_ref.get("pass", True) if cross_ref else True,
        # GEO is advisory — not a block for pass/fail
    ])

    # Hard gate: humanizer score < 30/50 → prose quality too poor to publish
    if humanizer.get("total", 0) < 30:
        all_pass = False

    # Soft gate: dbs_ai score < 4.0 → 严重 AI 味，警告
    dbs_ai_low = dbs_ai.get("score", 10) < 4.0

    results = {
        "ai_check": ai_check,
        "dbs_ai": dbs_ai,
        "word_count": word_check,
        "format": format_check,
        "facts": fact_check,
        "fabrication": fab_check,
        "semantic_facts": sem_check,
        "humanizer": humanizer,
        "terminology": term_check,
        "jargon": jargon_check,
        "geo": geo_check,
        "style_compliance": style_compliance,
        "value_density": value_density,
        "cross_reference": cross_ref,
        "overall_pass": all_pass and not dbs_ai_low,  # dbs_ai_low 时需要人工审查
        "dbs_ai_warning": dbs_ai_low,
    }

    # Style-humanizer alignment
    if category:
        style_vec = get_preset(category)
        results["style_coordinates"] = {
            "density": style_vec.density,
            "warmth": style_vec.warmth,
            "energy": style_vec.energy,
            "register": style_vec.register,
            "edge": style_vec.edge,
            "injection": style_vec.injection,
            "active": style_vec.active,
        }
        results["style_humanizer_map"] = {
            dim: {"humanizer_dim": hz_dim, "style_value": getattr(style_vec, dim)}
            for dim, hz_dim in STYLE_TO_HUMANIZER.items()
        }
        # 注意：style_humanizer_map 是参考映射（非因果关系）
        # 维度名称相似不代表风格指令会直接影响 humanizer 评分

    # Hard gate: "不是...而是..." — rate-based, genre-adjusted.
    # Opinion/comparison pieces naturally use contrast patterns; tutorials less so.
    article_len = len(article) if article else 0
    base_limit = max(3, int(article_len / 1000) + 1)
    opinion_signals = len(re.findall(
        r'(?:我认为|在我看来|真正的(?:问题|关键|核心)|选哪|该怎么选|要不要)'
        r'|(?:表面.*实则|实则|本质上|说到底)'
        r'|(?:我的|本站|实测|优化前|优化后|这一步|差距)'  # case-study markers
        r'|(?:你应该|开发者.*应该|为什么.*应该|不是.*更方便|改变了)'  # marketing markers
        , article))
    is_argumentative = opinion_signals >= 2
    not_x_limit = base_limit + 3 if is_argumentative else base_limit
    not_x_count = sum(f.get("count", 0) for f in ai_check.get("flags", [])
                      if f.get("pattern") in ("translation_not_x_but_y", "translation_not_x_is_y"))
    if not_x_count > not_x_limit:
        all_pass = False

    results["overall_score"] = compute_overall_score(results)
    results["suggestions"] = generate_revision_suggestions(results) if not all_pass else []

    # Publish gate: aggregate value_density + differentiation + unique_claims
    has_differentiation = len(differentiation or "") >= 20
    has_unique_claims = bool(research_output and research_output.get("unique_claims"))
    publish_gate = compute_publish_gate(
        value_density_result=value_density,
        has_differentiation=has_differentiation,
        has_unique_claims=has_unique_claims,
    )
    results["publish_gate"] = publish_gate

    return results


# Topic filtering，dbs-benchmark inspired 5-filter method

def filter_topic_by_benchmark(keyword: str,
                               category: str = "",
                               search_results: list[dict] = None) -> BenchmarkFilterResult:
    """选题五重过滤，dbs-benchmark 启发

    Args:
        keyword: 选题关键词
        category: 分类
        search_results: 搜索结果列表，格式：[{"title": str, "body": str}, ...]

    Returns:
        BenchmarkFilterResult
    """
    bf = BenchmarkTopicFilter(search_results=search_results or [])
    return bf.filter_topic(keyword, category)


def generate_topic_filter_report(keyword: str,
                                  category: str = "",
                                  search_results: list[dict] = None) -> str:
    """生成选题过滤报告

    Args:
        keyword: 选题关键词
        category: 分类
        search_results: 搜索结果列表

    Returns:
        Markdown 格式的报告
    """
    bf = BenchmarkTopicFilter(search_results=search_results or [])
    return bf.generate_report(keyword, category)


# Draft resonance check，dbs-resonate inspired 5-dimension diagnosis

def check_draft_resonance(draft: str, category: str = "") -> ResonanceReport:
    """文稿共鸣诊断

    Args:
        draft: 文稿内容
        category: 分类

    Returns:
        ResonanceReport
    """
    return check_resonance(draft, category)


def generate_resonance_diagnosis_report(draft: str, category: str = "") -> str:
    """生成文稿共鸣诊断报告

    Args:
        draft: 文稿内容
        category: 分类

    Returns:
        Markdown 格式的报告
    """
    return generate_resonance_report(draft, category)


# GEO（Generative Engine Optimization）checks，Frase 5-dimension model
