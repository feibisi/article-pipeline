"""Visual collaboration layer — Studio visual brief via NATS.

T-017: 从 compile 输出提取 visual_anchors → 构建 visual_brief JSON
通过 NATS 发送到 vm.studio.visual-request，监听 vm.elementary.visual-response
"""

import json
import subprocess
from dataclasses import dataclass, field
from typing import Literal
from datetime import datetime, timezone

from article_pipeline.contracts import CompileOutput, VisualAnchor


@dataclass
class VisualBrief:
    """视觉需求简报（发送给 Studio）"""
    request_id: str  # 唯一请求 ID
    requester: str  # 请求者（如 "elementary"）
    article_keyword: str  # 文章关键词（用于素材命名）
    hero_request: dict | None = None  # hero image 需求
    anchors: list[dict] = field(default_factory=list)  # visual_anchors 转换
    budget: dict = field(default_factory=dict)  # 预算/约束信息
    usage: str = "article"  # 使用场景（article/social/card）
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: str = "2.0"  # 契约版本


@dataclass
class VisualAsset:
    """Studio 返回的视觉资产"""
    request_id: str
    asset_type: Literal["hero", "screenshot", "diagram", "illustration"]
    url: str  # 资产 URL 或本地路径
    metadata: dict = field(default_factory=dict)


def extract_visual_brief(
    compile_output: CompileOutput,
    request_id: str | None = None,
) -> VisualBrief:
    """从 CompileOutput 提取视觉简报.

    Args:
        compile_output: compile 层的输出
        request_id: 可选的请求 ID，默认生成 UUID

    Returns:
        VisualBrief 可发送给 Studio
    """
    if request_id is None:
        from uuid import uuid4
        request_id = f"vb-{uuid4().hex[:8]}"

    # hero brief from compile output
    hero_request = None
    if compile_output.hero_brief:
        hero_request = {
            "concept": compile_output.hero_brief.concept,
            "mood": compile_output.hero_brief.mood,
            "dimensions": compile_output.hero_brief.dimensions,
            "keywords": compile_output.hero_brief.keywords,
        }

    # convert visual anchors to flat dicts
    anchors = []
    for va in compile_output.visual_anchors:
        anchor_dict = {
            "section_role": va.section_role,
            "concept": va.concept,
            "visual_type": va.visual_type,
        }
        if va.screenshot_target:
            anchor_dict["screenshot_target"] = va.screenshot_target
        if va.diagram_spec:
            anchor_dict["diagram_spec"] = va.diagram_spec
        anchors.append(anchor_dict)

    return VisualBrief(
        request_id=request_id,
        requester="elementary",
        article_keyword=compile_output.seo_metadata.title if compile_output.seo_metadata else "",
        hero_request=hero_request,
        anchors=anchors,
        budget={"priority": "normal", "max_assets": len(anchors) + (1 if hero_request else 0)},
        usage="article",
    )


def send_visual_request(brief: VisualBrief) -> bool:
    """通过 NATS 发送视觉请求到 Studio.

    Args:
        brief: VisualBrief

    Returns:
        是否成功发送
    """
    try:
        payload = json.dumps({
            "to": "studio",
            "type": "visual-request",
            "request_id": brief.request_id,
            "requester": brief.requester,
            "payload": {
                "article_keyword": brief.article_keyword,
                "hero_request": brief.hero_request,
                "anchors": brief.anchors,
                "budget": brief.budget,
                "usage": brief.usage,
                "created_at": brief.created_at,
                "version": brief.version,
            },
        }, ensure_ascii=False)

        result = subprocess.run(
            ["vm-dm", "studio", payload],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [visual] Failed to send NATS request: {e}")
        return False


def await_visual_response(request_id: str, timeout: int = 300) -> VisualAsset | None:
    """等待 Studio 返回视觉资产.

    Args:
        request_id: 请求 ID
        timeout: 超时时间（秒）

    Returns:
        VisualAsset 或 None
    """
    # 简化版：实际实现需要轮询 NATS 或监听响应
    # 这里返回 None 表示需要手动实现监听逻辑
    print(f"  [visual] Awaiting response for {request_id} (timeout: {timeout}s)")
    return None


def log_visual_asset(asset: VisualAsset, log_path: str = "logs/visual-assets.jsonl") -> None:
    """记录视觉资产到审计日志.

    Args:
        asset: VisualAsset
        log_path: 日志路径
    """
    import os
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "request_id": asset.request_id,
        "asset_type": asset.asset_type,
        "url": asset.url,
        "metadata": asset.metadata,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def run_visual_collaboration(compile_output: CompileOutput) -> dict:
    """运行视觉协作流程：提取 brief → 发送请求 → 等待响应 → 记录资产.

    Args:
        compile_output: compile 层的输出

    Returns:
        协作结果摘要
    """
    brief = extract_visual_brief(compile_output)
    sent = send_visual_request(brief)

    result = {
        "request_id": brief.request_id,
        "sent": sent,
        "hero_requested": brief.hero_request is not None,
        "anchors_requested": len(brief.anchors),
        "assets_received": [],
    }

    if not sent:
        result["error"] = "Failed to send NATS request"
        return result

    # 等待响应（实际实现需要异步处理）
    # asset = await_visual_response(brief.request_id)
    # if asset:
    #     log_visual_asset(asset)
    #     result["assets_received"].append(asset.url)

    return result


if __name__ == "__main__":
    # Test visual brief extraction
    from article_pipeline.contracts import (
        CompileOutput,
        HeroBrief,
        VisualAnchor,
        SeoMetadata,
    )

    compile_output = CompileOutput(
        markdown="# Test",
        hero_brief=HeroBrief(
            concept="服务器机房",
            mood="专业",
            dimensions="16:9",
        ),
        visual_anchors=[
            VisualAnchor(
                section_role="opening",
                concept="配置界面",
                visual_type="screenshot",
                screenshot_target="https://example.com",
            ),
        ],
        seo_metadata=SeoMetadata(
            title="Test Article",
            description="Test",
            keywords=[],
            excerpt="Test",
        ),
        tags=[],
        cta=[],
    )

    brief = extract_visual_brief(compile_output)
    print("=== Visual Brief ===")
    print(json.dumps({
        "request_id": brief.request_id,
        "article_keyword": brief.article_keyword,
        "hero_request": brief.hero_request,
        "anchors": brief.anchors,
    }, ensure_ascii=False, indent=2))

    print("\n=== Send Result ===")
    result = run_visual_collaboration(compile_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
