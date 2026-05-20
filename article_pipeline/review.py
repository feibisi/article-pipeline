"""Self-review module — fact check, AI detection, format, word count, semantic verification.

V2: Integrated Humanizer-zh 24 patterns + 5-dimension quality scoring.
Sources: CSDN AI味词库, Wikipedia "AI生成文的特征", Humanizer-zh (WikiProject AI Cleanup),
         53ai.com / Hello-SimpleAI / translate VM patterns, community observations.
"""
import json
import math
import re
import os

import requests
import yaml


def _load_config():
    config_path = os.path.expanduser("~/.config/article-pipeline/config.yaml")
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config if isinstance(config, dict) else {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


# ────────────────────────────────────────────────────────────────────
# AI-pattern vocabulary — Humanizer-zh 24 patterns + community corpus
# ────────────────────────────────────────────────────────────────────

CORE_PATTERNS = [
    # ── Cliché openings ──
    (r"在当今.{2,10}(?:时代|社会|世界)", "cliche_digital_era"),
    (r"随着.{2,12}的(?:发展|进步|普及|浪潮|推进|深入)", "cliche_with_development"),

    # ── Numbered transitions ──
    (r"首先.{0,8}其次.{0,8}(?:最后|再次|然后)", "numbered_first_second_last"),
    (r"^(?:首先|其次|再次|最后)[，,]", "numbered_transition_start"),

    # ── Summary clichés ──
    (r"总而言之", "summary_in_short"),
    (r"综上所述", "summary_to_conclude"),
    (r"总(?:的|体)来说", "summary_overall"),
    (r"归根结底", "summary_bottom_line"),
    (r"简而言之", "summary_briefly"),
    (r"从总体上看", "summary_from_overall"),

    # ── Filler phrases (AI loves these) ──
    (r"值得注意的是", "filler_worth_noting"),
    (r"不可忽视的是", "filler_cannot_ignore"),
    (r"必须指出的是", "filler_must_point_out"),
    (r"重要的是", "filler_important_is"),
    (r"可以认为", "filler_can_consider"),
    (r"这意味着", "filler_this_means"),
    (r"换句话说", "filler_in_other_words"),
    (r"具体来说", "filler_specifically"),
    (r"事实上", "filler_in_fact"),
    # Humanizer-zh Pattern 22: filler phrases
    (r"为了实现这一(?:目标|点)", "filler_to_achieve"),
    (r"由于.{2,8}的事实", "filler_due_to_fact"),
    (r"在这个时间点", "filler_at_this_point"),
    (r"具有.{2,8}的能力", "filler_has_ability"),

    # ── Translation-ese ──
    (r"毋庸置疑", "translation_undoubtedly"),
    (r"众所周知", "translation_as_we_know"),
    (r"不可否认", "translation_undeniable"),
    # "不是...而是" — AI high-frequency template, needs replacement
    (r"不是.{0,20}而是", "translation_not_x_but_y"),
    (r"不是.{0,20}(?<!而)是", "translation_not_x_is_y"),

    # ── Connector abuse ──
    (r"此外", "connector_furthermore"),
    (r"另一方面", "connector_on_other_hand"),
    (r"然而", "connector_however"),
    (r"因此", "connector_therefore"),
    (r"从而", "connector_thereby"),
    (r"因而", "connector_thus"),
    (r"基于此", "connector_based_on_this"),
    (r"鉴于", "connector_in_light_of"),
    (r"尤其是", "connector_especially"),
    (r"特别是", "connector_particularly"),

    # ── Overused qualifiers ──
    (r"一般来说", "qualifier_generally"),
    (r"显然", "qualifier_obviously"),
    (r"综合来看", "qualifier_comprehensively"),
    # Humanizer-zh Pattern 23: over-qualification
    (r"可以潜在地|可能被认为|产生一些影响", "over_qualifier"),

    # ── False structure words ──
    (r"作为结果", "struct_as_result"),
    (r"不仅.{0,15}而且", "struct_not_only_but_also"),

    # ── AI-invented compound words ──
    (r"模板海|插件海|功能海|数据海|组件海", "ai_word_X海"),
    (r"功能矩阵|环境矩阵|能力矩阵|设计矩阵", "ai_word_X矩阵"),
    (r"进化之路|必经之路|不二之选|终极之选", "ai_word_pseudo_profound"),

    # ══════════════════════════════════════════════════════════════════
    # Humanizer-zh patterns (integrated from SKILL.md)
    # ══════════════════════════════════════════════════════════════════

    # Pattern 1: 夸大意义 (exaggerated significance)
    (r"(?:标志着|见证了|凸显了?|彰显了?|象征着)", "hz_exaggerated_sig"),
    (r"为.{2,8}奠定基础", "hz_lay_foundation"),
    (r"关键转折点|不可磨灭的印记|深深植根于|至关重要的", "hz_milestone"),

    # Pattern 3: shallow -ing analysis (verb chains at sentence end)
    (r"反映了.{2,15}(?:趋势|格局|潮流|变化|联系|需求)", "hz_shallow_reflect"),

    # Pattern 4: promotional language
    (r"坐落于|充满活力的|令人叹为观止的|开创性的|必游之地|迷人的", "hz_promo_hyper"),
    (r"致力于|丰富的(?:文化|历史|自然)|自然之美", "hz_promo_puff"),

    # Pattern 5: vague attribution
    (r"行业报告显示|观察者指出|一些批评者认为", "hz_vague_attr"),
    (r"专家(?:普遍)?(?:认为|表示|指出)", "hz_vague_expert"),

    # Pattern 6: boilerplate "challenges and outlook"
    (r"尽管.{2,15}面临若干挑战", "hz_cliche_challenges"),
    (r"尽管存在这些挑战", "hz_cliche_despite"),

    # Pattern 8: copula avoidance (verbose "is" replacement)
    (r"(?:作为|充当).{2,12}(?:的体现|的证明|的提醒|的象征)", "hz_copula_avoid"),

    # Pattern 19: chatbot conversational residue
    (r"希望这对您有帮助|希望这些信息", "hz_chatbot_close"),
    (r"请告诉我|如果您需要", "hz_chatbot_prompt"),

    # Pattern 20: knowledge cutoff disclaimer
    (r"根据我(?:最后)?的训练(?:更新|数据)", "hz_chatbot_cutoff"),
    (r"虽然.{2,10}(?:细节|信息)(?:有限|稀缺)", "hz_chatbot_disclaimer"),

    # Pattern 24: generic positive conclusion
    (r"(?:光明的|美好的)(?:未来|前景)", "hz_bright_future"),
    (r"追求卓越的旅程|迈出了.{0,6}(?:重要|坚实|关键)(?:的一步|步伐)", "hz_positive_conclusion"),
    (r"不断演变的(?:格局|领域|生态)", "hz_evolving_landscape"),
    # Pattern 25: forced-colloquial — AI pretending to be casual
    (r"不铺垫了|说白了|死胡同|不废话|讲真|不绕弯子|直接告诉你", "hz_forced_casual"),
]

STRUCTURAL_PATTERNS = [
    (r"^(?:首先|其次|再次|最后|此外|另外|同时|另一方面)[，,]", "line_numbered_transition"),
    (r"^(?:总而言之|综上所述|总的来说|总体而言|综合来看|归根结底)[，,]", "line_summary_start"),
]


# ────────────────────────────────────────────────────────────────────
# Tag → weight classification
# ────────────────────────────────────────────────────────────────────

HEAVY_TAGS = {
    # Opening/summary clichés
    "numbered_first_second_last", "numbered_transition_start",
    "summary_in_short", "summary_to_conclude", "summary_overall",
    "summary_bottom_line", "summary_briefly", "summary_from_overall",
    "cliche_digital_era", "cliche_with_development",
    "struct_not_only_but_also",
    "ai_word_X海", "ai_word_X矩阵", "ai_word_pseudo_profound",
    # Humanizer-zh heavy: exaggerated significance, promotional, chatbot residue
    "hz_exaggerated_sig", "hz_milestone", "hz_lay_foundation",
    "hz_promo_hyper", "hz_cliche_challenges", "hz_cliche_despite",
    "hz_chatbot_close", "hz_chatbot_cutoff", "hz_chatbot_disclaimer",
    "hz_bright_future", "hz_positive_conclusion", "hz_evolving_landscape",
    "hz_copula_avoid", "hz_forced_casual",
}

FILLER_TAGS = {
    # Original fillers
    "filler_worth_noting", "filler_cannot_ignore", "filler_must_point_out",
    "filler_important_is", "filler_can_consider", "filler_this_means",
    "filler_in_other_words", "filler_specifically", "filler_in_fact",
    "translation_undoubtedly", "translation_as_we_know", "translation_undeniable",
    # Humanizer-zh fillers
    "filler_to_achieve", "filler_due_to_fact", "filler_at_this_point",
    "filler_has_ability",
    "over_qualifier",
    "hz_vague_attr", "hz_vague_expert",
    "hz_promo_puff", "hz_shallow_reflect",
    "hz_chatbot_prompt",
}

LIGHT_TAGS = {
    # Connectors and qualifiers (lower weight — some are valid in moderation)
    "connector_furthermore", "connector_on_other_hand", "connector_however",
    "connector_therefore", "connector_thereby", "connector_thus",
    "connector_based_on_this", "connector_in_light_of",
    "connector_especially", "connector_particularly",
    "qualifier_generally", "qualifier_obviously",
    "qualifier_comprehensively", "struct_as_result",
    # Valid Chinese patterns — frequency counter only
    "translation_not_x_but_y", "translation_not_x_is_y",
    "connector_for_example",
}


def check_ai_patterns(text: str) -> dict:
    """Check article for AI-generated text patterns. Returns score 0-10 and flags."""
    flags = []
    score = 10

    for pattern, tag in CORE_PATTERNS:
        matches = re.findall(pattern, text)
        if matches:
            flags.append({"pattern": tag, "count": len(matches), "match": matches[0][:60]})
            if tag in HEAVY_TAGS:
                score -= len(matches) * 2.0
            elif tag in FILLER_TAGS:
                score -= len(matches) * 1.0
            elif tag in LIGHT_TAGS:
                score -= len(matches) * 0.3

    for pattern, tag in STRUCTURAL_PATTERNS:
        matches = re.findall(pattern, text, re.MULTILINE)
        if matches:
            flags.append({"pattern": tag, "count": len(matches), "type": "structural"})
            score -= len(matches) * 1.5

    # Paragraph length uniformity
    paragraphs = [p for p in text.split("\n\n") if len(p.strip()) > 50]
    if len(paragraphs) >= 4:
        lengths = [len(p) for p in paragraphs]
        avg_len = sum(lengths) / len(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        cv = (variance ** 0.5) / avg_len if avg_len > 0 else 0
        if cv < 0.15:
            flags.append({"pattern": "uniform_paragraphs", "cv": round(cv, 3)})
            score -= 3

    # Humanizer-zh Pattern 10: three-item grouping (A、B和C of same structure)
    three_item = re.findall(
        r"(?:和|与|以及).{1,8}(?:、|，).{1,8}(?:和|与|以及).{1,8}(?:，|。|的)",
        text
    )
    if len(three_item) >= 3:
        flags.append({"pattern": "hz_three_item_rule", "count": len(three_item)})
        score -= 1.5

    return {
        "score": max(0, round(score, 1)),
        "flags": flags,
        "pass": score >= 6
    }


# ────────────────────────────────────────────────────────────────────
# 5-dimension quality scoring (Humanizer-zh)
# ────────────────────────────────────────────────────────────────────

def check_humanizer_quality(text: str) -> dict:
    """5-dimension quality scoring: 直接性/节奏/信任度/真实性/精炼度 (each 1-10, total /50)."""
    sentences = [s.strip() for s in re.split(r'[。.！!？?\n]', text) if len(s.strip()) > 5]

    # 1. 直接性 (Directness) — penalize filler openings, roundabout structure
    direct_deductions = 0
    direct_flags = []
    filler_openings = re.findall(
        r"(?:值得注意的是|不可忽视的是|必须指出的是|可以认为|事实上"
        r"|为了实现这一(?:目标|点)|由于.{2,6}的事实|在这个时间点)", text)
    if filler_openings:
        direct_deductions += len(filler_openings) * 1.5
        direct_flags.append(f"{len(filler_openings)} filler openings")
    roundabout = re.findall(
        r"(?:具有.{2,8}的能力|可以潜在地|可能被认为|作为.{2,8}(?:的体现|的证明))", text)
    if roundabout:
        direct_deductions += len(roundabout) * 1.0
        direct_flags.append(f"{len(roundabout)} roundabout expressions")
    directness = max(1, 10 - int(direct_deductions))

    # 2. 节奏 (Rhythm) — sentence length variation (coefficient of variation)
    if len(sentences) >= 4:
        lengths = [len(s) for s in sentences]
        avg = sum(lengths) / len(lengths)
        std = (sum((l - avg) ** 2 for l in lengths) / len(lengths)) ** 0.5
        cv = std / avg if avg > 0 else 0
        # Good rhythm: cv 0.3-0.6, bad: cv < 0.2 or > 0.8
        if cv < 0.15:
            rhythm = 2
        elif cv < 0.25:
            rhythm = 5
        elif cv < 0.5:
            rhythm = 9
        elif cv < 0.7:
            rhythm = 7
        else:
            rhythm = 5
    else:
        rhythm = 6  # not enough data

    # 3. 信任度 (Trust) — penalize vague attribution, over-qualification
    trust_deductions = 0
    trust_flags = []
    vague = re.findall(
        r"(?:行业报告显示|观察者指出|专家(?:普遍)?(?:认为|表示)|一些批评者认为"
        r"|根据我(?:最后)?的训练(?:更新|数据))", text)
    if vague:
        trust_deductions += len(vague) * 2.0
        trust_flags.append(f"{len(vague)} vague attributions")
    qual = re.findall(r"(?:可以潜在地|可能被认为|产生一些影响)", text)
    if qual:
        trust_deductions += len(qual) * 1.0
        trust_flags.append(f"{len(qual)} over-qualifications")
    trust = max(1, 10 - int(trust_deductions))

    # 4. 真实性 (Authenticity) — penalize promotional, cliché, chatbot residue
    auth_deductions = 0
    auth_flags = []
    promo = re.findall(
        r"(?:标志着|见证了|凸显了?|彰显了?|象征着|充满活力的|令人叹为观止的"
        r"|开创性的|迷人的|必游之地)", text)
    if promo:
        auth_deductions += len(promo) * 1.0
        auth_flags.append(f"{len(promo)} promotional/cliché words")
    chatbot = re.findall(
        r"(?:希望这对您有帮助|请告诉我|如果您需要|好问题)", text)
    if chatbot:
        auth_deductions += len(chatbot) * 2.5
        auth_flags.append(f"{len(chatbot)} chatbot residue")
    generic = re.findall(
        r"(?:光明的未来|追求卓越的旅程|迈出了.{0,4}(?:重要|坚实)的一步"
        r"|不断演变的(?:格局|领域))", text)
    if generic:
        auth_deductions += len(generic) * 1.5
        auth_flags.append(f"{len(generic)} generic conclusions")
    authenticity = max(1, 10 - int(auth_deductions))

    # 5. 精炼度 (Conciseness) — penalize padding, redundant phrasing
    concise_deductions = 0
    concise_flags = []
    padding = re.findall(
        r"(?:为了实现这一(?:目标|点)|由于.{2,6}的事实|在这个时间点|具有.{2,6}的能力)", text)
    if padding:
        concise_deductions += len(padding) * 1.0
        concise_flags.append(f"{len(padding)} padding phrases")
    # Check for consecutive sentences starting with same transition
    transition_starts = re.findall(
        r"^(?:此外|然而|因此|从而|同时|另一方面)[，,]", text, re.MULTILINE)
    if len(transition_starts) >= 4:
        concise_deductions += (len(transition_starts) - 3) * 0.5
        concise_flags.append(f"{len(transition_starts)} connector-started sentences")
    conciseness = max(1, 10 - int(concise_deductions))

    total = directness + rhythm + trust + authenticity + conciseness
    dimensions = {
        "直接性": {"score": directness, "flags": direct_flags},
        "节奏": {"score": rhythm, "flags": []},
        "信任度": {"score": trust, "flags": trust_flags},
        "真实性": {"score": authenticity, "flags": auth_flags},
        "精炼度": {"score": conciseness, "flags": concise_flags},
    }

    return {
        "total": total,
        "max": 50,
        "dimensions": dimensions,
        "grade": "优秀" if total >= 45 else "良好" if total >= 35 else "需修订",
        "pass": total >= 35,
    }


# ────────────────────────────────────────────────────────────────────
# Existing checks (word count, format, facts, fabrication, semantic)
# ────────────────────────────────────────────────────────────────────

def check_word_count(text: str, tier: str = "A") -> dict:
    chars = len(re.sub(r"[\s\n\r\d\W]", "", text))
    if tier == "A":
        min_chars, max_chars = 1000, 4000
    else:
        min_chars, max_chars = 2000, 8000
    if chars < min_chars:
        return {"pass": False, "chars": chars, "reason": "too_short", "min_required": min_chars}
    elif chars > max_chars:
        return {"pass": True, "chars": chars, "warning": "over_max", "max_recommended": max_chars}
    else:
        return {"pass": True, "chars": chars}


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
            "issues": issues, "pass": len(issues) <= 2}


def check_fabrication(article: str, research_note: str) -> dict:
    flags = []
    urls_in_article = set(re.findall(r'https?://[^\s\)\]"]+', article))
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
        if stat.strip() not in research_note:
            flags.append({"type": "unverifiable_stat", "stat": stat.strip()})
    named_sources = re.findall(
        r'(?:据|根据|按照)((?:[A-Z][a-zA-Z]+(?:\s[A-Z][a-zA-Z]+)*|[一-鿿]{2,8})(?:公司|团队|实验室|研究院|中心|部门|平台|网站|博客|报告|数据|统计|研究|调查|分析))',
        article)
    for src in named_sources:
        if src[:4] not in research_note and src not in research_note:
            flags.append({"type": "unverifiable_source", "source": src})
    person_claims = re.findall(
        r'([一-鿿]{2,4})(?:认为|指出|表示|强调|补充说|分析称)', article)
    for name in person_claims:
        if name not in research_note:
            flags.append({"type": "unverifiable_person", "name": name})
    score = max(0, 10 - len(flags) * 2)
    return {"fabrication_flags": len(flags), "details": flags[:10],
            "pass": len(flags) <= 2, "score": score}


# ── Terminology violations ──

WP_TERM_VIOLATIONS = [
    # Only catch standalone "块编辑器/块主题" — not "区块编辑器/区块主题"
    (r'(?<!区)块编辑器', '应为"区块编辑器"'),
    (r'(?<!区)块主题', '应为"区块主题"'),
    (r'以块为(?:单位|核心|基础|单元|内容)', '应为"以区块为..."'),
    # Catch standalone 块 used as WP concept, but NOT in generic phrases like "一块/两块/是块"
    (r'(?<![区模板块冰积石砖地方法一俩两三几])块(?=(?:编辑器|主题|模式|样式|为))', '应为"区块"'),
]


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
    eng_terms = {
        r'\bBlock\b': '区块', r'\bFSE\b': '全站编辑',
        r'\bFull Site Editing\b': '全站编辑', r'\bHook\b': '钩子',
        r'\bPattern\b': '区块模式', r'\bShortcode\b': '短代码',
    }
    for pattern, zh in eng_terms.items():
        matches = re.findall(pattern, article)
        for m in matches[:3]:
            # Skip explanatory usage: "全站编辑（Full Site Editing，简称 FSE）"
            context_start = max(0, article.find(m) - 30)
            context = article[context_start:article.find(m) + len(m) + 30]
            if re.search(r'[（(].*' + re.escape(m) + r'.*[）)]', context) or \
               re.search(r'简称\s*' + re.escape(m), context):
                continue
            flags.append({"type": "english_term", "match": m,
                          "fix": f'应使用中文"{zh}"'})

    return {
        "violations": len(flags),
        "details": flags[:12],
        "pass": len(flags) <= 2
    }


COCOBOOK_API = "http://192.168.1.137:8086"


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


# ────────────────────────────────────────────────────────────────────
# Scoring and suggestions
# ────────────────────────────────────────────────────────────────────

def compute_overall_score(results: dict) -> float:
    """Weighted overall quality score from review results."""
    weights = {"ai_check": 0.22, "format": 0.10, "fabrication": 0.25,
               "semantic_facts": 0.18, "word_count": 0.10, "humanizer": 0.15}
    # GEO is advisory — not in weighted score
    scores = {
        "ai_check": results.get("ai_check", {}).get("score", 0),
        "format": 7.0 if results.get("format", {}).get("pass") else 3.0,
        "fabrication": results.get("fabrication", {}).get("score", 0),
        "semantic_facts": 8.0 if results.get("semantic_facts", {}).get("pass") else 4.0,
        "word_count": 7.0 if results.get("word_count", {}).get("pass") else 3.0,
        "humanizer": (results.get("humanizer", {}).get("total", 25) / 50) * 10,
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

    # GEO suggestions
    geo = results.get("geo", {})
    if geo and not geo.get("pass", True):
        geo_sugs = geo.get("suggestions", [])
        suggestions.extend(geo_sugs)

    return suggestions


def run_self_review(article: str, tier: str = "A",
                    research_note: str = "") -> dict:
    """Run all self-review checks and return consolidated results."""
    ai_check = check_ai_patterns(article)
    word_check = check_word_count(article, tier)
    format_check = check_format(article)
    fact_check = check_facts(article, research_note) if research_note else {}
    fab_check = check_fabrication(article, research_note) if research_note else {}
    sem_check = check_semantic_facts(article)
    humanizer = check_humanizer_quality(article)
    term_check = check_terminology(article)
    geo_check = check_geo(article, tier)

    all_pass = all([
        ai_check.get("pass", False),
        word_check.get("pass", False),
        format_check.get("pass", False),
        fact_check.get("pass", True),
        fab_check.get("pass", True),
        sem_check.get("pass", not research_note),  # skip if no research note
        humanizer.get("pass", True),
        term_check.get("pass", True),
        # GEO is advisory — not a block for pass/fail
    ])

    results = {
        "ai_check": ai_check,
        "word_count": word_check,
        "format": format_check,
        "facts": fact_check,
        "fabrication": fab_check,
        "semantic_facts": sem_check,
        "humanizer": humanizer,
        "terminology": term_check,
        "geo": geo_check,
        "overall_pass": all_pass,
    }

    results["overall_score"] = compute_overall_score(results)
    results["suggestions"] = generate_revision_suggestions(results) if not all_pass else []

    return results
# ────────────────────────────────────────────────────────────────────
# GEO (Generative Engine Optimization) checks — Frase 5-dimension model
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
