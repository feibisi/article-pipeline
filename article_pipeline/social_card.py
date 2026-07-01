"""OG/社交分享卡自动生成.

T-020: OG/社交分享卡自动生成（依赖 T-017 Studio 契约）
基于 hero_brief 和 seo_metadata 生成社交分享卡。
"""

import os
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from article_pipeline.contracts import CompileOutput, HeroBrief, SeoMetadata


@dataclass
class SocialCardSpec:
    """社交分享卡规格"""
    title: str
    description: str
    dimensions: str  # 如 "1200x630"
    output_path: str
    template: str = "default"  # 模板名称


def generate_social_card(spec: SocialCardSpec) -> str | None:
    """生成社交分享卡.

    Args:
        spec: SocialCardSpec

    Returns:
        输出路径或 None
    """
    # 简化版：使用 Puppeteer 或类似工具截图
    # 实际实现需要与 Studio 协作
    output_dir = os.path.dirname(spec.output_path)
    os.makedirs(output_dir, exist_ok=True)

    # Placeholder: 创建一个简单的 HTML 模板
    html_path = spec.output_path.replace(".png", ".html")
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            margin: 0;
            padding: 0;
            width: {spec.dimensions.split('x')[0]}px;
            height: {spec.dimensions.split('x')[1]}px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
        }}
        .card {{
            padding: 60px;
            max-width: 80%;
        }}
        h1 {{
            font-size: 48px;
            margin: 0 0 20px 0;
            line-height: 1.2;
        }}
        p {{
            font-size: 24px;
            margin: 0;
            opacity: 0.9;
        }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{spec.title}</h1>
        <p>{spec.description}</p>
    </div>
</body>
</html>
"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 使用 Pinchtab 渲染 HTML 为图片
    try:
        result = subprocess.run(
            [
                "curl", "-s", "-o", spec.output_path,
                "http://localhost:9867/screenshot",
                "--data-urlencode", f"url=file://{html_path}",
                "--data-urlencode", f"width={spec.dimensions.split('x')[0]}",
                "--data-urlencode", f"height={spec.dimensions.split('x')[1]}",
            ],
            capture_output=True,
            timeout=30,
        )

        if result.returncode == 0 and os.path.exists(spec.output_path):
            # 清理临时 HTML
            os.remove(html_path)
            return spec.output_path
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [social_card] Failed to generate: {e}")
        return None


def extract_social_card_spec(compile_output: CompileOutput, output_path: str) -> SocialCardSpec:
    """从 CompileOutput 提取社交分享卡规格.

    Args:
        compile_output: compile 层的输出
        output_path: 输出路径

    Returns:
        SocialCardSpec
    """
    if compile_output.seo_metadata:
        title = compile_output.seo_metadata.title
        description = compile_output.seo_metadata.description
    else:
        title = "文章标题"
        description = "文章描述"

    if compile_output.hero_brief:
        dimensions = compile_output.hero_brief.dimensions
    else:
        dimensions = "1200x630"  # 标准 OG 尺寸

    return SocialCardSpec(
        title=title[:60] if title else "",  # 限制长度
        description=description[:100] if description else "",
        dimensions=dimensions,
        output_path=output_path,
    )


def run_social_card_generation(compile_output: CompileOutput, output_dir: str = "assets/social-cards") -> str | None:
    """运行社交分享卡生成流程.

    Args:
        compile_output: compile 层的输出
        output_dir: 输出目录

    Returns:
        生成路径或 None
    """
    import hashlib
    title_hash = hashlib.md5(
        (compile_output.seo_metadata.title if compile_output.seo_metadata else "").encode()
    ).hexdigest()[:8]
    output_path = os.path.join(output_dir, f"og-{title_hash}.png")

    spec = extract_social_card_spec(compile_output, output_path)
    return generate_social_card(spec)


if __name__ == "__main__":
    # Test social card generation
    from article_pipeline.contracts import CompileOutput, HeroBrief, SeoMetadata

    compile_output = CompileOutput(
        markdown="# Test",
        hero_brief=HeroBrief(
            concept="服务器机房",
            mood="专业",
            dimensions="1200x630",
        ),
        seo_metadata=SeoMetadata(
            title="Nginx 缓存配置完全指南",
            description="从零开始学习 Nginx 缓存配置，降低后端压力 70%",
            keywords=[],
            excerpt="Test",
        ),
        tags=[],
        cta=[],
    )

    print("=== Social Card Generation Test ===")
    result = run_social_card_generation(compile_output)
    if result:
        print(f"Generated: {result}")
    else:
        print("Generation failed")
