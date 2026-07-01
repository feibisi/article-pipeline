"""Screenshot automation — visual_anchors with screenshot_target.

T-019: 截图自动化（与质检管线对接）
从 visual_anchors 中提取 screenshot_target → 调用 Pinchtab API → 截图 → 优化 → 存储
"""

import os
import json
import subprocess
from dataclasses import dataclass
from typing import Literal
from pathlib import Path

from article_pipeline.contracts import VisualAnchor


@dataclass
class ScreenshotAsset:
    """截图资产"""
    url: str  # 源 URL
    path: str  # 本地存储路径
    visual_type: Literal["hero", "step", "comparison"]
    optimized: bool = False  # 是否已优化


def extract_screenshot_targets(anchors: list[VisualAnchor]) -> list[str]:
    """从 visual_anchors 提取需要截图的 URL.

    Args:
        anchors: visual_anchors 列表

    Returns:
        需要截图的 URL 列表（去重）
    """
    urls = set()
    for anchor in anchors:
        if anchor.visual_type == "screenshot" and anchor.screenshot_target:
            urls.add(anchor.screenshot_target)
    return sorted(urls)


def capture_with_pinchtab(url: str, output_dir: str = "assets/screenshots") -> str | None:
    """使用 Pinchtab API 截图.

    Args:
        url: 目标 URL
        output_dir: 输出目录

    Returns:
        截图路径或 None
    """
    # Pinchtab 服务运行在 http://localhost:9867
    try:
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        filename = f"screenshot-{url_hash}.png"
        output_path = os.path.join(output_dir, filename)
        os.makedirs(output_dir, exist_ok=True)

        # 调用 Pinchtab API
        result = subprocess.run(
            [
                "curl", "-s", "-o", output_path,
                f"http://localhost:9867/screenshot",
                "--data-urlencode", f"url={url}",
                "--data-urlencode", f"width=1200",
                "--data-urlencode", f"height=800",
            ],
            capture_output=True,
            timeout=30,
        )

        if result.returncode == 0 and os.path.exists(output_path):
            # 检查文件是否有效（非空且是图片）
            if os.path.getsize(output_path) > 1000:
                return output_path
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [screenshot] Failed to capture {url}: {e}")
        return None


def optimize_image(input_path: str) -> str | None:
    """使用 img-process 优化图片.

    Args:
        input_path: 输入路径

    Returns:
        优化后的路径或 None
    """
    try:
        output_path = input_path.replace(".png", ".webp")
        result = subprocess.run(
            ["img-process", "optimize", input_path, "-o", output_path, "--format", "webp"],
            capture_output=True,
            timeout=60,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # 如果 img-process 不可用，返回原路径
        return input_path


def run_screenshot_pipeline(
    anchors: list[VisualAnchor],
    output_dir: str = "assets/screenshots",
    optimize: bool = True,
) -> list[ScreenshotAsset]:
    """运行截图管线：提取 URL → 截图 → 优化.

    Args:
        anchors: visual_anchors 列表
        output_dir: 输出目录
        optimize: 是否优化图片

    Returns:
        ScreenshotAsset 列表
    """
    assets = []
    urls = extract_screenshot_targets(anchors)

    for url in urls:
        print(f"  [screenshot] Capturing {url[:50]}...")
        raw_path = capture_with_pinchtab(url, output_dir)

        if raw_path:
            final_path = raw_path
            if optimize:
                final_path = optimize_image(raw_path) or raw_path

            assets.append(ScreenshotAsset(
                url=url,
                path=final_path,
                visual_type="step",
                optimized=(final_path != raw_path),
            ))
            print(f"  [screenshot] Saved to {final_path}")
        else:
            print(f"  [screenshot] Failed to capture {url}")

    return assets


def update_article_metadata(
    task_id: int,
    assets: list[ScreenshotAsset],
    db,
) -> None:
    """更新文章元数据，添加截图资产路径.

    Args:
        task_id: 任务 ID
        assets: 截图资产列表
        db: PipelineDB 实例
    """
    meta = {
        "screenshots": [
            {
                "url": a.url,
                "path": a.path,
                "visual_type": a.visual_type,
            }
            for a in assets
        ]
    }
    db.save_meta(task_id, meta)


if __name__ == "__main__":
    # Test screenshot pipeline
    from article_pipeline.contracts import VisualAnchor

    anchors = [
        VisualAnchor(
            section_role="opening",
            concept="配置界面",
            visual_type="screenshot",
            screenshot_target="https://wenpai.net",
        ),
        VisualAnchor(
            section_role="body",
            concept="管理后台",
            visual_type="screenshot",
            screenshot_target="https://wenpai.net/admin",
        ),
    ]

    print("=== Screenshot Pipeline Test ===")
    assets = run_screenshot_pipeline(anchors, optimize=False)
    print(f"\nCaptured {len(assets)} screenshots:")
    for asset in assets:
        print(f"  - {asset.url[:50]} -> {asset.path}")
