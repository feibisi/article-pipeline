"""LLM-as-judge semantic review layer.

Why this exists
---------------
Every other check in ``article_pipeline.review`` is a *surface proxy*: regex
counts, word-frequency tables, sentence-length variance. Measured on the 10
real articles in the production DB plus 38 human-written reference excerpts,
those proxies separate machine slop from human prose by ~0.1-1.8 points on a
10-point scale (see ``docs/`` audit notes) — i.e. not at all. Three classes of
defect that a human editor rejects on sight are *structurally* out of reach for
them:

1. the topic itself is worthless,
2. the prose is correct but states no position,
3. ten thousand identical articles already exist,

plus the defect class that actually damages the brand: **fabricated facts** —
invented constants, code that cannot run, concepts explained backwards.

None of those are countable. They require reading. This module asks a model to
read.

Design constraints
------------------
* **Off by default.** ``judge_article`` is never called unless a caller opts in
  (``run_self_review(..., enable_semantic_judge=True)`` or
  ``AP_SEMANTIC_JUDGE=1``). Existing release behaviour is untouched.
* **Offline testable.** The single network call goes through an injectable
  ``call_fn`` defaulting to :func:`article_pipeline.llm.call_with_fallback`.
* **The judge does not decide.** It emits ordinal per-dimension scores and a
  per-claim verification table. The verdict is computed in Python from hard
  rules (:func:`_decide`). A model cannot rubber-stamp a decision it is never
  asked to make.
* **Every positive score must be paid for with a verbatim quote** that
  :func:`_validate_quotes` checks against the article. Unbacked praise is
  mechanically demoted to 0. This is the anti-rubber-stamp core: the judge can
  lie in prose but it cannot fake a substring.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

# ────────────────────────────────────────────────────────────────────
# Tunables
# ────────────────────────────────────────────────────────────────────

#: Ordinal band scale. Deliberately 0-4, not 0-10: a coarse forced-choice scale
#: resists the 7-8/10 clustering that makes LLM scores useless.
BAND_MAX = 4

#: A quote shorter than this is not evidence, it is a coincidence. Tuned for
#: Chinese: a typical zh clause is 8-15 characters, so 12 would reject
#: legitimate single-clause evidence like "真正的取舍不在参数上" (10 chars).
#: 8 zh characters is still far too specific to match by accident.
MIN_QUOTE_CHARS = 8

#: Article text handed to the judge is capped so cost stays predictable.
MAX_ARTICLE_CHARS = 12000
MAX_MATERIAL_CHARS = 8000

#: Known-bad excerpt embedded in every prompt as a calibration ballast. A judge
#: that scores this above ``CALIBRATION_MAX_PASS`` is mis-calibrated and its
#: verdict on the real article is discarded rather than trusted.
CALIBRATION_ANCHOR = (
    "在当今这个数字化时代，WordPress 已经成为全球最受欢迎的建站平台。"
    "随着技术的不断发展，网站性能优化变得越来越重要。本文将为您详细介绍"
    "几个实用的优化技巧，帮助您更好地提升网站速度。首先，我们需要了解"
    "缓存的重要性。缓存可以显著提高网站的加载速度，从而改善用户体验。"
    "其次，图片优化也是不可忽视的一环。总之，通过以上方法，相信您一定"
    "能够打造出一个高性能的网站。"
)
CALIBRATION_MAX_PASS = 1

_DIMENSIONS = ("factuality", "originality", "insight", "brand_fit")

#: Severities that make a factual defect disqualifying.
_FATAL_SEVERITIES = ("fatal",)

_VALID_CLAIM_VERDICTS = ("supported", "unsupported", "contradicted", "unverifiable")


# ────────────────────────────────────────────────────────────────────
# Output contract
# ────────────────────────────────────────────────────────────────────

@dataclass
class FactualClaim:
    """One checkable assertion lifted out of the article."""

    text: str
    kind: str = "other"          # constant | code | concept | statistic | quote | other
    verdict: str = "unverifiable"  # see _VALID_CLAIM_VERDICTS
    evidence: str = ""           # verbatim span from the supplied material
    severity: str = "minor"      # fatal | major | minor
    note: str = ""

    @property
    def is_fatal(self) -> bool:
        return (self.verdict in ("contradicted", "unsupported")
                and self.severity in _FATAL_SEVERITIES)


@dataclass
class DimensionVerdict:
    """Ordinal score for one judging dimension, plus its receipts."""

    name: str
    score: int = 0               # 0..BAND_MAX
    reason: str = ""
    quotes: list[str] = field(default_factory=list)
    quotes_verified: int = 0     # how many quotes were found verbatim
    demoted: bool = False        # True if score was cut for unbacked claims


@dataclass
class JudgeVerdict:
    """Full judge output. ``decision`` is computed in Python, never by the model."""

    decision: str = "unavailable"   # pass | revise | reject | unavailable
    score: float = 0.0              # 0-10, derived from bands
    dimensions: dict[str, DimensionVerdict] = field(default_factory=dict)
    claims: list[FactualClaim] = field(default_factory=list)
    unique_contribution: str = ""
    kill_reasons: list[str] = field(default_factory=list)
    reject_case: str = ""           # the model's own best argument for rejecting
    calibration_score: Optional[int] = None
    calibration_ok: bool = True
    model: str = ""
    tokens: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @property
    def available(self) -> bool:
        return self.decision in ("pass", "revise", "reject")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["dimensions"] = {k: asdict(v) for k, v in self.dimensions.items()}
        d["claims"] = [asdict(c) for c in self.claims]
        d["available"] = self.available
        return d


# ────────────────────────────────────────────────────────────────────
# Prompts
# ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一名以严苛著称的中文技术内容主编，负责终审即将发布到公司官网的文章。

你的职业风险是不对称的：放过一篇有事实错误或毫无信息增量的文章，会损害品牌可信度且需要公开更正；错杀一篇尚可的文章，只需作者重写一遍。因此当你犹豫时，压低分数。

三条不可协商的判断原则：

1. 只有能从原文**逐字复制**出来的句子才算证据。凡是你无法逐字引用来支撑的优点，视为不存在——系统会用字符串匹配核对你给出的每一条引文，编造引文会导致该维度直接判 0 分。
2. 「正确」不等于「有价值」。官方文档的复述、人人都知道的常识、可以套用在任何同类产品上的通用建议，一律算 0 分信息增量，无论文字多么流畅。
3. 事实断言必须能追溯到给定素材。文中出现的具体数字、配置常量、默认值、版本号、命令、代码、概念定义，若素材中查不到，就标为 unsupported——不要因为「听起来合理」或「符合常识」而放过。你对技术细节的直觉不是证据。

你只输出结构化评估，不输出最终的发布/不发布决定——那由调用方的规则引擎判定。"""


_RUBRIC = """评分采用 0-4 档序数量表（不是百分制，不要给小数）：

0 = 完全缺失。1 = 有痕迹但不成立。2 = 及格线，勉强算做到了。
3 = 明确做到，且能逐字引出证据。4 = 罕见的优秀。

**校准约束：在我们的语料中 4 分应当极少出现（低于 10%），2 分是常态。**如果你给出 3 分或 4 分，reason 中必须写明「相比同题材通稿多出了什么」这一具体差异。

四个维度：

- factuality（事实可靠性）：文中的事实断言能否从素材中验证。存在任何一条杜撰的常量/跑不通的代码/讲反的概念 → 最高 1 分。
- originality（信息增量）：这篇提供了哪一条别处拿不到的具体信息？必须能从原文逐字引出那一句。若你引不出具体的一句（只能概括说「讲得比较全面」），该维度为 0。
- insight（判断与洞见）：是否给出可反驳的观点、权衡、代价、适用边界。罗列「优点/缺点」小标题不算，要有作者自己的取舍立场。
- brand_fit（品牌契合）：是否结合了给定的品牌/产品语境。若通篇替换品牌名后依然通顺，为 0-1 分。"""


_OUTPUT_SCHEMA = """严格只输出一个 JSON 对象，不要 markdown 代码围栏，不要任何解释文字：

{
  "claims": [
    {"text": "文中的事实断言，逐字复制",
     "kind": "constant|code|concept|statistic|quote|other",
     "verdict": "supported|unsupported|contradicted|unverifiable",
     "evidence": "素材中支持它的原文片段，逐字复制；查不到就填空字符串",
     "severity": "fatal|major|minor",
     "note": "一句话说明"}
  ],
  "dimensions": {
    "factuality":  {"score": 0, "reason": "", "quotes": []},
    "originality": {"score": 0, "reason": "", "quotes": []},
    "insight":     {"score": 0, "reason": "", "quotes": []},
    "brand_fit":   {"score": 0, "reason": "", "quotes": []}
  },
  "unique_contribution": "用一句话写出这篇文章提供的、别处拿不到的那条具体信息；如果不存在，填空字符串",
  "kill_reasons": ["按你的判断，这篇文章最该被打回的理由，逐条列出"],
  "reject_case": "假设主编要求你必须写出一份退稿理由，你会怎么写（即使你倾向通过也必须填）",
  "calibration_score": 0,
  "weakest_sentences": ["原文中最空洞的 3 句，逐字复制"]
}

关于 claims：优先列出**可被证伪**的断言——具体数字、默认值、配置常量、版本号、命令行、代码行为、概念定义。最多 12 条。不要列「性能很重要」这类不可证伪的话。
关于 severity：读者照做会出错、或数字/常量是杜撰的 → fatal；概念讲反但不致操作失败 → major；表述不精确 → minor。
关于 calibration_score：下面「校准样本」按 originality 标准该得几分。"""


def build_judge_prompt(
    article: str,
    material: str = "",
    brand_context: str = "",
    topic: str = "",
    adversarial: bool = False,
) -> tuple[str, str]:
    """Build ``(system_prompt, user_prompt)`` for one judging pass.

    ``adversarial=True`` produces the second, pessimistic pass used by
    ``passes=2``: same rubric, prosecutorial framing. Scores from the two
    passes are combined with ``min()``, never averaged.
    """
    system = SYSTEM_PROMPT
    if adversarial:
        system += (
            "\n\n本轮你的角色是**退稿方**。默认立场是这篇文章不该发布，"
            "只有当原文能逐字提供反驳你的证据时才让步给分。"
        )

    article = (article or "")[:MAX_ARTICLE_CHARS]
    material = (material or "")[:MAX_MATERIAL_CHARS]

    parts = [_RUBRIC, "", _OUTPUT_SCHEMA, ""]
    if topic:
        parts += [f"【选题】{topic}", ""]
    if brand_context:
        parts += ["【品牌/产品语境】", brand_context, ""]
    parts += [
        "【可用素材】（事实核查的唯一依据。素材中没有的，就是查不到）",
        material or "（无素材——所有具体事实断言一律标 unsupported，"
                    "并在 kill_reasons 中指出本文无素材支撑）",
        "",
        "【校准样本】（已知的低质通稿，仅用于校准你的尺度，不要评审它的内容）",
        CALIBRATION_ANCHOR,
        "",
        "【待审文章】",
        article,
    ]
    return system, "\n".join(parts)


# ────────────────────────────────────────────────────────────────────
# Parsing / validation
# ────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a model response."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = []
    if fenced:
        candidates.append(fenced.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _norm_for_quote(s: str) -> str:
    """Whitespace-insensitive form for verbatim quote matching."""
    return re.sub(r"\s+", "", s or "")


def _clamp_band(v: Any) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(BAND_MAX, n))


def _validate_quotes(dim: DimensionVerdict, article: str) -> DimensionVerdict:
    """Demote any score that is not backed by a verbatim quote from the article.

    This is the mechanical anti-rubber-stamp check: a judge can write flattering
    prose, but it cannot fabricate a substring of a text we also hold. A score
    of 2 or more with zero verifiable quotes is cut to 1; a score of 3 or more
    is additionally capped at 2 unless the quote is substantial.
    """
    hay = _norm_for_quote(article)
    verified = 0
    for q in dim.quotes:
        nq = _norm_for_quote(q)
        if len(nq) >= MIN_QUOTE_CHARS and nq in hay:
            verified += 1
    dim.quotes_verified = verified

    if dim.score >= 2 and verified == 0:
        dim.score = 1 if dim.score >= 3 else 0
        dim.demoted = True
    elif dim.score >= 3 and verified == 0:
        dim.score = 2
        dim.demoted = True
    return dim


def parse_judge_response(text: str, article: str) -> JudgeVerdict:
    """Parse + validate a raw judge response into a :class:`JudgeVerdict`.

    Pure function, no I/O — this is what the unit tests exercise.
    """
    v = JudgeVerdict()
    data = _extract_json(text)
    if data is None:
        v.decision = "unavailable"
        v.error = "unparseable_judge_response"
        return v

    # ---- claims
    for raw in (data.get("claims") or [])[:24]:
        if not isinstance(raw, dict):
            continue
        verdict = str(raw.get("verdict", "unverifiable"))
        if verdict not in _VALID_CLAIM_VERDICTS:
            verdict = "unverifiable"
        v.claims.append(FactualClaim(
            text=str(raw.get("text", ""))[:400],
            kind=str(raw.get("kind", "other")),
            verdict=verdict,
            evidence=str(raw.get("evidence", ""))[:400],
            severity=str(raw.get("severity", "minor")),
            note=str(raw.get("note", ""))[:300],
        ))

    # A claim cannot be "supported" with no evidence span. Downgrade silently —
    # this is the most common way a lazy judge waves facts through.
    for c in v.claims:
        if c.verdict == "supported" and len(_norm_for_quote(c.evidence)) < MIN_QUOTE_CHARS:
            c.verdict = "unverifiable"
            c.note = (c.note + " [evidence missing → downgraded]").strip()

    # ---- dimensions
    dims_raw = data.get("dimensions") or {}
    for name in _DIMENSIONS:
        raw = dims_raw.get(name) or {}
        if not isinstance(raw, dict):
            raw = {}
        quotes = raw.get("quotes") or []
        if isinstance(quotes, str):
            quotes = [quotes]
        dim = DimensionVerdict(
            name=name,
            score=_clamp_band(raw.get("score", 0)),
            reason=str(raw.get("reason", ""))[:500],
            quotes=[str(q)[:400] for q in quotes if isinstance(q, (str, int, float))][:5],
        )
        v.dimensions[name] = _validate_quotes(dim, article or "")

    v.unique_contribution = str(data.get("unique_contribution", "") or "")[:500]
    kr = data.get("kill_reasons") or []
    if isinstance(kr, str):
        kr = [kr]
    v.kill_reasons = [str(x)[:300] for x in kr if str(x).strip()][:10]
    v.reject_case = str(data.get("reject_case", "") or "")[:800]

    cal = data.get("calibration_score")
    if cal is not None:
        v.calibration_score = _clamp_band(cal)
        v.calibration_ok = v.calibration_score <= CALIBRATION_MAX_PASS

    _decide(v)
    return v


def _decide(v: JudgeVerdict) -> JudgeVerdict:
    """Derive ``score`` and ``decision`` from the bands. Rules, not vibes."""
    weights = {"factuality": 0.40, "originality": 0.30,
               "insight": 0.20, "brand_fit": 0.10}
    total = sum(v.dimensions[n].score * w for n, w in weights.items()
                if n in v.dimensions)
    v.score = round(total / BAND_MAX * 10, 1)

    fact = v.dimensions.get("factuality", DimensionVerdict("factuality")).score
    orig = v.dimensions.get("originality", DimensionVerdict("originality")).score
    insight = v.dimensions.get("insight", DimensionVerdict("insight")).score

    fatal = [c for c in v.claims if c.is_fatal]
    contradicted = [c for c in v.claims if c.verdict == "contradicted"]

    reasons: list[str] = []

    # --- hard rejects
    if fatal:
        reasons.append(
            f"{len(fatal)} 条致命事实错误（如杜撰常量/跑不通的代码）: "
            + "; ".join(c.text[:60] for c in fatal[:3])
        )
    if contradicted:
        reasons.append(
            f"{len(contradicted)} 条与素材矛盾的断言: "
            + "; ".join(c.text[:60] for c in contradicted[:3])
        )
    if orig == 0:
        reasons.append("信息增量为 0：judge 无法从原文引出任何别处拿不到的具体信息")
    if not _norm_for_quote(v.unique_contribution):
        reasons.append("judge 未能写出本文独有的那条具体信息")
    if fact <= 1:
        reasons.append(f"事实可靠性仅 {fact}/{BAND_MAX}")

    if reasons:
        v.decision = "reject"
        v.kill_reasons = reasons + [r for r in v.kill_reasons if r not in reasons]
        return v

    # --- mis-calibrated judge: refuse to accept its blessing
    if not v.calibration_ok:
        v.decision = "revise"
        v.kill_reasons.insert(0, (
            f"judge 校准失败：把已知低质样本评为 {v.calibration_score}/{BAND_MAX}"
            f"（应 <= {CALIBRATION_MAX_PASS}），本次评分不可信，转人工"
        ))
        return v

    # --- borderline
    if orig <= 1 or insight <= 1 or v.score < 5.0:
        v.decision = "revise"
        if orig <= 1:
            v.kill_reasons.insert(0, f"信息增量偏低（{orig}/{BAND_MAX}）")
        if insight <= 1:
            v.kill_reasons.insert(0, f"缺乏可反驳的观点（insight {insight}/{BAND_MAX}）")
        return v

    v.decision = "pass"
    return v


# ────────────────────────────────────────────────────────────────────
# Aggregation across passes
# ────────────────────────────────────────────────────────────────────

def merge_verdicts(verdicts: list[JudgeVerdict]) -> JudgeVerdict:
    """Pessimistic merge: per-dimension ``min()``, union of claims and kills.

    Averaging two judges converges on "fine". Taking the minimum means a single
    reader who spotted a fabricated constant is enough to stop the article.
    """
    usable = [v for v in verdicts if v.available]
    if not usable:
        return verdicts[0] if verdicts else JudgeVerdict(error="no_verdicts")
    if len(usable) == 1:
        return usable[0]

    out = JudgeVerdict(model="+".join(sorted({v.model for v in usable if v.model})))
    for name in _DIMENSIONS:
        worst = min((v.dimensions[name] for v in usable if name in v.dimensions),
                    key=lambda d: d.score, default=DimensionVerdict(name))
        out.dimensions[name] = worst
    for v in usable:
        out.claims.extend(v.claims)
        for r in v.kill_reasons:
            if r not in out.kill_reasons:
                out.kill_reasons.append(r)
    # unique_contribution: keep it only if *every* pass found one.
    contribs = [v.unique_contribution for v in usable]
    out.unique_contribution = contribs[0] if all(_norm_for_quote(c) for c in contribs) else ""
    out.reject_case = "\n---\n".join(v.reject_case for v in usable if v.reject_case)
    out.calibration_ok = all(v.calibration_ok for v in usable)
    cals = [v.calibration_score for v in usable if v.calibration_score is not None]
    out.calibration_score = max(cals) if cals else None
    out.tokens = {
        "input_tokens": sum(v.tokens.get("input_tokens", 0) for v in usable),
        "output_tokens": sum(v.tokens.get("output_tokens", 0) for v in usable),
    }
    _decide(out)
    return out


# ────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────

def is_enabled(explicit: Optional[bool] = None) -> bool:
    """Feature flag. Default **off**; env var ``AP_SEMANTIC_JUDGE=1`` opts in."""
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("AP_SEMANTIC_JUDGE", "").strip().lower() in ("1", "true", "yes", "on")


def estimate_cost(article: str, material: str = "", passes: int = 1,
                  usd_per_mtok_in: float = 3.0,
                  usd_per_mtok_out: float = 15.0) -> dict:
    """Rough per-article token/cost estimate. ~1.6 chars per token for zh text."""
    prompt_overhead = len(SYSTEM_PROMPT) + len(_RUBRIC) + len(_OUTPUT_SCHEMA) + len(CALIBRATION_ANCHOR)
    chars_in = min(len(article or ""), MAX_ARTICLE_CHARS) \
        + min(len(material or ""), MAX_MATERIAL_CHARS) + prompt_overhead
    tok_in = int(chars_in / 1.6) * passes
    tok_out = 1400 * passes
    return {
        "passes": passes,
        "input_tokens": tok_in,
        "output_tokens": tok_out,
        "usd": round(tok_in / 1e6 * usd_per_mtok_in + tok_out / 1e6 * usd_per_mtok_out, 4),
    }


def judge_article(
    article: str,
    material: str = "",
    brand_context: str = "",
    topic: str = "",
    passes: int = 1,
    call_fn: Optional[Callable[..., dict]] = None,
    max_tokens: int = 3000,
) -> JudgeVerdict:
    """Run the semantic judge over one article.

    Args:
        article: Article text under review.
        material: Research material — the *only* admissible evidence for fact
            checking. Empty material means every concrete claim is unsupported.
        brand_context: Brand/product context for the ``brand_fit`` dimension.
        topic: The commissioned topic/keyword.
        passes: 1 = single read. 2 = adds an adversarial second read, merged
            with :func:`merge_verdicts` (pessimistic ``min``).
        call_fn: LLM callable with the signature of
            :func:`article_pipeline.llm.call_with_fallback`. Injected in tests.
        max_tokens: Output cap per pass.

    Returns:
        :class:`JudgeVerdict`. On any transport/parse failure the decision is
        ``"unavailable"`` with ``error`` set — callers must treat that as
        "no signal", never as a pass.
    """
    if not (article or "").strip():
        return JudgeVerdict(decision="unavailable", error="empty_article")

    if call_fn is None:
        from article_pipeline.llm import call_with_fallback
        call_fn = call_with_fallback

    verdicts: list[JudgeVerdict] = []
    for i in range(max(1, passes)):
        system, user = build_judge_prompt(
            article, material=material, brand_context=brand_context,
            topic=topic, adversarial=(i > 0),
        )
        try:
            resp = call_fn(system, user, max_tokens=max_tokens, temperature=0.0)
        except Exception as exc:  # noqa: BLE001 — transport must never crash review
            verdicts.append(JudgeVerdict(decision="unavailable",
                                         error=f"call_failed: {type(exc).__name__}"))
            continue
        if not isinstance(resp, dict) or resp.get("error"):
            err = resp.get("error", "bad_response") if isinstance(resp, dict) else "bad_response"
            verdicts.append(JudgeVerdict(decision="unavailable", error=str(err)))
            continue
        v = parse_judge_response(resp.get("content", ""), article)
        v.model = resp.get("model", "")
        v.tokens = resp.get("tokens", {}) or {}
        verdicts.append(v)

    return merge_verdicts(verdicts)


def apply_judge_to_gate(gate: dict, verdict: JudgeVerdict) -> dict:
    """Fold a :class:`JudgeVerdict` into a ``compute_publish_gate`` result.

    Semantics — the judge may **tighten** but never loosen a hard failure:

    * ``reject``  → gate decision becomes ``fail``.
    * ``revise``  → a ``pass`` is downgraded to ``needs_human``.
    * ``pass``    → may lift ``needs_human`` to ``pass``, but only when the
      surface gate's complaint was density (never when it was a hard ``fail``),
      and only when the judge's own evidence was verified.
    * ``unavailable`` → gate untouched.
    """
    out = dict(gate or {})
    out["semantic_judge"] = verdict.to_dict()
    if not verdict.available:
        return out

    decision = out.get("decision")
    blocking = list(out.get("blocking_reasons") or [])

    if verdict.decision == "reject":
        out["decision"] = "fail"
        out["reason"] = "语义评审判定不可发布：" + "；".join(verdict.kill_reasons[:3])
        out["blocking_reasons"] = blocking + [f"[judge] {r}" for r in verdict.kill_reasons[:5]]
        return out

    if verdict.decision == "revise":
        if decision == "pass":
            out["decision"] = "needs_human"
            out["reason"] = ("表层门控通过但语义评审要求修改：" +
                             "；".join(verdict.kill_reasons[:3]))
        out["blocking_reasons"] = blocking + [f"[judge] {r}" for r in verdict.kill_reasons[:5]]
        return out

    # verdict.decision == "pass"
    if decision == "needs_human":
        verified = all(d.quotes_verified > 0 for d in verdict.dimensions.values()
                       if d.score >= 2)
        if verified and verdict.calibration_ok and verdict.score >= 6.0:
            out["decision"] = "pass"
            out["reason"] = (
                f"表层密度不足但语义评审放行（judge {verdict.score}/10，"
                f"独有信息：{verdict.unique_contribution[:60]}）"
            )
    return out


__all__ = [
    "FactualClaim", "DimensionVerdict", "JudgeVerdict",
    "build_judge_prompt", "parse_judge_response", "merge_verdicts",
    "judge_article", "apply_judge_to_gate", "is_enabled", "estimate_cost",
    "SYSTEM_PROMPT", "CALIBRATION_ANCHOR", "BAND_MAX",
]
