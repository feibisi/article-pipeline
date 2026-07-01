"""Tests for screenshot automation (T-019)."""

import pytest
from article_pipeline.screenshot import (
    extract_screenshot_targets,
    ScreenshotAsset,
)
from article_pipeline.contracts import VisualAnchor


class TestExtractScreenshotTargets:
    def test_extract_single_target(self):
        anchors = [
            VisualAnchor(
                section_role="opening",
                concept="配置界面",
                visual_type="screenshot",
                screenshot_target="https://example.com",
            ),
        ]
        urls = extract_screenshot_targets(anchors)
        assert urls == ["https://example.com"]

    def test_extract_multiple_targets(self):
        anchors = [
            VisualAnchor(
                section_role="opening",
                concept="配置界面",
                visual_type="screenshot",
                screenshot_target="https://example.com/1",
            ),
            VisualAnchor(
                section_role="body",
                concept="管理后台",
                visual_type="screenshot",
                screenshot_target="https://example.com/2",
            ),
        ]
        urls = extract_screenshot_targets(anchors)
        assert len(urls) == 2
        assert "https://example.com/1" in urls
        assert "https://example.com/2" in urls

    def test_deduplication(self):
        anchors = [
            VisualAnchor(
                section_role="opening",
                concept="配置界面",
                visual_type="screenshot",
                screenshot_target="https://example.com",
            ),
            VisualAnchor(
                section_role="body",
                concept="管理后台",
                visual_type="screenshot",
                screenshot_target="https://example.com",
            ),
        ]
        urls = extract_screenshot_targets(anchors)
        assert urls == ["https://example.com"]

    def test_ignore_non_screenshot(self):
        anchors = [
            VisualAnchor(
                section_role="opening",
                concept="架构图",
                visual_type="diagram",
                diagram_spec="三层架构",
            ),
            VisualAnchor(
                section_role="body",
                concept="配置界面",
                visual_type="screenshot",
                screenshot_target="https://example.com",
            ),
        ]
        urls = extract_screenshot_targets(anchors)
        assert urls == ["https://example.com"]

    def test_empty_anchors(self):
        urls = extract_screenshot_targets([])
        assert urls == []

    def test_screenshot_without_target(self):
        anchors = [
            VisualAnchor(
                section_role="opening",
                concept="配置界面",
                visual_type="screenshot",
                screenshot_target=None,
            ),
        ]
        urls = extract_screenshot_targets(anchors)
        assert urls == []


class TestScreenshotAsset:
    def test_asset_creation(self):
        asset = ScreenshotAsset(
            url="https://example.com",
            path="/assets/test.png",
            visual_type="step",
        )
        assert asset.url == "https://example.com"
        assert asset.path == "/assets/test.png"
        assert asset.visual_type == "step"
        assert asset.optimized is False

    def test_asset_optimized_flag(self):
        asset = ScreenshotAsset(
            url="https://example.com",
            path="/assets/test.webp",
            visual_type="hero",
            optimized=True,
        )
        assert asset.optimized is True
