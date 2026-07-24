"""Tests for social card generation (T-020)."""

import pytest
from article_pipeline.social_card import (
    extract_social_card_spec,
    SocialCardSpec,
)
from article_pipeline.contracts import CompileOutput, HeroBrief, SeoMetadata


class TestExtractSocialCardSpec:
    def test_extract_with_full_metadata(self):
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=HeroBrief(
                concept="服务器机房",
                mood="专业",
                dimensions="1200x630",
            ),
            seo_metadata=SeoMetadata(
                title="Nginx 缓存配置指南",
                description="从零开始学习",
                keywords=[],
                excerpt="Test",
            ),
            tags=[],
            cta=[],
        )

        spec = extract_social_card_spec(compile_output, "output/og-test.png")

        assert spec.title == "Nginx 缓存配置指南"
        assert spec.description == "从零开始学习"
        assert spec.dimensions == "1200x630"
        assert spec.output_path == "output/og-test.png"
        assert spec.template == "default"

    def test_extract_with_minimal_data(self):
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=None,
            seo_metadata=SeoMetadata(
                title="",
                description="",
                keywords=[],
                excerpt="",
            ),
            tags=[],
            cta=[],
        )

        spec = extract_social_card_spec(compile_output, "output/og-test.png")

        assert spec.title == ""
        assert spec.description == ""
        assert spec.dimensions == "1200x630"  # fallback default

    def test_title_truncation(self):
        long_title = "A" * 100
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=None,
            seo_metadata=SeoMetadata(
                title=long_title,
                description="Test",
                keywords=[],
                excerpt="Test",
            ),
            tags=[],
            cta=[],
        )

        spec = extract_social_card_spec(compile_output, "output/og-test.png")

        assert len(spec.title) <= 60

    def test_description_truncation(self):
        long_desc = "B" * 200
        compile_output = CompileOutput(
            markdown="# Test",
            hero_brief=None,
            seo_metadata=SeoMetadata(
                title="Test",
                description=long_desc,
                keywords=[],
                excerpt="Test",
            ),
            tags=[],
            cta=[],
        )

        spec = extract_social_card_spec(compile_output, "output/og-test.png")

        assert len(spec.description) <= 100



# REMOVED: dataclass constructor-echo tests. They instantiated a dataclass
# and asserted back the literals just passed in — the "code under test" was
# the literal in the test body. Zero defect-detection power.
