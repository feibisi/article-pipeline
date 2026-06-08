"""AI pattern detection and humanizer quality scoring."""
from article_pipeline.config import load_config
import json
import math
import re
import os

import requests
import yaml

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
    # Em-dash abuse — AI uses —— as universal connector; humans use it sparingly
    (r"——", "filler_em_dash"),

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
    # Pattern 26: textbook table-of-contents titles
    (r"的?好在哪里[，,]?不好在哪里|的优缺点分析|的概述与展望$|的优势与不足", "hz_textbook_titles"),
    # Pattern 27: numbered section organization (exam/report style)
    (r"第[一二三四五六七八九十]问[：:]|第[一二三四五六七八九十]段[：:]", "hz_numbered_sections"),
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
    # Humanizer-zh heavy: promotional, chatbot residue, unmistakable AI artifacts
    "hz_milestone", "hz_lay_foundation",
    "hz_promo_hyper", "hz_cliche_challenges", "hz_cliche_despite",
    "hz_chatbot_close", "hz_chatbot_cutoff", "hz_chatbot_disclaimer",
    "hz_bright_future", "hz_positive_conclusion", "hz_evolving_landscape",
    "hz_copula_avoid", "hz_forced_casual", "hz_textbook_titles", "hz_numbered_sections",
}

FILLER_TAGS = {
    # Original fillers
    "filler_worth_noting", "filler_cannot_ignore", "filler_must_point_out",
    "filler_important_is", "filler_can_consider", "filler_this_means",
    # Natural rhetoric that's AI-overused — worth flagging, not heavy
    "hz_exaggerated_sig",
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
    # Em-dash overuse — AI's favorite punctuation, but some is natural
    "filler_em_dash",
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
                score -= len(matches) * 0.5
            elif tag in LIGHT_TAGS:
                # Frequency counters — small signal, not a hard quality hit
                score -= len(matches) * 0.1

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

