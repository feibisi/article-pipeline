"""Value density assessment — detect slop content via 5 dimensions.

Slop detection criteria:
1. Unique info ratio — claims not found in DDG top 10 (>20%)
2. Verifiable operations — paragraphs with concrete commands/code/URLs/versions (>30%)
3. Source depth — distinct cocobook sources referenced (>=3)
4. Judgment density — clear stance statements per H2 (>=2)
5. Counter-intuitive — claims contradicting mainstream search with evidence (>=1)

Gate rules:
- < 4.0 → fail (slop, do not publish)
- 4.0 ~ 6.0 → needs_human (manual review required)
- >= 6.0 → pass (recommended to publish)
"""

import re
from typing import Any


# ────────────────────────────────────────────────────────────────────
# 1. Unique info ratio — claims not appearing in DDG top 10 results
# ────────────────────────────────────────────────────────────────────

CLAIM_PATTERNS = [
    r'(?:据|根据|数据显示|研究表明|统计|报告)([^。.!！?\n]{10,80})',
    r'(?:性能|速度|效率|安全性|稳定性)(?:提升|降低|改善|优化|增强)([^。.!！?\n]{5,60})',
    r'(?:支持|兼容|适用于|适用于|限制于)([^。.!！?\n]{5,60})',
    r'(?:版本|v[0-9]|\.[\d.]+)(?:特性|功能|问题)([^。.!！?\n]{5,60})',
    r'(?:默认|配置|设置)(?:为|是)([^。.!！?\n]{5,40})',
    r'(?:推荐|建议|应该|最佳实践)(?:使用|采用|选择)([^。.!！?\n]{5,60})',
]


def _extract_claims(article: str) -> list[str]:
    """Extract factual claims from article."""
    claims = []
    for pattern in CLAIM_PATTERNS:
        matches = re.findall(pattern, article)
        claims.extend(matches)
    # Also extract sentences with numbers/versions
    sentences = re.split(r'[。.!！?\n]', article)
    for s in sentences:
        s = s.strip()
        if len(s) < 15 or len(s) > 120:
            continue
        if re.search(r'\d+(?:\.\d+)?%|\d+[\s]*(?:倍|亿|万|千|秒|ms|MB|GB)', s):
            if not re.search(r'^[选咱你我]的|像选|举例|例如|比如', s[:20]):
                claims.append(s)
    # Deduplicate while preserving order
    seen = set()
    unique_claims = []
    for c in claims:
        norm = c.replace(' ', '').strip()
        if norm and norm not in seen:
            seen.add(norm)
            unique_claims.append(c)
    return unique_claims[:15]


def _check_unique_info(claims: list[str], ddg_results: list[dict]) -> float:
    """Check what fraction of claims are NOT found in DDG top 10."""
    if not claims:
        return 0.0

    # Normalize DDG results for comparison
    ddg_snippets = []
    for r in ddg_results[:10]:
        title = r.get("title", "").lower()
        body = r.get("body", "").lower()
        ddg_snippets.append(title + " " + body)

    unique_count = 0
    for claim in claims:
        claim_lower = claim[:50].lower()
        # Check if claim appears in any DDG result
        found = False
        for snippet in ddg_snippets:
            # Check for partial phrase overlap (at least 8 consecutive chars)
            for i in range(len(claim_lower) - 7):
                phrase = claim_lower[i:i+8]
                if phrase in snippet:
                    found = True
                    break
            if found:
                break
        if not found:
            unique_count += 1

    ratio = unique_count / len(claims) if claims else 0
    # Score: 20% unique → 4/10, 50% → 7/10, 80%+ → 10/10
    score = min(10, 2 + ratio * 10)
    return round(score, 1)


# ────────────────────────────────────────────────────────────────────
# 2. Verifiable operations — concrete actionable content
# ────────────────────────────────────────────────────────────────────

# Patterns for verifiable content
COMMAND_PATTERNS = [
    r'\b(?:apt|dnf|yum|npm|pip|composer|docker|kubectl|git|wget|curl|systemctl|ssh)\s+[\w\-]+',
    r'\b(?:sudo|doas)\s+(?:apt|dnf|yum|npm|pip|composer|docker|kubectl|git)',
    r'[`$]?\s*(?:\w+/)?\w+(?:\s+[\w\-]+){1,3}',  # Command-like patterns
]

CODE_PATTERNS = [
    r'```[\s\S]{20,}```',  # Code blocks
    r'\bfunction\s+\w+\s*\(',
    r'\bclass\s+\w+',
    r'\bdef\s+\w+\s*\(',
    r'<\?php',
    r'import\s+\w+',
    r'from\s+\w+\s+import',
]

URL_PATTERNS = [
    r'https?://[^\s\)\]"]+',
]

VERSION_PATTERNS = [
    r'\bv?[0-9]+\.[0-9]+\.[0-9]+(?:\.[a-z0-9]+)?',
    r'\b(?:PHP|Python|Node|Java|Go|Nginx|WordPress)\s+[0-9]+\.[0-9]+',
    r'\b[0-9]+\.[0-9]+(?:\s*(?:alpha|beta|rc| LTS))?$',  # Version numbers
]

SPECIFIC_VALUE_PATTERNS = [
    r'\b\d+\s*[MBKG]B\b',
    r'\b\d+\s*ms\b',
    r'\b\d+\s*(?:threads?|cores?|workers?|connections?)\b',
    r'\b(?:port|端口)\s*[:\s]*\d{2,5}',
]


def _check_verifiable_operations(article: str) -> float:
    """Check proportion of paragraphs with verifiable content."""
    paragraphs = re.split(r'\n\n+', article)
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 30]

    if not paragraphs:
        return 0.0

    verifiable_count = 0
    for para in paragraphs:
        has_command = any(re.search(p, para) for p in COMMAND_PATTERNS)
        has_code = any(re.search(p, para) for p in CODE_PATTERNS)
        has_url = any(re.search(p, para) for p in URL_PATTERNS)
        has_version = any(re.search(p, para) for p in VERSION_PATTERNS)
        has_specific = any(re.search(p, para) for p in SPECIFIC_VALUE_PATTERNS)

        if has_command or has_code or has_url or has_version or has_specific:
            verifiable_count += 1

    ratio = verifiable_count / len(paragraphs)
    # Score: 30% → 4/10, 60% → 7/10, 90%+ → 10/10
    score = min(10, ratio * 12)
    return round(score, 1)


# ────────────────────────────────────────────────────────────────────
# 3. Source depth — distinct sources referenced
# ────────────────────────────────────────────────────────────────────

# Source domains in cocobook
KNOWN_SOURCES = {
    # Official docs
    'wordpress.org', 'developer.wordpress.org', 'php.net', 'nginx.org',
    'docs.docker.com', 'kubernetes.io', 'redis.io',
    # High-quality blogs (acceptable)
    'moz.com', 'css-tricks.com', 'smashingmagazine.com',
    # Chinese technical (acceptable)
    'kancloud.cn', 'laravel-china.org',
}


def _check_source_depth(article: str, research_output: dict) -> float:
    """Count distinct sources referenced."""
    sources = set()

    # Extract URLs from article
    urls = re.findall(r'https?://([^\s/\)]+)', article)
    for domain in urls:
        # Normalize domain
        base = domain.replace('www.', '').split('/')[0]
        sources.add(base)

    # Extract from research output
    if research_output:
        research_sources = research_output.get("sources", [])
        if isinstance(research_sources, list):
            for src in research_sources:
                if isinstance(src, str):
                    match = re.search(r'([^\s/]+\.[a-z]{2,})', src)
                    if match:
                        sources.add(match.group(1))

    # Check cocobook references
    if 'cocobook' in str(article).lower() or 'cocobook' in str(research_output).lower():
        sources.add('cocobook')

    # Count distinct sources (excluding known-low-quality)
    content_farms = {'csdn.net', 'juejin.cn', 'jianshu.com', 'zhihu.com', 'toutiao.com'}
    quality_sources = sources - content_farms

    count = len(quality_sources)

    # Score: 1 source → 2/10, 2 → 5/10, 3 → 8/10, 4+ → 10/10
    if count == 0:
        score = 0
    elif count == 1:
        score = 3
    elif count == 2:
        score = 6
    elif count == 3:
        score = 8
    else:
        score = 10

    return float(score)


# ────────────────────────────────────────────────────────────────────
# 4. Judgment density — clear stance statements
# ────────────────────────────────────────────────────────────────────

JUDGMENT_KEYWORDS = [
    # Strong assertions
    r'是(?:唯一|最佳|最好|最差|不可|必须|应该|值得)(?:的|选择|方案|做法)',
    r'(?:必须|应该|应当|需要|值得)(?:采用|使用|避免|注意|考虑)',
    r'(?:推荐|建议|推荐)(?:使用|采用|选择|优先)',
    # Clear positions
    r'(?:反对|不支持|不建议|避免|不要)(?:使用|采用|选择)',
    r'(?:优点|优势|好处|益处)(?:是|在于)',
    r'(?:缺点|劣势|问题|不足|风险)(?:是|在于)',
    # Definitive statements
    r'(?:本质上|说到底|归根结底)(?:是|在于)',
    r'(?:关键|核心|重点)(?:在于|是)',
    r'(?:唯一|最佳|最好|最差)(?:的)?(?:方法|方案|做法|选择)',
    # Value judgments
    r'值得(?:推荐|使用|学习|借鉴)',
    r'不(?:值得|建议|推荐|适合)',
    r'(?:更|最)(?:好|优|佳|适合)(?:的(?:方案|选择|做法))?',
]


def _count_h2_sections(article: str) -> int:
    """Count H2 sections."""
    h2_count = len(re.findall(r'^##\s', article, re.MULTILINE))
    return max(1, h2_count)  # Avoid division by zero


def _check_judgment_density(article: str) -> float:
    """Count judgment statements per H2 section."""
    judgment_count = 0
    for pattern in JUDGMENT_KEYWORDS:
        matches = len(re.findall(pattern, article))
        judgment_count += matches

    h2_count = _count_h2_sections(article)
    per_h2 = judgment_count / h2_count

    # Score: 0.5/H2 → 3/10, 1/H2 → 6/10, 2+/H2 → 10/10
    score = min(10, per_h2 * 5)
    return round(score, 1)


# ────────────────────────────────────────────────────────────────────
# 5. Counter-intuitive — claims contradicting mainstream with evidence
# ────────────────────────────────────────────────────────────────────

CONTRAST_MARKERS = [
    r'(?:然而|但是|但|不过|相反|反之)(?:，|,)?',
    r'(?:与之相反|反其道而行之)',
    r'(?:并非|不是)(?:而|而是)',
    r'(?:实际上|事实上|真的)',
    r'(?:虽然|尽管)(?:.*?)(?:但是|但)',
]

EVIDENCE_MARKERS = [
    r'(?:实测|测试|验证|实验|数据)(?:显示|表明|发现|结果)',
    r'(?:根据|据|按照)(?:数据|测试|实验|研究)',
    r'(?:性能|速度|效率)(?:提升|降低)(?:\d+[%％]?\s*|达到)',
    r'(?:耗时|延迟)(?:减少|降低|增加)',
]


def _check_counter_intuitive(article: str, ddg_results: list[dict]) -> float:
    """Check for counter-intuitive claims with evidence."""
    score = 0.0

    # Find contrast statements
    contrast_count = 0
    for pattern in CONTRAST_MARKERS:
        contrast_count += len(re.findall(pattern, article))

    # Among contrast statements, look for evidence
    evidence_count = 0
    for pattern in EVIDENCE_MARKERS:
        evidence_count += len(re.findall(pattern, article))

    # Check for specific "myth vs fact" patterns
    myth_fact = len(re.findall(
        r'(?:误区|误解|很多人认为|常见错误)(?:.*?)(?:实际上|事实上|但是|然而)',
        article
    ))

    # Score calculation
    # At least one contrast with evidence → base score
    if contrast_count >= 1 and evidence_count >= 1:
        score = 5.0
    # Myth-busting content
    if myth_fact >= 1:
        score = max(score, 6.0)

    # Multiple well-supported counter-intuitive claims
    if contrast_count >= 2 and evidence_count >= 2:
        score = 8.0
    if contrast_count >= 3 and evidence_count >= 2:
        score = 10.0

    # Bonus: claims contradicting DDG consensus
    if ddg_results:
        # Check if article takes position against mainstream
        mainstream_keywords = ['推荐', '最佳', '最常用', '流行']
        ddg_text = ' '.join(r.get('body', '') for r in ddg_results[:5])
        for kw in mainstream_keywords:
            if kw in ddg_text and f'不{kw}' in article:
                score = min(10, score + 2)
                break

    return round(score, 1)


# ────────────────────────────────────────────────────────────────────
# Main assessment function
# ────────────────────────────────────────────────────────────────────

def assess_value_density(
    article: str,
    research_output: dict,
    ddg_results: list[dict] | None = None
) -> dict:
    """Assess value density of article across 5 dimensions.

    Args:
        article: The article text to assess
        research_output: Research output dict containing sources, claims, etc.
        ddg_results: DuckDuckGo search results (list of dicts with 'title', 'body')

    Returns:
        Dict with:
        - overall_score: float 0-10
        - details: dict with 5 dimension scores
        - recommendation: "pass" | "needs_human" | "fail"
        - reason: str explaining the recommendation
    """
    # Mock DDG results if not provided (for testing)
    if ddg_results is None:
        ddg_results = []

    # Extract claims for unique info check
    claims = _extract_claims(article)

    # Run all 5 checks
    unique_info_score = _check_unique_info(claims, ddg_results)
    verifiable_score = _check_verifiable_operations(article)
    source_depth_score = _check_source_depth(article, research_output)
    judgment_score = _check_judgment_density(article)
    counter_intuitive_score = _check_counter_intuitive(article, ddg_results)

    # Calculate overall (weighted average)
    weights = {
        "unique_info": 0.20,
        "verifiable": 0.25,
        "source_depth": 0.20,
        "judgment": 0.20,
        "counter_intuitive": 0.15,
    }

    overall = (
        unique_info_score * weights["unique_info"] +
        verifiable_score * weights["verifiable"] +
        source_depth_score * weights["source_depth"] +
        judgment_score * weights["judgment"] +
        counter_intuitive_score * weights["counter_intuitive"]
    )
    overall = round(overall, 1)

    # Determine recommendation
    # 门控规则（三档，与 ROADMAP.md 和 SYSTEM-DEFINITION.md 保持一致）:
    #   < 4.0   → fail（slop，不可发布）
    #   4.0~6.0 → needs_human（需人工判断）
    #   >= 6.0  → pass（推荐发布）
    if overall < 4.0:
        recommendation = "fail"
        reason = (
            f"综合评分 {overall}/10 低于门槛。"
            f"独占信息({unique_info_score}/10)、可验证操作({verifiable_score}/10)、"
            f"素材深度({source_depth_score}/10)、判断密度({judgment_score}/10)、"
            f"反直觉({counter_intuitive_score}/10)均偏低，内容疑似 slop。"
        )
    elif overall < 6.0:
        recommendation = "needs_human"
        weak_dims = []
        if unique_info_score < 5:
            weak_dims.append("独占信息")
        if verifiable_score < 5:
            weak_dims.append("可验证操作")
        if source_depth_score < 5:
            weak_dims.append("素材深度")
        if judgment_score < 5:
            weak_dims.append("判断密度")
        if counter_intuitive_score < 5:
            weak_dims.append("反直觉")
        reason = (
            f"综合评分 {overall}/10 处于边界区。"
            f"{'、'.join(weak_dims)} 维度较弱，需人工判断内容价值。"
        )
    else:
        recommendation = "pass"
        reason = (
            f"综合评分 {overall}/10，内容密度充足。"
            f"独占信息({unique_info_score}/10)、可验证操作({verifiable_score}/10)、"
            f"素材深度({source_depth_score}/10)、判断密度({judgment_score}/10)、"
            f"反直觉({counter_intuitive_score}/10)均达到发布标准。"
        )

    return {
        "overall_score": overall,
        "details": {
            "unique_info_ratio": unique_info_score,
            "verifiable_operations": verifiable_score,
            "source_depth": source_depth_score,
            "judgment_density": judgment_score,
            "counter_intuitive": counter_intuitive_score,
        },
        "recommendation": recommendation,
        "reason": reason,
        "claims_analyzed": len(claims),
    }


# ────────────────────────────────────────────────────────────────────
# Test function
# ────────────────────────────────────────────────────────────────────

def _test():
    """Run a simple test of the value density assessment."""
    # Sample article with decent value density
    article = """
# Nginx 缓存配置实战指南

## 为什么需要缓存

很多开发者认为 Nginx 只是反向代理，实际上 Nginx 的缓存能力可以显著降低后端压力。实测显示，合理配置缓存可减少 70% 的后端请求。

## 基础配置

以下命令安装 Nginx：

```bash
sudo apt install nginx
```

在 `/etc/nginx/nginx.conf` 中添加：

```nginx
proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m;
```

## 性能对比

不使用缓存时，TPS 约 2000；启用缓存后，TPS 可达 8000+。提升高达 4 倍。

根据官方文档，Nginx 1.24+ 的缓存性能有显著优化。

## 常见误区

很多人认为缓存越多越好，实际上过度的缓存会导致数据不一致。应该根据业务特点设置合理的过期时间。

推荐使用 `proxy_cache_valid` 指令明确指定过期策略。
"""

    research_output = {
        "sources": [
            "https://nginx.org/docs/",
            "https://developer.wordpress.org/",
            "https://php.net/manual",
        ]
    }

    ddg_results = [
        {"title": "Nginx Caching Guide", "body": "Nginx can cache responses"},
        {"title": "How to Configure Nginx", "body": "Basic nginx configuration"},
        {"title": "Nginx Performance", "body": "Nginx is fast"},
    ]

    result = assess_value_density(article, research_output, ddg_results)

    print("=== Value Density Assessment ===")
    print(f"Overall Score: {result['overall_score']}/10")
    print(f"Recommendation: {result['recommendation']}")
    print(f"Reason: {result['reason']}")
    print("\nDetails:")
    for dim, score in result['details'].items():
        print(f"  {dim}: {score}/10")
    print(f"\nClaims analyzed: {result['claims_analyzed']}")

    # Test with low-quality article
    slop_article = """
# 关于 Nginx

Nginx 是一个很好的工具。很多人都在使用 Nginx。

## 介绍

Nginx 很有用。它可以做很多事情。

## 总结

总的来说，Nginx 是一款非常优秀的软件，值得大家使用。
"""

    print("\n=== Slop Article Test ===")
    slop_result = assess_value_density(slop_article, {}, ddg_results)
    print(f"Overall Score: {slop_result['overall_score']}/10")
    print(f"Recommendation: {slop_result['recommendation']}")
    print(f"Reason: {slop_result['reason']}")


if __name__ == "__main__":
    _test()
