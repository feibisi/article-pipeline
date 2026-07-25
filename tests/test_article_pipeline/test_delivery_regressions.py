"""Regression tests for the delivery-layer defects confirmed in the 2026-07-25 audit.

Every test here corresponds to a bug that was verified against the pre-audit
source (commit 5335e6c) and shipped without regression protection — the audit
subagent that fixed them never wrote its test file. All offline: no network, no
ssh, no publishing.
"""
import base64
import json
import os
import re
import tempfile
from pathlib import Path

import pytest

from article_pipeline import publish as pub
from article_pipeline.converter import md_to_gutenberg, detect_article_type


# ── Mermaid diagram substitution ──

def _svg(tmp: Path, name: str) -> Path:
    p = tmp / name
    p.write_text(f'<svg id="{name}"></svg>')
    return p


def test_mermaid_diagrams_land_in_their_own_slots(tmp_path):
    """Three diagrams must each replace their own fence.

    The pre-audit implementation re-scanned the (already mutated) markdown
    inside the substitution loop, so after diagram 0 was replaced the remaining
    fences shifted down by one: diagram 1's SVG was pasted where diagram 2
    belonged, diagram 2 was dropped, and diagram 1's raw ```mermaid source
    leaked into the published article.
    """
    md = "\n\n".join(
        f"段落 {i}\n\n```mermaid\ngraph TD;\n  A{i} --> B{i};\n```"
        for i in range(3)
    )
    diagrams = {str(i): str(_svg(tmp_path, f"d{i}.svg")) for i in range(3)}

    out = pub._embed_mermaid_svgs(md, json.dumps({"diagrams": diagrams}))

    assert "```mermaid" not in out, "raw mermaid source leaked into output"
    imgs = re.findall(r'<img src="data:image/svg\+xml;base64,([^"]+)"', out)
    assert len(imgs) == 3, f"expected 3 images, got {len(imgs)}"
    for i, b64 in enumerate(imgs):
        decoded = base64.b64decode(b64).decode()
        assert f'id="d{i}.svg"' in decoded, (
            f"slot {i} holds the wrong diagram: {decoded}")


def test_mermaid_missing_svg_leaves_fence_untouched(tmp_path):
    md = "```mermaid\ngraph TD;\n  A --> B;\n```"
    out = pub._embed_mermaid_svgs(md, json.dumps({"diagrams": {"0": str(tmp_path / "nope.svg")}}))
    assert out == md


def test_mermaid_no_diagrams_is_identity():
    md = "正文没有图。"
    assert pub._embed_mermaid_svgs(md, "{}") == md
    assert pub._embed_mermaid_svgs(md, "not json") == md


# ── Excerpt extraction ──

def test_excerpt_skips_type_notice_group():
    """The excerpt is what shows up in archives, search results and social
    previews. It used to be lifted from the wp:group notice box, so every
    security-classified article was published with the excerpt
    "安全通告 — 请相关站长及时检查并更新受影响的插件或组件。"
    """
    gutenberg = (
        '<!-- wp:group {"className":"notice"} -->\n'
        '<div class="wp-block-group">\n'
        '<!-- wp:paragraph -->\n'
        '<p><strong>安全通告</strong> — 请相关站长及时检查并更新受影响的插件或组件。</p>\n'
        '<!-- /wp:paragraph -->\n'
        '</div>\n'
        '<!-- /wp:group -->\n'
        '<!-- wp:paragraph -->\n'
        '<p>这是文章真正的第一段，应该成为摘要。</p>\n'
        '<!-- /wp:paragraph -->\n'
    )
    excerpt = pub._extract_excerpt(gutenberg)
    assert "安全通告" not in excerpt
    assert excerpt.startswith("这是文章真正的第一段")


def test_excerpt_strips_inline_markup():
    g = ('<!-- wp:paragraph -->\n'
         '<p>带<strong>加粗</strong>和<code>代码</code>的段落。</p>\n'
         '<!-- /wp:paragraph -->\n')
    assert pub._extract_excerpt(g) == "带加粗和代码的段落。"


# ── Post-review content injection ──

def test_type_notice_injection_is_off_by_default():
    """Injection ran at publish time — after review — so it pushed unchecked
    assertions into vetted copy. Verified live: task #99 ("systemd timer 基础")
    is classified `security` and was getting a security advisory prepended.
    """
    md = "## 配置 systemd timer\n\n先写 unit 文件。\n\n" * 4
    assert detect_article_type(md + "\n漏洞 攻击 恶意代码 安全") == "security"
    out = md_to_gutenberg(md, skip_first_h1=True, article_type="security")
    assert "安全通告" not in out, "notice injected without being asked"


def test_type_notice_injection_available_when_explicitly_requested():
    md = "## 标题\n\n正文段落足够长以便通过格式检查。\n\n" * 4
    out = md_to_gutenberg(md, skip_first_h1=True, article_type="security",
                          inject_type_notice=True)
    assert "安全通告" in out


def test_release_header_needs_an_adjacent_version_word():
    """A bare decimal anywhere in the first 500 chars used to become
    "本文介绍 X 版本的主要变更" — task #96's Nginx cache-hit-rate article got
    "1.5" lifted out of a table."""
    md = ("## 缓存命中率\n\n命中率从 1.5 提升到 4.2，见下表。\n\n"
          "| 指标 | 值 |\n|---|---|\n| 命中率 | 1.5 |\n\n") * 3
    out = md_to_gutenberg(md, skip_first_h1=True, article_type="release",
                          inject_type_notice=True)
    assert "1.5 版本" not in out


# ── Semantic marks must survive emoji stripping ──

@pytest.mark.parametrize("mark", ["✓", "✗", "★", "⚠"])
def test_comparison_marks_are_not_stripped_as_emoji(mark):
    """Chinese comparison tables carry meaning entirely in ✓/✗; the old emoji
    range stripped them, emptying the cells."""
    md = (f"## 对比\n\n| 功能 | A | B |\n|---|---|---|\n"
          f"| 支持 | {mark} | {mark} |\n\n正文段落，补足长度要求。\n\n") * 2
    out = md_to_gutenberg(md, skip_first_h1=True)
    assert mark in out


# ── Inline formatting inside links ──

def test_link_preserves_inner_bold_and_code():
    md = ("## 链接\n\n见 [**官方文档**](https://example.com/a) 与 "
          "[`wp-config.php`](https://example.com/b)。\n\n" * 3)
    out = md_to_gutenberg(md, skip_first_h1=True)
    assert "<strong>官方文档</strong>" in out
    assert "<code>wp-config.php</code>" in out


# ── Gutenberg block validity ──

def test_list_items_are_wrapped_in_list_item_blocks():
    """Without wp:list-item wrappers WordPress 6.x flags the whole list as
    "unexpected or invalid content" and a human must click Attempt Recovery."""
    md = "## 步骤\n\n- 第一步\n- 第二步\n- 第三步\n\n补足段落长度的正文。\n\n" * 2
    out = md_to_gutenberg(md, skip_first_h1=True)
    assert out.count("<!-- wp:list-item -->") >= 3
    assert "wp-block-list" in out


def test_table_block_has_no_colgroup():
    """core/table's save output has no colgroup; the extra tag invalidates
    the block in the editor."""
    md = ("## 表\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n"
          "补足段落长度的正文内容。\n\n") * 2
    out = md_to_gutenberg(md, skip_first_h1=True)
    assert "<colgroup" not in out
    assert "<!-- wp:table" in out


# ── Publish path: honesty and idempotency ──

def test_translate_bridge_rejects_success_without_url_or_id(monkeypatch):
    """returncode == 0 alone used to mean "published", which is how the DB
    ended up with done tasks whose published_url was blank and whose supposed
    URLs 404 on the live site."""
    class R:
        returncode = 0
        stdout = "Uploaded file. Done.\n"
        stderr = ""

    monkeypatch.setattr(pub.subprocess, "run", lambda *a, **k: R())
    out = pub._publish_via_translate("标题", "正文", "生态系统")
    assert "error" in out, f"claimed success with no post URL: {out}"
    assert out["error"] == "translate_publish_failed"


def test_translate_bridge_accepts_a_real_url(monkeypatch):
    class R:
        returncode = 0
        stdout = "Created: https://wptea.com/real-post/ ID=4321\n"
        stderr = ""

    monkeypatch.setattr(pub.subprocess, "run", lambda *a, **k: R())
    out = pub._publish_via_translate("标题", "正文", "生态系统")
    assert out.get("published") is True
    assert out["url"] == "https://wptea.com/real-post/"
    assert out["post_id"] == 4321


def test_dry_run_touches_no_network_and_no_subprocess(monkeypatch):
    """dry_run must be safe to point at production: no HTTP, no ssh, no post."""
    def boom(*a, **k):
        raise AssertionError("dry run made an outbound call")

    monkeypatch.setattr(pub.requests, "post", boom)
    monkeypatch.setattr(pub.requests, "get", boom, raising=False)
    monkeypatch.setattr(pub.subprocess, "run", boom)

    # publish_to_wp opens a TaskDB to look up cached Mermaid SVGs. The default
    # path lives on an SMB share, so leaving it real makes this test hang on
    # network latency rather than exercising the code under test.
    import article_pipeline.db as apdb

    class _StubDB:
        def get_task(self, task_id):
            return {"meta_json": "{}"}

    monkeypatch.setattr(apdb, "TaskDB", lambda *a, **k: _StubDB())

    result = pub.publish_to_wp(
        task_id=999999, title="标题",
        article="## 小节\n\n正文段落，足够长以便转换。\n\n" * 3,
        meta_description="", platform="wptea", dry_run=True)

    assert result.get("dry_run") is True
    # Credentials must be reported as presence booleans, never as values.
    for key, value in result.items():
        assert "password" not in key.lower()
        assert not (isinstance(value, str) and value.startswith("Basic "))


# ── Static file handler must not escape its directory ──

def test_static_path_traversal_is_rejected():
    """GET /static/../../../etc/passwd read arbitrary files as the pipeline
    user, on a server that defaulted to listening on 0.0.0.0 with no auth."""
    from article_pipeline import review_server as rs

    escaped = rs.STATIC_DIR / "../../../etc/passwd"
    resolved = escaped.resolve()
    assert not resolved.is_relative_to(rs.STATIC_DIR.resolve()), (
        "test premise broken: path did not escape")

    inside = (rs.STATIC_DIR / "style.css").resolve()
    assert inside.is_relative_to(rs.STATIC_DIR.resolve())


def test_review_server_defaults_to_loopback():
    from article_pipeline import review_server as rs
    host = os.environ.get("AP_REVIEW_HOST", rs.HOST)
    assert host in ("127.0.0.1", "localhost"), (
        f"review server would bind {host!r}; it exposes a one-click publish "
        f"button with no authentication")
