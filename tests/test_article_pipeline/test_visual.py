"""Tests for visual collaboration layer (T-017)."""

import pytest
from article_pipeline.visual import extract_visual_brief, VisualBrief
from article_pipeline.contracts import (
    CompileOutput,
    HeroBrief,
    VisualAnchor,
    SeoMetadata,
)


class TestExtractVisualBrief:
    def test_extract_with_hero_and_anchors(self):
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=HeroBrief(
                concept="服务器机房",
                mood="专业",
                dimensions="16:9",
                keywords=["server"],
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

        assert brief.request_id.startswith("vb-")
        assert brief.requester == "elementary"
        assert brief.article_keyword == "Test Article"
        assert brief.hero_request is not None
        assert brief.hero_request["concept"] == "服务器机房"
        assert brief.hero_request["mood"] == "专业"
        assert len(brief.anchors) == 1
        assert brief.anchors[0]["section_role"] == "opening"
        assert brief.anchors[0]["visual_type"] == "screenshot"
        assert brief.anchors[0]["screenshot_target"] == "https://example.com"

    def test_extract_with_minimal_data(self):
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=None,
            visual_anchors=[],
            seo_metadata=SeoMetadata(
                title="Minimal",
                description="",
                keywords=[],
                excerpt="",
            ),
            tags=[],
            cta=[],
        )

        brief = extract_visual_brief(compile_output)

        assert brief.hero_request is None
        assert len(brief.anchors) == 0

    def test_custom_request_id(self):
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=None,
            visual_anchors=[],
            seo_metadata=SeoMetadata(
                title="Custom ID",
                description="",
                keywords=[],
                excerpt="",
            ),
            tags=[],
            cta=[],
        )

        brief = extract_visual_brief(compile_output, request_id="custom-123")

        assert brief.request_id == "custom-123"

    def test_anchor_with_diagram_spec(self):
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=None,
            visual_anchors=[
                VisualAnchor(
                    section_role="body",
                    concept="架构图",
                    visual_type="diagram",
                    diagram_spec="三层架构：客户端-网关-后端",
                ),
            ],
            seo_metadata=SeoMetadata(
                title="Diagram Test",
                description="",
                keywords=[],
                excerpt="",
            ),
            tags=[],
            cta=[],
        )

        brief = extract_visual_brief(compile_output)

        assert len(brief.anchors) == 1
        assert brief.anchors[0]["visual_type"] == "diagram"
        assert brief.anchors[0]["diagram_spec"] == "三层架构：客户端-网关-后端"

    def test_brief_version(self):
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=None,
            visual_anchors=[],
            seo_metadata=SeoMetadata(
                title="Version Test",
                description="",
                keywords=[],
                excerpt="",
            ),
            tags=[],
            cta=[],
        )

        brief = extract_visual_brief(compile_output)

        assert brief.version == "2.0"
        assert brief.usage == "article"
