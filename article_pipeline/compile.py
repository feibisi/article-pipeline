"""Compile layer — assemble all layer outputs into final writer prompt.

This is Layer 5 of the cascade: it takes outputs from Synthesis, Framework, Style,
and Prosody layers, combines with validated material, and produces the final prompt
for the writer LLM.

T-016: Extended to output structured JSON metadata alongside markdown.
"""

import json
from typing import Any
from dataclasses import dataclass, field

from article_pipeline.contracts import (
    FrameworkOutput,
    StyleOutput,
    ProsodyOutput,
    CompileOutput,
    HeroBrief,
    VisualAnchor,
    SeoMetadata,
)


def _count_tokens(text: str) -> int:
    """Rough token count (1 token ≈ 3 characters for Chinese)."""
    return len(text) // 3


def _infer_hero_brief(
    framework: FrameworkOutput,
    keyword: str,
    category: str,
) -> HeroBrief:
    """从 framework 和关键词推断封面图需求.

    简化版启发式规则，后续可升级为 LLM 推断。
    """
    # 根据品类推断 mood
    mood_map = {
        "tutorial": "清晰、实用、可信赖",
        "troubleshooting": "紧急、解决、专业",
        "comparison": "客观、对比、清晰",
        "opinion": "鲜明、有立场、引人思考",
        "case-study": "真实、经验丰富、可借鉴",
    }
    mood = mood_map.get(category, "专业、清晰、有价值")

    # 从 visual_anchors 或 takeaway 推断 concept
    if framework.visual_anchors and framework.visual_anchors[0].get("concept"):
        concept = framework.visual_anchors[0]["concept"]
    else:
        # fallback: 从 takeaway 提取关键词
        concept = f"{keyword} 技术场景，专业风格"

    return HeroBrief(
        concept=concept,
        mood=mood,
        dimensions="16:9",  # 标准 hero 尺寸
        keywords=[keyword, category],
    )


def _build_visual_anchors(
    framework: FrameworkOutput,
) -> list[VisualAnchor]:
    """从 framework.visual_anchors 构建类型化视觉锚点."""
    if not framework.visual_anchors:
        return []

    anchors = []
    for va in framework.visual_anchors:
        anchor = VisualAnchor(
            section_role=va.get("section_role", ""),
            concept=va.get("concept", ""),
            visual_type=va.get("visual_type", "none"),
            screenshot_target=va.get("screenshot_target"),
            diagram_spec=va.get("diagram_spec"),
        )
        anchors.append(anchor)
    return anchors


def _infer_seo_metadata(
    framework: FrameworkOutput,
    keyword: str,
    material: dict,
) -> SeoMetadata:
    """从 framework 和素材推断 SEO 元数据."""
    # 标题：takeaway + 关键词
    title = f"{framework.takeaway} — {keyword}"

    # 描述：entry_state + exit_state
    description = f"{framework.reader_entry_state} → {framework.reader_exit_state}"

    # 关键词
    keywords = [keyword]

    # 摘要：取 takeaway 前 150 字
    excerpt = framework.takeaway[:150]

    return SeoMetadata(
        title=title,
        description=description,
        keywords=keywords,
        excerpt=excerpt,
    )


def _derive_tags(
    category: str,
    keyword: str,
    framework: FrameworkOutput,
) -> list[str]:
    """从品类和 framework 推导标签."""
    tags = [category]

    # 从 method 提取技术栈
    if "nginx" in keyword.lower():
        tags.append("nginx")
    if "wordpress" in keyword.lower():
        tags.append("wordpress")

    return list(set(tags))


def _extract_cta(
    framework: FrameworkOutput,
) -> list[str]:
    """从 framework 提取下一步行动建议."""
    # 简化版：从 exit_state 推断
    if "配置" in framework.reader_exit_state:
        return ["根据实际情况调整配置参数", "在测试环境验证后再部署"]
    if "排查" in framework.reader_exit_state or "解决" in framework.reader_exit_state:
        return ["按诊断路径逐步排查", "验证修复是否生效"]
    return ["将文章收藏作为参考"]


def build_writer_prompt(
    framework: FrameworkOutput,
    style: StyleOutput,
    prosody: ProsodyOutput,
    material: dict,
    keyword: str,
    category: str,
    max_tokens: int = 8000,
) -> str:
    """Build complete writer prompt from all layer outputs.

    Args:
        framework: FrameworkOutput from Layer 2
        style: StyleOutput from Layer 3
        prosody: ProsodyOutput from Layer 4
        material: Validated material from research
        keyword: Original keyword
        category: Article category
        max_tokens: Maximum prompt tokens (default 8000)

    Returns:
        Complete writer prompt
    """
    sections = []

    # 1. 核心判断
    if framework.takeaway:
        sections.append(f"""## 核心判断

{framework.takeaway}

读者进入时认为：{framework.reader_entry_state}
读者出去时应该理解：{framework.reader_exit_state}
""")

    # 2. 文章结构（方法论）
    if framework.structure:
        sections.append("## 文章结构\n")
        for i, section in enumerate(framework.structure):
            role = section.get("role", "body")
            purpose = section.get("purpose", "")
            sections.append(f"### {i+1}. {role}\n{purpose}\n")
        sections.append("\n")

    # 3. 风格约束
    constraints = style.constraints if hasattr(style, 'constraints') else {}
    if constraints:
        sections.append("## 风格约束\n")
        require = constraints.get("require", [])
        avoid = constraints.get("avoid", [])
        if require:
            sections.append("### 必须做到\n")
            for r in require:
                sections.append(f"- {r}\n")
        if avoid:
            sections.append("### 避免出现\n")
            for a in avoid:
                sections.append(f"- {a}\n")
        sections.append("\n")

    # 4. 语感参考
    if prosody.samples:
        sections.append("## 语感参考\n")
        sections.append(f"{prosody.rhythm_hint}\n\n")
        sections.append("参考范本：\n")
        for sample in prosody.samples[:2]:
            sections.append(f"> {sample[:100]}...\n\n")

    # 5. 精选素材
    if material:
        sections.append("## 精选素材\n")
        evidence = material.get("evidence_for", [])
        for e in evidence[:5]:
            if isinstance(e, dict):
                claim = e.get("claim", "")
                source = e.get("source", "")
                sections.append(f"- {claim} (来源: {source})\n")
            else:
                sections.append(f"- {e}\n")
        sections.append("\n")

    # 6. 写作要求
    sections.append(f"""## 写作要求

关键词：{keyword}
分类：{category}

基于以上结构和素材，写成一篇完整的文章。
保持连贯性，每段自然过渡。
不要使用"综上所述""首先...其次"等 AI 惯用套话。
""")

    # 组装并检查 token
    prompt = "\n".join(sections)

    # Token 门控：超限时裁剪素材
    if _count_tokens(prompt) > max_tokens:
        # 移除精选素材部分
        sections = [s for s in sections if "精选素材" not in s]
        prompt = "\n".join(sections)

    return prompt


def run_compile(
    framework: FrameworkOutput,
    style: StyleOutput,
    prosody: ProsodyOutput,
    material: dict,
    keyword: str,
    category: str,
    max_tokens: int = 8000,
) -> CompileOutput:
    """Run compile layer: assemble all outputs into structured output.

    Args:
        framework: FrameworkOutput from Layer 2
        style: StyleOutput from Layer 3
        prosody: ProsodyOutput from Layer 4
        material: Validated material from research
        keyword: Original keyword
        category: Article category
        max_tokens: Maximum prompt tokens (default 8000)

    Returns:
        CompileOutput with markdown prompt and structured metadata
    """
    # 1. 构建 markdown prompt
    markdown = build_writer_prompt(
        framework=framework,
        style=style,
        prosody=prosody,
        material=material,
        keyword=keyword,
        category=category,
        max_tokens=max_tokens,
    )

    # 2. 构建结构化元数据
    hero_brief = _infer_hero_brief(framework, keyword, category)
    visual_anchors = _build_visual_anchors(framework)
    seo_metadata = _infer_seo_metadata(framework, keyword, material)
    tags = _derive_tags(category, keyword, framework)
    cta = _extract_cta(framework)

    return CompileOutput(
        markdown=markdown,
        hero_brief=hero_brief,
        visual_anchors=visual_anchors,
        seo_metadata=seo_metadata,
        tags=tags,
        cta=cta,
    )


def compile_to_json(output: CompileOutput) -> str:
    """Convert CompileOutput to JSON string for downstream tools.

    Args:
        output: CompileOutput from run_compile

    Returns:
        JSON string with structured metadata
    """
    return json.dumps({
        "markdown": output.markdown,
        "hero_brief": {
            "concept": output.hero_brief.concept if output.hero_brief else "",
            "mood": output.hero_brief.mood if output.hero_brief else "",
            "dimensions": output.hero_brief.dimensions if output.hero_brief else "",
            "keywords": output.hero_brief.keywords if output.hero_brief else [],
        } if output.hero_brief else None,
        "visual_anchors": [
            {
                "section_role": v.section_role,
                "concept": v.concept,
                "visual_type": v.visual_type,
                "screenshot_target": v.screenshot_target,
                "diagram_spec": v.diagram_spec,
            }
            for v in output.visual_anchors
        ],
        "seo_metadata": {
            "title": output.seo_metadata.title if output.seo_metadata else "",
            "description": output.seo_metadata.description if output.seo_metadata else "",
            "keywords": output.seo_metadata.keywords if output.seo_metadata else [],
            "excerpt": output.seo_metadata.excerpt if output.seo_metadata else "",
        } if output.seo_metadata else None,
        "tags": output.tags,
        "cta": output.cta,
    }, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    # Test compile layer with structured output
    from article_pipeline.contracts import FrameworkOutput, StyleOutput, ProsodyOutput

    framework = FrameworkOutput(
        method="cognitive_scaffold",
        structure=[
            {"role": "opening", "purpose": "展示终态"},
            {"role": "body", "purpose": "逐步骤执行"},
        ],
        takeaway="Nginx 缓存可显著降低后端压力",
        reader_entry_state="读者认为缓存很复杂",
        reader_exit_state="读者理解了 Nginx 缓存的基本配置",
        visual_anchors=[
            {
                "section_role": "opening",
                "concept": "Nginx 配置界面，绿色指示灯",
                "visual_type": "screenshot",
                "screenshot_target": "https://nginx.org/en/docs/",
            },
        ],
    )

    style = StyleOutput(
        vector={"density": 0.0, "warmth": 0.4},
        constraints={"require": ["展示终态", "每步有验证"], "avoid": ["抽象理论先行"]},
        rendered_instructions="略",
        aesthetic_concepts=["分寸"],
    )

    prosody = ProsodyOutput(
        samples=["示例范本..."],
        sample_type="scaffold",
        negative_constraints="不要说'综上所述'",
        rhythm_hint="层层递进",
    )

    material = {"evidence_for": [{"claim": "实测显示缓存减少 70% 请求", "source": "Nginx 官方"}]}

    output = run_compile(framework, style, prosody, material, "Nginx 缓存", "tutorial")
    print("=== Compile Markdown (first 500 chars) ===")
    print(output.markdown[:500])
    print("\n=== Structured Metadata ===")
    print(json.dumps({
        "hero_brief": {
            "concept": output.hero_brief.concept if output.hero_brief else None,
            "mood": output.hero_brief.mood if output.hero_brief else None,
        },
        "visual_anchors_count": len(output.visual_anchors),
        "seo_title": output.seo_metadata.title if output.seo_metadata else None,
        "tags": output.tags,
        "cta": output.cta,
    }, ensure_ascii=False, indent=2))
