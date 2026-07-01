"""Compile layer — assemble all layer outputs into final writer prompt.

This is Layer 5 of the cascade: it takes outputs from Synthesis, Framework, Style,
and Prosody layers, combines with validated material, and produces the final prompt
for the writer LLM.
"""

import json
from typing import Any
from dataclasses import dataclass

from article_pipeline.contracts import FrameworkOutput, StyleOutput, ProsodyOutput


def _count_tokens(text: str) -> int:
    """Rough token count (1 token ≈ 3 characters for Chinese)."""
    return len(text) // 3


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
) -> str:
    """Run compile layer: assemble all outputs into writer prompt.

    Args:
        framework: FrameworkOutput from Layer 2
        style: StyleOutput from Layer 3
        prosody: ProsodyOutput from Layer 4
        material: Validated material from research
        keyword: Original keyword
        category: Article category

    Returns:
        Complete writer prompt
    """
    return build_writer_prompt(
        framework=framework,
        style=style,
        prosody=prosody,
        material=material,
        keyword=keyword,
        category=category,
    )


if __name__ == "__main__":
    # Test compile layer
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

    prompt = run_compile(framework, style, prosody, material, "Nginx 缓存", "tutorial")
    print("=== Compile Prompt ===")
    print(prompt[:500])
    print("...")
