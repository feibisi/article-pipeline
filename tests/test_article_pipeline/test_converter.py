"""Tests for converter module."""
import pytest
from article_pipeline.converter import (
    detect_article_type, md_to_gutenberg, extract_title, _strip_emoji,
)


def test_detect_security():
    text = "WordPress 漏洞 CVE-2024-1234 安全更新"
    assert detect_article_type(text) == "security"


def test_detect_release():
    text = "WordPress 6.7 版本发布更新日志"
    assert detect_article_type(text) == "release"


def test_detect_plugin():
    text = "WordPress 插件 WooCommerce 新版功能"
    assert detect_article_type(text) == "plugin"


def test_detect_general():
    text = "这是一篇普通的教程文章，关于 PHP 基础知识"
    assert detect_article_type(text) == "general"


def test_md_to_gutenberg_headings():
    md = "# 标题\n\n## 第一节\n\n内容\n\n## 第二节\n\n更多内容"
    html = md_to_gutenberg(md, skip_first_h1=True)
    assert "wp:heading" in html
    assert "第一节" in html
    assert "第二节" in html
    # H1 should be skipped
    assert html.count("wp:heading") >= 2


def test_md_to_gutenberg_paragraphs():
    md = "第一段\n\n第二段\n\n第三段"
    html = md_to_gutenberg(md)
    assert html.count("<!-- wp:paragraph -->") == 3


def test_md_to_gutenberg_code_block():
    md = "```python\nprint('hello')\n```"
    html = md_to_gutenberg(md)
    assert "wp:code" in html
    assert "print" in html


def test_md_to_gutenberg_list():
    md = "- 项目一\n- 项目二\n- 项目三"
    html = md_to_gutenberg(md)
    assert "wp:list" in html
    assert "项目一" in html


def test_md_to_gutenberg_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |"
    html = md_to_gutenberg(md)
    assert "wp:table" in html


def test_md_to_gutenberg_strips_emoji():
    md = "标题 🔥\n\n段落 🚀 内容"
    html = md_to_gutenberg(md)
    assert "🔥" not in html
    assert "🚀" not in html


def test_extract_title():
    assert extract_title("# 我的标题\n正文") == "我的标题"
    assert extract_title("没有标题的正文") is None


def test_strip_emoji():
    assert _strip_emoji("Hello 🔥 World 🚀") == "Hello  World "
    assert _strip_emoji("纯文本") == "纯文本"
